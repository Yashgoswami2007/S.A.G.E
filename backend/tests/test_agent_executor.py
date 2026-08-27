import unittest
import asyncio
import tempfile
import pathlib
from sage.models.registry import ModelRegistry
from sage.agent.router import ModelRouter
from sage.tools import create_default_tool_registry
from sage.agent.profiles import ProfileManager
from sage.agent.executor import ReActExecutor
from sage.agent.state import AgentState

class TestAgentExecutor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        yaml_content = """
models:
  - id: reasoning-model
    name: Reasoning Model
    model_path: /models/reasoning.gguf
    server_port: 8001
    capabilities: ["reasoning"]
    priority: 1
    min_vram_gb: 6
    context_length: 8192
"""
        p = pathlib.Path(self.temp_dir.name) / "model_registry.yaml"
        p.write_text(yaml_content)
        registry = ModelRegistry(str(p))
        router = ModelRouter(registry)
        tools = create_default_tool_registry()
        profiles = ProfileManager()
        self.executor = ReActExecutor(router=router, tool_registry=tools, profile_manager=profiles)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_end_to_end_list_dir(self):
        async def _async_test():
            from sage.config import settings
            settings.WORKSPACE_DIR = self.temp_dir.name
            (pathlib.Path(self.temp_dir.name) / "sample.txt").write_text("demo file")

            resp = await self.executor.run(
                prompt="List the files in my workspace",
                profile_name="general"
            )

            self.assertEqual(resp.status, AgentState.COMPLETED)
            self.assertIn("sample.txt", resp.output)

            # Verify trace structure
            trace = resp.trace
            self.assertEqual(trace.task_id, resp.task_id)
            self.assertEqual(trace.selected_model, "reasoning-model")
            self.assertGreaterEqual(len(trace.events), 5)

            states = [e.agent_state for e in trace.events]
            self.assertIn(AgentState.PLANNING, states)
            self.assertIn(AgentState.ACTING, states)
            self.assertIn(AgentState.OBSERVING, states)
            self.assertIn(AgentState.REFLECTING, states)
            self.assertIn(AgentState.DELIVERING, states)
            self.assertIn(AgentState.COMPLETED, states)

        asyncio.run(_async_test())

    def test_retry_limits_on_failure(self):
        async def _async_test():
            # Mock a tool that always fails to test max retries
            class FailingTool:
                name = "fail_tool"
                description = "Always fails"
                permission = "SAFE"
                parameters = {}
                async def execute(self, **kwargs):
                    from sage.tools.base import ToolResult
                    return ToolResult(success=False, output="", error="Forced failure")

            self.executor.tool_registry.register(FailingTool())
            
            # Force planner to call failing tool
            async def mock_plan(*args, **kwargs):
                from sage.agent.schemas import Plan, Step
                return Plan(summary="Fail test", steps=[Step(step_id=1, description="fail", tool_name="fail_tool")])

            self.executor.planner.create_plan = mock_plan

            resp = await self.executor.run(prompt="test failure limits", profile_name="general")
            self.assertEqual(resp.status, AgentState.FAILED)
            
            # Check that retry count was tracked
            fail_events = [e for e in resp.trace.events if e.retry_count > 0]
            self.assertGreaterEqual(len(fail_events), 3)

        asyncio.run(_async_test())

if __name__ == "__main__":
    unittest.main()
