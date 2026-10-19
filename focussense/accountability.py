
import time


class AccountabilityController:
    """Manage FocusSense face-presence accountability rules."""

    def __init__(self, engine, grace_seconds=5, clock=None):
        if grace_seconds <= 0:
            raise ValueError("Grace period must be positive.")

        self.engine = engine
        self.grace_seconds = grace_seconds
        self.clock = clock or time.monotonic

        self.face_missing_since = None
        self.warning_used = False
        self.warning_pause = False
        self.violation_count = 0
        self.message = "Ready to focus."

    def update(self, face_detected):
        """Update accountability using face-presence detection."""

        # Face detection is not required during breaks.
        if self.engine.phase != "focus":
            self.face_missing_since = None
            return self._state()

        # Do not enforce rules without an active focus timer.
        if self.engine.status not in ("running", "paused"):
            self.face_missing_since = None
            return self._state()
        # Manual pause freezes accountability checks.
        if self.engine.status == "paused" and not self.warning_pause:
             self.face_missing_since = None
             return self._state()
        now = self.clock()

        # Face is visible.
        if face_detected:
            self.face_missing_since = None

            # Resume automatically only if the warning caused the pause.
            if self.engine.status == "paused" and self.warning_pause:
                self.engine.resume()
                self.warning_pause = False
                self.message = (
                    "Welcome back! Your focus timer has resumed."
                )

            return self._state()

        # Wait for the user to return before counting a second absence.
        if self.engine.status == "paused" and self.warning_used:
            self.face_missing_since = None
            return self._state()

        # Start timing a continuous absence.
        if self.face_missing_since is None:
            self.face_missing_since = now
            return self._state()

        # Allow five seconds for the user to return.
        if now - self.face_missing_since < self.grace_seconds:
            return self._state()

        # FIRST VIOLATION: pause the timer and show a warning.
        if not self.warning_used:
            if self.engine.status == "running":
                self.engine.pause()
                self.warning_pause = True

            self.warning_used = True
            self.violation_count += 1
            self.message = (
                "Warning 1: Face not detected. "
                "Return to the camera to resume your session."
            )
            self.face_missing_since = None
            return self._state()

        # SECOND VIOLATION: reset only the current focus interval.
        if self.engine.status in ("running", "paused"):
            self.engine.reset_current_focus_interval()

        self.violation_count += 1
        self.warning_used = False
        self.warning_pause = False
        self.face_missing_since = None
        self.message = (
            "Warning 2: Focus interval reset. "
            "Press Start to try this interval again."
        )

        return self._state()

    def start_after_reset(self):
        """Restart a reset interval when the user presses Start."""

        state = self.engine.start_current_interval()

        self.face_missing_since = None
        self.warning_used = False
        self.warning_pause = False
        self.message = "Focus interval restarted. Stay in frame."

        return state

    def _state(self):
        """Return session and accountability information."""

        return {
            **self.engine.snapshot(),
            "face_missing": self.face_missing_since is not None,
            "warning_used": self.warning_used,
            "warning_pause": self.warning_pause,
            "violation_count": self.violation_count,
            "message": self.message,
        }
