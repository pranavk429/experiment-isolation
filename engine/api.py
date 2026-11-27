"""Minimal stdlib Flagsmith Admin and Edge API clients."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .config import Config
from .util import EngineError


class ApiError(EngineError):
    """An API request failed. Message is sanitized and truncated."""

    def __init__(self, status: int, path: str, message: str) -> None:
        self.status = status
        self.path = path
        super().__init__("HTTP %s on %s: %s" % (status, path, message[:400]))


def _safe_detail(raw: bytes, secret: str) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if secret:
        text = text.replace(secret, "<redacted>")
    try:
        parsed = json.loads(text)
    except ValueError:
        return " ".join(text.split())[:400]
    if isinstance(parsed, dict):
        if "detail" in parsed:
            return str(parsed["detail"])[:400]
        return json.dumps(parsed, separators=(",", ":"))[:400]
    return str(parsed)[:400]


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
        url = path if path.startswith("http") else self.base + path
        data = None
        headers = {
            "Authorization": "Api-Key " + self.config.admin_key,
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        safe_path = path.replace(self.config.env_key, "<env>")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = _safe_detail(exc.read(), self.config.admin_key)
            raise ApiError(exc.code, safe_path, detail.replace(self.config.env_key, "<env>")) from exc
        except urllib.error.URLError as exc:
            raise EngineError("Cannot reach Flagsmith at %s: %s" % (self.base, exc.reason)) from exc
        except (TimeoutError, OSError) as exc:
            raise EngineError("Flagsmith request timed out or failed: %s" % exc) from exc
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as exc:
            raise EngineError("Non-JSON response from %s" % safe_path) from exc

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
        next_url = path
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
        projects = self.get_all("/api/v1/projects/")
        for project in projects:
            if str(project.get("id")) == str(wanted) or project.get("name") == wanted:
                return int(project["id"])
        raise EngineError("Project %r not found on %s" % (wanted, self.base))

    def environment(self) -> Dict[str, Any]:
        data = self.get("/api/v1/environments/%s/" % self.config.env_key)
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
        url = self.base + "/api/v1/identities/?" + query
        request = urllib.request.Request(
            url,
            headers={
                "X-Environment-Key": self.config.env_key,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise ApiError(exc.code, "/api/v1/identities/", _safe_detail(exc.read(), "")) from exc
        except urllib.error.URLError as exc:
            raise EngineError("Cannot reach Flagsmith at %s: %s" % (self.base, exc.reason)) from exc
        except (TimeoutError, OSError) as exc:
            raise EngineError("Flagsmith identity request timed out or failed: %s" % exc) from exc
