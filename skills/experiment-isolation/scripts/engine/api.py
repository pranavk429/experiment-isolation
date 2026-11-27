"""Minimal stdlib Flagsmith Admin and Edge API clients.

Structured admin and edge calls use urllib with header authentication for
strict HTTP status checking and pagination; synthetic trait evaluation uses
``flagsmith evaluate --persist --json`` in ``sampling.py``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

from .config import Config
from .util import EngineError, sanitize_text


class ApiError(EngineError):
    """An API request failed. Message is sanitized and truncated."""

    def __init__(self, status: int, path: str, message: str) -> None:
        self.status = status
        self.path = path
        super().__init__(f"HTTP {status} on {path}: {message[:400]}")


def _safe_detail(raw: bytes, *secrets: str) -> str:
    text = raw.decode("utf-8", "replace").strip()
    text = sanitize_text(text, *secrets, limit=2000)
    try:
        parsed = json.loads(text)
    except ValueError:
        return text[:400]
    if isinstance(parsed, dict):
        detail = parsed.get("detail") or parsed.get("message")
        if detail is not None:
            return sanitize_text(str(detail), *secrets)
        return sanitize_text(json.dumps(parsed, separators=(",", ":")), *secrets)
    return sanitize_text(str(parsed), *secrets)


def request_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Any] = None,
    timeout: float = 60.0,
    secrets: Sequence[str] = (),
    safe_path: Optional[str] = None,
    not_found_none: bool = False,
) -> Any:
    """Execute an HTTP JSON request with sanitized errors."""
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    display_path = safe_path or url
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if not_found_none and exc.code == 404:
            return None
        raise ApiError(exc.code, display_path, _safe_detail(exc.read(), *secrets)) from exc
    except urllib.error.URLError as exc:
        raise EngineError(f"Cannot reach Flagsmith ({display_path}): {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise EngineError(f"Flagsmith request timed out or failed: {exc}") from exc
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise EngineError(f"Non-JSON response from {display_path}") from exc


class AdminAPI:
    """Flagsmith admin API using the Authorization Api-Key header."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base = config.api_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base}{path}"
        safe_path = path.replace(self.config.env_key, "<env>")
        return request_json(
            method,
            url,
            headers={"Authorization": f"Api-Key {self.config.admin_key}"},
            payload=payload,
            timeout=60.0,
            secrets=(self.config.admin_key, self.config.env_key),
            safe_path=safe_path,
        )

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, payload if payload is not None else {})

    def patch(self, path: str, payload: Dict[str, Any]) -> Any:
        return self._request("PATCH", path, payload)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def get_all(self, path: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Read a paginated list endpoint."""
        results: List[Dict[str, Any]] = []
        next_url: Optional[str] = path
        while next_url and len(results) < limit:
            page = self.get(next_url)
            if isinstance(page, list):
                results.extend(page)
                break
            if not isinstance(page, dict):
                break
            results.extend(page.get("results") or [])
            next_url = page.get("next")
        return results[:limit]

    def resolve_project_id(self) -> int:
        """Resolve FLAGSMITH_PROJECT (id or name) to a project id."""
        wanted = self.config.project
        for project in self.get_all("/api/v1/projects/"):
            if str(project.get("id")) == str(wanted) or project.get("name") == wanted:
                return int(project["id"])
        raise EngineError(f"Project {wanted!r} not found on {self.base}")

    def environment(self) -> Dict[str, Any]:
        data = self.get(f"/api/v1/environments/{self.config.env_key}/")
        if not isinstance(data, dict):
            raise EngineError("Unexpected environment response")
        return data


class EdgeAPI:
    """Flagsmith Edge API using the X-Environment-Key header."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base = config.api_url.rstrip("/")

    def identity(self, identifier: str) -> Optional[Dict[str, Any]]:
        query = urllib.parse.urlencode({"identifier": identifier})
        url = f"{self.base}/api/v1/identities/?{query}"
        return request_json(
            "GET",
            url,
            headers={"X-Environment-Key": self.config.env_key},
            timeout=30.0,
            secrets=(self.config.env_key, self.config.admin_key),
            safe_path="/api/v1/identities/",
            not_found_none=True,
        )
