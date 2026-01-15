import unittest
from pathlib import Path


class FrontendInteractionTests(unittest.TestCase):
    def test_interaction_handlers_present(self):
        content = Path("web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("setupPetInteraction", content)
        self.assertIn("triggerRandomMotion", content)
        self.assertIn("petting-spark", Path("web/index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
