import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

STATE_DB_PATH = os.getenv("STATE_DB_PATH", "bot_state.sqlite3")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lecture_notifications (
    lecture_id        TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    sent_at           TEXT NOT NULL,
    title             TEXT,
    PRIMARY KEY (lecture_id, notification_type)
)
"""

_INSERT_SQL = """
INSERT OR IGNORE INTO lecture_notifications (lecture_id, notification_type, sent_at, title)
VALUES (?, ?, ?, ?)
"""

_SELECT_SQL = """
SELECT 1 FROM lecture_notifications
WHERE lecture_id = ? AND notification_type = ?
"""


def _connect():
    return sqlite3.connect(STATE_DB_PATH)


def init_state_store():
    from contextlib import closing
    with closing(_connect()) as conn:
        with conn:
            conn.execute(_CREATE_TABLE_SQL)


def was_notified(lecture_id, notification_type):
    from contextlib import closing
    with closing(_connect()) as conn:
        row = conn.execute(_SELECT_SQL, (str(lecture_id), notification_type)).fetchone()
    return row is not None


def claim_notification(lecture_id, notification_type, title):
    from contextlib import closing
    with closing(_connect()) as conn:
        with conn:
            cur = conn.execute(
                _INSERT_SQL,
                (str(lecture_id), notification_type, datetime.now(timezone.utc).isoformat(), title),
            )
        return cur.rowcount == 1


def mark_notified(lecture_id, notification_type, title):
    claim_notification(lecture_id, notification_type, title)