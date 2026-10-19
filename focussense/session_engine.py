import time
class SessionEngine:
    """Manage FocusSense focus and break cycles."""

    def __init__(self, focus_minutes=25, break_minutes=5, clock=None):
        if focus_minutes <= 0 or break_minutes <= 0:
            raise ValueError("Focus and break durations must be positive.")

        self.focus_seconds = focus_minutes * 60
        self.break_seconds = break_minutes * 60
        self.clock = clock or time.monotonic

        self.status = "idle"
        self.phase = None
        self.current_cycle = 0
        self.planned_cycles = 0
        self.completed_focus_intervals = 0
        self._deadline = None
        self._paused_remaining = None

    def start(self, cycles=4):
        if self.status != "idle":
            raise RuntimeError("This session has already started.")
        if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles < 1:
            raise ValueError("Cycles must be a positive integer.")

        self.planned_cycles = cycles
        self.current_cycle = 1
        self.phase = "focus"
        self.status = "running"
        self._deadline = self.clock() + self.focus_seconds
        return self.snapshot()

    @property
    def remaining_seconds(self):
        if self.status in ("paused", "awaiting_restart"):
            return max(0, self._paused_remaining or 0)
        if self.status == "running":
            return max(0, self._deadline - self.clock())
        return 0

    def tick(self):
        """Advance phases when their deadlines have passed."""
        while self.status == "running" and self.clock() >= self._deadline:
            old_deadline = self._deadline

            if self.phase == "focus":
                self.completed_focus_intervals += 1
                self.phase = "break"
                duration = self.break_seconds
            else:
                if self.current_cycle >= self.planned_cycles:
                    self.status = "completed"
                    self._deadline = None
                    break

                self.current_cycle += 1
                self.phase = "focus"
                duration = self.focus_seconds

            # Preserve accurate timing even if tick() runs late.
            self._deadline = old_deadline + duration

        return self.snapshot()

    def pause(self):
        if self.status != "running":
            raise RuntimeError("Only a running session can be paused.")

        self._paused_remaining = self.remaining_seconds
        self.status = "paused"
        self._deadline = None
        return self.snapshot()

    def resume(self):
        if self.status != "paused":
            raise RuntimeError("Only a paused session can be resumed.")

        self._deadline = self.clock() + self._paused_remaining
        self._paused_remaining = None
        self.status = "running"
        return self.snapshot()
    def reset_current_focus_interval(self):
        """Reset only the current focus interval and wait for Start."""
        if self.phase != "focus" or self.status not in ("running", "paused"):
            raise RuntimeError("Only an active focus interval can be reset.")

        self.status = "awaiting_restart"
        self._deadline = None
        self._paused_remaining = self.focus_seconds
        return self.snapshot()

    def start_current_interval(self):
        """Restart a reset focus interval when the user presses Start."""
        if self.status != "awaiting_restart":
            raise RuntimeError("No reset interval is waiting to restart.")

        self._deadline = self.clock() + self._paused_remaining
        self._paused_remaining = None
        self.status = "running"
        return self.snapshot()
    def early_exit(self):
        if self.status not in ("running", "paused"):
            raise RuntimeError("There is no active session to exit.")

        self.status = "incomplete"
        self._deadline = None
        self._paused_remaining = None
        return self.snapshot()

    def snapshot(self):
        remaining = self.remaining_seconds
        return {
            "status": self.status,
            "phase": self.phase,
            "current_cycle": self.current_cycle,
            "planned_cycles": self.planned_cycles,
            "completed_focus_intervals": self.completed_focus_intervals,
            "remaining_seconds": int(remaining + 0.999999),
        }

