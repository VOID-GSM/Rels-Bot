import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

_CREATE_OPEN_SCHEDULE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lecture_open_schedule (
    lecture_id TEXT PRIMARY KEY,
    open_at    TEXT NOT NULL,
    title      TEXT,
    notified   INTEGER NOT NULL DEFAULT 0
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

_INSERT_OPEN_SCHEDULE_SQL = """
INSERT OR IGNORE INTO lecture_open_schedule (lecture_id, open_at, title, notified)
VALUES (?, ?, ?, ?)
"""

_SELECT_DUE_OPEN_SQL = """
SELECT lecture_id, open_at, title FROM lecture_open_schedule
WHERE notified = 0 AND open_at <= ?
"""

_UPDATE_OPEN_NOTIFIED_SQL = """
UPDATE lecture_open_schedule SET notified = 1 WHERE lecture_id = ?
"""


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(STATE_DB_PATH)


def init_state_store() -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_OPEN_SCHEDULE_TABLE_SQL)
            conn.execute("PRAGMA journal_mode=WAL;")


def was_notified(lecture_id: Any, notification_type: str) -> bool:
    with closing(_connect()) as conn:
        row = conn.execute(_SELECT_SQL, (str(lecture_id), notification_type)).fetchone()
    return row is not None


def claim_notification(lecture_id: Any, notification_type: str, title: Optional[str] = None) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as conn:
        with conn:
            cur = conn.execute(
                _INSERT_SQL,
                (str(lecture_id), notification_type, now_iso, title),
            )
            return cur.rowcount == 1


def mark_notified(lecture_id: Any, notification_type: str, title: Optional[str] = None) -> bool:
    return claim_notification(lecture_id, notification_type, title)


def schedule_open_notification(
    lecture_id: Any,
    open_at_iso: str,
    title: Optional[str] = None,
    notified: int = 0,
) -> None:
    """신청 시작(오후 4시 20분) 알림을 예약한다.

    notified=1로 넣으면 '이미 처리된 것'으로 기록되어 실제 알림은 나가지 않는다.
    (봇 재시작 시 기존 강연들에 대해 사용)
    이미 같은 lecture_id로 예약된 건이 있으면 무시된다.
    """
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                _INSERT_OPEN_SCHEDULE_SQL,
                (str(lecture_id), open_at_iso, title, notified),
            )


def get_due_open_notifications(now_iso: str) -> List[Dict[str, Any]]:
    """아직 알림을 안 보냈고, 예정 시각이 지난 강연 목록을 반환한다."""
    with closing(_connect()) as conn:
        rows = conn.execute(_SELECT_DUE_OPEN_SQL, (now_iso,)).fetchall()
    return [{"lecture_id": row[0], "open_at": row[1], "title": row[2]} for row in rows]


def mark_open_notified(lecture_id: Any) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(_UPDATE_OPEN_NOTIFIED_SQL, (str(lecture_id),))
            