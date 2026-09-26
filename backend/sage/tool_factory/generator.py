import logging
import re
from typing import Optional
from sage.models.client import OpenAICompatibleClient
from sage.tool_factory.models import ToolSpecification, FactoryError, ToolSynthesisState
from sage.security.policy import SecurityProfile

logger = logging.getLogger("sage.tool_factory.generator")

class ToolGenerator:
    """Generates Python code for a tool based on a specification."""
    
    def __init__(self, client: OpenAICompatibleClient, model_id: str):
        self.client = client
        self.model_id = model_id
        
    async def generate_code(self, spec: ToolSpecification, profile: SecurityProfile, error_feedback: str = "") -> str:
        
        blocked_str = ", ".join(profile.blocked_modules) if profile.blocked_modules else "None"
        allowed_str = ", ".join(profile.allowed_modules) if profile.allowed_modules else "Any standard module"
        blocked_functions = ("eval, exec, globals, locals, compile, __import__")

        system_prompt = (
                "You are an expert Python developer generating a tool for the SAGE agent.\n"
                "You must implement a subclass of `BaseTool` from `sage.tools.base`.\n"
                "The generated code will be saved as a Python file and executed in an isolated environment.\n\n"

                "Rules:\n"
                "1. You MUST import BaseTool and ToolResult from sage.tools.base\n"
                "2. Define a class that inherits from BaseTool.\n"
                "3. Set the `name`, `description`, and `parameters` (input schema) class attributes.\n"
                "4. Implement the `async def execute(self, **kwargs) -> ToolResult:` method.\n"
                "5. Return a `ToolResult(success=..., output=..., error=...)`.\n"
                f"6. SECURITY CONSTRAINT: You MUST NOT import or use these blocked modules: {blocked_str}.\n"
                f"7. SECURITY CONSTRAINT: You MUST NOT call these blocked functions: {blocked_functions}.\n"
                f"8. You are encouraged to use these allowed modules: {allowed_str}.\n"
                "9. Do not attempt to bypass or circumvent any security restriction.\n"
                "10. Return ONLY valid Python code wrapped in ```python ... ``` block. No other text.\n"
            )
        
        user_prompt = (
            f"Please generate the Python code for this tool specification:\n"
            f"Name: {spec.name}\n"
            f"Description: {spec.description}\n"
            f"Input Schema: {spec.input_schema}\n"
            f"Dependencies: {spec.dependencies}\n"
        )
        
        if error_feedback:
            user_prompt += f"\n\nPREVIOUS ERROR TO FIX:\n{error_feedback}\n"
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            resp = await self.client.chat(model=self.model_id, messages=messages, temperature=0.2)
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Strip think tags first
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            
            # Extract python code
            if "```python" in content:
                code = content.split("```python")[1].split("```")[0].strip()
            elif "```" in content:
                code = content.split("```")[1].split("```")[0].strip()
            else:
                code = content
                
            if not code or "class " not in code:
                raise FactoryError(
                    stage=ToolSynthesisState.GENERATING,
                    error_type="MISSING_CODE_BLOCK",
                    message="Failed to extract valid Python code from LLM output.",
                    details=f"Raw output:\n{content}",
                    repairable=True
                )
                
            return code
            
        except FactoryError:
            raise
        except Exception as e:
            logger.error("Failed to generate tool code: %s", e, exc_info=True)
            raise FactoryError(
                stage=ToolSynthesisState.GENERATING,
                error_type="INTERNAL_ERROR",
                message=f"An unexpected error occurred during generation: {str(e)}",
                details=str(e),
                repairable=False
            )
