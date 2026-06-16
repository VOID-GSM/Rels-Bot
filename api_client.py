import json
import os
from datetime import datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

LECTURES_API_URL = os.getenv("LECTURES_API_URL", "https://rels-alpha.vercel.app/api/lectures")
API_AUTHORIZATION = os.getenv("API_AUTHORIZATION", "")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "")
API_COOKIE = os.getenv("API_COOKIE", "")


class ApiError(RuntimeError):
    pass


def _headers():
    headers = {
        "Accept": "application/json",
        "User-Agent": "rels-discord-bot/1.0",
    }
    if API_AUTHORIZATION:
        headers["Authorization"] = API_AUTHORIZATION
    elif API_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {API_BEARER_TOKEN}"
    if API_COOKIE:
        headers["Cookie"] = API_COOKIE
    return headers


def _request_json(url):
    request = Request(url, headers=_headers())
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


def _pick(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in ("lectures", "data", "content", "result", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _pick(value)
            if nested:
                return nested
    return []


def _first(source, *keys, default=None):
    if not isinstance(source, dict):
        return default
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return default


def _nested(source, key, *nested_keys, default=None):
    value = _first(source, key, default={})
    if not isinstance(value, dict):
        return default
    return _first(value, *nested_keys, default=default)


def _parse_datetime(value):
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _date_part(value):
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.date()
    return value


def _time_part(value):
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.time()
    return value


def _normalize(raw):
    lecture_date = _first(raw, "lecture_date", "lectureDate", "date", "startDate")
    lecture_time = _first(raw, "lecture_time", "lectureTime", "time", "startTime")
    starts_at = _first(raw, "startsAt", "startAt", "lectureAt", "createdAt")

    enrolled_count = _first(
        raw,
        "enrolled_count",
        "enrolledCount",
        "applicantCount",
        "applicationCount",
        "participantCount",
        "currentCount",
        default=0,
    )

    try:
        enrolled_count = int(enrolled_count or 0)
    except (TypeError, ValueError):
        enrolled_count = 0

    return {
        "id": _first(raw, "id", "lectureId", "uuid", default=_first(raw, "title", "name", default="unknown")),
        "title": _first(raw, "title", "name", "lectureTitle", default="제목 없음"),
        "description": _first(raw, "description", "content", default=""),
        "status": str(_first(raw, "status", "state", default="OPEN")).upper(),
        "lecture_location": _first(raw, "lecture_location", "lectureLocation", "location", "place", default="미정"),
        "lecture_date": _date_part(lecture_date or starts_at),
        "lecture_time": _time_part(lecture_time or starts_at),
        "application_deadline": _first(
            raw,
            "application_deadline",
            "applicationDeadline",
            "deadline",
            "dueDate",
        ),
        "total_capacity": _first(raw, "total_capacity", "totalCapacity", "capacity", "maxParticipants", default=0),
        "creator_name": _first(
            raw,
            "creator_name",
            "creatorName",
            "speaker",
            "speakerName",
            "lecturer",
            default=_nested(raw, "creator", "name", "nickname", default="미정"),
        ),
        "enrolled_count": enrolled_count,
        "raw": raw,
    }


def fetch_open_lectures():
    payload = _request_json(LECTURES_API_URL)
    lectures = [_normalize(item) for item in _pick(payload)]
    return [lecture for lecture in lectures if lecture["status"] in {"OPEN", "CONFIRMED"}]


def fetch_all_lectures_basic():
    return [lecture for lecture in fetch_open_lectures() if lecture["status"] == "OPEN"]


def fetch_enrollment_counts():
    return {
        lecture["id"]: {
            "lecture_id": lecture["id"],
            "enrolled_count": lecture.get("enrolled_count", 0),
        }
        for lecture in fetch_open_lectures()
    }
