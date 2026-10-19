
import unittest
from focussense.session_engine import SessionEngine
class FakeClock:
    """A controllable clock so tests don't wait in real time."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestSessionEngine(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.engine = SessionEngine(
            focus_minutes=1,
            break_minutes=2,
            clock=self.clock,
        )

    def test_custom_durations(self):
        self.assertEqual(self.engine.focus_seconds, 60)
        self.assertEqual(self.engine.break_seconds, 120)

    def test_default_durations(self):
        engine = SessionEngine(clock=self.clock)
        self.assertEqual(engine.focus_seconds, 25 * 60)
        self.assertEqual(engine.break_seconds, 5 * 60)

    def test_focus_transitions_to_break(self):
        self.engine.start(cycles=2)

        self.clock.advance(60)
        state = self.engine.tick()

        self.assertEqual(state["phase"], "break")
        self.assertEqual(state["completed_focus_intervals"], 1)

    def test_break_transitions_to_next_focus(self):
        self.engine.start(cycles=2)

        self.clock.advance(60)
        self.engine.tick()

        self.clock.advance(120)
        state = self.engine.tick()

        self.assertEqual(state["phase"], "focus")
        self.assertEqual(state["current_cycle"], 2)

    def test_session_completes_after_all_cycles(self):
        self.engine.start(cycles=1)

        self.clock.advance(60)
        self.engine.tick()

        self.clock.advance(120)
        state = self.engine.tick()

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["completed_focus_intervals"], 1)

    def test_pause_and_resume_preserve_time(self):
        self.engine.start(cycles=1)

        self.clock.advance(20)
        self.engine.pause()

        self.clock.advance(100)
        self.assertEqual(self.engine.remaining_seconds, 40)

        self.engine.resume()
        self.clock.advance(40)
        state = self.engine.tick()

        self.assertEqual(state["phase"], "break")

    def test_early_exit_preserves_completed_intervals(self):
        self.engine.start(cycles=2)

        self.clock.advance(60)
        self.engine.tick()

        self.engine.early_exit()
        state = self.engine.snapshot()

        self.assertEqual(state["status"], "incomplete")
        self.assertEqual(state["completed_focus_intervals"], 1)

    def test_invalid_cycle_count_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.start(cycles=0)

    def test_invalid_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            SessionEngine(focus_minutes=0)

        with self.assertRaises(ValueError):
            SessionEngine(break_minutes=-1)
    def test_reset_preserves_completed_intervals(self):
        self.engine.start(cycles=2)

        # Complete the first focus interval.
        self.clock.advance(60)
        self.engine.tick()

        # Finish the break and enter the second focus interval.
        self.clock.advance(120)
        self.engine.tick()

        # Spend 30 seconds in the second focus interval.
        self.clock.advance(30)
        self.engine.reset_current_focus_interval()

        state = self.engine.snapshot()

        self.assertEqual(state["status"], "awaiting_restart")
        self.assertEqual(state["phase"], "focus")
        self.assertEqual(state["completed_focus_intervals"], 1)
        self.assertEqual(state["remaining_seconds"], 60)

    def test_reset_waits_for_manual_restart(self):
        self.engine.start(cycles=2)
        self.clock.advance(20)
        self.engine.reset_current_focus_interval()

        self.clock.advance(100)
        self.assertEqual(self.engine.remaining_seconds, 60)

        self.engine.start_current_interval()
        self.clock.advance(60)
        state = self.engine.tick()

        self.assertEqual(state["phase"], "break")
        self.assertEqual(state["completed_focus_intervals"], 1)

if __name__ == "__main__":
    unittest.main()
