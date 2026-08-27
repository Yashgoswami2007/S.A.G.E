import unittest
import asyncio
import tempfile
import pathlib
from sage.tools import create_default_tool_registry
from sage.tools.base import ToolPermission
from sage.agent.profiles import ProfileManager

class TestTools(unittest.TestCase):
    def setUp(self):
        self.registry = create_default_tool_registry()
        self.profile_mgr = ProfileManager()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_all_7_tools_registered(self):
        expected_tools = {
            "read_file", "write_file", "list_dir",
            "search_files", "execute_command", "get_file_info", "apply_patch"
        }
        registered = {t.name for t in self.registry.list_tools()}
        self.assertTrue(expected_tools.issubset(registered))

    def test_openai_schema_generation(self):
        schemas = self.registry.get_openai_schemas()
        self.assertEqual(len(schemas), 7)
        for s in schemas:
            self.assertEqual(s["type"], "function")
            self.assertIn("name", s["function"])
            self.assertIn("description", s["function"])
            self.assertIn("parameters", s["function"])

    def test_tool_permission_enforcement(self):
        analyst = self.profile_mgr.get_profile("analyst")
        coder = self.profile_mgr.get_profile("coder")

        # Analyst is restricted to safe tools
        self.assertTrue(analyst.is_tool_allowed("read_file", ToolPermission.SAFE))
        self.assertFalse(analyst.is_tool_allowed("write_file", ToolPermission.MODIFY))
        self.assertFalse(analyst.is_tool_allowed("execute_command", ToolPermission.HIGH_RISK))

        # Coder has access to all tools
        self.assertTrue(coder.is_tool_allowed("execute_command", ToolPermission.HIGH_RISK))

    def test_file_operations(self):
        async def _async_test():
            from sage.config import settings
            settings.WORKSPACE_DIR = self.temp_dir.name

            # 1. write_file
            res_write = await self.registry.execute_tool("write_file", {"path": "test.txt", "content": "hello world"})
            self.assertTrue(res_write.success)

            # 2. read_file
            res_read = await self.registry.execute_tool("read_file", {"path": "test.txt"})
            self.assertTrue(res_read.success)
            self.assertEqual(res_read.output, "hello world")

            # 3. list_dir
            res_list = await self.registry.execute_tool("list_dir", {"path": "."})
            self.assertTrue(res_list.success)
            self.assertIn("test.txt", res_list.output)

            # 4. get_file_info
            res_info = await self.registry.execute_tool("get_file_info", {"path": "test.txt"})
            self.assertTrue(res_info.success)
            self.assertEqual(res_info.data["name"], "test.txt")

            # 5. search_files
            res_search = await self.registry.execute_tool("search_files", {"pattern": "*.txt", "query": "hello"})
            self.assertTrue(res_search.success)
            self.assertIn("test.txt", res_search.output)

            # 6. apply_patch
            res_patch = await self.registry.execute_tool("apply_patch", {"path": "test.txt", "target": "hello", "replacement": "goodbye"})
            self.assertTrue(res_patch.success)
            res_read2 = await self.registry.execute_tool("read_file", {"path": "test.txt"})
            self.assertEqual(res_read2.output, "goodbye world")

        asyncio.run(_async_test())

    def test_execute_command(self):
        async def _async_test():
            from sage.config import settings
            settings.WORKSPACE_DIR = self.temp_dir.name
            res = await self.registry.execute_tool("execute_command", {"command": "echo 'sage test'"})
            self.assertTrue(res.success)
            self.assertIn("sage test", res.output)

        asyncio.run(_async_test())

if __name__ == "__main__":
    unittest.main()
