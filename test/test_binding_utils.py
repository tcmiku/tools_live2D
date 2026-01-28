import json
import os
import tempfile
import unittest

from backend.binding_utils import extract_motions_expressions, list_model_paths


class BindingUtilsTests(unittest.TestCase):
    def test_extract_motions_expressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = os.path.join(tmp, "web", "model", "demo")
            os.makedirs(web_dir, exist_ok=True)
            path = os.path.join(web_dir, "demo.model3.json")
            data = {
                "FileReferences": {
                    "Motions": {"Idle": [], "Tap": []},
                    "Expressions": [{"Name": "smile"}, {"Name": "sad"}],
                }
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            motions, expressions = extract_motions_expressions(tmp, "model/demo/demo.model3.json")
            self.assertEqual(set(motions), {"Idle", "Tap"})
            self.assertEqual(expressions, ["smile", "sad"])

    def test_list_model_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = os.path.join(tmp, "web", "model", "a")
            os.makedirs(web_dir, exist_ok=True)
            with open(os.path.join(web_dir, "a.model3.json"), "w", encoding="utf-8") as f:
                json.dump({}, f)
            with open(os.path.join(web_dir, "ignore.txt"), "w", encoding="utf-8") as f:
                f.write("x")
            paths = list_model_paths(tmp)
            self.assertEqual(paths, ["model/a/a.model3.json"])


if __name__ == "__main__":
    unittest.main()
