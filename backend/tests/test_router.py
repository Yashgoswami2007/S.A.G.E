import unittest
import tempfile
import pathlib
from sage.models.registry import ModelRegistry
from sage.agent.router import ModelRouter

class TestModelRouter(unittest.TestCase):
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

  - id: coding-model
    name: Coding Model
    model_path: /models/coding.gguf
    server_port: 8002
    capabilities: ["coding"]
    priority: 1
    min_vram_gb: 6
    context_length: 8192

  - id: vision-model
    name: Vision Model
    model_path: /models/vision.gguf
    server_port: 8003
    capabilities: ["vision"]
    priority: 1
    min_vram_gb: 6
    context_length: 8192
"""
        p = pathlib.Path(self.temp_dir.name) / "model_registry.yaml"
        p.write_text(yaml_content)
        self.registry = ModelRegistry(str(p))
        for model in self.registry.models.values():
            model.status = "READY"
        self.router = ModelRouter(self.registry)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_deterministic_routing_coder_profile(self):
        model, reason = self.router.route("write a python script", profile_name="coder")
        self.assertEqual(model.id, "coding-model")
        self.assertIn("coder profile requested", reason)

    def test_deterministic_routing_image_modality(self):
        model, reason = self.router.route("analyze report", file_attachments=["report.png"])
        self.assertEqual(model.id, "vision-model")
        self.assertIn("image modality detected", reason)

    def test_deterministic_routing_keywords(self):
        model, reason = self.router.route("refactor python code function", profile_name="general")
        self.assertEqual(model.id, "coding-model")
        self.assertIn("coding keywords detected", reason)

    def test_deterministic_routing_default_fallback(self):
        model, reason = self.router.route("what is the capital of France?", profile_name="general")
        self.assertEqual(model.id, "reasoning-model")
        self.assertIn("default profile 'general'", reason)

if __name__ == "__main__":
    unittest.main()
