
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "focussense.db"


def local_now():
    """Return the current local date and time with timezone information."""
    return datetime.now().astimezone()


class FocusHistory:
    """Store FocusSense session history and daily focus goals in SQLite."""

    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        self._initialize_database()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self):
        """Create database tables if they do not already exist."""
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    start_date TEXT NOT NULL,
                    focus_minutes INTEGER NOT NULL,
                    break_minutes INTEGER NOT NULL,
                    planned_cycles INTEGER NOT NULL,
                    completed_focus_intervals INTEGER NOT NULL DEFAULT 0,
                    focused_seconds INTEGER NOT NULL DEFAULT 0,
                    violation_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            connection.execute("""
                INSERT OR IGNORE INTO settings (key, value)
                VALUES ('daily_goal_minutes', '120')
            """)

    def create_session(
        self, focus_minutes, break_minutes, planned_cycles
    ):
        """Create a database record when a focus session starts."""
        started = local_now()

        with self._connect() as connection:
            cursor = connection.execute("""
                INSERT INTO sessions (
                    started_at,
                    start_date,
                    focus_minutes,
                    break_minutes,
                    planned_cycles,
                    status
                )
                VALUES (?, ?, ?, ?, ?, 'running')
            """, (
                started.isoformat(timespec="seconds"),
                started.date().isoformat(),
                focus_minutes,
                break_minutes,
                planned_cycles,
            ))

            return cursor.lastrowid

    def update_session(
        self,
        session_id,
        focused_seconds,
        status,
        completed_focus_intervals,
        violation_count,
    ):
        """Update recorded focus time and session progress."""
        finished_at = None

        if status in ("completed", "incomplete"):
            finished_at = local_now().isoformat(timespec="seconds")

        with self._connect() as connection:
            connection.execute("""
                UPDATE sessions
                SET focused_seconds = ?,
                    status = ?,
                    completed_focus_intervals = ?,
                    violation_count = ?,
                    ended_at = CASE
                        WHEN ? IS NOT NULL
                        THEN COALESCE(ended_at, ?)
                        ELSE ended_at
                    END
                WHERE id = ?
            """, (
                max(0, int(focused_seconds)),
                status,
                completed_focus_intervals,
                violation_count,
                finished_at,
                finished_at,
                session_id,
            ))

    def set_daily_goal(self, minutes):
        """Save a custom daily focus goal in whole minutes."""
        if not isinstance(minutes, int) or isinstance(minutes, bool):
            raise ValueError("Daily goal must be a whole number of minutes.")

        if not 1 <= minutes <= 1440:
            raise ValueError("Daily goal must be between 1 and 1440 minutes.")

        with self._connect() as connection:
            connection.execute("""
                INSERT INTO settings (key, value)
                VALUES ('daily_goal_minutes', ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value
            """, (str(minutes),))

        return minutes

    def get_daily_goal(self):
        """Return the saved daily goal, in minutes."""
        with self._connect() as connection:
            row = connection.execute("""
                SELECT value
                FROM settings
                WHERE key = 'daily_goal_minutes'
            """).fetchone()

        return int(row["value"]) if row else 120

    def daily_summary(self, day=None):
        """Return the focus-time summary for a particular day."""
        day = day or date.today()

        with self._connect() as connection:
            row = connection.execute("""
                SELECT
                    COALESCE(SUM(focused_seconds), 0) AS focused_seconds,
                    COUNT(*) AS session_count,
                    COALESCE(
                        SUM(completed_focus_intervals), 0
                    ) AS completed_intervals
                FROM sessions
                WHERE start_date = ?
            """, (day.isoformat(),)).fetchone()

        focused_seconds = int(row["focused_seconds"])
        goal_minutes = self.get_daily_goal()

        return {
            "date": day.isoformat(),
            "focused_seconds": focused_seconds,
            "focused_minutes": focused_seconds // 60,
            "session_count": row["session_count"],
            "completed_focus_intervals": row["completed_intervals"],
            "daily_goal_minutes": goal_minutes,
            "goal_progress_percent": min(
                100,
                round(focused_seconds / (goal_minutes * 60) * 100),
            ),
        }

    def recent_days(self, days=7):
        """Return daily focus totals for the last several calendar days."""
        if not isinstance(days, int) or days < 1:
            raise ValueError("Days must be a positive whole number.")

        today = date.today()
        first_day = today - timedelta(days=days - 1)

        with self._connect() as connection:
            rows = connection.execute("""
                SELECT
                    start_date AS date,
                    SUM(focused_seconds) AS focused_seconds,
                    COUNT(*) AS session_count
                FROM sessions
                WHERE start_date BETWEEN ? AND ?
                GROUP BY start_date
                ORDER BY start_date
            """, (
                first_day.isoformat(),
                today.isoformat(),
            )).fetchall()

        by_date = {
            row["date"]: {
                "focused_seconds": row["focused_seconds"],
                "session_count": row["session_count"],
            }
            for row in rows
        }

        result = []

        for offset in range(days):
            day = first_day + timedelta(days=offset)
            values = by_date.get(day.isoformat(), {
                "focused_seconds": 0,
                "session_count": 0,
            })

            result.append({
                "date": day.isoformat(),
                "focused_seconds": values["focused_seconds"],
                "session_count": values["session_count"],
            })

        return result
