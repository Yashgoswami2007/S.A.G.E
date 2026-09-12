import json
import logging
import re
from typing import Optional
from sage.models.client import OpenAICompatibleClient
from sage.tool_factory.models import ToolSpecification, FactoryError, ToolSynthesisState

logger = logging.getLogger("sage.tool_factory.designer")

class ToolDesigner:
    """Designs a tool specification based on task requirements and capabilities."""
    
    def __init__(self, client: OpenAICompatibleClient, model_id: str):
        self.client = client
        self.model_id = model_id
        
    async def design_tool(self, capability: str, task_context: str, requirements: str) -> ToolSpecification:
        system_prompt = (
            "You are a Tool Designer for the SAGE agent. Your job is to design a new tool specification.\n"
            "The tool must fulfill the requested capability. The tool will be implemented as a Python class.\n"
            "Return ONLY a JSON object representing the tool specification with no extra text or markdown, matching this schema:\n"
            "{\n"
            '  "name": "snake_case_tool_name",\n'
            '  "description": "Clear description of what the tool does",\n'
            '  "capability": "the requested capability",\n'
            '  "version": "1.0.0",\n'
            '  "input_schema": {"type": "object", "properties": {...}, "required": [...]},\n'
            '  "output_schema": {"type": "object", "properties": {...}},\n'
            '  "dependencies": ["list of python packages, e.g. openpyxl"],\n'
            '  "permissions": {\n'
            '    "filesystem": {"read": ["workspace"], "write": ["artifacts"]},\n'
            '    "network": false,\n'
            '    "subprocess": false\n'
            '  },\n'
            '  "runtime": {"language": "python", "timeout_seconds": 60}\n'
            "}\n\n"
            "IMPORTANT: Request ONLY the permissions absolutely necessary. Default network and subprocess to false."
        )
        
        user_prompt = (
            f"Capability requested: {capability}\n\n"
            f"Task Context:\n{task_context}\n\n"
            f"Requirements:\n{requirements}\n\n"
            "Please design the tool specification."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            resp = await self.client.chat(model=self.model_id, messages=messages, temperature=0.1)
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Strip think tags first
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            
            # Simple heuristic to extract JSON if surrounded by markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            else:
                # Find first { and last }
                start = content.find('{')
                end = content.rfind('}')
                if start != -1 and end != -1:
                    content = content[start:end+1]
                
            try:
                data = json.loads(content)
            except json.JSONDecodeError as jde:
                # Attempt to strip trailing commas
                content = re.sub(r',\s*([\]}])', r'\1', content)
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as jde2:
                    raise FactoryError(
                        stage=ToolSynthesisState.DESIGNING,
                        error_type="JSON_PARSE_ERROR",
                        message="Failed to parse LLM output as JSON.",
                        details=f"Error: {jde2}\nRaw Content: {content}",
                        repairable=True
                    )
                    
            try:
                return ToolSpecification(**data)
            except Exception as ve:
                raise FactoryError(
                    stage=ToolSynthesisState.DESIGNING,
                    error_type="SPEC_VALIDATION_ERROR",
                    message="Parsed JSON does not match ToolSpecification schema.",
                    details=f"Error: {ve}\nParsed JSON: {data}",
                    repairable=True
                )
            
        except FactoryError:
            raise
        except Exception as e:
            logger.error("Failed to design tool: %s", e, exc_info=True)
            raise FactoryError(
                stage=ToolSynthesisState.DESIGNING,
                error_type="INTERNAL_ERROR",
                message=f"An unexpected error occurred during design: {str(e)}",
                details=str(e),
                repairable=False
            )
