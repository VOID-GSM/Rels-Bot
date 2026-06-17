import json
import os
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

LECTURES_API_URL = os.getenv(
    "LECTURES_API_URL",
    "https://rels-alpha.vercel.app/api/lectures/discord",
)
API_AUTHORIZATION = os.getenv("API_AUTHORIZATION", "")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "")
API_COOKIE = os.getenv("API_COOKIE", "")
PAGE_SIZE = int(os.getenv("LECTURES_PAGE_SIZE", "100"))


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


def _with_query(url, params):
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


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


def _parse_datetime(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _date_part(value):
    parsed = _parse_datetime(value)
    return parsed.date() if parsed else value


def _time_part(value):
    parsed = _parse_datetime(value)
    return parsed.time() if parsed else value


def _normalize(raw):
    lecture_date = _first(raw, "lectureDate", "lecture_date", "date")
    lecture_time = _first(raw, "lectureTime", "lecture_time", "time")
    starts_at = _first(raw, "startsAt", "startAt", "lectureAt")
    capacity_by_grade = _first(raw, "capacityByGrade", "capacity_by_grade", default={}) or {}
    total_capacity = _first(raw, "totalCapacity", "total_capacity", "capacity", default=0)
    enrolled_count = _first(raw, "enrolledCount", "enrolled_count", "applicantCount", default=0)

    try:
        enrolled_count = int(enrolled_count or 0)
    except (TypeError, ValueError):
        enrolled_count = 0

    if not total_capacity and isinstance(capacity_by_grade, dict):
        total_capacity = sum(int(value or 0) for value in capacity_by_grade.values())

    try:
        total_capacity = int(total_capacity or 0)
    except (TypeError, ValueError):
        total_capacity = 0
        
    deadline = _first(raw, "applicationDeadline", "application_deadline", "deadline")
    if deadline and isinstance(deadline, str):
        deadline = deadline.replace("T", " ")

    lecture_id = _first(raw, "id", "lectureId", default="")
    lecture_url = f"https://rels-alpha.vercel.app/lectures/{lecture_id}" if lecture_id else "https://rels-alpha.vercel.app"

    target_grades = _format_target(capacity_by_grade)
    if target_grades == "전체":
        target_info = f"전체 인원 ({total_capacity}명)"
    else:
        target_info = f"신청 가능한 학년: {target_grades} ({total_capacity}명)"

    return {
        "id": lecture_id if lecture_id else _first(raw, "title", default="unknown"),
        "title": _first(raw, "title", default="제목 없음"),
        "description": _first(raw, "description", default=""),
        "status": str(_first(raw, "status", default="OPEN")).upper(),
        "lecture_location": _first(raw, "lectureLocation", "lecture_location", "location", default="미정"),
        "lecture_date": _date_part(lecture_date or starts_at),
        "lecture_time": _time_part(lecture_time or starts_at),
        "application_deadline": deadline,
        "total_capacity": total_capacity,
        "creator_name": _first(raw, "creatorName", "creator_name", "speakerName", "speaker", default="미정"),
        "target": target_grades,
        "target_info": target_info, 
        "lecture_url": lecture_url,  
        "enrolled_count": enrolled_count,
        "raw": raw,
    }


def _format_target(capacity_by_grade):
    if not isinstance(capacity_by_grade, dict) or not capacity_by_grade:
        return "전체"

    grades = sorted(str(grade) for grade, capacity in capacity_by_grade.items() if int(capacity or 0) > 0)
    if not grades:
        return "전체"
    return ", ".join(f"{grade}학년" for grade in grades)


def fetch_open_lectures():
    url = _with_query(LECTURES_API_URL, {"size": PAGE_SIZE})
    payload = _request_json(url)
    lectures = [_normalize(item) for item in _pick_lectures(payload)]
    return [
        lecture
        for lecture in lectures
        if lecture["status"] in {"OPEN", "CONFIRMED", "CONFIRM"}
    ]


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


# --- 디스코드 봇 컴포넌트(main.py 등)에서 메시지를 출력할 때 참고할 수 있는 빌더 가이드 함수 ---
def get_embed_description_example(lecture):
    """
    !릴스 명령어 처리부나 알람 전송부에서 Embed description 혹은 필드를 구성할 때 
    아래 형식을 참고하여 조립하시면 스크린샷과 같이 줄바꿈 공백이 반영됩니다.
    """
    return (
        f"**연사자**: {lecture['creator_name']}\n\n"
        f"**일시**: {lecture['lecture_date']} {lecture['lecture_time']}\n\n"
        f"**마감**: {lecture['application_deadline']}\n\n"
        f"**대상**: {lecture['target_info']}\n\n"
        f"**바로가기**: [강연 상세 보기]({lecture['lecture_url']})"
    )