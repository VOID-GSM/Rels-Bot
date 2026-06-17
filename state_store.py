import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

STATE_DB_PATH = os.getenv("STATE_DB_PATH", "bot_state.sqlite3")


def init_state_store():
    with sqlite3.connect(STATE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lecture_notifications (
                lecture_id TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                title TEXT,
                PRIMARY KEY (lecture_id, notification_type)
            )
            """
        )


def was_notified(lecture_id, notification_type):
    with sqlite3.connect(STATE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM lecture_notifications
            WHERE lecture_id = ? AND notification_type = ?
            """,
            (str(lecture_id), notification_type),
        ).fetchone()
    return row is not None


def mark_notified(lecture_id, notification_type, title):
    with sqlite3.connect(STATE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO lecture_notifications (
                lecture_id,
                notification_type,
                sent_at,
                title
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(lecture_id),
                notification_type,
                datetime.now(timezone.utc).isoformat(),
                title,
            ),
        )