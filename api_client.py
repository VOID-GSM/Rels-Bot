import json
import os
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import timezone
 
from dotenv import load_dotenv
 
load_dotenv()
 
LECTURES_API_URL = os.getenv(
    "LECTURES_API_URL",
    "https://rels-alpha.vercel.app/api/lectures/discord",
)
PAGE_SIZE = int(os.getenv("LECTURES_PAGE_SIZE", "100"))
 
 
class ApiError(RuntimeError):
    pass
 
 
def _with_query(url, params):
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"
 
 
def _request_json(url):
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
        raise ApiError(f"API 응답이 JSON이 아닙니다: {body[:300]}") from exc
 
 
def _pick_lectures(payload):
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
 
 
def _first(source, *keys, default=None):
    if not isinstance(source, dict):
        return default
 
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
 
    return default
 
 
def _format_target(capacity_by_grade):
    if not isinstance(capacity_by_grade, dict) or not capacity_by_grade:
        return "전체"
 
    grades = []
    for grade, capacity in capacity_by_grade.items():
        try:
            if int(capacity or 0) > 0:
                grades.append(str(grade))
        except (TypeError, ValueError):
            continue
 
    try:
        grades.sort(key=int)
    except ValueError:
        grades.sort()
 
    return ", ".join(f"{grade}학년" for grade in grades) if grades else "전체"
 
 
def _normalize(raw):
    capacity_by_grade = _first(raw, "capacityByGrade", "capacity_by_grade", default={}) or {}
 
    total_capacity = _first(raw, "totalCapacity", "total_capacity", "capacity", default=0)
    enrolled_count = _first(raw, "enrolledCount", "enrolled_count", "applicantCount", default=0)
 
    try:
        enrolled_count = int(enrolled_count or 0)
    except (TypeError, ValueError):
        enrolled_count = 0
 
    if not total_capacity and isinstance(capacity_by_grade, dict):
        total_capacity = 0
        for value in capacity_by_grade.values():
            try:
                total_capacity += int(value or 0)
            except (TypeError, ValueError):
                continue
 
    try:
        total_capacity = int(total_capacity or 0)
    except (TypeError, ValueError):
        total_capacity = 0
 
    lecture_date = _first(raw, "lectureDate", "lecture_date", "date")
    lecture_time = _first(raw, "lectureTime", "lecture_time", "time")
    starts_at = _first(raw, "startsAt", "startAt", "lectureAt")
    
 
    parsed_starts_at = _parse_datetime(starts_at)
 
    return {
        "id": _first(raw, "id", "lectureId", default=_first(raw, "title", default="unknown")),
        "title": _first(raw, "title", default="제목 없음"),
        "description": _first(raw, "description", default=""),
        "status": str(_first(raw, "lectureStatus", "lecture_status", "status", default="OPEN")).upper(),
        "lecture_location": _first(raw, "lectureLocation", "lecture_location", "location", default="미정"),
        "lecture_date": lecture_date or (parsed_starts_at.date() if parsed_starts_at else None),
        "lecture_time": lecture_time or (parsed_starts_at.time() if parsed_starts_at else None),
        "application_deadline": _first(raw, "applicationDeadline", "application_deadline", "deadline"),
        "total_capacity": total_capacity,
        "creator_name": _first(raw, "creatorName", "creator_name", "speakerName", "speaker", default="미정"),
        "target": _format_target(capacity_by_grade),
        "enrolled_count": enrolled_count,
        "lecture_url": f"https://rels-alpha.vercel.app/lectures/{_first(raw, 'lectureId', 'id', default=None)}",
    }
 
 
def fetch_open_lectures():
    payload = _request_json(_with_query(LECTURES_API_URL, {"size": PAGE_SIZE}))
    lectures = [_normalize(item) for item in _pick_lectures(payload)]
 
    return [
        lecture
        for lecture in lectures
        if lecture["status"] in {"OPEN", "CONFIRMED", "CONFIRM"}
    ]
 
 
def fetch_all_lectures_basic():
    return [lecture for lecture in fetch_open_lectures() if lecture["status"] == "OPEN"]
 
 
def fetch_enrollment_counts(lectures=None):
    lectures = lectures if lectures is not None else fetch_open_lectures()
 
    return {
        lecture["id"]: {
            "lecture_id": lecture["id"],
            "enrolled_count": lecture.get("enrolled_count", 0),
        }
        for lecture in lectures
    }

def _parse_datetime(value):
    if not value or not isinstance(value, str):
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None