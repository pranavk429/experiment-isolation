"""Segment rule evaluation and bucket-range discovery."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .api import AdminAPI


class UnsupportedRule(RuntimeError):
    """A rule (for example PERCENTAGE_SPLIT) cannot be projected locally."""


def fetch_segments(api: AdminAPI, project_id: int) -> List[Dict[str, Any]]:
    """List all project segments."""
    return api.get_all("/api/v1/projects/%s/segments/" % project_id)


def segment_map(segments: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {int(segment["id"]): segment for segment in segments}


def audience_segment_ids(experiment: Dict[str, Any]) -> List[int]:
    """Read audience segment ids from an experiment detail payload."""
    rollout = experiment.get("experiment_rollout") or {}
    audience = rollout.get("audience") or {}
    ids: List[int] = []
    for segment in audience.get("segments") or []:
        if isinstance(segment, dict) and segment.get("id") is not None:
            ids.append(int(segment["id"]))
    for raw in audience.get("segment_ids") or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            pass
    return sorted(set(ids))


def iter_conditions(rule: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield conditions from a rule tree."""
    for condition in rule.get("conditions") or []:
        if isinstance(condition, dict):
            yield condition
    for child in rule.get("rules") or []:
        if isinstance(child, dict):
            for condition in iter_conditions(child):
                yield condition


def segment_has_percentage_split(segment: Dict[str, Any]) -> bool:
    """An experiment audience may never contain PERCENTAGE_SPLIT."""
    for rule in segment.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for condition in iter_conditions(rule):
            if condition.get("operator") == "PERCENTAGE_SPLIT":
                return True
    return False


def audience_has_percentage_split(
    segment_ids: Sequence[int], segments: Dict[int, Dict[str, Any]]
) -> bool:
    for segment_id in segment_ids:
        segment = segments.get(int(segment_id))
        if segment and segment_has_percentage_split(segment):
            return True
    return False


def _as_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _condition_matches(condition: Dict[str, Any], traits: Dict[str, object]) -> bool:
    operator = str(condition.get("operator") or "").upper()
    prop = str(condition.get("property") or "")
    expected = condition.get("value")
    if operator == "PERCENTAGE_SPLIT":
        raise UnsupportedRule("audience contains PERCENTAGE_SPLIT")
    if prop.startswith("$."):
        # Identity key and other reserved properties are not traits.
        if operator == "NOT_EQUAL":
            return True
        if operator == "EQUAL":
            return False
        raise UnsupportedRule("unsupported identity property %s" % prop)
    actual = traits.get(prop)
    if operator == "EQUAL":
        return str(actual) == str(expected)
    if operator == "NOT_EQUAL":
        return str(actual) != str(expected)
    if operator in ("IN", "NOT_IN"):
        if isinstance(expected, (list, tuple)):
            options = [str(item) for item in expected]
        else:
            options = [item.strip() for item in str(expected).split(",") if item.strip()]
        present = str(actual) in options
        return present if operator == "IN" else not present
    if operator in ("CONTAINS", "NOT_CONTAINS"):
        present = actual is not None and str(expected) in str(actual)
        return present if operator == "CONTAINS" else not present
    if actual is None:
        return False
    left = _as_number(actual)
    right = _as_number(expected)
    if left is not None and right is not None:
        if operator == "GREATER_THAN":
            return left > right
        if operator == "GREATER_THAN_INCLUSIVE":
            return left >= right
        if operator == "LESS_THAN":
            return left < right
        if operator == "LESS_THAN_INCLUSIVE":
            return left <= right
    else:
        left_s, right_s = str(actual), str(expected)
        if operator == "GREATER_THAN":
            return left_s > right_s
        if operator == "GREATER_THAN_INCLUSIVE":
            return left_s >= right_s
        if operator == "LESS_THAN":
            return left_s < right_s
        if operator == "LESS_THAN_INCLUSIVE":
            return left_s <= right_s
    raise UnsupportedRule("unsupported operator %s" % operator)


def rule_matches(rule: Dict[str, Any], traits: Dict[str, object]) -> bool:
    """Evaluate an ALL/ANY rule tree against trait values."""
    kind = str(rule.get("type") or "ALL").upper()
    checks: List[bool] = [
        _condition_matches(condition, traits) for condition in rule.get("conditions") or []
    ]
    checks.extend(
        rule_matches(child, traits)
        for child in rule.get("rules") or []
        if isinstance(child, dict)
    )
    if not checks:
        return True
    return all(checks) if kind == "ALL" else any(checks)


def segment_matches(segment: Dict[str, Any], traits: Dict[str, object]) -> bool:
    """Evaluate a segment. Top-level rules are combined with AND."""
    rules = [rule for rule in segment.get("rules") or [] if isinstance(rule, dict)]
    return all(rule_matches(rule, traits) for rule in rules)


def segment_is_bucket_range(
    segment: Dict[str, Any], trait: str, operator: str, value: str
) -> bool:
    """True when a segment is exactly one bucket range and nothing else."""
    rules = segment.get("rules") or []
    if len(rules) != 1 or not isinstance(rules[0], dict):
        return False
    if rules[0].get("rules"):
        return False
    conditions = [item for item in rules[0].get("conditions") or [] if isinstance(item, dict)]
    if len(conditions) != 1:
        return False
    condition = conditions[0]
    return (
        condition.get("property") == trait
        and str(condition.get("operator")).upper() == operator
        and str(condition.get("value")) == value
        and not segment_has_percentage_split(segment)
    )


def segment_is_range(
    segment: Dict[str, Any], trait: str, lo: int, hi: int
) -> bool:
    """True when a segment matches exactly the inclusive bucket range [lo, hi].

    Semantic check: probe all 100 bucket values. This accepts the legacy
    single-bound segments (LESS_THAN 50 and GREATER_THAN_INCLUSIVE 50) as
    equivalent to [0, 49] and [50, 99].
    """
    if not (0 <= lo <= hi <= 99):
        return False
    if segment_has_percentage_split(segment):
        return False
    for bucket in range(100):
        try:
            matched = segment_matches(segment, {trait: bucket})
        except UnsupportedRule:
            return False
        if matched != (lo <= bucket <= hi):
            return False
    return True


def find_bucket_segment(
    segments: Sequence[Dict[str, Any]], trait: str, operator: str, value: str
) -> Optional[Dict[str, Any]]:
    """Find an existing exact single-bound bucket segment, preferring the oldest."""
    matches = [
        segment
        for segment in segments
        if segment_is_bucket_range(segment, trait, operator, value)
    ]
    matches.sort(key=lambda item: int(item.get("id") or 0))
    return matches[0] if matches else None


def find_range_segment(
    segments: Sequence[Dict[str, Any]], trait: str, lo: int, hi: int
) -> Optional[Dict[str, Any]]:
    """Find an existing segment whose audience is exactly [lo, hi]."""
    matches = [
        segment
        for segment in segments
        if segment_is_range(segment, trait, lo, hi)
    ]
    matches.sort(key=lambda item: int(item.get("id") or 0))
    return matches[0] if matches else None
