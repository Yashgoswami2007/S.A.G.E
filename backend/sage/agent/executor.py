import os
import re
import time
import json
import logging
from typing import Callable, Optional, Awaitable, Any
from sage.agent.state import AgentState, ExecutionTrace, TraceEvent
from sage.agent.schemas import AgentResponse, Plan
from sage.agent.profiles.manager import ProfileManager
from sage.agent.router import ModelRouter
from sage.models.client import OpenAICompatibleClient
from sage.tools.registry import ToolRegistry
from sage.tools.base import ToolPermission
from sage.agent.planner import Planner
from sage.core.utils import generate_id

StreamCallback = Callable[[TraceEvent], Awaitable[None]]
logger = logging.getLogger("sage.executor")

class ReActExecutor:
    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        profile_manager: ProfileManager,
        lifecycle_manager=None,
        max_steps: int = 15,
        max_retries_per_step: int = 3
    ):
        self.router = router
        self.tool_registry = tool_registry
        self.profile_manager = profile_manager
        self.lifecycle_manager = lifecycle_manager
        self.planner = Planner()
        self.max_steps = max_steps
        self.max_retries_per_step = max_retries_per_step

    async def run(
        self,
        prompt: str,
        profile_name: str = "general",
        task_id: Optional[str] = None,
        file_attachments: Optional[list] = None,
        stream_callback: Optional[StreamCallback] = None,
        require_approval_for_high_risk: bool = True
    ) -> AgentResponse:
        task_id = task_id or generate_id()
        profile = self.profile_manager.get_profile(profile_name)

        # 1. Route Model (Deterministic)
        model_config, routing_reason = self.router.route(
            prompt=prompt,
            profile_name=profile.name,
            file_attachments=file_attachments
        )

        # 1b. VRAM Swap — if the router returned [needs_swap], trigger model swap
        if "[needs_swap]" in routing_reason and self.lifecycle_manager:
            # Find what's currently loaded so we can unload it
            currently_loaded = [
                m for m in self.router.registry.list_all()
                if m.status == "READY" and m.id != model_config.id
            ]
            if currently_loaded:
                await self.lifecycle_manager.swap_model(
                    load_id=model_config.id,
                    unload_id=currently_loaded[0].id
                )
            else:
                await self.lifecycle_manager.start_model(model_config.id)
            routing_reason = routing_reason.replace(" [needs_swap]", " [swapped]")

        client = OpenAICompatibleClient(base_url=f"http://localhost:{model_config.server_port}")
        # llama-server uses the model file path as the model ID in API calls,
        # not the registry short-name (e.g. "qwen3-8b").
        # Use model_path when it is an actual file path, fall back to id otherwise.
        llm_model_id = model_config.model_path if os.path.isabs(model_config.model_path) else model_config.id

        # ── Fallback helper ──────────────────────────────────────────────────
        async def _try_activate_fallback(failed_id: str):
            """
            If the routed model fails during execution, attempt to activate its
            configured fallback and re-route.  Returns (new_client, new_model_id,
            new_model_config) or raises if no fallback is available.
            """
            fallback_cfg = self.router.registry.get_fallback(failed_id)
            if not fallback_cfg:
                raise RuntimeError(
                    f"Model {failed_id} failed and no fallback is configured."
                )
            logger.warning(
                f"Model {failed_id} unavailable during execution. "
                f"Activating fallback: {fallback_cfg.id}"
            )
            if self.lifecycle_manager:
                # Unload the failed model first to free VRAM, then start fallback
                await self.lifecycle_manager.swap_model(
                    load_id=fallback_cfg.id,
                    unload_id=failed_id
                )
            else:
                raise RuntimeError(
                    f"Cannot activate fallback {fallback_cfg.id}: no lifecycle manager."
                )
            if fallback_cfg.status != "READY":
                raise RuntimeError(
                    f"Fallback {fallback_cfg.id} started but never became READY."
                )
            new_client = OpenAICompatibleClient(
                base_url=f"http://localhost:{fallback_cfg.server_port}"
            )
            new_model_id = (
                fallback_cfg.model_path
                if os.path.isabs(fallback_cfg.model_path)
                else fallback_cfg.id
            )
            return new_client, new_model_id, fallback_cfg

        # Initialize persistent trace
        trace = ExecutionTrace(
            task_id=task_id,
            prompt=prompt,
            profile_name=profile.name,
            selected_model=model_config.id,
            routing_reason=routing_reason
        )

        async def emit(event: TraceEvent):
            trace.add_event(event)
            if stream_callback:
                await stream_callback(event)

        # 2. State = PLANNING
        plan_event = TraceEvent(
            task_id=task_id,
            agent_state=AgentState.PLANNING,
            profile=profile.name,
            selected_model=model_config.id,
            routing_reason=routing_reason,
            reflection=f"Routing decision: Selected {model_config.id} because ({routing_reason})"
        )
        await emit(plan_event)

        # Planning — with fallback if the primary model is unreachable
        try:
            plan: Plan = await self.planner.create_plan(prompt, profile, client, llm_model_id)
        except Exception as plan_err:
            logger.warning(
                f"Planning failed with model {model_config.id} ({plan_err}). "
                "Attempting fallback model."
            )
            try:
                client, llm_model_id, model_config = await _try_activate_fallback(model_config.id)
                routing_reason = f"fallback to {model_config.id} after primary planning failure"
                plan = await self.planner.create_plan(prompt, profile, client, llm_model_id)
            except Exception as fb_err:
                logger.error(f"Fallback planning also failed: {fb_err}")
                return AgentResponse(
                    task_id=task_id,
                    status=AgentState.FAILED,
                    output=f"All models unavailable. Primary error: {plan_err}. Fallback error: {fb_err}",
                    trace=trace
                )
        
        if plan and (len(plan.steps) > 1 or (len(plan.steps) == 1 and plan.steps[0].tool_name)):
            plan_created_event = TraceEvent(
                task_id=task_id,
                agent_state=AgentState.PLANNING,
                profile=profile.name,
                selected_model=model_config.id,
                tool_args={"plan": plan.model_dump()}
            )
            await emit(plan_created_event)

        final_output = ""
        current_step_idx = 0
        step_retry_count = 0

        # Main ReAct Execution Loop
        while current_step_idx < len(plan.steps) and len(trace.events) < self.max_steps:
            step = plan.steps[current_step_idx]

            # 3. State = ACTING
            tool_name = step.tool_name
            tool_args = step.tool_args or {}

            # Permission Check & Approval State
            if tool_name:
                tool_inst = self.tool_registry.get_tool(tool_name)
                if tool_inst and tool_inst.permission == ToolPermission.HIGH_RISK and require_approval_for_high_risk:
                    # Transition to WAITING_FOR_APPROVAL
                    approval_event = TraceEvent(
                        task_id=task_id,
                        step_id=step.step_id,
                        agent_state=AgentState.WAITING_FOR_APPROVAL,
                        profile=profile.name,
                        selected_model=model_config.id,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        reflection=f"High-risk operation '{tool_name}' requires approval before execution."
                    )
                    await emit(approval_event)
                    # For Phase 1 backend test harness: auto-approve after state transition record
                    
            act_event = TraceEvent(
                task_id=task_id,
                step_id=step.step_id,
                agent_state=AgentState.ACTING,
                profile=profile.name,
                selected_model=model_config.id,
                tool_name=tool_name,
                tool_args=tool_args
            )
            await emit(act_event)

            # 4. State = OBSERVING
            start_time = time.time()
            if tool_name:
                tool_res = await self.tool_registry.execute_tool(
                    name=tool_name,
                    kwargs=tool_args,
                    allowed_tools=profile.allowed_tools
                )
                duration_ms = (time.time() - start_time) * 1000.0

                obs_event = TraceEvent(
                    task_id=task_id,
                    step_id=step.step_id,
                    agent_state=AgentState.OBSERVING,
                    profile=profile.name,
                    selected_model=model_config.id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_res.output if tool_res.success else None,
                    error=tool_res.error if not tool_res.success else None,
                    duration_ms=duration_ms,
                    retry_count=step_retry_count
                )
                await emit(obs_event)

                # 5. State = REFLECTING
                if tool_res.success:
                    final_output = tool_res.output
                    reflection_msg = f"Step {step.step_id} succeeded: {tool_res.output[:100]}"
                    reflect_event = TraceEvent(
                        task_id=task_id,
                        step_id=step.step_id,
                        agent_state=AgentState.REFLECTING,
                        profile=profile.name,
                        selected_model=model_config.id,
                        reflection=reflection_msg
                    )
                    await emit(reflect_event)
                    current_step_idx += 1
                    step_retry_count = 0
                else:
                    # Retry Logic
                    step_retry_count += 1
                    reflection_msg = f"Step {step.step_id} failed: {tool_res.error}. Retry count: {step_retry_count}/{self.max_retries_per_step}"
                    reflect_event = TraceEvent(
                        task_id=task_id,
                        step_id=step.step_id,
                        agent_state=AgentState.REFLECTING,
                        profile=profile.name,
                        selected_model=model_config.id,
                        error=tool_res.error,
                        reflection=reflection_msg,
                        retry_count=step_retry_count
                    )
                    await emit(reflect_event)

                    if step_retry_count >= self.max_retries_per_step:
                        # Max retries reached, fail execution
                        fail_event = TraceEvent(
                            task_id=task_id,
                            step_id=step.step_id,
                            agent_state=AgentState.FAILED,
                            profile=profile.name,
                            selected_model=model_config.id,
                            error=f"Exceeded max retries ({self.max_retries_per_step}) for step {step.step_id}"
                        )
                        await emit(fail_event)
                        return AgentResponse(
                            task_id=task_id,
                            status=AgentState.FAILED,
                            output="",
                            trace=trace
                        )
            else:
                # LLM Direct Response step
                messages = [
                    {"role": "system", "content": f"You are a helpful assistant operating under profile '{profile.name}'."}
                ]
                messages.append({"role": "user", "content": prompt})
                
                # Append tool observation history for context
                for evt in trace.events:
                    if evt.agent_state == AgentState.OBSERVING and evt.tool_result:
                        msg_str = f"Observation from {evt.tool_name}: {evt.tool_result[:500]}"
                        messages.append({"role": "user", "content": msg_str})

                if stream_callback:
                    final_output = ""
                    async for token in client.chat_stream(model=llm_model_id, messages=messages):
                        final_output += token
                        token_event = TraceEvent(
                            task_id=task_id,
                            step_id=step.step_id,
                            agent_state=AgentState.OBSERVING,
                            profile=profile.name,
                            selected_model=model_config.id,
                            token=token
                        )
                        await stream_callback(token_event)
                else:
                    try:
                        llm_resp = await client.chat(model=llm_model_id, messages=messages)
                    except Exception as llm_err:
                        logger.warning(
                            f"LLM call failed for {model_config.id} ({llm_err}). "
                            "Attempting fallback model."
                        )
                        try:
                            client, llm_model_id, model_config = await _try_activate_fallback(model_config.id)
                            routing_reason = f"fallback to {model_config.id} after LLM call failure"
                            llm_resp = await client.chat(model=llm_model_id, messages=messages)
                        except Exception as fb_err:
                            logger.error(f"Fallback LLM call also failed: {fb_err}")
                            return AgentResponse(
                                task_id=task_id,
                                status=AgentState.FAILED,
                                output=f"All models unavailable. Primary error: {llm_err}. Fallback error: {fb_err}",
                                trace=trace
                            )
                    choices = llm_resp.get("choices", [{}])
                    raw = choices[0].get("message", {}).get("content", "") or ""
                    # Strip Qwen3-style <think>...</think> reasoning blocks; keep only the answer
                    final_output = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                    if not final_output:
                        final_output = raw.strip() or "No output generated."
                
                duration_ms = (time.time() - start_time) * 1000.0
                obs_event = TraceEvent(
                    task_id=task_id,
                    step_id=step.step_id,
                    agent_state=AgentState.OBSERVING,
                    profile=profile.name,
                    selected_model=model_config.id,
                    tool_result=final_output,
                    duration_ms=duration_ms
                )
                await emit(obs_event)
                current_step_idx += 1

        # 6. State = DELIVERING
        deliver_event = TraceEvent(
            task_id=task_id,
            agent_state=AgentState.DELIVERING,
            profile=profile.name,
            selected_model=model_config.id,
            reflection=f"Final output generated successfully."
        )
        await emit(deliver_event)

        # 7. State = COMPLETED
        completed_event = TraceEvent(
            task_id=task_id,
            agent_state=AgentState.COMPLETED,
            profile=profile.name,
            selected_model=model_config.id
        )
        await emit(completed_event)

        return AgentResponse(
            task_id=task_id,
            status=AgentState.COMPLETED,
            output=final_output,
            trace=trace
        )
