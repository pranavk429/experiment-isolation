"""Segment rule evaluation, composition, and semantic range discovery."""

from __future__ import annotations

import operator as op
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .api import AdminAPI


class UnsupportedRule(RuntimeError):
    """A rule (for example PERCENTAGE_SPLIT) cannot be projected locally."""


_ORDER_OPS: Dict[str, Callable[[Any, Any], bool]] = {
    "GREATER_THAN": op.gt,
    "GREATER_THAN_INCLUSIVE": op.ge,
    "LESS_THAN": op.lt,
    "LESS_THAN_INCLUSIVE": op.le,
}


def fetch_segments(api: AdminAPI, project_id: int) -> List[Dict[str, Any]]:
    """List all project segments."""
    return api.get_all(f"/api/v1/projects/{project_id}/segments/")


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
            yield from iter_conditions(child)


def segment_has_percentage_split(segment: Dict[str, Any]) -> bool:
    """An experiment audience may never contain PERCENTAGE_SPLIT."""
    for rule in segment.get("rules") or []:
        if isinstance(rule, dict):
            if any(c.get("operator") == "PERCENTAGE_SPLIT" for c in iter_conditions(rule)):
                return True
    return False


def audience_has_percentage_split(
    segment_ids: Sequence[int], segments: Dict[int, Dict[str, Any]]
) -> bool:
    return any(
        (seg := segments.get(int(segment_id))) and segment_has_percentage_split(seg)
        for segment_id in segment_ids
    )


def _as_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_options(expected: Any) -> List[str]:
    if isinstance(expected, (list, tuple)):
        return [str(item) for item in expected]
    return [item.strip() for item in str(expected).split(",") if item.strip()]


def _condition_matches(condition: Dict[str, Any], traits: Dict[str, object]) -> bool:
    kind = str(condition.get("operator") or "").upper()
    prop = str(condition.get("property") or "")
    expected = condition.get("value")
    if kind == "PERCENTAGE_SPLIT":
        raise UnsupportedRule("audience contains PERCENTAGE_SPLIT")
    if prop.startswith("$."):
        if kind in ("NOT_EQUAL", "EQUAL"):
            return kind == "NOT_EQUAL"
        raise UnsupportedRule(f"unsupported identity property {prop}")
    actual = traits.get(prop)
    if kind in ("EQUAL", "NOT_EQUAL"):
        return (str(actual) == str(expected)) if kind == "EQUAL" else (str(actual) != str(expected))
    if kind in ("IN", "NOT_IN"):
        present = str(actual) in _parse_options(expected)
        return present if kind == "IN" else not present
    if kind in ("CONTAINS", "NOT_CONTAINS"):
        present = actual is not None and str(expected) in str(actual)
        return present if kind == "CONTAINS" else not present
    if actual is None:
        return False
    cmp_fn = _ORDER_OPS.get(kind)
    if cmp_fn is None:
        raise UnsupportedRule(f"unsupported operator {kind}")
    left, right = _as_number(actual), _as_number(expected)
    if left is not None and right is not None:
        return cmp_fn(left, right)
    return cmp_fn(str(actual), str(expected))


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


def sanitize_rule_tree(rule: Dict[str, Any], exclude_trait: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Normalize a rule tree, optionally stripping conditions on *exclude_trait*."""
    conditions = []
    for cond in rule.get("conditions") or []:
        if not isinstance(cond, dict):
            continue
        prop = str(cond.get("property") or cond.get("trait") or "")
        if exclude_trait and prop == exclude_trait:
            continue
        conditions.append(
            {
                "operator": str(cond.get("operator") or "").upper(),
                "property": prop,
                "value": str(cond.get("value") if cond.get("value") is not None else ""),
            }
        )
    children = [
        cleaned
        for child in rule.get("rules") or []
        if isinstance(child, dict)
        and (cleaned := sanitize_rule_tree(child, exclude_trait=exclude_trait)) is not None
    ]
    if not conditions and not children:
        return None
    return {
        "type": str(rule.get("type") or "ALL").upper(),
        "rules": children,
        "conditions": conditions,
    }


def strip_bucket_conditions(rules: Sequence[Dict[str, Any]], trait: str) -> List[Dict[str, Any]]:
    """Return normalized non-bucket targeting rules from *rules*."""
    cleaned: List[Dict[str, Any]] = []
    for rule in rules:
        if isinstance(rule, dict):
            sanitized = sanitize_rule_tree(rule, exclude_trait=trait)
            if sanitized is not None:
                cleaned.append(sanitized)
    return cleaned


def extract_base_rules(segment: Dict[str, Any], trait: str) -> List[Dict[str, Any]]:
    """Extract normalized non-bucket rules from a Flagsmith segment."""
    return strip_bucket_conditions(segment.get("rules") or [], trait)


def bucket_range_conditions(trait: str, lo: int, hi: int) -> List[Dict[str, str]]:
    """Flagsmith conditions for inclusive bucket range [lo, hi]."""
    conditions: List[Dict[str, str]] = []
    if lo > 0:
        conditions.append(
            {"operator": "GREATER_THAN_INCLUSIVE", "property": trait, "value": str(lo)}
        )
    conditions.append({"operator": "LESS_THAN", "property": trait, "value": str(hi + 1)})
    return conditions


def compose_segment_rules(
    base_rules: Sequence[Dict[str, Any]], trait: str, lo: int, hi: int
) -> List[Dict[str, Any]]:
    """Compose optional *base_rules* with bucket range [lo, hi] under top-level ALL."""
    range_conds = bucket_range_conditions(trait, lo, hi)
    cleaned = strip_bucket_conditions(base_rules, trait)
    if not cleaned:
        return [{"type": "ALL", "rules": [], "conditions": range_conds}]
    if len(cleaned) == 1 and cleaned[0]["type"] == "ALL" and not cleaned[0]["rules"]:
        return [
            {
                "type": "ALL",
                "rules": [],
                "conditions": list(cleaned[0]["conditions"]) + range_conds,
            }
        ]
    return [{"type": "ALL", "rules": cleaned, "conditions": range_conds}]


def _canonical_rule_signature(rules: Sequence[Dict[str, Any]]) -> Any:
    def norm_rule(rule: Dict[str, Any]) -> Tuple[str, Tuple[Any, ...], Tuple[Any, ...]]:
        conds = sorted(
            (
                str(c.get("operator") or "").upper(),
                str(c.get("property") or ""),
                str(c.get("value") or ""),
            )
            for c in rule.get("conditions") or []
            if isinstance(c, dict)
        )
        children = sorted(
            (norm_rule(child) for child in rule.get("rules") or [] if isinstance(child, dict)),
            key=str,
        )
        return (str(rule.get("type") or "ALL").upper(), tuple(children), tuple(conds))

    return tuple(sorted((norm_rule(r) for r in rules if isinstance(r, dict)), key=str))


def _synthesize_matching_traits(rules: Sequence[Dict[str, Any]]) -> Dict[str, object]:
    traits: Dict[str, object] = {}

    def apply_cond(cond: Dict[str, Any]) -> None:
        prop = str(cond.get("property") or "")
        if not prop or prop.startswith("$."):
            return
        kind = str(cond.get("operator") or "").upper()
        val = cond.get("value")
        if kind == "EQUAL":
            traits[prop] = str(val)
        elif kind == "NOT_EQUAL":
            traits[prop] = f"__not_{val}"
        elif kind == "IN":
            opts = _parse_options(val)
            traits[prop] = opts[0] if opts else ""
        elif kind == "NOT_IN":
            traits[prop] = "__absent__"
        elif kind == "CONTAINS":
            traits[prop] = str(val)
        elif kind == "NOT_CONTAINS":
            traits[prop] = "__absent__"
        elif kind in _ORDER_OPS:
            num = _as_number(val)
            if num is None:
                traits[prop] = str(val)
            elif kind == "GREATER_THAN":
                traits[prop] = num + 1
            elif kind == "LESS_THAN":
                traits[prop] = num - 1
            else:
                traits[prop] = num

    for rule in rules:
        if isinstance(rule, dict):
            for cond in iter_conditions(rule):
                apply_cond(cond)
    return traits


def segment_is_bucket_range(
    segment: Dict[str, Any], trait: str, operator: str, value: str
) -> bool:
    """True when a segment is exactly one bucket range and nothing else."""
    rules = segment.get("rules") or []
    if len(rules) != 1 or not isinstance(rules[0], dict) or rules[0].get("rules"):
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


def _rule_properties(rules: Sequence[Dict[str, Any]], exclude_trait: str) -> Set[str]:
    """Return non-bucket condition properties referenced anywhere in *rules*."""
    props: Set[str] = set()
    for rule in rules:
        if isinstance(rule, dict):
            for cond in iter_conditions(rule):
                prop = str(cond.get("property") or cond.get("trait") or "")
                if prop != exclude_trait:
                    props.add(prop)
    return props


def segment_is_range(
    segment: Dict[str, Any],
    trait: str,
    lo: int,
    hi: int,
    base_rules: Optional[Sequence[Dict[str, Any]]] = None,
) -> bool:
    """True when *segment* matches *base_rules* (if any) AND bucket range [lo, hi]."""
    if not (0 <= lo <= hi <= 99) or segment_has_percentage_split(segment):
        return False
    expected_base = strip_bucket_conditions(base_rules or [], trait)
    actual_props = _rule_properties(segment.get("rules") or [], trait)
    allowed_props = _rule_properties(expected_base, trait)
    if actual_props != allowed_props:
        return False
    actual_base = extract_base_rules(segment, trait)
    if _canonical_rule_signature(actual_base) != _canonical_rule_signature(expected_base):
        return False
    probe_traits: Dict[str, object] = {}
    if expected_base:
        probe_traits = _synthesize_matching_traits(expected_base)
        if not segment_matches({"rules": expected_base}, probe_traits):
            return False
    for bucket in range(100):
        try:
            matched = segment_matches(segment, {**probe_traits, trait: bucket})
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
    segments: Sequence[Dict[str, Any]],
    trait: str,
    lo: int,
    hi: int,
    base_rules: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Find an existing segment whose audience equals *base_rules* AND [lo, hi]."""
    matches = [
        segment
        for segment in segments
        if segment_is_range(segment, trait, lo, hi, base_rules=base_rules)
    ]
    matches.sort(key=lambda item: int(item.get("id") or 0))
    return matches[0] if matches else None
