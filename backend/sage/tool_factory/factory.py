import os
import json
import logging
import asyncio
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Callable, Awaitable

from sage.config import settings
from sage.models.client import OpenAICompatibleClient
from sage.sandbox.sandbox_manager import SandboxManager
from sage.tools.registry import ToolRegistry
from sage.tools.dynamic_runtime import DynamicTool
from sage.security.policy import SecurityPolicy
from sage.tool_factory.models import ToolSpecification, ToolProvenance, ToolSynthesisState, FactoryError
from sage.tool_factory.designer import ToolDesigner
from sage.tool_factory.generator import ToolGenerator
from sage.tool_factory.validator import ToolValidator
from sage.tool_factory.tester import ToolTester
from sage.agent.state import TraceEvent, AgentState

logger = logging.getLogger("sage.tool_factory.factory")

class ToolFactory:
    def __init__(
        self,
        client: OpenAICompatibleClient,
        model_id: str,
        sandbox_manager: SandboxManager,
        registry: ToolRegistry,
    ):
        self.client = client
        self.model_id = model_id
        self.sandbox_manager = sandbox_manager
        self.registry = registry
        
        self.designer = ToolDesigner(client, model_id)
        self.generator = ToolGenerator(client, model_id)
        self.tester = ToolTester(sandbox_manager)
        
        self.dynamic_dir = Path(settings.DYNAMIC_TOOLS_DIR) / "generated"
        self.dynamic_dir.mkdir(parents=True, exist_ok=True)

    # ── Per-stage timeout helpers ────────────────────────────────────────

    @staticmethod
    def _stage_timeout(stage: str) -> int:
        """Return the timeout in seconds for a specific factory stage."""
        timeouts = {
            "design": settings.TOOL_FACTORY_DESIGN_TIMEOUT,
            "generate": settings.TOOL_FACTORY_GENERATE_TIMEOUT,
            "validate": settings.TOOL_FACTORY_VALIDATE_TIMEOUT,
            "test": settings.TOOL_FACTORY_TEST_TIMEOUT,
        }
        return timeouts.get(stage, settings.DYNAMIC_TOOLS_SANDBOX_TIMEOUT_SECONDS)

    @staticmethod
    def _overall_timeout() -> int:
        """Return the overall factory timeout budget."""
        return settings.DYNAMIC_TOOLS_SANDBOX_TIMEOUT_SECONDS * settings.TOOL_FACTORY_OVERALL_MULTIPLIER

    # ── Main Entry Point ────────────────────────────────────────────────

    async def synthesize_tool(
        self, 
        capability: str, 
        task_context: str, 
        requirements: str, 
        task_id: str,
        profile_name: str = "default",
        emit_cb: Optional[Callable[[TraceEvent], Awaitable[None]]] = None
    ) -> Tuple[bool, str]:
        """
        Orchestrates the dynamic creation of a tool.
        Returns (success: bool, message: str)
        """
        logger.info(f"Synthesizing capability: {capability}")
        tool_name = "unknown"
        tool_factory_id = str(uuid.uuid4())
        factory_start = time.time()
        
        # Track per-stage timing for observability
        stage_timings: dict = {}
        last_stage_error: Optional[str] = None
        
        async def emit(
            stage: ToolSynthesisState,
            msg: str,
            attempt: int = None,
            max_attempts: int = None,
            tool_name: Optional[str] = None,
        ):
            if emit_cb:
                await emit_cb(
                    TraceEvent(
                        task_id=task_id,
                        step_id=-1,
                        agent_state=AgentState.TOOL_SYNTHESIS,
                        profile=profile_name,
                        synthesis_info={
                            "stage": stage.value,
                            "message": msg,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "tool_name": tool_name or "unknown",
                            "tool_factory_id": tool_factory_id,
                        },
                    )
                )

        try:
            # Overall timeout for synthesis process
            overall_budget = self._overall_timeout()
            logger.info(
                "Tool Factory: starting synthesis (overall budget: %ds, "
                "design: %ds, generate: %ds, validate: %ds, test: %ds)",
                overall_budget,
                self._stage_timeout("design"),
                self._stage_timeout("generate"),
                self._stage_timeout("validate"),
                self._stage_timeout("test"),
            )

            success, message = await asyncio.wait_for(
                self._synthesize_loop(
                    capability, task_context, requirements, task_id,
                    emit, stage_timings,
                ),
                timeout=overall_budget,
            )

            total_ms = (time.time() - factory_start) * 1000
            timing_summary = ", ".join(
                f"{k}: {v:.0f}ms" for k, v in stage_timings.items()
            )
            logger.info(
                "Tool Factory: finished in %.0fms [%s] — %s",
                total_ms, timing_summary,
                "SUCCESS" if success else "FAILED",
            )

            if success:
                await emit(ToolSynthesisState.COMPLETED, message)
            else:
                await emit(ToolSynthesisState.FAILED, message)
            return success, message
            
        except asyncio.TimeoutError:
            total_ms = (time.time() - factory_start) * 1000
            timing_summary = ", ".join(
                f"{k}: {v:.0f}ms" for k, v in stage_timings.items()
            )
            # Include per-stage timing and the last known error for observability
            msg = (
                f"Tool synthesis timed out after {total_ms / 1000:.0f}s "
                f"(budget: {self._overall_timeout()}s). "
                f"Stage timings: [{timing_summary or 'no stages completed'}]. "
                f"Last error: {last_stage_error or 'none recorded'}. "
                f"The LLM may be unresponsive or inference is too slow for the current hardware."
            )
            logger.error(msg)
            await emit(ToolSynthesisState.FAILED, msg)
            return False, msg
        except asyncio.CancelledError:
            msg = "Tool synthesis cancelled."
            logger.info(msg)
            await emit(ToolSynthesisState.CANCELLED, msg)
            raise
        except Exception as e:
            msg = f"Unexpected failure in tool factory: {e}"
            logger.error(msg, exc_info=True)
            await emit(ToolSynthesisState.FAILED, msg)
            return False, msg

    async def _synthesize_loop(
        self, capability: str, task_context: str, requirements: str,
        task_id: str, emit: Callable, stage_timings: dict,
    ) -> Tuple[bool, str]:
        
        # ── 1. DESIGN ────────────────────────────────────────────────────
        await emit(ToolSynthesisState.DESIGNING, "Designing tool specification...")
        design_start = time.time()
        try:
            spec = await asyncio.wait_for(
                self.designer.design_tool(capability, task_context, requirements),
                timeout=self._stage_timeout("design"),
            )
        except asyncio.TimeoutError:
            stage_timings["design"] = (time.time() - design_start) * 1000
            msg = (
                f"Design stage timed out after {self._stage_timeout('design')}s. "
                "The LLM call to generate the tool specification did not complete in time."
            )
            logger.error(msg)
            return False, f"TOOL_DESIGN_TIMEOUT: {msg}"
        except FactoryError as e:
            stage_timings["design"] = (time.time() - design_start) * 1000
            logger.error(f"Design failed: {e}")
            return False, f"TOOL_DESIGN_FAILED: {e.message}"
        except Exception as e:
            stage_timings["design"] = (time.time() - design_start) * 1000
            logger.error(f"Design stage unexpected error: {e}", exc_info=True)
            return False, f"TOOL_DESIGN_ERROR: {str(e)}"

        stage_timings["design"] = (time.time() - design_start) * 1000
        tool_name = spec.name
        logger.info(
            "Designed tool spec: %s v%s (%.0fms)",
            spec.name, spec.version, stage_timings["design"],
        )
        await emit(ToolSynthesisState.DESIGNING, f"Designed tool spec: {spec.name}", tool_name=tool_name)
        
        # ── Determine Security Profile ───────────────────────────────────
        profile = SecurityPolicy.get_profile("SAFE")
        
        # ── 2. VALIDATE SPECIFICATION ────────────────────────────────────
        await emit(ToolSynthesisState.VALIDATING, "Validating tool specification...", tool_name=tool_name)
        validate_spec_start = time.time()
        try:
            ToolValidator.validate_specification(spec, profile)
        except FactoryError as e:
            stage_timings["validate_spec"] = (time.time() - validate_spec_start) * 1000
            logger.warning(f"Tool specification rejected by security policy: {e.details}")
            return False, f"TOOL_SECURITY_REJECTED: {e.details}"
        stage_timings["validate_spec"] = (time.time() - validate_spec_start) * 1000
            
        # ── Repair Loop ──────────────────────────────────────────────────
        max_attempts = settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS
        attempt = 0
        last_error = ""
        generated_code = ""
        
        while attempt < max_attempts:
            attempt += 1
            logger.info(f"Generating code for '{spec.name}', attempt {attempt}/{max_attempts}")
            
            # ── 3. GENERATE CODE ─────────────────────────────────────────
            await emit(
                ToolSynthesisState.GENERATING, "Generating code...",
                attempt=attempt, max_attempts=max_attempts, tool_name=tool_name,
            )
            gen_start = time.time()
            try:
                generated_code = await asyncio.wait_for(
                    self.generator.generate_code(spec, profile, error_feedback=last_error),
                    timeout=self._stage_timeout("generate"),
                )
            except asyncio.TimeoutError:
                gen_ms = (time.time() - gen_start) * 1000
                stage_timings[f"generate_attempt_{attempt}"] = gen_ms
                msg = (
                    f"Code generation timed out after {self._stage_timeout('generate')}s "
                    f"(attempt {attempt}/{max_attempts}). "
                    "The LLM call to generate Python code did not complete in time."
                )
                logger.error(msg)
                if attempt < max_attempts:
                    last_error = msg
                    continue
                return False, f"TOOL_GENERATION_TIMEOUT: {msg}"
            except FactoryError as e:
                gen_ms = (time.time() - gen_start) * 1000
                stage_timings[f"generate_attempt_{attempt}"] = gen_ms
                logger.error(f"Generation failed: {e}")
                if e.repairable and attempt < max_attempts:
                    last_error = f"Code generation error: {e.message}\nDetails: {e.details}"
                    continue
                return False, f"TOOL_GENERATION_FAILED: {e.message}"
            except Exception as e:
                gen_ms = (time.time() - gen_start) * 1000
                stage_timings[f"generate_attempt_{attempt}"] = gen_ms
                logger.error(f"Generation unexpected error: {e}", exc_info=True)
                if attempt < max_attempts:
                    last_error = f"Unexpected generation error: {str(e)}"
                    continue
                return False, f"TOOL_GENERATION_ERROR: {str(e)}"

            stage_timings[f"generate_attempt_{attempt}"] = (time.time() - gen_start) * 1000
                
            # ── 4. VALIDATE CODE (AST) ───────────────────────────────────
            await emit(
                ToolSynthesisState.VALIDATING, "Validating generated code (AST)...",
                attempt=attempt, max_attempts=max_attempts, tool_name=tool_name,
            )
            validate_start = time.time()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(ToolValidator.validate_code, generated_code, profile),
                    timeout=self._stage_timeout("validate"),
                )
            except asyncio.TimeoutError:
                stage_timings[f"validate_attempt_{attempt}"] = (time.time() - validate_start) * 1000
                last_error = "AST validation timed out — code may be excessively large."
                logger.warning(last_error)
                continue
            except FactoryError as e:
                stage_timings[f"validate_attempt_{attempt}"] = (time.time() - validate_start) * 1000
                logger.warning(f"AST validation failed: {e.details}")
                last_error = f"Validation Errors:\n{e.message}\nDetails:\n{e.details}"
                continue
            stage_timings[f"validate_attempt_{attempt}"] = (time.time() - validate_start) * 1000
                
            # ── 5. SANDBOX TEST ──────────────────────────────────────────
            logger.info("Running sandbox tests...")
            await emit(
                ToolSynthesisState.TESTING, "Running deterministic sandbox tests...",
                attempt=attempt, max_attempts=max_attempts, tool_name=tool_name,
            )
            test_start = time.time()
            try:
                await asyncio.wait_for(
                    self.tester.test_tool(spec, generated_code),
                    timeout=self._stage_timeout("test"),
                )
            except asyncio.TimeoutError:
                test_ms = (time.time() - test_start) * 1000
                stage_timings[f"test_attempt_{attempt}"] = test_ms
                msg = (
                    f"Sandbox test timed out after {self._stage_timeout('test')}s "
                    f"(attempt {attempt}/{max_attempts})."
                )
                logger.warning(msg)
                last_error = msg
                continue
            except FactoryError as e:
                stage_timings[f"test_attempt_{attempt}"] = (time.time() - test_start) * 1000
                logger.warning(f"Sandbox test failed: {e.message}\n{e.details}")
                last_error = f"Sandbox Test Errors:\n{e.message}\nDetails:\n{e.details}"
                continue
            stage_timings[f"test_attempt_{attempt}"] = (time.time() - test_start) * 1000
                
            # If we get here, validation and testing passed
            logger.info(
                "Tool passed validation and tests on attempt %d/%d.",
                attempt, max_attempts,
            )
            break
            
        else:
            # Exceeded max attempts
            msg = f"Exceeded {max_attempts} repair attempts. Last error: {last_error}"
            self._cleanup_tool_dir(spec.name)
            return False, f"TOOL_GENERATION_FAILED: {msg}"
            
        # ── 6. SAVE AND REGISTER ─────────────────────────────────────────
        await emit(ToolSynthesisState.REGISTERING, "Registering verified tool...", tool_name=tool_name)
        register_start = time.time()
        success, message = self._save_and_register(spec, generated_code, task_id)
        stage_timings["register"] = (time.time() - register_start) * 1000

        # ── 7. VERIFY REGISTRATION ───────────────────────────────────────
        if success:
            registered_tool = self.registry.get_tool(spec.name)
            if registered_tool is None:
                logger.error(
                    "Tool '%s' was saved but NOT found in registry after registration!",
                    spec.name,
                )
                return False, (
                    f"TOOL_REGISTRATION_VERIFY_FAILED: Tool '{spec.name}' was saved "
                    "to disk but could not be found in the registry. "
                    "This is likely a DynamicTool initialization error."
                )
            logger.info(
                "Registration verified: tool '%s' is in the registry.", spec.name,
            )

        return success, message

    def _cleanup_tool_dir(self, name: str):
        tool_dir = self.dynamic_dir / name
        if tool_dir.exists():
            shutil.rmtree(tool_dir, ignore_errors=True)

    def _save_and_register(self, spec: ToolSpecification, code: str, task_id: str) -> Tuple[bool, str]:
        """Saves the generated tool to disk and registers it."""
        try:
            tool_dir = self.dynamic_dir / spec.name
            tool_dir.mkdir(parents=True, exist_ok=True)
            
            # Write code
            code_path = tool_dir / "tool.py"
            code_path.write_text(code, encoding="utf-8")
            
            # Write manifest
            manifest_path = tool_dir / "manifest.json"
            manifest_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
            
            # Write provenance
            provenance = ToolProvenance(
                name=spec.name,
                version=spec.version,
                created_at=datetime.utcnow().isoformat(),
                created_for_capability=spec.capability,
                generator_model=self.model_id,
                source_task_id=task_id,
                security_policy="SAFE",
                dependencies=spec.dependencies,
                validation_status="approved",
                sandbox_status="passed"
            )
            prov_path = tool_dir / "provenance.json"
            prov_path.write_text(provenance.model_dump_json(indent=2), encoding="utf-8")
            
            # Register in current session
            dynamic_tool = DynamicTool(spec, str(code_path), self.sandbox_manager)
            self.registry.register(dynamic_tool)
            
            logger.info(f"Successfully registered dynamic tool: {spec.name}")
            return True, f"Successfully synthesized capability into tool: {spec.name}"
            
        except Exception as e:
            logger.error("Failed to register dynamic tool: %s", e)
            self._cleanup_tool_dir(spec.name)
            return False, f"TOOL_REGISTRATION_FAILED: {str(e)}"
