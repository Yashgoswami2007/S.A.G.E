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
        Generates an initial structured step-by-step plan for the user prompt.
        """
        system_prompt = (
            f"You are a task planner for the '{profile.name}' agent profile. "
            "Decompose the user request into clear, logical steps. "
            "Allowed tools for this profile: " + ", ".join(profile.allowed_tools) + "."
        )
        
        # Simple heuristic planning for basic queries
        if "list" in prompt.lower() and "file" in prompt.lower():
            return Plan(
                summary="List files in the workspace directory",
                steps=[
                    Step(
                        step_id=1,
                        description="List files in workspace using list_dir",
                        tool_name="list_dir",
                        tool_args={"path": "."}
                    )
                ]
            )
            
        if "read" in prompt.lower():
            return Plan(
                summary="Read specified file from workspace",
                steps=[
                    Step(
                        step_id=1,
                        description="Read file contents using read_file",
                        tool_name="read_file",
                        tool_args={"path": "."}
                    )
                ]
            )

        # Default general plan
        return Plan(
            summary=f"Process request: {prompt}",
            steps=[
                Step(
                    step_id=1,
                    description=f"Analyze and execute task: {prompt}",
                    tool_name=None,
                    tool_args=None
                )
            ]
        )
