
import unittest

from focussense.session_engine import SessionEngine
from focussense.accountability import AccountabilityController


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestAccountabilityController(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.engine = SessionEngine(
            focus_minutes=1,
            break_minutes=1,
            clock=self.clock,
        )
        self.engine.start(cycles=2)
        self.controller = AccountabilityController(
            self.engine,
            grace_seconds=5,
            clock=self.clock,
        )

    def test_short_absence_does_not_pause(self):
        self.controller.update(False)
        self.clock.advance(4)
        state = self.controller.update(False)

        self.assertEqual(state["status"], "running")
        self.assertEqual(state["violation_count"], 0)

    def test_first_violation_pauses_timer(self):
        self.controller.update(False)
        self.clock.advance(5)
        state = self.controller.update(False)

        self.assertEqual(state["status"], "paused")
        self.assertTrue(state["warning_used"])
        self.assertEqual(state["violation_count"], 1)

    def test_face_return_resumes_timer(self):
        self.controller.update(False)
        self.clock.advance(5)
        self.controller.update(False)

        state = self.controller.update(True)

        self.assertEqual(state["status"], "running")
        self.assertTrue(state["warning_used"])

    def test_second_violation_resets_current_interval(self):
        # First violation.
        self.controller.update(False)
        self.clock.advance(5)
        self.controller.update(False)

        # Return to frame.
        self.controller.update(True)

        # Second violation.
        self.controller.update(False)
        self.clock.advance(5)
        state = self.controller.update(False)

        self.assertEqual(state["status"], "awaiting_restart")
        self.assertEqual(state["remaining_seconds"], 60)
        self.assertEqual(state["completed_focus_intervals"], 0)
        self.assertFalse(state["warning_used"])
        self.assertEqual(state["violation_count"], 2)

    def test_reset_can_be_restarted(self):
        self.controller.update(False)
        self.clock.advance(5)
        self.controller.update(False)
        self.controller.update(True)
        self.controller.update(False)
        self.clock.advance(5)
        self.controller.update(False)

        self.controller.start_after_reset()

        self.assertEqual(self.engine.status, "running")
        self.assertEqual(self.engine.remaining_seconds, 60)


if __name__ == "__main__":
    unittest.main()
