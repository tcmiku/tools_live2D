import json
import unittest
from pathlib import Path


class MotionGroupTests(unittest.TestCase):
    def test_model_has_motion_groups(self):
        model_path = Path("web/model/miku/miku.model3.json")
        data = json.loads(model_path.read_text(encoding="utf-8"))
        motions = data.get("FileReferences", {}).get("Motions", {})
        self.assertTrue(isinstance(motions, dict))
        self.assertIn("Tap", motions)
        self.assertIn("Flick", motions)


if __name__ == "__main__":
    unittest.main()
