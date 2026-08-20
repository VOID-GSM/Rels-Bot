import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Optional

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


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(STATE_DB_PATH)


def init_state_store() -> None:
    """DB 테이블 생성 및 WAL 모드 설정"""
    with closing(_connect()) as conn:
        with conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute("PRAGMA journal_mode=WAL;")


def was_notified(lecture_id: Any, notification_type: str) -> bool:
    """특정 알림 발송 여부 조회"""
    with closing(_connect()) as conn:
        row = conn.execute(_SELECT_SQL, (str(lecture_id), notification_type)).fetchone()
    return row is not None


def claim_notification(lecture_id: Any, notification_type: str, title: Optional[str] = None) -> bool:
    """알림 선점 시도 (최초 등록 성공 시 True, 이미 존재 시 False 반환)"""
    now_iso = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as conn:
        with conn:
            cur = conn.execute(
                _INSERT_SQL,
                (str(lecture_id), notification_type, now_iso, title),
            )
            return cur.rowcount == 1


def mark_notified(lecture_id: Any, notification_type: str, title: Optional[str] = None) -> bool:
    """알림 완료 상태로 저장"""
    return claim_notification(lecture_id, notification_type, title)