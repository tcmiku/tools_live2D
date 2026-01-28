import unittest

from backend.mood import compute_mood, mood_bucket, mood_interval_factor


class MoodTests(unittest.TestCase):
    def test_compute_mood_bounds(self):
        self.assertEqual(compute_mood(0, 0, 0, 0), 20)
        self.assertEqual(compute_mood(0, 0, 0, 10 * 3600 * 1000), 0)
        self.assertEqual(compute_mood(3 * 3600, 100, 20, 0), 100)

    def test_mood_bucket(self):
        self.assertEqual(mood_bucket(85), ("开心", "😊"))
        self.assertEqual(mood_bucket(70), ("愉快", "🙂"))
        self.assertEqual(mood_bucket(50), ("平静", "😐"))
        self.assertEqual(mood_bucket(30), ("低落", "😔"))
        self.assertEqual(mood_bucket(10), ("孤独", "😢"))

    def test_mood_interval_factor(self):
        self.assertAlmostEqual(mood_interval_factor(100), 0.8)
        self.assertAlmostEqual(mood_interval_factor(0), 1.2)


if __name__ == "__main__":
    unittest.main()
