"""Tests for Planner schema generation, mandatory registry requirement, and step validation."""
import unittest
import asyncio
from unittest.mock import AsyncMock

from sage.agent.planner import Planner
from sage.agent.profiles import ProfileManager
from sage.agent.schemas import Plan
from sage.tools import create_default_tool_registry


class TestPlanner(unittest.TestCase):
    def setUp(self):
        self.planner = Planner()
        self.registry = create_default_tool_registry()
        self.profile_mgr = ProfileManager()
        self.coder_profile = self.profile_mgr.get_profile("coder")

    def test_search_files_schema_is_exposed_to_planner(self):
        """Verify the exact tool parameters contract for search_files."""
        tool = self.registry.get_tool("search_files")
        self.assertIsNotNone(tool)

        schema = tool.parameters
        self.assertIn("pattern", schema["properties"])
        self.assertIn("query", schema["properties"])
        self.assertIn("pattern", schema["required"])
        self.assertNotIn("path", schema["properties"])

    def test_format_tool_schemas_renders_exact_parameters(self):
        """Planner's prompt section must contain parameters, required/optional tags, and no path."""
        prompt_section = self.planner._format_tool_schemas(self.coder_profile, self.registry)
        
        # Must describe search_files and its exact arguments
        self.assertIn("search_files", prompt_section)
        self.assertIn("pattern: string [REQUIRED]", prompt_section)
        self.assertIn("query: string [OPTIONAL]", prompt_section)
        self.assertIn("DO NOT use any other arguments", prompt_section)
        
        # Must not mention path as a parameter for search_files
        search_files_block = prompt_section.split("search_files")[1].split("DO NOT use any other arguments")[0]
        self.assertNotIn("path", search_files_block)

    def test_create_plan_rejects_missing_or_none_registry(self):
        """create_plan must enforce tool_registry requirement."""
        mock_client = AsyncMock()
        
        # Passing None should raise ValueError
        with self.assertRaises(ValueError):
            asyncio.run(
                self.planner.create_plan(
                    prompt="test",
                    profile=self.coder_profile,
                    client=mock_client,
                    model_id="test-model",
                    tool_registry=None,
                )
            )

    def test_planner_validates_and_rejects_unexpected_path_arg(self):
        """When LLM returns a plan with unexpected 'path' arg for search_files,
        planner catches it and safely falls back to a safe general plan.
        """
        mock_client = AsyncMock()
        # Mock LLM returning hallucinated 'path' argument
        mock_client.chat.return_value = {
            "choices": [{
                "message": {
                    "content": '```json\n{"summary": "Search PDFs", "steps": [{"step_id": 1, "description": "find pdfs", "tool_name": "search_files", "tool_args": {"path": ".", "pattern": "*.pdf"}}]}\n```'
                }
            }]
        }

        plan: Plan = asyncio.run(
            self.planner.create_plan(
                prompt="find all pdfs",
                profile=self.coder_profile,
                client=mock_client,
                model_id="test-model",
                tool_registry=self.registry,
            )
        )

        # Because 'path' was unexpected, plan validation failed and fallback plan was returned
        self.assertIn("fallback", plan.summary.lower())
        self.assertEqual(len(plan.steps), 1)
        self.assertIsNone(plan.steps[0].tool_name)

    def test_planner_accepts_valid_tool_args(self):
        """When LLM returns valid tool arguments, the plan is accepted."""
        mock_client = AsyncMock()
        # Mock LLM returning valid arguments for search_files
        mock_client.chat.return_value = {
            "choices": [{
                "message": {
                    "content": '```json\n{"summary": "Search PDFs", "steps": [{"step_id": 1, "description": "find pdfs", "tool_name": "search_files", "tool_args": {"pattern": "*.pdf"}}]}\n```'
                }
            }]
        }

        plan: Plan = asyncio.run(
            self.planner.create_plan(
                prompt="find all pdfs",
                profile=self.coder_profile,
                client=mock_client,
                model_id="test-model",
                tool_registry=self.registry,
            )
        )

        self.assertEqual(plan.summary, "Search PDFs")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool_name, "search_files")
        self.assertEqual(plan.steps[0].tool_args, {"pattern": "*.pdf"})


if __name__ == "__main__":
    unittest.main()
