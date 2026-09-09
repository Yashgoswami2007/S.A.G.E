import json
import logging
from typing import List, Optional, Dict
from sage.agent.schemas import Plan, Step
from sage.models.client import OpenAICompatibleClient
from sage.agent.profiles.base import AgentProfile

logger = logging.getLogger("sage.agent.planner")


class Planner:

    @staticmethod
    def _format_tool_schemas(profile: AgentProfile, tool_registry) -> str:
        """Build tool documentation from the single source of truth: the registry."""
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
        return "\n".join(lines)

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
        `history` contains prior text-only conversation turns.
        """
        if tool_registry is None:
            raise ValueError("tool_registry is required for Planner.create_plan()")

        tool_section = self._format_tool_schemas(profile, tool_registry)

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
            f"{tool_section}\n"
            "IMPORTANT:\n"
            "- Use ONLY the exact parameters listed for the selected tool.\n"
            "- Copy parameter names exactly from the tool schema.\n"
            "- Do NOT invent, rename, or add parameters.\n"
            "- tool_args must be a JSON object containing only valid parameters for that tool.\n"
            "- If the tool has no arguments, use an empty object {}.\n"
            "- If no tool is needed, set tool_name and tool_args to null.\n"
        )
        
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                *(history or []),
                {"role": "user", "content": prompt},
            ]
            
            response = await client.chat(
                model=model_id,
                messages=messages,
                temperature=0.1,
                max_tokens=2048,
                circuit_breaker_key=circuit_breaker_key,
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            data = json.loads(content)
            
            steps = []
            for s in data.get("steps", []):
                tool_name = s.get("tool_name")
                tool_args = s.get("tool_args")

                if tool_name:
                    tool_registry.validate_tool_call(tool_name, tool_args)

                steps.append(Step(
                    step_id=s.get("step_id", len(steps) + 1),
                    description=s.get("description", "Step"),
                    tool_name=tool_name,
                    tool_args=tool_args
                ))
                
            return Plan(summary=data.get("summary", "Generated Plan"), steps=steps)
            
        except Exception as e:
            logger.error(
                "Planner failed: %s\nLLM output: %r",
                e,
                content if "content" in locals() else None,
                exc_info=True,
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

