from aiohttp import client_middleware_digest_auth
import json
import logging
import re
from typing import List, Optional, Dict, Set, Tuple
from sage.agent.schemas import Plan, Step
from sage.models.client import OpenAICompatibleClient
from sage.agent.profiles.base import AgentProfile
from sage.config import settings

logger = logging.getLogger("sage.agent.planner")


class Planner:

    # ── Schema Formatting ────────────────────────────────────────────────

    @staticmethod
    def _format_tool_schemas(profile: AgentProfile, tool_registry) -> str:
        """Build tool documentation from the single source of truth: the registry.

        Iterates every tool in the registry whose name is in
        ``profile.allowed_tools`` and renders its ``parameters`` JSON schema
        as a human-readable block the LLM can follow exactly.
        """
        # Filter manually — don't assume list_tools() accepts allowed_tools
        tools = [
            tool for tool in tool_registry.list_tools()
            if tool.name in profile.allowed_tools
        ]
        if not tools:
            return "No tools are available for this profile.\n"

        lines = ["Available tools and their parameters:\n"]
        for tool in sorted(tools, key=lambda t: t.name):
            props = tool.parameters.get("properties", {})
            required = set(tool.parameters.get("required", []))

            param_parts = []
            for pname, pschema in props.items():
                req_tag = "[REQUIRED]" if pname in required else "[OPTIONAL]"
                ptype = pschema.get("type", "string")
                desc = pschema.get("description", "")
                
                default_val = pschema.get("default")
                default_str = f" (Default: {default_val})" if default_val is not None else ""
                
                desc_str = f": {desc}" if desc else ""
                param_parts.append(f"  - {pname}: {ptype} {req_tag}{default_str}{desc_str}")
            params_str = "\n".join(param_parts) if param_parts else "  (no parameters)"

            lines.append(f"{tool.name}")
            lines.append(f"Description: {tool.description}")
            lines.append(f"Parameters:\n{params_str}")
            lines.append("DO NOT use any other arguments.\n")
            
        # Add synthesize_capability meta-tool
        lines.append("synthesize_capability")
        lines.append("Description: A meta-tool that generates a new capability/tool dynamically. Use when the user asks to create/synthesize a new tool or when no existing tool can fulfill a step.")
        lines.append("Parameters:")
        lines.append("  - capability: string [REQUIRED]: The capability you need (e.g. 'spreadsheet_generation')")
        lines.append("  - reason: string [REQUIRED]: Why existing tools are insufficient.")
        lines.append("  - requirements: string [REQUIRED]: Detailed requirements for the new tool (e.g., formats, operations).")
        lines.append("DO NOT use any other arguments.\n")
        
        
        formatted_schema = "\n".join(lines)
        max_chars = settings.TOOL_SCHEMA_MAX_TOKENS * 4
        if len(formatted_schema) > max_chars:
            logger.warning(f"Tool schema exceeds maximum budget ({len(formatted_schema)} chars > {max_chars} chars)")
            # Truncating schema might break JSON, but protects context window
            formatted_schema = formatted_schema[:max_chars] + "\n...[TRUNCATED]"
            
        return formatted_schema

    # ── Synthesis Intent Detection ───────────────────────────────────────

    @staticmethod
    def _detect_synthesis_intent(prompt: str) -> bool:
        """Heuristically detects if the user is asking to create a tool dynamically."""
        keywords = [
            "make a tool", "create a tool", "build a tool", "generate a tool",
            "synthesize", "tool factory", "new tool", "custom tool",
            "write a tool", "develop a tool",
        ]
        prompt_lower = prompt.lower()
        return any(kw in prompt_lower for kw in keywords)

    # ── Tool Classification ──────────────────────────────────────────────

    @staticmethod
    def _classify_tool(
        tool_name: str,
        tool_registry,
        synthesized_tools: Set[str],
    ) -> str:
        """Classify a tool reference as EXISTING, FUTURE, or UNKNOWN.

        Returns:
            'existing'  — tool is registered and ready to use
            'future'    — tool will be created by a preceding synthesize_capability step
            'unknown'   — tool does not exist and is not scheduled for synthesis
        """
        if tool_name == "synthesize_capability":
            return "existing"  # meta-tool, always available
        if tool_registry.get_tool(tool_name):
            return "existing"
        if tool_name in synthesized_tools:
            return "future"
        return "unknown"

    # ── Plan Normalization ───────────────────────────────────────────────

    @staticmethod
    def _normalize_synthesis_plan(
        raw_steps: List[dict],
        prompt: str,
        tool_registry,
        synthesis_intent: bool,
    ) -> Tuple[List[dict], Set[str]]:
        """Normalize a plan to ensure synthesize → execute ordering.

        This fixes LLM plans that reference not-yet-created tools without
        a preceding synthesize_capability step.  It:
          1. Collects all tools that synthesize_capability steps will create.
          2. Identifies tool references that are neither existing nor scheduled
             for synthesis.
          3. If synthesis intent is detected OR unknown tools are referenced,
             injects the missing synthesize_capability steps.
          4. Reorders so synthesis always precedes execution.

        Returns:
            (normalized_steps, synthesized_tools_set)
        """
        # Pass 1: Identify tools that will be synthesized by explicit steps
        synthesized_tools: Set[str] = set()
        for s in raw_steps:
            if s.get("tool_name") == "synthesize_capability":
                args = s.get("tool_args")
                if isinstance(args, dict):
                    cap = args.get("capability")
                    if cap:
                        synthesized_tools.add(cap)

        # Pass 2: Find tool references that are unknown AND not scheduled for synthesis
        unknown_tools: Set[str] = set()
        for s in raw_steps:
            tn = s.get("tool_name")
            if tn and tn != "synthesize_capability":
                classification = Planner._classify_tool(tn, tool_registry, synthesized_tools)
                if classification == "unknown":
                    unknown_tools.add(tn)

        # Pass 3: Inject synthesis steps for unknown tools if synthesis intent detected
        #   OR if the LLM referenced tools that don't exist (likely meant to create them)
        injected_steps = []
        if unknown_tools and (synthesis_intent or len(unknown_tools) > 0):
            for ut in sorted(unknown_tools):
                logger.info(
                    "Injecting synthesize_capability for unknown tool '%s' "
                    "(synthesis_intent=%s)", ut, synthesis_intent,
                )
                injected_steps.append({
                    "step_id": 0,  # will be renumbered
                    "description": f"Synthesize the '{ut}' tool dynamically",
                    "tool_name": "synthesize_capability",
                    "tool_args": {
                        "capability": ut,
                        "reason": f"Tool '{ut}' does not exist yet — creating it to fulfill the user request.",
                        "requirements": prompt,
                    },
                })
                synthesized_tools.add(ut)

        # Pass 4: If synthesis intent is strong but NO synthesize_capability in plan at all,
        #   inject a generic one
        if synthesis_intent and not synthesized_tools and not injected_steps:
            logger.info("Synthesis intent detected but no synthesis steps — injecting generic.")
            injected_steps.append({
                "step_id": 0,
                "description": "Synthesize the requested tool",
                "tool_name": "synthesize_capability",
                "tool_args": {
                    "capability": "user_requested_tool",
                    "reason": "User explicitly asked to create a tool.",
                    "requirements": prompt,
                },
            })

        # Combine: synthesis steps first, then original steps
        normalized = injected_steps + raw_steps

        # Renumber step_ids
        for i, s in enumerate(normalized):
            s["step_id"] = i + 1

        return normalized, synthesized_tools

    # ── Plan Generation ──────────────────────────────────────────────────

    async def create_plan(
        self,
        prompt: str,
        profile: AgentProfile,
        client: OpenAICompatibleClient,
        model_id: str,
        circuit_breaker_key: Optional[str] = None,
        *,
        tool_registry,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Plan:
        """
        Generates an initial structured step-by-step plan for the user prompt using the LLM.

        `model_id` is the value sent in the API payload (may be an absolute file path
        for llama-server).  `circuit_breaker_key` is the logical registry ID used for
        circuit-breaker state; defaults to `model_id` when not provided.
        `tool_registry` is mandatory to ensure the LLM receives exact schemas.
        """
        if tool_registry is None:
            raise ValueError("tool_registry is required for Planner.create_plan()")

        # ── Step 0: Detect synthesis intent BEFORE anything else ─────────
        synthesis_intent = self._detect_synthesis_intent(prompt)
        if synthesis_intent:
            logger.info("Synthesis intent detected in prompt: %r", prompt[:120])

        tool_section = self._format_tool_schemas(profile, tool_registry)
        
        history_block = ""
        if history:
            # Implement sliding window truncation based on token budget
            max_history_chars = settings.HISTORY_MAX_TOKENS * 4
            current_chars = 0
            retained_history = []
            
            # Walk backwards from most recent message
            for msg in reversed(history):
                line = f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}"
                if current_chars + len(line) > max_history_chars:
                    retained_history.insert(0, "...[EARLIER HISTORY TRUNCATED DUE TO BUDGET]")
                    break
                retained_history.insert(0, line)
                current_chars += len(line)
                
            history_text = "\n".join(retained_history)
            history_block = (
                "Previous conversation:\n"
                f"{history_text}\n\n"
                "Use the previous conversation to resolve references such as: "
                "'another one', 'that', 'make it shorter', 'change the second option', etc. "
                "The current user request takes priority.\n\n"
            )

        system_prompt = (
            f"You are a task planner for the '{profile.name}' agent profile. "
            "Decompose the user request into clear, logical steps. "
            "Respond ONLY with a JSON object in the following format:\n"
            "{\n"
            '  "summary": "High level summary of the plan",\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_id": 1,\n'
            '      "description": "Description of the step",\n'
            '      "tool_name": "exact_tool_name_or_null",\n'
            '      "tool_args": null\n'
            '    }\n'
            "  ]\n"
            "}\n\n"
            f"{history_block}"
            f"{tool_section}\n"
            "IMPORTANT:\n"
            "- Use ONLY the exact parameters listed for the selected tool.\n"
            "- Copy parameter names exactly from the tool schema.\n"
            "- Do NOT invent, rename, or add parameters.\n"
            "- tool_args must be a JSON object containing only valid parameters for that tool.\n"
            "- If the tool has no arguments, use an empty object {}.\n"
            "- If no tool is needed, set tool_name and tool_args to null.\n"
            "- If the user asks to CREATE or SYNTHESIZE a new tool, use 'synthesize_capability' as tool_name.\n"
            "- After synthesizing a tool, add a separate step to EXECUTE it.\n"
        )
        
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            response = await client.chat(
                model=model_id,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,  # 4K planner budget
                circuit_breaker_key=circuit_breaker_key,
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Strip <think> tags (Qwen3)
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            
            # Simple heuristic to extract JSON if surrounded by markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            data = json.loads(content)
            raw_steps = data.get("steps", [])

            # ── Step 1: Normalize plan for synthesis ordering ────────────
            normalized_steps, synthesized_tools = self._normalize_synthesis_plan(
                raw_steps, prompt, tool_registry, synthesis_intent
            )

            # ── Step 2: Validate and build Step objects ──────────────────
            steps = []
            for s in normalized_steps:
                tool_name = s.get("tool_name")
                tool_args = s.get("tool_args")

                if tool_name and tool_name != "synthesize_capability":
                    classification = self._classify_tool(
                        tool_name, tool_registry, synthesized_tools
                    )

                    if classification == "existing":
                        # Validate arguments against registered schema
                        try:
                            tool_registry.validate_tool_call(tool_name, tool_args)
                        except ValueError as ve:
                            logger.warning(
                                "Validation failed for existing tool '%s': %s — "
                                "keeping step, executor will handle retry.",
                                tool_name, ve,
                            )
                    elif classification == "future":
                        # Tool will be created by a preceding synthesize_capability step.
                        # We can't validate args yet — skip validation gracefully.
                        logger.info(
                            "Skipping validation for future tool '%s' — "
                            "will be synthesized during execution.", tool_name,
                        )
                    else:
                        # Genuinely unknown: no synthesis planned, not in registry
                        logger.warning(
                            "Dropping step with genuinely unknown tool '%s' — "
                            "not in registry and not scheduled for synthesis.",
                            tool_name,
                        )
                        continue  # skip this step entirely

                steps.append(
                    Step(
                        step_id=s.get("step_id", len(steps) + 1),
                        description=s.get("description", "Step"),
                        tool_name=tool_name,
                        tool_args=tool_args,
                    )
                )

            return Plan(summary=data.get("summary", "Generated Plan"), steps=steps)
            
        except Exception as e:
            logger.error(
                "Planner failed: %s\nLLM output: %r",
                e,
                content if "content" in locals() else None,
                exc_info=True,
            )
            # ── Fallback: if synthesis intent was detected, produce a
            #    minimal plan with synthesize_capability instead of a
            #    bare LLM-only step that can't do anything useful.
            if synthesis_intent:
                logger.info(
                    "Planner exception with synthesis intent — "
                    "generating fallback synthesis plan."
                )
                return Plan(
                    summary=f"Synthesize tool (fallback): {prompt[:80]}",
                    steps=[
                        Step(
                            step_id=1,
                            description="Synthesize the requested tool",
                            tool_name="synthesize_capability",
                            tool_args={
                                "capability": "user_requested_tool",
                                "reason": "Planner failed to generate a valid plan; falling back to direct synthesis.",
                                "requirements": prompt,
                            },
                        )
                    ],
                )

            return Plan(
                summary=f"Process request (fallback): {prompt}",
                steps=[
                    Step(
                        step_id=1,
                        description=f"Analyze and execute task: {prompt}",
                        tool_name=None,
                        tool_args=None
                    )
                ]
            )