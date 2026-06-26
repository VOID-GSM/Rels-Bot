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
    with _connect() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()


def was_notified(lecture_id, notification_type):
    """이미 해당 알림을 보냈는지 조회 (점유하지 않음)."""
    with _connect() as conn:
        row = conn.execute(_SELECT_SQL, (str(lecture_id), notification_type)).fetchone()
    return row is not None


def claim_notification(lecture_id, notification_type, title):
    """
    아직 보낸 적 없는 알림이면 즉시 DB에 기록(점유)하고 True를 반환.
    이미 기록된 알림이면 False를 반환.
    INSERT OR IGNORE + rowcount로 동시성 안전하게 처리.
    """
    with _connect() as conn:
        cur = conn.execute(
            _INSERT_SQL,
            (str(lecture_id), notification_type, datetime.now(timezone.utc).isoformat(), title),
        )
        conn.commit()
    return cur.rowcount == 1


def mark_notified(lecture_id, notification_type, title):
    claim_notification(lecture_id, notification_type, title)