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

    # Spring Page<T> 응답은 보통 content 안에 목록이 들어옵니다.
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