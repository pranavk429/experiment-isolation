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
import hashlib
import html
import json
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lablib import DEFAULT_API_URL, LAB_DIR, LabError, load_env, request_json

IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
COUNTRIES = ("US", "GB")
PLATFORMS = ("mobile", "desktop")

FLAGS = {
    "pricing_banner": {
        "title": "Pricing banner",
        "eyebrow": "EXPERIMENT 01 · PRICING",
        "description": "Does urgency copy move US mobile checkout?",
        "control": "Simple pricing that scales with your team.",
        "variant": "Only 3 seats left — save 20% today.",
    },
    "onboarding_tip": {
        "title": "Onboarding tip",
        "eyebrow": "EXPERIMENT 02 · ACTIVATION",
        "description": "Does a shorter first-session tip improve activation?",
        "control": "Welcome! Take the full guided tour to set up your workspace.",
        "variant": "Start with a 3-step tour. You can finish setup later.",
    },
}

CSS = """
:root {
  color-scheme: dark;
  --ink: #070b10;
  --panel: #0f161e;
  --panel-2: #131d27;
  --line: #22303d;
  --line-soft: rgba(255,255,255,.08);
  --text: #e9f0f5;
  --muted: #8fa1b1;
  --lime: #c9ff4d;
  --lime-dim: rgba(201,255,77,.13);
  --coral: #ff6b5e;
  --teal: #63e6d5;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body {
  background:
    radial-gradient(900px 420px at 12% -8%, rgba(201,255,77,.10), transparent 60%),
    radial-gradient(700px 380px at 94% 4%, rgba(99,230,213,.08), transparent 62%),
    var(--ink);
  color: var(--text); font-family: var(--sans); line-height: 1.5;
}
a { color: inherit; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 0 24px; }
header {
  position: sticky; top: 0; z-index: 10;
  background: rgba(7,11,16,.82); backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--line-soft);
}
.nav { display: flex; align-items: center; justify-content: space-between; height: 66px; gap: 18px; }
.brand { display: flex; align-items: center; gap: 11px; font-family: var(--mono); font-size: 12px; letter-spacing: .13em; text-transform: uppercase; }
.mark { width: 28px; height: 28px; border: 1px solid var(--lime); border-radius: 8px; display: grid; place-items: center; color: var(--lime); font-weight: 700; }
.nav-links { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.nav-links a {
  text-decoration: none; color: var(--muted); font-family: var(--mono); font-size: 11px;
  letter-spacing: .08em; text-transform: uppercase; padding: 8px 10px; border-radius: 7px;
}
.nav-links a:hover, .nav-links a.active { color: var(--text); background: rgba(255,255,255,.05); }
main { padding: 46px 0 64px; }
.hero { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); gap: 36px; align-items: end; padding-bottom: 34px; border-bottom: 1px solid var(--line-soft); }
.kicker { font-family: var(--mono); font-size: 11px; letter-spacing: .18em; text-transform: uppercase; color: var(--lime); margin-bottom: 14px; }
h1 { font-size: clamp(34px, 5vw, 62px); line-height: .98; letter-spacing: -.035em; margin: 0 0 18px; font-weight: 650; }
h1 span { color: var(--lime); }
.lede { color: var(--muted); max-width: 58ch; margin: 0; font-size: 16px; }
.identity {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 18px;
  box-shadow: 0 24px 60px rgba(0,0,0,.24);
}
.identity h2 { margin: 0 0 4px; font-size: 13px; font-family: var(--mono); letter-spacing: .12em; text-transform: uppercase; }
.identity p { margin: 0 0 14px; color: var(--muted); font-size: 12px; }
label { display: block; font-family: var(--mono); font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-bottom: 5px; }
input, select {
  width: 100%; background: #0a1118; color: var(--text); border: 1px solid var(--line);
  border-radius: 8px; padding: 10px 11px; font: 13px var(--mono); outline: none;
}
input:focus, select:focus { border-color: var(--lime); box-shadow: 0 0 0 3px var(--lime-dim); }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.field { margin-bottom: 11px; }
button, .button {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  background: var(--lime); color: #0a1004; border: 0; border-radius: 8px;
  padding: 10px 13px; font: 700 12px var(--mono); letter-spacing: .04em; cursor: pointer;
  text-decoration: none; width: 100%;
}
button:hover, .button:hover { filter: brightness(1.06); }
.trace { margin-top: 12px; font: 10px/1.5 var(--mono); color: var(--muted); word-break: break-all; }
.trace b { color: var(--teal); font-weight: 500; }
.identity-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.pill {
  display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line);
  border-radius: 999px; padding: 4px 8px; font: 10px var(--mono); color: var(--muted);
  letter-spacing: .04em; text-transform: uppercase;
}
.pill strong { color: var(--text); font-weight: 600; }
.pill.lime { border-color: rgba(201,255,77,.4); color: var(--lime); background: var(--lime-dim); }
.section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin: 34px 0 14px; }
.section-head h2 { margin: 0; font-size: 17px; letter-spacing: -.01em; }
.section-head p { margin: 0; color: var(--muted); font: 11px var(--mono); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.card {
  position: relative; overflow: hidden; background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--line); border-radius: 14px;
}
.card::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 2px; background: linear-gradient(90deg, var(--lime), var(--teal), transparent); opacity: .75; }
.card-inner { padding: 20px; }
.eyebrow { font: 10px var(--mono); letter-spacing: .15em; color: var(--teal); text-transform: uppercase; }
.card h3 { margin: 7px 0 3px; font-size: 22px; letter-spacing: -.02em; }
.card .desc { margin: 0 0 16px; color: var(--muted); font-size: 13px; }
.preview { border: 1px solid var(--line); border-radius: 10px; background: #0a1118; padding: 15px; min-height: 104px; display: flex; flex-direction: column; justify-content: center; }
.preview .label { font: 9px var(--mono); letter-spacing: .14em; text-transform: uppercase; color: var(--muted); margin-bottom: 7px; }
.preview .copy { font-size: 16px; line-height: 1.35; }
.preview.urgent { border-color: rgba(255,107,94,.38); background: linear-gradient(135deg, rgba(255,107,94,.10), #0a1118 60%); }
.preview.short { border-color: rgba(201,255,77,.32); background: linear-gradient(135deg, rgba(201,255,77,.08), #0a1118 60%); }
.card-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; }
.value { font: 11px var(--mono); color: var(--muted); }
.value code { color: var(--text); background: rgba(255,255,255,.06); border: 1px solid var(--line-soft); padding: 2px 5px; border-radius: 4px; }
.state { display: inline-flex; align-items: center; gap: 6px; font: 10px var(--mono); text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.dot.on { background: var(--lime); box-shadow: 0 0 10px rgba(201,255,77,.65); }
.dot.off { background: #536575; }
.notice { border: 1px solid rgba(255,107,94,.45); background: rgba(255,107,94,.09); color: #ffc7c1; border-radius: 10px; padding: 13px 15px; margin: 20px 0 0; font-size: 13px; }
.notice code { font-family: var(--mono); color: #fff; }
.trace-panel { margin-top: 24px; border: 1px solid var(--line); border-radius: 12px; background: rgba(15,22,30,.72); padding: 15px 17px; }
.trace-panel h3 { margin: 0 0 9px; font: 11px var(--mono); letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.trace-grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; }
.trace-item { border-left: 1px solid var(--line); padding-left: 10px; }
.trace-item span { display: block; font: 9px var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.trace-item strong { display: block; font: 12px var(--mono); color: var(--text); margin-top: 3px; overflow-wrap: anywhere; }
footer { border-top: 1px solid var(--line-soft); padding: 20px 0 34px; color: var(--muted); font: 11px/1.6 var(--mono); }
footer .wrap { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; }
@media (max-width: 820px) {
  .hero { grid-template-columns: 1fr; align-items: start; }
  .grid { grid-template-columns: 1fr; }
  .trace-grid { grid-template-columns: 1fr 1fr; }
  main { padding-top: 30px; }
}
"""


def stable_bucket(identifier: str) -> int:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return int(digest[0:8], 16) % 100


def evaluate_identity(api_url: str, env_key: str, identifier: str, country: str, platform: str) -> Dict[str, Any]:
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
    raw_flags = {}
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
    flags = {}
    for name in FLAGS:
        flags[name] = raw_flags.get(
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
    return {
        "identifier": identifier,
        "bucket": bucket,
        "country": country,
        "platform": platform,
        "traits": {trait["trait_key"]: trait["trait_value"] for trait in traits},
        "flags": flags,
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
    preview_class = ""
    if enabled and str(value) == spec["variant"]:
        preview_class = "urgent" if name == "pricing_banner" else "short"
    preview_copy = spec["variant"] if enabled and str(value) == spec["variant"] else spec["control"]
    if flag.get("experiment_name"):
        if flag.get("in_experiment"):
            experiment_note = "in experiment: <b>%s</b>" % _esc(flag["experiment_name"])
        else:
            experiment_note = "outside audience: <b>%s</b>" % _esc(flag["experiment_name"])
    else:
        experiment_note = "not reporting (draft or no experiment)"
    if not enabled:
        experiment_note = "flag disabled"
    return f"""
    <article class="card">
      <div class="card-inner">
        <div class="eyebrow">{_esc(spec["eyebrow"])}</div>
        <h3>{_esc(spec["title"])}</h3>
        <p class="desc">{_esc(spec["description"])}</p>
        <div class="preview {preview_class}">
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
    nav = [
        ("home", "/", "Home"),
        ("pricing", "/pricing", "Pricing"),
        ("onboarding", "/onboarding", "Onboarding"),
    ]
    nav_html = "".join(
        '<a class="%s" href="%s">%s</a>' % ("active" if key == active else "", href, label)
        for key, href, label in nav
    )
    api_href = "/api/evaluate?%s" % urllib.parse.urlencode(
        {"identifier": identifier, "country": country, "platform": platform}
    )
    if evaluation:
        bucket = evaluation["bucket"]
        flags = evaluation["flags"]
        identity_meta = (
            '<div class="identity-meta">'
            '<span class="pill lime">bucket <strong>%s</strong></span>'
            '<span class="pill">country <strong>%s</strong></span>'
            '<span class="pill">platform <strong>%s</strong></span>'
            '<span class="pill">traits persisted</span>'
            "</div>" % (bucket, _esc(country), _esc(platform))
        )
        trace = (
            '<div class="trace"><b>POST</b> /api/v1/identities/ · '
            "X-Environment-Key: •••• · identifier=%s</div>" % _esc(identifier)
        )
        selected = [focus] if focus in FLAGS else list(FLAGS)
        cards = "".join(flag_card(name, flags[name]) for name in selected)
        trace_grid = (
            '<div class="trace-grid">'
            '<div class="trace-item"><span>identity</span><strong>%s</strong></div>'
            '<div class="trace-item"><span>bucket trait</span><strong>%s</strong></div>'
            '<div class="trace-item"><span>country / platform</span><strong>%s / %s</strong></div>'
            '<div class="trace-item"><span>edge endpoint</span><strong>POST /api/v1/identities/</strong></div>'
            "</div>" % (_esc(identifier), bucket, _esc(country), _esc(platform))
        )
    else:
        identity_meta = ""
        trace = ""
        cards = ""
        trace_grid = ""

    notice = '<div class="notice"><strong>Evaluation failed.</strong> %s</div>' % _esc(error) if error else ""
    section_title = "Live experiment flags" if not focus else "%s · live flag" % FLAGS[focus]["title"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(section_title)} · Experiment Isolation Lab</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' fill='%23070b10'/><path d='M25 70 50 24l25 46' stroke='%23c9ff4d' stroke-width='9' fill='none'/></svg>">
  <style>{CSS}</style>
</head>
<body>
<header>
  <div class="wrap nav">
    <div class="brand"><span class="mark">I</span> Isolation Lab</div>
    <nav class="nav-links">{nav_html}<a href="{_esc(api_href)}">API JSON</a></nav>
  </div>
</header>
<main class="wrap">
  <section class="hero">
    <div>
      <div class="kicker">Flagsmith · local storefront</div>
      <h1>Two experiments.<br><span>One audience.</span></h1>
      <p class="lede">This storefront evaluates two live flags for a synthetic visitor. Both experiment drafts target <code>us_mobile</code>, so they compete for the same people. The stable <code>flagsmith_experiment_bucket</code> trait is what makes a disjoint fix possible.</p>
    </div>
    <form class="identity" method="get" action="/">
      <h2>Evaluate an identity</h2>
      <p>Traits are persisted in your local Flagsmith instance.</p>
      <div class="field">
        <label for="identifier">Identifier</label>
        <input id="identifier" name="identifier" value="{_esc(identifier)}" autocomplete="off" spellcheck="false">
      </div>
      <div class="row">
        <div class="field">
          <label for="country">Country</label>
          <select id="country" name="country">
            <option value="US" {"selected" if country == "US" else ""}>US</option>
            <option value="GB" {"selected" if country == "GB" else ""}>GB</option>
          </select>
        </div>
        <div class="field">
          <label for="platform">Platform</label>
          <select id="platform" name="platform">
            <option value="mobile" {"selected" if platform == "mobile" else ""}>mobile</option>
            <option value="desktop" {"selected" if platform == "desktop" else ""}>desktop</option>
          </select>
        </div>
      </div>
      <button type="submit">Evaluate flags →</button>
      {identity_meta}
      {trace}
    </form>
  </section>
  {notice}
  <div class="section-head">
    <h2>{_esc(section_title)}</h2>
    <p>SDK/edge evaluation · synthetic traffic</p>
  </div>
  <section class="grid">{cards}</section>
  <section class="trace-panel">
    <h3>Request trace</h3>
    {trace_grid if trace_grid else '<div class="notice">Start the lab, then reload this page.</div>'}
  </section>
</main>
<footer>
  <div class="wrap">
    <span>Local only · synthetic identities · no production data</span>
    <span>Flagsmith {_esc(api_url)} · <a href="/api/health">health</a></span>
  </div>
</footer>
</body>
</html>
"""


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

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        api_url = self.server.api_url  # type: ignore[attr-defined]
        env_key = self.server.env_key  # type: ignore[attr-defined]

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
                self._send(
                    400,
                    render_page(None, "demo-us-mobile-001", "US", "mobile", None, str(exc), api_url).encode("utf-8"),
                    "text/html; charset=utf-8",
                )
            return

        if parsed.path == "/api/evaluate":
            try:
                evaluation = evaluate_identity(api_url, env_key, identifier, country, platform)
                payload = {"ok": True, **evaluation}
                for flag in payload["flags"].values():
                    flag.pop("reason", None)
                self._json(200, payload)
            except LabError as exc:
                self._json(502, {"ok": False, "error": str(exc), "identifier": identifier})
            return

        focus = None
        if parsed.path == "/pricing":
            focus = "pricing_banner"
        elif parsed.path == "/onboarding":
            focus = "onboarding_tip"
        elif parsed.path != "/":
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return

        try:
            evaluation = evaluate_identity(api_url, env_key, identifier, country, platform)
            page = render_page(evaluation, identifier, country, platform, focus, "", api_url)
        except LabError as exc:
            page = render_page(None, identifier, country, platform, focus, str(exc), api_url)
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None:
        print("storefront: " + (fmt % args), flush=True)


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
    print("Storefront: http://localhost:%d" % args.port)
    print("  Flagsmith: %s" % api_url)
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
