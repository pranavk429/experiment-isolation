"""Environment and credential loading for a local Flagsmith instance."""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from .util import ConfigError, parse_env_file

DEFAULT_ENV_FILE = Path.home() / "flagsmith-local" / "flagsmith.env"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def load_env_file(path: Optional[Path] = None) -> None:
    """Load export KEY=value lines without overriding existing environment variables."""
    env_path = path or DEFAULT_ENV_FILE
    for name, value in parse_env_file(env_path).items():
        if name not in os.environ:
            os.environ[name] = value


def _host_scoped_key_name(api_url: str) -> str:
    parsed = urllib.parse.urlparse(api_url)
    host = re.sub(r"[^A-Za-z0-9]", "_", parsed.hostname or "")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"FLAGSMITH_API_KEY_{host}_{port}"


def _should_load_default_env(pre_api_url: str) -> bool:
    if not DEFAULT_ENV_FILE.is_file():
        return False
    if not pre_api_url:
        return True
    file_url = (parse_env_file(DEFAULT_ENV_FILE).get("FLAGSMITH_API_URL") or "").strip().rstrip("/")
    return bool(file_url and file_url == pre_api_url)


def _resolve_env_file() -> str:
    explicit = (os.environ.get("FLAGSMITH_ENV_FILE") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        load_env_file(path)
        return str(path) if path.is_file() else ""
    pre_api_url = (os.environ.get("FLAGSMITH_API_URL") or "").strip().rstrip("/")
    if _should_load_default_env(pre_api_url):
        load_env_file(DEFAULT_ENV_FILE)
        return str(DEFAULT_ENV_FILE)
    return ""


@dataclass
class Config:
    """Resolved local Flagsmith configuration. Secrets are hidden from repr."""

    api_url: str
    admin_key: str = field(repr=False)
    env_key: str = field(repr=False)
    project: str
    env_file: str = ""

    @classmethod
    def load(cls, env_key: Optional[str] = None) -> "Config":
        env_file = _resolve_env_file()
        api_url = (os.environ.get("FLAGSMITH_API_URL") or "").strip().rstrip("/")
        if not api_url:
            raise ConfigError(
                "FLAGSMITH_API_URL is not set. Export FLAGSMITH_API_URL, an admin API key, "
                "and DEV_ENV_KEY (or set FLAGSMITH_ENV_FILE)."
            )
        parsed = urllib.parse.urlparse(api_url)
        if parsed.hostname not in LOCAL_HOSTS and os.environ.get("ISO_ALLOW_REMOTE") != "1":
            raise ConfigError(
                f"Refusing non-local API URL {api_url!r} "
                "(set ISO_ALLOW_REMOTE=1 only for a disposable host)"
            )
        scoped_name = _host_scoped_key_name(api_url)
        admin_key = (
            os.environ.get(scoped_name) or os.environ.get("FLAGSMITH_API_KEY") or ""
        ).strip()
        if not admin_key:
            raise ConfigError(
                f"No admin API key found (expected {scoped_name} or FLAGSMITH_API_KEY)."
            )
        selected_env = (
            env_key
            or os.environ.get("DEV_ENV_KEY")
            or os.environ.get("FLAGSMITH_ENVIRONMENT_KEY")
            or os.environ.get("FLAGSMITH_ENVIRONMENT")
            or ""
        ).strip()
        if not selected_env:
            raise ConfigError(
                "No environment key. Pass --env or set DEV_ENV_KEY / FLAGSMITH_ENVIRONMENT_KEY."
            )
        project = (os.environ.get("FLAGSMITH_PROJECT") or "1").strip()
        return cls(
            api_url=api_url,
            admin_key=admin_key,
            env_key=selected_env,
            project=project,
            env_file=env_file,
        )

    def cli_env(self) -> Dict[str, str]:
        """Environment for the flagsmith subprocess; contains secrets, never printed."""
        child = os.environ.copy()
        child.update(
            {
                "FLAGSMITH_API_URL": self.api_url,
                "FLAGSMITH_ENVIRONMENT": self.env_key,
                "FLAGSMITH_PROJECT": self.project,
                "FLAGSMITH_NO_INPUT": "1",
            }
        )
        child.setdefault(_host_scoped_key_name(self.api_url), self.admin_key)
        child.setdefault("FLAGSMITH_API_KEY", self.admin_key)
        return child

    def public_environment(self, name: str, environment_id: int) -> Dict[str, object]:
        """Non-secret environment descriptor for reports."""
        return {
            "id": environment_id,
            "name": name,
            "key_prefix": self.env_key[:4],
        }
