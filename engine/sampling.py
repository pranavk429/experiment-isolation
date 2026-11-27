"""Deterministic synthetic sample construction and persistence.

Identities are stable across runs: index i always gets the same identifier,
traits and bucket. Traits are persisted through the Flagsmith CLI so that
Flagsmith itself performs experiment enrollment; we only read it back.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .api import AdminAPI, EdgeAPI
from .config import Config
from .util import EngineError

SAMPLE_TRAITS = ["country", "platform", "flagsmith_experiment_bucket"]
TRAIT_MATRIX = (
    ("US", "mobile"),  # 50%
    ("US", "mobile"),
    ("US", "mobile"),
    ("US", "mobile"),
    ("US", "mobile"),
    ("GB", "mobile"),  # 30%
    ("GB", "mobile"),
    ("GB", "mobile"),
    ("US", "desktop"),  # 20%
    ("US", "desktop"),
)


@dataclass(frozen=True)
class SampleIdentity:
    """One synthetic identity with its stable traits."""

    identifier: str
    traits: Dict[str, object]

    @property
    def bucket(self) -> int:
        return int(self.traits["flagsmith_experiment_bucket"])


def bucket_for(identifier: str) -> int:
    """Stable 0-99 bucket from the first eight sha256 hex characters."""
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return int(digest[0:8], 16) % 100


def build_sample(size: int, prefix: str = "iso") -> List[SampleIdentity]:
    """Build a deterministic 50/30/20 US-mobile / GB-mobile / US-desktop sample."""
    if size < 2:
        raise EngineError("--samples must be at least 2")
    if size > 5000:
        raise EngineError("--samples is capped at 5000")
    identities: List[SampleIdentity] = []
    for index in range(1, size + 1):
        identifier = "%s_%04d" % (prefix, index)
        country, platform = TRAIT_MATRIX[(index - 1) % len(TRAIT_MATRIX)]
        identities.append(
            SampleIdentity(
                identifier=identifier,
                traits={
                    "country": country,
                    "platform": platform,
                    "flagsmith_experiment_bucket": bucket_for(identifier),
                },
            )
        )
    return identities


def jaccard(a: Set[int], b: Set[int]) -> Tuple[int, int, float]:
    """Return shared count, union count and Jaccard similarity."""
    shared = len(a & b)
    union = len(a | b)
    return shared, union, (float(shared) / union if union else 0.0)


def _trait_map(identity_payload: Dict[str, object]) -> Dict[str, object]:
    traits: Dict[str, object] = {}
    for trait in identity_payload.get("traits") or []:
        if isinstance(trait, dict):
            traits[str(trait.get("trait_key"))] = trait.get("trait_value")
    return traits


def traits_match(identity_payload: Optional[Dict[str, object]], expected: Dict[str, object]) -> bool:
    """True when every expected trait is already persisted with the same value."""
    if not identity_payload:
        return False
    current = _trait_map(identity_payload)
    for key, value in expected.items():
        if str(current.get(key)) != str(value):
            return False
    return True


def find_flagsmith() -> str:
    """Locate the Flagsmith v2 CLI without invoking a shell."""
    configured = os.environ.get("FLAGSMITH_BIN")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("flagsmith")
    if found:
        return found
    candidate = Path.home() / ".cache" / "fstools" / "node_modules" / ".bin" / "flagsmith"
    if candidate.is_file():
        return str(candidate)
    raise EngineError(
        "Flagsmith CLI not found. Add ~/.cache/fstools/node_modules/.bin to PATH "
        "or set FLAGSMITH_BIN."
    )


def _sanitize(text: str, config: Config) -> str:
    clean = text.replace(config.admin_key, "<redacted>").replace(config.env_key, "<redacted>")
    return " ".join(clean.split())[:300]


def _persist_one(config: Config, binary: str, sample: SampleIdentity, edge: EdgeAPI) -> Dict[str, object]:
    existing = edge.identity(sample.identifier)
    if traits_match(existing, sample.traits):
        return existing  # type: ignore[return-value]
    command = [
        binary,
        "evaluate",
        "--identity",
        sample.identifier,
        "--persist",
        "--json",
    ]
    for key in SAMPLE_TRAITS:
        command.extend(["--trait", "%s=%s" % (key, sample.traits[key])])
    try:
        completed = subprocess.run(
            command,
            env=config.cli_env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EngineError("flagsmith evaluate failed for %s: %s" % (sample.identifier, exc)) from exc
    if completed.returncode != 0:
        raise EngineError(
            "flagsmith evaluate failed for %s: %s"
            % (sample.identifier, _sanitize(completed.stderr or completed.stdout, config))
        )
    payload = edge.identity(sample.identifier)
    if not payload:
        raise EngineError("Identity %s was not persisted" % sample.identifier)
    if not traits_match(payload, sample.traits):
        raise EngineError("Identity %s has unexpected traits after persistence" % sample.identifier)
    return payload


def persist_sample(
    config: Config,
    samples: Sequence[SampleIdentity],
    workers: int = 8,
) -> Dict[str, Dict[str, object]]:
    """Persist traits for each identity in parallel and return Edge payloads."""
    binary = find_flagsmith()
    edge = EdgeAPI(config)
    payloads: Dict[str, Dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as pool:
        futures = {
            sample.identifier: pool.submit(_persist_one, config, binary, sample, edge)
            for sample in samples
        }
        for sample in samples:
            payloads[sample.identifier] = futures[sample.identifier].result()
    return payloads


def enrollment_by_experiment(
    payloads: Dict[str, Dict[str, object]],
) -> Dict[int, Set[int]]:
    """Map experiment id to the identities Flagsmith reports as in_experiment."""
    enrolled: Dict[int, Set[int]] = {}
    for identifier, payload in payloads.items():
        for flag in payload.get("flags") or []:
            if not isinstance(flag, dict):
                continue
            metadata = flag.get("metadata")
            if metadata is None:
                continue
            if not isinstance(metadata, dict):
                raise EngineError(
                    "Malformed experiment metadata on identity %s: metadata is not an object"
                    % identifier
                )
            experiment = metadata.get("experiment")
            if experiment is None:
                continue
            if not isinstance(experiment, dict):
                raise EngineError(
                    "Malformed experiment metadata on identity %s: experiment is not an object"
                    % identifier
                )
            if experiment.get("in_experiment") is True:
                raw_id = experiment.get("id")
                try:
                    experiment_id = int(raw_id)
                except (TypeError, ValueError) as exc:
                    raise EngineError(
                        "Malformed experiment metadata on identity %s: missing "
                        "or non-integer experiment id" % identifier
                    ) from exc
                enrolled.setdefault(experiment_id, set()).add(identifier)
    return enrolled


def cleanup_identities(
    config: Config,
    identifiers: Iterable[str],
) -> Dict[str, int]:
    """Best-effort deletion of synthetic identities by exact identifier."""
    wanted = set(identifiers)
    if not wanted:
        return {"deleted": 0, "failed": 0}
    api = AdminAPI(config)
    found: Dict[str, int] = {}
    for item in api.get_all("/api/v1/environments/%s/identities/" % config.env_key, limit=2000):
        identifier = str(item.get("identifier"))
        if identifier in wanted and item.get("id") is not None:
            found[identifier] = int(item["id"])
    deleted = 0
    failed = 0
    for identifier, identity_id in found.items():
        try:
            api.delete(
                "/api/v1/environments/%s/identities/%s/" % (config.env_key, identity_id)
            )
            deleted += 1
        except Exception:
            failed += 1
    return {"deleted": deleted, "failed": failed}
