from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


_DEFAULT_ORIGIN = "https://mobifitness.ru"
_API_PATH = "/api/v8"
_FRANCHISE_ID = "706603"
_USER_AGENT = (
    "Android Mobifitness/4.22.4 "
    "(com.mobifitness.aquastarpavelec706603; "
    "build:4.22.4.11.20250903-1616.c69fc4f1)"
)
_HEADERS = {
    "Accept-Language": "ru-RU",
    "Content-Type": "application/json; charset=utf-8",
    "User-Agent": _USER_AGENT,
    "X-CustomBuild": "4.22.4.11.20250903-1616.c69fc4f1",
    "X-CustomOS": "Android",
    "X-CustomVersion": "4.22.4",
}

_lock = threading.Lock()
_access_token: str | None = None
_origin = _DEFAULT_ORIGIN


class AquaStarError(RuntimeError):
    pass


class _HttpStatusError(AquaStarError):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"Mobifitness returned HTTP {status} for {url}")
        self.status = status


@dataclass(frozen=True)
class AquaStarLoad:
    people: int
    title: str


@dataclass(frozen=True)
class _ClubRef:
    id: int
    title: str


async def get_current_load() -> AquaStarLoad:
    return await asyncio.to_thread(_get_current_load_sync)


def _get_current_load_sync() -> AquaStarLoad:
    global _access_token

    with _lock:
        token = _access_token or _request_service_token()
        try:
            clubs = _request_json("/franchise/clubs.json", token=token)
        except _HttpStatusError as exc:
            if exc.status != 401:
                raise
            token = _request_service_token()
            clubs = _request_json("/franchise/clubs.json", token=token)

        load = _find_load(clubs)
        if load is not None:
            return load

        refs = sorted(_find_club_refs(clubs), key=lambda club: not _is_paveletskaya(club.title))
        for club in refs:
            try:
                details = _request_json(f"/clubs/{club.id}.json", token=token)
            except _HttpStatusError as exc:
                if exc.status != 401:
                    continue
                token = _request_service_token()
                details = _request_json(f"/clubs/{club.id}.json", token=token)
            load = _find_load(details)
            if load is not None:
                return load

    raise AquaStarError("Mobifitness response does not contain currentLoad")


def _request_service_token() -> str:
    global _access_token, _origin

    query = urlencode(
        {
            "response_type": "token",
            "client_id": _FRANCHISE_ID,
            "locale": "ru-RU",
            "scope": "1",
        }
    )
    payload = _request_json(f"/oauth/access_token?{query}", token=None)
    if not isinstance(payload, dict):
        raise AquaStarError("Mobifitness token response is not an object")

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise AquaStarError("Mobifitness token response does not contain access_token")

    base_host = payload.get("base_host")
    if isinstance(base_host, str):
        normalized = _normalize_origin(base_host)
        if normalized is not None:
            _origin = normalized

    _access_token = token
    return token


def _request_json(path: str, *, token: str | None) -> Any:
    url = f"{_origin}{_API_PATH}{path}"
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise _HttpStatusError(exc.code, url) from exc
    except URLError as exc:
        raise AquaStarError(f"Mobifitness network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise AquaStarError("Mobifitness request timed out") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise AquaStarError("Mobifitness returned invalid JSON") from exc


def _normalize_origin(value: str) -> str | None:
    origin = value.strip()
    if not origin:
        return None
    if not origin.startswith("https://"):
        origin = f"https://{origin}"

    parsed = urlsplit(origin)
    host = (parsed.hostname or "").lower()
    if host != "mobifitness.ru" and not host.endswith(".mobifitness.ru"):
        return None
    return f"https://{host}"


def _find_load(value: Any) -> AquaStarLoad | None:
    fallback: AquaStarLoad | None = None
    if isinstance(value, list):
        for child in value:
            candidate = _find_load(child)
            if candidate is not None and _is_paveletskaya(candidate.title):
                return candidate
            if fallback is None and candidate is not None:
                fallback = candidate
        return fallback
    if not isinstance(value, dict):
        return None

    raw_load = value.get("currentLoad", value.get("current_load"))
    if raw_load is not None:
        try:
            people = int(str(raw_load).strip())
        except ValueError:
            pass
        else:
            title = str(value.get("title") or "AQUASTAR Павелецкая")
            return AquaStarLoad(people=people, title=title)

    for child in value.values():
        candidate = _find_load(child)
        if candidate is not None and _is_paveletskaya(candidate.title):
            return candidate
        if fallback is None and candidate is not None:
            fallback = candidate
    return fallback


def _find_club_refs(value: Any) -> list[_ClubRef]:
    result: list[_ClubRef] = []
    _collect_club_refs(value, result)
    return result


def _collect_club_refs(value: Any, result: list[_ClubRef]) -> None:
    if isinstance(value, list):
        for child in value:
            _collect_club_refs(child, result)
        return
    if not isinstance(value, dict):
        return

    club_id = value.get("id")
    title = value.get("title")
    if isinstance(club_id, int) and isinstance(title, str) and title:
        result.append(_ClubRef(id=club_id, title=title))
        return

    for child in value.values():
        _collect_club_refs(child, result)


def _is_paveletskaya(title: str) -> bool:
    lowered = title.lower()
    return "павел" in lowered or "pav" in lowered
