#!/usr/bin/env python3
"""Tiny stdlib storefront for the Experiment Isolation Lab.

Two pages (pricing banner, onboarding tip) are evaluated through the Flagsmith
SDK/edge endpoint POST /api/v1/identities/ with a synthetic identity. Every
evaluation sends the stable integer trait flagsmith_experiment_bucket (0-99),
which is what disjoint experiment audiences are built on.

Run: python3 lab/storefront/app.py --port 8020
"""

from __future__ import annotations

import argparse
import html
import json
import re
import string
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

STOREFRONT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STOREFRONT_DIR.parent))

import lablib  # noqa: E402, F401
from engine.sampling import bucket_for  # noqa: E402
from lablib import DEFAULT_API_URL, LAB_DIR, LabError, load_env, request_json  # noqa: E402

TEMPLATES_DIR = STOREFRONT_DIR / "templates"
STATIC_DIR = STOREFRONT_DIR / "static"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
COUNTRIES = ("US", "GB")
PLATFORMS = ("mobile", "desktop")

FLAGS = {
    "pricing_banner": {
        "title": "Pricing banner",
        "eyebrow": "EXPERIMENT 01 · PRICING",
        "description": "Does urgency copy move US mobile checkout?",
        "control": "Simple pricing that scales with your team.",
        "variant_key": "urgent",
        "variant_copy": "Only 3 seats left — save 20% today.",
    },
    "onboarding_tip": {
        "title": "Onboarding tip",
        "eyebrow": "EXPERIMENT 02 · ACTIVATION",
        "description": "Does a shorter first-session tip improve activation?",
        "control": "Welcome! Take the full guided tour to set up your workspace.",
        "variant_key": "short",
        "variant_copy": "Start with a 3-step tour. You can finish setup later.",
    },
}

stable_bucket = bucket_for


def _parse_flags(body: Any) -> Dict[str, Dict[str, Any]]:
    raw_flags: Dict[str, Dict[str, Any]] = {}
    if isinstance(body, dict):
        for item in body.get("flags") or []:
            feature = item.get("feature") or {}
            name = str(feature.get("name", ""))
            if not name:
                continue
            metadata = item.get("metadata") or {}
            experiment = metadata.get("experiment") or {}
            raw_flags[name] = {
                "name": name,
                "enabled": bool(item.get("enabled")),
                "value": item.get("feature_state_value"),
                "variant": item.get("variant"),
                "reason": item.get("reason"),
                "in_experiment": bool(experiment.get("in_experiment")),
                "experiment_id": experiment.get("id"),
                "experiment_name": experiment.get("name"),
            }
    return {
        name: raw_flags.get(
            name,
            {
                "name": name,
                "enabled": False,
                "value": None,
                "variant": None,
                "reason": "feature not returned by the edge API",
                "in_experiment": False,
                "experiment_id": None,
                "experiment_name": None,
            },
        )
        for name in FLAGS
    }


def evaluate_identity(
    api_url: str, env_key: str, identifier: str, country: str, platform: str
) -> Dict[str, Any]:
    bucket = stable_bucket(identifier)
    traits = [
        {"trait_key": "country", "trait_value": country},
        {"trait_key": "platform", "trait_value": platform},
        {"trait_key": "flagsmith_experiment_bucket", "trait_value": bucket},
    ]
    body = request_json(
        "POST",
        "/api/v1/identities/",
        base_url=api_url,
        payload={"identifier": identifier, "traits": traits},
        extra_headers={"X-Environment-Key": env_key},
        timeout=12.0,
    )
    return {
        "identifier": identifier,
        "bucket": bucket,
        "country": country,
        "platform": platform,
        "traits": {trait["trait_key"]: trait["trait_value"] for trait in traits},
        "flags": _parse_flags(body),
    }


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _first(query: Dict[str, list], key: str, default: str) -> str:
    values = query.get(key) or []
    return values[0] if values else default


def parse_identity(query: Dict[str, list]) -> Tuple[str, str, str]:
    identifier = _first(query, "identifier", "demo-us-mobile-001").strip()
    country = _first(query, "country", "US").strip().upper()
    platform = _first(query, "platform", "mobile").strip().lower()
    if not IDENTIFIER_RE.match(identifier):
        raise ValueError("Identifier must be 1-128 characters: letters, numbers, . _ : @ -")
    if country not in COUNTRIES:
        country = "US"
    if platform not in PLATFORMS:
        platform = "mobile"
    return identifier, country, platform


def flag_card(name: str, flag: Dict[str, Any]) -> str:
    spec = FLAGS[name]
    value = flag.get("value")
    variant = flag.get("variant") or value
    enabled = bool(flag.get("enabled"))
    on_class = "on" if enabled else "off"
    state_text = "flag on" if enabled else "flag off"
    is_variant = enabled and str(value) == spec["variant_key"]
    preview_class = f" {spec['variant_key']}" if is_variant else ""
    preview_copy = spec["variant_copy"] if is_variant else spec["control"]
    if not enabled:
        experiment_note = "flag disabled"
    elif flag.get("experiment_name"):
        prefix = "in experiment" if flag.get("in_experiment") else "outside audience"
        experiment_note = f"{prefix}: <b>{_esc(flag['experiment_name'])}</b>"
    else:
        experiment_note = "not reporting (draft or no experiment)"
    return f"""
    <article class="card">
      <div class="card-inner">
        <div class="eyebrow">{_esc(spec["eyebrow"])}</div>
        <h3>{_esc(spec["title"])}</h3>
        <p class="desc">{_esc(spec["description"])}</p>
        <div class="preview{preview_class}">
          <div class="label">rendered variant</div>
          <div class="copy">{_esc(preview_copy)}</div>
        </div>
        <div class="card-foot">
          <div class="value">value <code>{_esc(value)}</code> · variant <code>{_esc(variant)}</code></div>
          <div class="state"><span class="dot {on_class}"></span>{state_text}</div>
        </div>
        <div class="trace">{experiment_note}</div>
      </div>
    </article>
    """


def _load_template() -> string.Template:
    return string.Template((TEMPLATES_DIR / "index.html").read_text(encoding="utf-8"))


def _render_identity_summary(
    evaluation: Optional[Dict[str, Any]],
    identifier: str,
    country: str,
    platform: str,
    focus: Optional[str],
) -> Tuple[str, str, str, str]:
    if not evaluation:
        return "", "", "", '<div class="notice">Start the lab, then reload this page.</div>'
    bucket = evaluation["bucket"]
    flags = evaluation["flags"]
    identity_meta = (
        '<div class="identity-meta">'
        f'<span class="pill lime">bucket <strong>{bucket}</strong></span>'
        f'<span class="pill">country <strong>{_esc(country)}</strong></span>'
        f'<span class="pill">platform <strong>{_esc(platform)}</strong></span>'
        '<span class="pill">traits persisted</span>'
        "</div>"
    )
    trace = (
        '<div class="trace"><b>POST</b> /api/v1/identities/ · '
        f"X-Environment-Key: •••• · identifier={_esc(identifier)}</div>"
    )
    selected = [focus] if focus in FLAGS else list(FLAGS)
    cards = "".join(flag_card(name, flags[name]) for name in selected)
    trace_grid = (
        '<div class="trace-grid">'
        f'<div class="trace-item"><span>identity</span><strong>{_esc(identifier)}</strong></div>'
        f'<div class="trace-item"><span>bucket trait</span><strong>{bucket}</strong></div>'
        f'<div class="trace-item"><span>country / platform</span><strong>{_esc(country)} / {_esc(platform)}</strong></div>'
        '<div class="trace-item"><span>edge endpoint</span><strong>POST /api/v1/identities/</strong></div>'
        "</div>"
    )
    return identity_meta, trace, cards, trace_grid


def render_page(
    evaluation: Optional[Dict[str, Any]],
    identifier: str,
    country: str,
    platform: str,
    focus: Optional[str],
    error: str,
    api_url: str,
) -> str:
    active = focus or "home"
    nav = [("home", "/", "Home"), ("pricing", "/pricing", "Pricing"), ("onboarding", "/onboarding", "Onboarding")]
    nav_html = "".join(
        f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>'
        for key, href, label in nav
    )
    api_params = urllib.parse.urlencode({"identifier": identifier, "country": country, "platform": platform})
    identity_meta, trace, cards, trace_panel_body = _render_identity_summary(
        evaluation, identifier, country, platform, focus
    )
    notice = f'<div class="notice"><strong>Evaluation failed.</strong> {_esc(error)}</div>' if error else ""
    section_title = "Live experiment flags" if not focus else f"{FLAGS[focus]['title']} · live flag"
    return _load_template().substitute(
        section_title=_esc(section_title),
        nav_html=nav_html,
        api_href=_esc(f"/api/evaluate?{api_params}"),
        identifier=_esc(identifier),
        us_selected="selected" if country == "US" else "",
        gb_selected="selected" if country == "GB" else "",
        mobile_selected="selected" if platform == "mobile" else "",
        desktop_selected="selected" if platform == "desktop" else "",
        identity_meta=identity_meta,
        trace=trace,
        notice=notice,
        cards=cards,
        trace_panel_body=trace_panel_body,
        api_url=_esc(api_url),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "IsolationLabStorefront/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, indent=2).encode("utf-8"), "application/json; charset=utf-8")

    def _handle_evaluate(self, api_url: str, env_key: str, identifier: str, country: str, platform: str) -> None:
        try:
            evaluation = evaluate_identity(api_url, env_key, identifier, country, platform)
        except LabError as exc:
            self._json(502, {"ok": False, "error": str(exc), "identifier": identifier})
            return
        payload = {"ok": True, **evaluation}
        for flag in payload["flags"].values():
            flag.pop("reason", None)
        self._json(200, payload)

    def _handle_page(
        self, path: str, api_url: str, env_key: str, identifier: str, country: str, platform: str
    ) -> None:
        focus_map = {"/": None, "/pricing": "pricing_banner", "/onboarding": "onboarding_tip"}
        if path not in focus_map:
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        focus = focus_map[path]
        try:
            evaluation = evaluate_identity(api_url, env_key, identifier, country, platform)
            page = render_page(evaluation, identifier, country, platform, focus, "", api_url)
        except LabError as exc:
            page = render_page(None, identifier, country, platform, focus, str(exc), api_url)
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        api_url = self.server.api_url  # type: ignore[attr-defined]
        env_key = self.server.env_key  # type: ignore[attr-defined]

        if parsed.path == "/static/styles.css":
            css = (STATIC_DIR / "styles.css").read_bytes()
            self._send(200, css, "text/css; charset=utf-8")
            return
        if parsed.path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "experiment-isolation-storefront",
                    "flagsmith_api": api_url,
                    "environment_key_configured": bool(env_key),
                },
            )
            return

        try:
            identifier, country, platform = parse_identity(query)
        except ValueError as exc:
            if parsed.path == "/api/evaluate":
                self._json(400, {"ok": False, "error": str(exc)})
            else:
                page = render_page(None, "demo-us-mobile-001", "US", "mobile", None, str(exc), api_url)
                self._send(400, page.encode("utf-8"), "text/html; charset=utf-8")
            return

        if parsed.path == "/api/evaluate":
            self._handle_evaluate(api_url, env_key, identifier, country, platform)
            return
        self._handle_page(parsed.path, api_url, env_key, identifier, country, platform)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        status = code.value if isinstance(code, HTTPStatus) else code
        print(f'storefront: "{self.requestline}" {status} {size}', flush=True)

    def log_message(self, fmt: str, *args: Any) -> None:
        detail = f"{fmt} {args}" if args else fmt
        print(f"storefront: {detail}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--env-file", type=Path, default=LAB_DIR / ".env")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = load_env(args.env_file)
    api_url = (args.api_url or env.get("LAB_API_URL") or env.get("FLAGSMITH_API_URL") or DEFAULT_API_URL).rstrip("/")
    env_key = env.get("LAB_DEV_ENV_KEY") or env.get("FLAGSMITH_ENVIRONMENT_KEY")
    if not env_key:
        print("storefront: error: no Development environment key in lab/.env; run bash lab/run.sh", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.api_url = api_url  # type: ignore[attr-defined]
    server.env_key = env_key  # type: ignore[attr-defined]
    print(f"Storefront: http://localhost:{args.port}")
    print(f"  Flagsmith: {api_url}")
    print("  Synthetic evaluations via POST /api/v1/identities/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
