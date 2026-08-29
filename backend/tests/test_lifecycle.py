import unittest
import asyncio
import tempfile
import pathlib
import os
from unittest.mock import patch, MagicMock, AsyncMock

from sage.models.registry import ModelRegistry, ModelConfig
from sage.models.lifecycle import ModelLifecycleManager

class TestModelLifecycleManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        yaml_content = """
models:
  - id: test-model-1
    name: Test Model 1
    model_path: /invalid/path/does/not/exist.gguf
    server_port: 8001
    capabilities: ["reasoning"]
    priority: 1
    min_vram_gb: 1
    context_length: 2048
    auto_start: true
  - id: test-model-2
    name: Test Model 2
    model_path: {valid_path}
    server_port: 8002
    capabilities: ["coding"]
    priority: 1
    min_vram_gb: 1
    context_length: 2048
    auto_start: true
"""
        self.valid_file_path = pathlib.Path(self.temp_dir.name) / "dummy.gguf"
        self.valid_file_path.write_text("dummy")
        
        yaml_path = pathlib.Path(self.temp_dir.name) / "registry.yaml"
        yaml_path.write_text(yaml_content.replace("{valid_path}", str(self.valid_file_path)))
        
        self.registry = ModelRegistry(str(yaml_path))
        self.lifecycle = ModelLifecycleManager(self.registry)

    def tearDown(self):
        # Ensure we cancel any background tasks
        async def _stop():
            await self.lifecycle.stop_all()
        asyncio.run(_stop())
        self.temp_dir.cleanup()

    def test_missing_file_marks_unavailable(self):
        async def _test():
            await self.lifecycle.start_all()
            
            m1 = self.registry.models["test-model-1"]
            self.assertEqual(m1.status, "UNAVAILABLE")
            
        asyncio.run(_test())

    @patch("asyncio.create_subprocess_exec")
    def test_spawn_marks_degraded_initially(self, mock_create_subprocess):
        async def _test():
            mock_proc = AsyncMock()
            mock_proc.returncode = None
            mock_create_subprocess.return_value = mock_proc
            
            # Start all, but we only have 1 valid model
            await self.lifecycle.start_all()
            
            m2 = self.registry.models["test-model-2"]
            self.assertEqual(m2.status, "DEGRADED")
            
            # Subprocess should have been called
            mock_create_subprocess.assert_called_once()
            args = mock_create_subprocess.call_args[0]
            self.assertEqual(args[0], "llama-server")
            self.assertIn(str(self.valid_file_path), args)
            
        asyncio.run(_test())

    def test_get_ready_by_capability(self):
        m1 = self.registry.models["test-model-1"]
        m2 = self.registry.models["test-model-2"]
        
        # Initially both UNAVAILABLE
        self.assertIsNone(self.registry.get_ready_by_capability("reasoning"))
        self.assertIsNone(self.registry.get_ready_by_capability("coding"))
        
        # Mark one as READY
        m2.status = "READY"
        
        found = self.registry.get_ready_by_capability("coding")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, "test-model-2")
        
        # Should still not find reasoning
        self.assertIsNone(self.registry.get_ready_by_capability("reasoning"))

if __name__ == "__main__":
    unittest.main()
