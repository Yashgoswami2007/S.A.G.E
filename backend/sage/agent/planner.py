from typing import List
from sage.agent.schemas import Plan, Step
from sage.models.client import OpenAICompatibleClient
from sage.agent.profiles.base import AgentProfile
import json

class Planner:
    async def create_plan(
        self,
        prompt: str,
        profile: AgentProfile,
        client: OpenAICompatibleClient,
        model_id: str
    ) -> Plan:
        """
        Generates an initial structured step-by-step plan for the user prompt using the LLM.
        """
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
            '      "tool_name": "name_of_tool_if_applicable",\n'
            '      "tool_args": {"arg1": "value1"}\n'
            '    }\n'
            "  ]\n"
            "}\n\n"
            f"Allowed tools for this profile: {', '.join(profile.allowed_tools)}.\n"
            "If no tools are needed, leave tool_name and tool_args as null."
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
                max_tokens=2048  # increased: Qwen3 <think> blocks need headroom
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Simple heuristic to extract JSON if surrounded by markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            data = json.loads(content)
            
            steps = []
            for s in data.get("steps", []):
                steps.append(Step(
                    step_id=s.get("step_id", 1),
                    description=s.get("description", "Step"),
                    tool_name=s.get("tool_name"),
                    tool_args=s.get("tool_args")
                ))
                
            return Plan(summary=data.get("summary", "Generated Plan"), steps=steps)
            
        except Exception as e:
            # Fallback to general plan on parsing error
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
