import os
import sqlite3
from datetime import datetime, timezone
 
from dotenv import load_dotenv
 
load_dotenv()
 
STATE_DB_PATH = os.getenv("STATE_DB_PATH", "bot_state.sqlite3")
 
 
def init_state_store():
    conn = sqlite3.connect(STATE_DB_PATH)
    try:
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
        conn.commit()
    finally:
        conn.close()
 
 
def was_notified(lecture_id, notification_type):
    """이미 해당 알림을 보냈는지 조회만 한다 (점유하지 않음)."""
    conn = sqlite3.connect(STATE_DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM lecture_notifications
            WHERE lecture_id = ? AND notification_type = ?
            """,
            (str(lecture_id), notification_type),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
 
 
def claim_notification(lecture_id, notification_type, title):
    """
    아직 보낸 적 없는 알림이면 즉시 기록(점유)하고 True를 반환한다.
    이미 보낸 적 있으면 False를 반환한다.
 
    '보내기 전에 먼저 DB에 기록'하는 방식이라, 전송 직후 기록이 실패해서
    같은 알림이 중복 전송되는 문제를 구조적으로 막아준다.
    INSERT OR IGNORE + rowcount 체크라서 동시성 문제도 안전하다.
    """
    conn = sqlite3.connect(STATE_DB_PATH)
    try:
        cur = conn.execute(
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
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()
 
 
def mark_notified(lecture_id, notification_type, title):
    claim_notification(lecture_id, notification_type, title)