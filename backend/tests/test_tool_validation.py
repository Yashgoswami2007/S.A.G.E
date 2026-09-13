"""Regression tests for tool argument validation.

These tests exercise the exact failure scenarios encountered in production:
- search_files called with an unexpected 'path' argument  (was: crash)
- search_files with correct arguments                     (was: never reached)
- list_dir with various path arguments
- Argument validation: missing required, wrong type, traversal
"""
import unittest
import asyncio
import tempfile
import os
from pathlib import Path

from sage.tools import create_default_tool_registry
from sage.config import settings


class TestSearchFilesValidation(unittest.TestCase):
    """Regression: search_files(path=".", pattern="*.pdf") must not crash."""

    def setUp(self):
        self.registry = create_default_tool_registry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self._orig_workspace = settings.WORKSPACE_DIR
        settings.WORKSPACE_DIR = self.temp_dir.name

        # Create test files
        uploads = Path(self.temp_dir.name) / "uploads"
        uploads.mkdir()
        (uploads / "report.pdf").write_text("invoice data")
        (uploads / "notes.txt").write_text("some notes")

    def tearDown(self):
        settings.WORKSPACE_DIR = self._orig_workspace
        self.temp_dir.cleanup()

    def test_search_files_valid_pattern(self):
        """search_files(pattern='*.pdf') → succeeds"""
        async def _test():
            res = await self.registry.execute_tool("search_files", {"pattern": "*.pdf"})
            self.assertTrue(res.success, f"Expected success but got error: {res.error}")
            self.assertIn("report.pdf", res.output)
        asyncio.run(_test())

    def test_search_files_with_query(self):
        """search_files(pattern='*.pdf', query='invoice') → succeeds"""
        async def _test():
            res = await self.registry.execute_tool("search_files", {"pattern": "*.pdf", "query": "invoice"})
            self.assertTrue(res.success, f"Expected success but got error: {res.error}")
            self.assertIn("report.pdf", res.output)
        asyncio.run(_test())

    def test_search_files_unexpected_path_arg(self):
        """search_files(path='.', pattern='*.pdf') → structured validation error, not crash."""
        async def _test():
            res = await self.registry.execute_tool(
                "search_files",
                {"path": ".", "pattern": "*.pdf"},
            )
            self.assertFalse(res.success)
            self.assertIn("unexpected arguments", res.error.lower())
            self.assertIn("path", res.error)
            self.assertIn("pattern", res.error)  # valid args listed in error
            self.assertIn("query", res.error)    # valid args listed in error
        asyncio.run(_test())

    def test_search_files_wrong_type(self):
        """search_files(pattern=123) → type validation error."""
        async def _test():
            res = await self.registry.execute_tool("search_files", {"pattern": 123})
            self.assertFalse(res.success)
            self.assertIn("expected type", res.error.lower())
            self.assertIn("string", res.error)
        asyncio.run(_test())

    def test_search_files_missing_required(self):
        """search_files() with no pattern → missing required error."""
        async def _test():
            res = await self.registry.execute_tool("search_files", {})
            self.assertFalse(res.success)
            self.assertIn("missing required", res.error.lower())
            self.assertIn("pattern", res.error)
        asyncio.run(_test())

    def test_search_files_schema_is_exposed_to_planner(self):
        """Exact test: search_files schema must expose pattern and query, NOT path."""
        tool = self.registry.get_tool("search_files")
        self.assertIsNotNone(tool)

        schema = tool.parameters
        self.assertIn("pattern", schema["properties"])
        self.assertIn("query", schema["properties"])
        self.assertIn("pattern", schema["required"])
        self.assertNotIn("path", schema["properties"])

    def test_integer_validation_rejects_boolean(self):
        """Registry validation must not treat boolean True/False as integer."""
        async def _test():
            res = await self.registry.execute_tool(
                "read_xlsx",
                {"path": "test.xlsx", "max_rows": True},
            )
            self.assertFalse(res.success)
            self.assertIn("expected type 'integer', got bool", res.error)
        asyncio.run(_test())


class TestReadPDFArgumentAliases(unittest.TestCase):
    """Regression: LLM often sends file_path instead of path for read_pdf."""

    def setUp(self):
        self.registry = create_default_tool_registry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self._orig_workspace = settings.WORKSPACE_DIR
        settings.WORKSPACE_DIR = self.temp_dir.name

        pdf_path = Path(self.temp_dir.name) / "sample.pdf"
        try:
            import fitz
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Hello PDF")
            doc.save(str(pdf_path))
            doc.close()
        except ImportError:
            pdf_path.write_bytes(b"%PDF-1.4 minimal")

    def tearDown(self):
        settings.WORKSPACE_DIR = self._orig_workspace
        self.temp_dir.cleanup()

    def test_read_pdf_accepts_file_path_alias(self):
        async def _test():
            res = await self.registry.execute_tool(
                "read_pdf",
                {"file_path": "sample.pdf"},
            )
            # Alias normalization should map file_path -> path (not crash on bad kwarg)
            self.assertNotIn("unexpected keyword argument", res.error or "")
            self.assertNotIn("unexpected arguments", (res.error or "").lower())
            if res.success:
                self.assertIn("sample.pdf", res.output)
            else:
                # Without PyMuPDF installed, we still expect a dependency error — not arg error
                self.assertIn("PyMuPDF", res.error or "")
        asyncio.run(_test())

    def test_read_pdf_rejects_unknown_args_after_normalization(self):
        async def _test():
            res = await self.registry.execute_tool(
                "read_pdf",
                {"file_path": "sample.pdf", "unknown_arg": "x"},
            )
            self.assertFalse(res.success)
            self.assertIn("unexpected arguments", res.error.lower())
        asyncio.run(_test())


class TestListDirValidation(unittest.TestCase):
    """Regression: list_dir must return actual workspace contents."""

    def setUp(self):
        self.registry = create_default_tool_registry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self._orig_workspace = settings.WORKSPACE_DIR
        settings.WORKSPACE_DIR = self.temp_dir.name

        # Create workspace structure
        sandbox = Path(self.temp_dir.name) / "sandbox_runs"
        sandbox.mkdir()
        uploads = Path(self.temp_dir.name) / "uploads"
        uploads.mkdir()
        (uploads / "test.pdf").write_text("pdf content")

    def tearDown(self):
        settings.WORKSPACE_DIR = self._orig_workspace
        self.temp_dir.cleanup()

    def test_list_dir_default_empty_args(self):
        """list_dir({}) → workspace contents (default path='.')"""
        async def _test():
            res = await self.registry.execute_tool("list_dir", {})
            self.assertTrue(res.success, f"Expected success but got error: {res.error}")
            self.assertIn("sandbox_runs", res.output)
            self.assertIn("uploads", res.output)
        asyncio.run(_test())

    def test_list_dir_dot(self):
        """list_dir('.') → same as default"""
        async def _test():
            res = await self.registry.execute_tool("list_dir", {"path": "."})
            self.assertTrue(res.success, f"Expected success but got error: {res.error}")
            self.assertIn("sandbox_runs", res.output)
            self.assertIn("uploads", res.output)
        asyncio.run(_test())

    def test_list_dir_subdirectory(self):
        """list_dir('uploads') → uploaded file(s)"""
        async def _test():
            res = await self.registry.execute_tool("list_dir", {"path": "uploads"})
            self.assertTrue(res.success, f"Expected success but got error: {res.error}")
            self.assertIn("test.pdf", res.output)
        asyncio.run(_test())

    def test_list_dir_traversal_blocked(self):
        """list_dir('../') → blocked by containment check"""
        async def _test():
            res = await self.registry.execute_tool("list_dir", {"path": "../"})
            # Should fail — either PermissionError caught as ToolResult error,
            # or the path doesn't pass containment check
            self.assertFalse(res.success)
        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
