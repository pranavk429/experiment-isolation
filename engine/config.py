"""Environment and credential loading for the local Flagsmith instance."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from .util import ConfigError

DEFAULT_ENV_FILE = Path.home() / "flagsmith-local" / "flagsmith.env"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def load_env_file(path: Optional[Path] = None) -> None:
    """Load export KEY=value lines without overriding the real environment.

    This mirrors sourcing ~/flagsmith-local/flagsmith.env so direct command
    invocation also works. Values are never logged.
    """
    env_path = path or DEFAULT_ENV_FILE
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if name and name not in os.environ:
            os.environ[name] = value


def _host_scoped_key_name(api_url: str) -> str:
    parsed = urllib.parse.urlparse(api_url)
    host = (parsed.hostname or "").replace(".", "_")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return "FLAGSMITH_API_KEY_%s_%s" % (host, port)


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
        load_env_file()
        api_url = (os.environ.get("FLAGSMITH_API_URL") or "").strip().rstrip("/")
        if not api_url:
            raise ConfigError(
                "FLAGSMITH_API_URL is not set. Source ~/flagsmith-local/flagsmith.env."
            )
        parsed = urllib.parse.urlparse(api_url)
        if parsed.hostname not in LOCAL_HOSTS and os.environ.get("ISO_ALLOW_REMOTE") != "1":
            raise ConfigError(
                "Refusing non-local API URL %r (set ISO_ALLOW_REMOTE=1 only for a disposable host)"
                % api_url
            )
        admin_key = (
            os.environ.get(_host_scoped_key_name(api_url))
            or os.environ.get("FLAGSMITH_API_KEY")
            or ""
        ).strip()
        if not admin_key:
            raise ConfigError(
                "No admin API key found (expected %s)." % _host_scoped_key_name(api_url)
            )
        selected_env = (env_key or os.environ.get("DEV_ENV_KEY") or "").strip()
        if not selected_env:
            raise ConfigError("No environment key. Pass --env or set DEV_ENV_KEY.")
        project = (os.environ.get("FLAGSMITH_PROJECT") or "1").strip()
        return cls(
            api_url=api_url,
            admin_key=admin_key,
            env_key=selected_env,
            project=project,
            env_file=str(DEFAULT_ENV_FILE) if DEFAULT_ENV_FILE.is_file() else "",
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
