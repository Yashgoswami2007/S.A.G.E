import json
import logging
from sage.tool_factory.models import ToolSpecification, FactoryError, ToolSynthesisState
from sage.sandbox.sandbox_manager import SandboxManager
from sage.config import settings

logger = logging.getLogger("sage.tool_factory.tester")

def _generate_dummy_inputs(schema: dict) -> dict:
    inputs = {}
    properties = schema.get("properties", {})
    for key, prop in properties.items():
        type_ = prop.get("type", "string")
        if type_ == "string":
            inputs[key] = "dummy_string"
        elif type_ == "integer" or type_ == "number":
            inputs[key] = 1
        elif type_ == "boolean":
            inputs[key] = True
        elif type_ == "array":
            inputs[key] = []
        elif type_ == "object":
            inputs[key] = {}
        else:
            inputs[key] = None
    return inputs

class ToolTester:
    """Tests generated tool code in a sandbox using a deterministic wrapper script."""
    
    def __init__(self, sandbox_manager: SandboxManager):
        self.sandbox_manager = sandbox_manager

    def generate_test_script(self, spec: ToolSpecification, code: str) -> str:
        """Generates a deterministic test script that validates the tool."""
        dummy_inputs = _generate_dummy_inputs(spec.input_schema)
        
        wrapper_script = (
            f"{code}\n\n"
            f"import asyncio\n"
            f"import json\n"
            f"import sys\n"
            f"async def __main__():\n"
            f"    try:\n"
            f"        tool_class = next(c for n, c in globals().items() if isinstance(c, type) and c.__name__ != 'BaseTool' and issubclass(c, BaseTool))\n"
            f"        tool_instance = tool_class()\n"
            f"        kwargs = {json.dumps(dummy_inputs)}\n"
            f"        result = await tool_instance.execute(**kwargs)\n"
            f"        if result.success:\n"
            f"            print('TEST_PASSED')\n"
            f"        else:\n"
            f"            print('TEST_FAILED: ' + str(result.error))\n"
            f"    except Exception as e:\n"
            f"        print('TEST_FAILED_EXCEPTION: ' + str(e))\n"
            f"asyncio.run(__main__())\n"
        )
        return wrapper_script

    async def test_tool(self, spec: ToolSpecification, code: str) -> bool:
        """Runs the deterministic test script in the sandbox."""
        test_script = self.generate_test_script(spec, code)
        
        # Execute with working_dir=WORKSPACE_DIR for containment & relative paths
        result = await self.sandbox_manager.execute_code(
            test_script, 
            language="python",
            working_dir=settings.WORKSPACE_DIR
        )
        
        if not result.success:
            raise FactoryError(
                stage=ToolSynthesisState.TESTING,
                error_type="SANDBOX_CRASH",
                message="Sandbox execution crashed or timed out.",
                details=f"Exit Code: {result.exit_code}\nStdout: {result.stdout}\nStderr: {result.stderr}",
                repairable=True
            )
            
        if "TEST_FAILED_EXCEPTION" in result.stdout:
            raise FactoryError(
                stage=ToolSynthesisState.TESTING,
                error_type="TEST_EXCEPTION",
                message="Tool execution raised an exception.",
                details=f"Output:\n{result.stdout}\nStderr:\n{result.stderr}",
                repairable=True
            )
            
        if "TEST_FAILED" in result.stdout:
            raise FactoryError(
                stage=ToolSynthesisState.TESTING,
                error_type="TEST_FAILURE",
                message="Tool execute() returned success=False.",
                details=f"Output:\n{result.stdout}\nStderr:\n{result.stderr}",
                repairable=True
            )
            
        if "TEST_PASSED" not in result.stdout:
            raise FactoryError(
                stage=ToolSynthesisState.TESTING,
                error_type="TEST_INCOMPLETE",
                message="Test did not output TEST_PASSED or failed silently.",
                details=f"Output:\n{result.stdout}\nStderr:\n{result.stderr}",
                repairable=True
            )
            
        return True
