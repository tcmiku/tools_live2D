import os
import tempfile
import unittest

from backend.reminders import ReminderEngine, ReminderConfig, ReminderStore


class DummyState:
    def __init__(self, status: str) -> None:
        self.status = status


class ReminderEngineTests(unittest.TestCase):
    def test_rest_reminder_triggered_after_interval(self):
        config = ReminderConfig(rest_enabled=True, rest_interval_min=1)
        engine = ReminderEngine(config)
        state = DummyState("active")
        events = engine.update_focus(state, now=0)
        self.assertEqual(events, [])
        events = engine.update_focus(state, now=60)
        self.assertIn("rest", events)

    def test_rest_not_triggered_when_idle(self):
        config = ReminderConfig(rest_enabled=True, rest_interval_min=1)
        engine = ReminderEngine(config)
        state = DummyState("active")
        engine.update_focus(state, now=0)
        state = DummyState("idle")
        events = engine.update_focus(state, now=60)
        self.assertEqual(events, [])

    def test_water_timer(self):
        config = ReminderConfig(water_enabled=True, water_interval_min=1)
        engine = ReminderEngine(config)
        events = engine.update_timers(now=0)
        self.assertEqual(events, [])
        events = engine.update_timers(now=60)
        self.assertIn("water", events)


class ReminderStoreTests(unittest.TestCase):
    def test_add_remove_and_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "reminders.json")
            store = ReminderStore(path)
            item = store.add_todo("test", 10.0)
            self.assertEqual(len(store.list_todos()), 1)
            due = store.due_items(now=10.0)
            self.assertEqual(len(due), 1)
            store.mark_triggered(item["id"])
            due_after = store.due_items(now=10.0)
            self.assertEqual(len(due_after), 0)
            store.remove_todo(item["id"])
            self.assertEqual(len(store.list_todos()), 0)


if __name__ == "__main__":
    unittest.main()
