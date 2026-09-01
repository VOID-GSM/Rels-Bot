import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

LECTURES_API_URL = os.getenv(
    "LECTURES_API_URL",
    "https://rels.io.kr/api/lectures/discord",
)
PAGE_SIZE = int(os.getenv("LECTURES_PAGE_SIZE", "100"))

LECTURE_BASE_URL = (
    os.getenv("LECTURE_BASE_URL", "https://rels.io.kr/lectures").strip().rstrip("/")
)

OPEN_STATUSES = {"OPEN", "CONFIRMED", "CONFIRM"}


class ApiError(RuntimeError):
    pass


def _with_query(url: str, params: Dict[str, Any]) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _request_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "rels-discord-bot/1.0",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ApiError(f"API 요청 실패: HTTP {exc.code} {exc.reason} {detail}") from exc
    except Exception as exc:
        raise ApiError(f"API 요청 실패: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError(f"API 응답을 확인해주세요: {body[:300]}") from exc


def _pick_lectures(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    for key in ("content", "lectures", "data", "items", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _pick_lectures(value)
            if nested:
                return nested

    return []


def _first(source: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    if not isinstance(source, dict):
        return default

    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value

    return default


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    try:
        text = (
            value.strip()
            .replace(" ", "T")
            .replace("Z", "+00:00")
            .replace("z", "+00:00")
        )
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_target_grades(capacity_by_grade: Any) -> List[int]:
    if not isinstance(capacity_by_grade, dict) or not capacity_by_grade:
        return []

    grades: List[int] = []
    for grade, capacity in capacity_by_grade.items():
        try:
            if int(capacity or 0) > 0:
                grades.append(int(grade))
        except (TypeError, ValueError):
            continue

    return sorted(grades)


def _format_target(target_grades: List[int]) -> str:
    if not target_grades:
        return "전체"
    return ", ".join(f"{grade}학년" for grade in target_grades)


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    capacity_by_grade = (
        _first(raw, "capacityByGrade", "capacity_by_grade", default={}) or {}
    )
    target_grades = _extract_target_grades(capacity_by_grade)

    try:
        enrolled_count = int(
            _first(raw, "enrolledCount", "enrolled_count", "applicantCount", default=0)
            or 0
        )
    except (TypeError, ValueError):
        enrolled_count = 0

    total_capacity = _first(
        raw, "totalCapacity", "total_capacity", "capacity", default=0
    )
    if not total_capacity and isinstance(capacity_by_grade, dict):
        total_capacity = sum(
            int(v)
            for v in capacity_by_grade.values()
            if isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit())
        )
    try:
        total_capacity = int(total_capacity or 0)
    except (TypeError, ValueError):
        total_capacity = 0

    starts_at_raw = _first(raw, "startsAt", "starts_at", "startDate", "start_date")
    starts_at = _parse_datetime(starts_at_raw)

    created_at = _parse_datetime(_first(raw, "createdAt", "created_at"))

    lecture_id = _first(raw, "id", "lectureId")
    url_id = _first(raw, "lectureId", "id")

    return {
        "id": lecture_id or _first(raw, "title", default="unknown"),
        "title": _first(raw, "title", default="제목 없음"),
        "description": _first(raw, "description", default=""),
        "status": str(
            _first(raw, "lectureStatus", "lecture_status", "status", default="OPEN")
        ).upper(),
        "lecture_location": _first(
            raw, "lectureLocation", "lecture_location", "location", default="미정"
        ),
        "lecture_date": _first(raw, "lectureDate", "lecture_date", "date")
        or (starts_at.date() if starts_at else None),
        "lecture_time": _first(raw, "lectureTime", "lecture_time", "time")
        or (starts_at.time() if starts_at else None),
        "application_deadline": _first(
            raw, "applicationDeadline", "application_deadline", "deadline"
        ),
        "total_capacity": total_capacity,
        "creator_name": _first(
            raw, "creatorName", "creator_name", "speakerName", "speaker", default="미정"
        ),
        "target": _format_target(target_grades),
        "target_grades": target_grades,
        "enrolled_count": enrolled_count,
        "lecture_url": f"{LECTURE_BASE_URL}/{url_id}" if url_id else None,
        "created_at": created_at,
    }


def fetch_open_lectures() -> List[Dict[str, Any]]:
    payload = _request_json(_with_query(LECTURES_API_URL, {"size": PAGE_SIZE}))
    lectures = [_normalize(item) for item in _pick_lectures(payload)]
    return [lec for lec in lectures if lec["status"] in OPEN_STATUSES]


def fetch_active_lectures() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    active = []

    for lecture in fetch_open_lectures():
        deadline = _parse_datetime(lecture.get("application_deadline"))
        if deadline is None or deadline > now:
            active.append(lecture)

    return active


def fetch_all_lectures_basic() -> List[Dict[str, Any]]:
    return [lec for lec in fetch_open_lectures() if lec["status"] == "OPEN"]


def fetch_enrollment_counts(
    lectures: Optional[List[Dict[str, Any]]] = None,
) -> Dict[Any, Dict[str, Any]]:
    target_lectures = lectures if lectures is not None else fetch_open_lectures()

    return {
        lecture["id"]: {
            "lecture_id": lecture["id"],
            "enrolled_count": lecture.get("enrolled_count", 0),
        }
        for lecture in target_lectures
    }
