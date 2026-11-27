"""Compact receipt combining audit, plan, verify, and optional apply results."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .util import estimate_tokens


def _max_jaccard(audit: Dict[str, Any]) -> float:
    values = [float(item.get("jaccard") or 0.0) for item in audit.get("overlaps") or []]
    return max(values) if values else 0.0


def _remaining_collisions(audit: Dict[str, Any], changes: List[Dict[str, Any]]) -> int:
    planned_ids = {int(change["experiment_id"]) for change in changes}
    collisions = audit.get("collisions") or []
    planned_collisions = sum(
        1
        for pair in collisions
        if int(pair[0]) in planned_ids and int(pair[1]) in planned_ids
    )
    return max(0, len(collisions) - planned_collisions)


def build_receipt(
    audit: Dict[str, Any],
    plan: Dict[str, Any],
    verify: Dict[str, Any],
    apply_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble a small, human-reviewable receipt."""
    changes = list(plan.get("audience_changes") or [])
    rollback = [f"restore {','.join(str(c['experiment_id']) for c in changes)}"] if changes else []
    pass_result = bool(verify.get("pass"))
    receipt: Dict[str, Any] = {
        "product": "experiment-isolation",
        "environment": (audit.get("environment") or {}).get("name"),
        "scope": "planned_experiments",
        "sample_size": verify.get("sample_size") or audit.get("sample_size"),
        "before": {
            "verdict": audit.get("verdict"),
            "max_jaccard": round(_max_jaccard(audit), 4),
            "multi_exposed_rate": round(float(audit.get("multi_exposed_rate") or 0.0), 4),
        },
        "after": {
            "verdict": "isolated" if pass_result else "collision",
            "max_jaccard": round(float(verify.get("after_jaccard") or 0.0), 4),
            "multi_exposed_rate": round(
                float(verify.get("after_multi_exposed_rate") or 0.0), 4
            ),
        },
        "changes": len(changes) * 2,
        "token_count": {
            "audit": estimate_tokens(audit),
            "plan": estimate_tokens(plan),
            "apply": estimate_tokens(apply_result) if apply_result else 0,
            "verify": estimate_tokens(verify),
            "receipt": 0,
        },
        "remaining_environment_collisions": _remaining_collisions(audit, changes),
        "rollback": rollback,
        "pass": pass_result,
    }
    receipt["token_count"]["receipt"] = estimate_tokens(receipt)
    return receipt
