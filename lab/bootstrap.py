#!/usr/bin/env python3
"""Bootstrap the Experiment Isolation Lab's self-hosted Flagsmith instance.

Sequence (mirrors the official coding-agent guide):
  1. POST /api/v1/auth/users/             (superuser, only while no users exist)
  2. POST /api/v1/organisations/
  3. POST /api/v1/projects/
  4. POST /api/v1/environments/           (Development and Production)
  5. POST /api/v1/environments/<key>/warehouse-connections/
  6. POST /api/v1/organisations/<id>/master-api-keys/

Docs: https://docs.flagsmith.com/getting-started/run-locally-with-a-coding-agent

The generated lab/.env is written with mode 600. Keys and passwords are never
printed; the summary only names what was created.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import string
import sys
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from lablib import (
    DEFAULT_API_URL,
    DEFAULT_EMAIL,
    DEFAULT_ORG_NAME,
    DEFAULT_PROJECT_NAME,
    ENV_PATH,
    LabError,
    find_by_name,
    get_list,
    load_env,
    request_json,
    require,
    wait_for_url,
    write_env,
)

ADMIN_KEY_NAME = "Experiment Isolation Lab"
DEV_NAME = "Development"
PROD_NAME = "Production"
PASSWORD_ALPHABET = string.ascii_letters + string.digits + "-_"


def generate_password(length: int = 28) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def version_payload(base_url: str) -> Dict[str, Any]:
    body = request_json("GET", "/version/", base_url=base_url)
    return body if isinstance(body, dict) else {}


def has_users(version: Dict[str, Any]) -> bool:
    data = version.get("self_hosted_data") or {}
    return bool(data.get("has_users"))


def token_is_valid(base_url: str, token: str) -> bool:
    try:
        request_json("GET", "/auth/users/me/", base_url=base_url, token=token)
        return True
    except LabError:
        return False


def api_key_is_valid(base_url: str, api_key: str) -> bool:
    try:
        request_json("GET", "/organisations/", base_url=base_url, api_key=api_key)
        return True
    except LabError:
        return False


def login(base_url: str, email: str, password: str) -> str:
    body = request_json(
        "POST",
        "/auth/login/",
        base_url=base_url,
        payload={"email": email, "password": password},
    )
    if not isinstance(body, dict):
        raise LabError("Login returned an unexpected response")
    return require(body.get("key"), "Login did not return an API token")


def create_admin(base_url: str, email: str, password: str) -> str:
    last_error: Optional[LabError] = None
    for attempt in range(3):
        try:
            body = request_json(
                "POST",
                "/auth/users/",
                base_url=base_url,
                payload={
                    "email": email,
                    "password": password,
                    "re_password": password,
                    "first_name": "Isolation",
                    "last_name": "Lab",
                    "superuser": True,
                },
                expected=(200, 201),
            )
            if isinstance(body, dict) and body.get("key"):
                return str(body["key"])
            return login(base_url, email, password)
        except LabError as exc:
            last_error = exc
            # A freshly started Django process can briefly answer 405 before its
            # URL configuration is fully live. Retry only that transient case.
            if "HTTP 405" not in str(exc) or attempt == 2:
                raise
            time.sleep(2)
    raise last_error or LabError("Could not create the admin user")


def ensure_admin(
    base_url: str, version: Dict[str, Any], env: Dict[str, str]
) -> Tuple[str, str, str]:
    """Create the first superuser or reuse the one recorded in lab/.env."""
    existing_token = env.get("LAB_ADMIN_TOKEN", "")
    if has_users(version):
        if existing_token and token_is_valid(base_url, existing_token):
            print("Admin: reusing the token saved in lab/.env")
            return existing_token, env.get("LAB_ADMIN_EMAIL", ""), env.get("LAB_ADMIN_PASSWORD", "")
        email = env.get("LAB_ADMIN_EMAIL", DEFAULT_EMAIL)
        password = env.get("LAB_ADMIN_PASSWORD", "")
        if not password:
            raise LabError(
                "Flagsmith already has users but lab/.env has no admin password.\n"
                "  Either restore lab/.env or remove the lab volume and start clean:\n"
                "  docker compose -p isolation-lab -f lab/docker-compose.yml down -v"
            )
        token = login(base_url, email, password)
        print(f"Admin: logged in as {email}")
        return token, email, password

    email = env.get("LAB_ADMIN_EMAIL", DEFAULT_EMAIL)
    password = env.get("LAB_ADMIN_PASSWORD") or generate_password()
    try:
        token = create_admin(base_url, email, password)
        print(f"Admin: created superuser {email}")
    except LabError as exc:
        # A race with another bootstrap is the only expected reason to get here.
        if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
            raise
        token = login(base_url, email, password)
        print(f"Admin: user already existed, logged in as {email}")
    return token, email, password


def ensure_org(base_url: str, token: str, env: Dict[str, str]) -> Dict[str, Any]:
    name = env.get("LAB_ORG_NAME", DEFAULT_ORG_NAME)
    org = find_by_name(get_list("/organisations/", base_url=base_url, token=token), name)
    if org:
        return org
    org = request_json(
        "POST", "/organisations/", base_url=base_url, token=token, payload={"name": name}
    )
    if not isinstance(org, dict):
        raise LabError("Organisation creation returned an unexpected response")
    print(f"Organisation: created {name}")
    return org


def ensure_project(
    base_url: str, token: str, org_id: int, env: Dict[str, str]
) -> Dict[str, Any]:
    name = env.get("LAB_PROJECT_NAME", DEFAULT_PROJECT_NAME)
    try:
        projects = get_list(
            f"/organisations/{org_id}/projects/", base_url=base_url, token=token
        )
    except LabError:
        projects = [
            project
            for project in get_list("/projects/", base_url=base_url, token=token)
            if project.get("organisation") == org_id
        ]
    project = find_by_name(projects, name)
    if project:
        return project
    project = request_json(
        "POST",
        "/projects/",
        base_url=base_url,
        token=token,
        payload={"name": name, "organisation": org_id},
    )
    if not isinstance(project, dict):
        raise LabError("Project creation returned an unexpected response")
    print(f"Project: created {name}")
    return project


def ensure_environment(
    base_url: str, token: str, project_id: int, name: str
) -> Dict[str, Any]:
    environments = get_list(
        f"/environments/?project={project_id}", base_url=base_url, token=token
    )
    environment = find_by_name(environments, name)
    if environment:
        return environment
    environment = request_json(
        "POST",
        "/environments/",
        base_url=base_url,
        token=token,
        payload={"name": name, "project": project_id},
    )
    if not isinstance(environment, dict):
        raise LabError("Environment creation returned an unexpected response")
    print(f"Environment: created {name}")
    return environment


def ensure_warehouse(
    base_url: str, token: str, environment: Dict[str, Any], enabled: bool
) -> str:
    """Connect an environment to Flagsmith's own Postgres warehouse."""
    if not enabled:
        raise LabError(
            "Experimentation is disabled. Set EXPERIMENTATION_ENABLED=true and recreate the lab:\n"
            "  docker compose -p isolation-lab -f lab/docker-compose.yml down -v\n"
            "  bash lab/run.sh"
        )
    key = require(environment.get("api_key"), "Environment is missing its API key")
    path = f"/environments/{key}/warehouse-connections/"
    for connection in get_list(path, base_url=base_url, token=token):
        if connection.get("warehouse_type") != "postgres":
            continue
        status = str(connection.get("status", "")).lower()
        if status == "connected":
            return status
        # A previous bootstrap may have created the row but failed the test.
        print(f"Warehouse: found an existing Postgres connection in status {status!r}")
        break

    body = request_json(
        "POST",
        path,
        base_url=base_url,
        token=token,
        payload={
            "warehouse_type": "postgres",
            "config": {"source": "flagsmith_database"},
        },
    )
    status = str((body or {}).get("status", "")).lower() if isinstance(body, dict) else ""
    if status != "connected":
        raise LabError(
            f"Warehouse connection did not reach status=connected (got {status or 'no status'!r}).\n"
            "  Check: docker compose -p isolation-lab -f lab/docker-compose.yml logs --tail=40 flagsmith"
        )
    return status


def ensure_admin_key(
    base_url: str, token: str, org_id: int, env: Dict[str, str]
) -> str:
    existing = env.get("LAB_ADMIN_API_KEY", "")
    if existing and api_key_is_valid(base_url, existing):
        print("Admin API key: reusing the key saved in lab/.env")
        return existing
    body = request_json(
        "POST",
        f"/organisations/{org_id}/master-api-keys/",
        base_url=base_url,
        token=token,
        payload={"name": ADMIN_KEY_NAME, "is_admin": True},
    )
    if not isinstance(body, dict):
        raise LabError("Admin API key creation returned an unexpected response")
    key = require(body.get("key"), "Admin API key was not returned (it is shown only once)")
    if not api_key_is_valid(base_url, key):
        raise LabError("New admin API key could not authenticate a test request")
    print("Admin API key: created and saved to lab/.env")
    return key


def update_env(
    env: Dict[str, str],
    base_url: str,
    email: str,
    password: str,
    token: str,
    org: Dict[str, Any],
    project: Dict[str, Any],
    dev: Dict[str, Any],
    prod: Dict[str, Any],
    admin_key: str,
) -> None:
    parsed = urlparse(base_url)
    host = re.sub(r"[^A-Za-z0-9]", "_", parsed.hostname or "localhost")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    env.update(
        {
            "LAB_API_URL": base_url,
            "LAB_ADMIN_EMAIL": email,
            "LAB_ADMIN_PASSWORD": password,
            "LAB_ADMIN_TOKEN": token,
            "LAB_ORG_ID": str(org.get("id", "")),
            "LAB_ORG_NAME": str(org.get("name", "")),
            "LAB_PROJECT_ID": str(project.get("id", "")),
            "LAB_PROJECT_NAME": str(project.get("name", "")),
            "LAB_DEV_ENV_ID": str(dev.get("id", "")),
            "LAB_DEV_ENV_KEY": str(dev.get("api_key", "")),
            "LAB_PROD_ENV_ID": str(prod.get("id", "")),
            "LAB_PROD_ENV_KEY": str(prod.get("api_key", "")),
            "LAB_ADMIN_API_KEY": admin_key,
            "FLAGSMITH_API_URL": base_url,
            "FLAGSMITH_API_KEY": admin_key,
            "FLAGSMITH_ENVIRONMENT_KEY": str(dev.get("api_key", "")),
            "DEV_ENV_KEY": str(dev.get("api_key", "")),
            "PROD_ENV_KEY": str(prod.get("api_key", "")),
            "FLAGSMITH_PROJECT": str(project.get("name", "")),
            f"FLAGSMITH_API_KEY_{host}_{port}": admin_key,
        }
    )
    if (parsed.hostname, port) != ("localhost", 8010):
        env["FLAGSMITH_API_KEY_localhost_8010"] = admin_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.environ.get("LAB_API_URL", DEFAULT_API_URL),
        help=f"Flagsmith base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="Seconds to wait for the API to become healthy (default: 240)",
    )
    return parser.parse_args()


def _check_experimentation(base_url: str) -> Tuple[Dict[str, Any], bool]:
    version = version_payload(base_url)
    experimentation_enabled = bool(version.get("experimentation_enabled"))
    image_tag = version.get("image_tag") or "unknown"
    print(f"  Version: {image_tag}; experimentation enabled: {experimentation_enabled}")
    if not experimentation_enabled:
        raise LabError(
            "This Flagsmith instance was started with experimentation disabled.\n"
            "  The lab Compose file sets EXPERIMENTATION_ENABLED=true; recreate it with:\n"
            "  docker compose -p isolation-lab -f lab/docker-compose.yml down -v && bash lab/run.sh"
        )
    return version, experimentation_enabled


def _print_summary(
    base_url: str,
    org: Dict[str, Any],
    project: Dict[str, Any],
    dev_status: str,
    prod_status: str,
) -> None:
    print("")
    print("Lab ready.")
    print(f"  Flagsmith:      {base_url}")
    print(f"  Organisation:   {org.get('name')} (id {org.get('id')})")
    print(f"  Project:        {project.get('name')} (id {project.get('id')})")
    print(f"  Environments:   {DEV_NAME}, {PROD_NAME} (keys saved to lab/.env)")
    print(f"  Warehouse:      Development={dev_status}, Production={prod_status}")
    print("  Secrets:        saved to lab/.env (chmod 600, gitignored)")
    print("  Next:           python3 lab/seed/seed.py")


def main() -> int:
    args = parse_args()
    base_url = args.api_url.rstrip("/")
    api_base = f"{base_url}/api/v1"
    env = load_env()
    print("Experiment Isolation Lab bootstrap")
    print(f"  API: {base_url}")
    print(f"  Env: {ENV_PATH} (mode 600)")
    wait_for_url(f"{base_url}/health/liveness/", args.timeout, "Flagsmith API")
    # Allow Django URL configuration to finish loading after liveness turns 200.
    time.sleep(1.5)

    version, experimentation_enabled = _check_experimentation(base_url)
    token, email, password = ensure_admin(api_base, version, env)
    env.update({"LAB_ADMIN_EMAIL": email, "LAB_ADMIN_PASSWORD": password, "LAB_ADMIN_TOKEN": token})
    write_env(env)

    org = ensure_org(api_base, token, env)
    project = ensure_project(api_base, token, int(org["id"]), env)
    dev = ensure_environment(api_base, token, int(project["id"]), DEV_NAME)
    prod = ensure_environment(api_base, token, int(project["id"]), PROD_NAME)
    dev_status = ensure_warehouse(api_base, token, dev, experimentation_enabled)
    prod_status = ensure_warehouse(api_base, token, prod, experimentation_enabled)
    admin_key = ensure_admin_key(api_base, token, int(org["id"]), env)

    update_env(env, base_url, email, password, token, org, project, dev, prod, admin_key)
    write_env(env)
    _print_summary(base_url, org, project, dev_status, prod_status)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LabError as exc:
        print(f"bootstrap: error: {exc}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("bootstrap: interrupted", file=sys.stderr)
        sys.exit(130)
