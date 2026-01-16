import unittest
from pathlib import Path

from backend.ai_client import AIClient
from backend.bridge import BackendBridge
from backend.settings import AppSettings


class ModelListTests(unittest.TestCase):
    def test_get_available_models_detects_model_files(self):
        base_dir = Path(__file__).resolve().parents[1]
        model_dir = base_dir / "web" / "model" / "test_model_list"
        model_file = model_dir / "test.model3.json"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_file.write_text("{}", encoding="utf-8")
        try:
            settings = AppSettings()
            bridge = BackendBridge(AIClient(settings), settings=settings)
            models = bridge.getAvailableModels()
            paths = [item.get("path") for item in models]
            self.assertIn("model/test_model_list/test.model3.json", paths)
        finally:
            if model_file.exists():
                model_file.unlink()
            try:
                model_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
