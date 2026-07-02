import copy
import hashlib
import json
from collections import Counter
from typing import Any, Mapping

from progress_store import now_iso
from smart_practice_profile import SMART_PRACTICE_POLICY_VERSION, UTILITY_COMPONENT_BOUNDS

POLICY_SCHEMA_VERSION = 1
GOVERNANCE_SCHEMA_VERSION = 1
VALID_POLICY_STATUSES = {
    "draft",
    "shadow",
    "candidate",
    "active",
    "rejected",
    "expired",
    "rolled_back",
    "archived",
}
PROMOTION_THRESHOLDS = {
    "minimum_shadow_decisions": 50,
    "minimum_supported_challenger_outcomes": 30,
    "minimum_24h_outcomes": 20,
    "minimum_7d_outcomes": 10,
    "minimum_counterfactual_coverage_rate": 0.35,
    "minimum_observation_age_days": 7,
}
REGRESSION_TOLERANCES = {
    "7d_concept_recall": 0.02,
    "weakness_recovery": 0.03,
    "repair_relapse": 0.03,
    "source_risk": 0.05,
    "repetition_cost": 0.05,
    "due_backlog": 0.01,
    "calibration_error": 0.03,
    "fatigue_cost": 0.05,
}
DRIFT_TYPES = (
    "calibration_drift",
    "performance_drift",
    "learner_skill_drift",
    "domain_weakness_drift",
    "question_bank_drift",
    "source_quality_drift",
    "role_distribution_drift",
    "repair_effectiveness_drift",
)


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def policy_checksum(policy: Mapping[str, Any]) -> str:
    payload = {
        "policy_id": policy.get("policy_id"),
        "policy_version": policy.get("policy_version"),
        "policy_schema_version": policy.get("policy_schema_version"),
        "policy_values": policy.get("policy_values"),
        "parent_policy_id": policy.get("parent_policy_id"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def default_policy_values() -> dict[str, Any]:
    return {
        "role_shares": {
            "due_retention": 0.25,
            "weak_repair": 0.25,
            "blueprint_coverage": 0.25,
            "transfer": 0.15,
            "controlled_stretch": 0.10,
        },
        "utility_component_scales": {name: 1.0 for name in UTILITY_COMPONENT_BOUNDS},
        "utility_component_bounds": dict(UTILITY_COMPONENT_BOUNDS),
        "source_risk_settings": {"baseline": 85.0, "decayed_penalty": 0.22, "conflict_penalty": 0.28},
        "fatigue_settings": {"high_burnout_difficulty_penalty": 0.12, "negative_momentum_penalty": 0.08},
        "review_interval_multiplier": 1.0,
        "repair_trigger_settings": {"weak_repair_min_pressure": 20.0, "wrong_memory_min_pressure": 35.0},
        "repair_spacing_settings": {"contrast_delay": 2, "transfer_delay": 3, "spaced_retrieval_min_days": 1},
        "weakness_thresholds": {"active_weak_wrong_surplus": 1, "false_weak_successes": 2},
        "prediction_calibration": {"recall_probability_offset": 0.0},
        "exploration_settings": {"transfer_min_value": 4.0},
        "repetition_settings": {"recent_concept_penalty": 2.0, "correct_streak_penalty": 1.4},
        "minimum_evidence_thresholds": dict(PROMOTION_THRESHOLDS),
        "graph_enabled": True,
        "minimum_edge_evidence": 0.45,
        "minimum_diagnosis_confidence": 0.45,
        "maximum_graph_utility_contribution": 4.0,
        "prerequisite_repair_enabled": True,
        "confusion_repair_enabled": True,
        "transfer_diagnosis_enabled": True,
        "item_specific_diagnosis_enabled": True,
        "source_problem_diagnosis_enabled": True,
        "edge_calibration_enabled": True,
        "edge_weight_max_adjustment": 0.10,
        "minimum_edge_support": 3,
        "minimum_edge_contradiction": 2,
        "maximum_prerequisite_depth": 2,
        "maximum_graph_candidates": 20,
        "information_value_enabled": True,
        "maximum_information_value_contribution": 6.0,
        "question_quality_enabled": True,
        "minimum_question_quality_samples": 10,
        "possible_bad_key_minimum_samples": 20,
        "quality_risk_maximum": 4.0,
    }


def make_policy(
    *,
    policy_id: str,
    policy_version: str,
    policy_name: str,
    status: str,
    created_at: str,
    created_by: str,
    parent_policy_id: str = "",
    policy_values: Mapping[str, Any] | None = None,
    evidence_reference: Mapping[str, Any] | None = None,
    change_summary: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    policy = {
        "policy_id": policy_id,
        "policy_version": policy_version,
        "policy_name": policy_name,
        "created_at": created_at,
        "created_by": created_by,
        "parent_policy_id": parent_policy_id,
        "status": status,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "policy_values": copy.deepcopy(dict(policy_values or default_policy_values())),
        "evidence_reference": dict(evidence_reference or {}),
        "change_summary": list(change_summary or []),
        "checksum": "",
    }
    policy["checksum"] = policy_checksum(policy)
    return policy


def bootstrap_policy(created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or "2026-01-01T00:00:00"
    return make_policy(
        policy_id=stable_id("policy", "bootstrap", SMART_PRACTICE_POLICY_VERSION, POLICY_SCHEMA_VERSION),
        policy_version=SMART_PRACTICE_POLICY_VERSION,
        policy_name="Smart Practice 9 Bootstrap",
        status="active",
        created_at=created_at,
        created_by="legacy_migration",
        evidence_reference={"source": "legacy_smart_practice_configuration"},
        change_summary=[{"field": "bootstrap", "old_value": None, "new_value": "legacy configuration"}],
    )


def audit_event(
    event_type: str,
    created_at: str,
    *,
    actor: str = "system",
    active_policy_before: str = "",
    active_policy_after: str = "",
    candidate_policy_id: str = "",
    measurement_report_ids: list[str] | None = None,
    recommendation_ids: list[str] | None = None,
    evidence_summary: Mapping[str, Any] | None = None,
    reason: str = "",
    policy_checksum_value: str = "",
    result: str = "ok",
) -> dict[str, Any]:
    payload = {
        "event_type": event_type,
        "created_at": created_at,
        "actor": actor,
        "active_policy_before": active_policy_before,
        "active_policy_after": active_policy_after,
        "candidate_policy_id": candidate_policy_id,
        "measurement_report_ids": list(measurement_report_ids or []),
        "recommendation_ids": list(recommendation_ids or []),
        "evidence_summary": dict(evidence_summary or {}),
        "reason": reason,
        "policy_checksum": policy_checksum_value,
        "result": result,
    }
    payload["audit_event_id"] = stable_id(
        "audit",
        event_type,
        created_at,
        active_policy_before,
        active_policy_after,
        candidate_policy_id,
        reason,
        result,
    )
    return payload


def append_audit(governance: dict[str, Any], event: Mapping[str, Any]) -> None:
    existing = {row.get("audit_event_id") for row in governance.setdefault("audit_log", [])}
    if event.get("audit_event_id") not in existing:
        governance["audit_log"].append(dict(event))


def empty_governance(created_at: str | None = None) -> dict[str, Any]:
    policy = bootstrap_policy(created_at=created_at)
    governance = {
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "active_policy_id": policy["policy_id"],
        "policies": {policy["policy_id"]: policy},
        "candidates": {},
        "shadow_decisions": {},
        "challenger_evaluations": {},
        "drift_reports": {},
        "recovery_snapshots": {},
        "audit_log": [],
        "invalid_data_count": 0,
        "last_updated_at": created_at or policy["created_at"],
    }
    append_audit(
        governance,
        audit_event(
            "policy_bootstrapped",
            governance["last_updated_at"],
            active_policy_after=policy["policy_id"],
            policy_checksum_value=policy["checksum"],
            reason="Migrated from legacy Smart Practice configuration.",
        ),
    )
    return governance


def validate_policy_values(values: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    allowed = set(default_policy_values())
    unknown = set(values) - allowed
    if unknown:
        reasons.append(f"unknown_fields:{','.join(sorted(unknown))}")
    shares = dict(values.get("role_shares") or {})
    if abs(sum(float(v) for v in shares.values()) - 1.0) > 0.001:
        reasons.append("role_shares_must_total_one")
    if any(float(v) < 0 for v in shares.values()):
        reasons.append("role_share_negative")
    for name, bounds in dict(values.get("utility_component_bounds") or {}).items():
        if name not in UTILITY_COMPONENT_BOUNDS:
            reasons.append(f"unknown_utility_bound:{name}")
            continue
        low, high = bounds
        if float(low) < 0 or float(high) < float(low):
            reasons.append(f"invalid_utility_bound:{name}")
    for name, scale in dict(values.get("utility_component_scales") or {}).items():
        if float(scale) <= 0 or float(scale) > 2.0:
            reasons.append(f"invalid_utility_scale:{name}")
    source = dict(values.get("source_risk_settings") or {})
    fatigue = dict(values.get("fatigue_settings") or {})
    if any(float(v) < 0 for v in source.values()):
        reasons.append("source_penalty_cannot_reward")
    if any(float(v) < 0 for v in fatigue.values()):
        reasons.append("fatigue_penalty_cannot_reward")
    multiplier = float(values.get("review_interval_multiplier", 1.0))
    if multiplier < 0.9 or multiplier > 1.1:
        reasons.append("review_multiplier_out_of_bounds")
    spacing = dict(values.get("repair_spacing_settings") or {})
    if int(spacing.get("contrast_delay", 0)) < 1 or int(spacing.get("transfer_delay", 0)) < 1:
        reasons.append("repair_spacing_immediate_only")
    minimums = dict(values.get("minimum_evidence_thresholds") or {})
    if any(float(v) <= 0 for v in minimums.values()):
        reasons.append("minimum_evidence_must_be_positive")
    calibration = dict(values.get("prediction_calibration") or {})
    if abs(float(calibration.get("recall_probability_offset", 0.0))) > 0.05:
        reasons.append("probability_offset_out_of_bounds")
    if float(values.get("minimum_edge_evidence", 0.45) or 0.45) < 0.0 or float(values.get("minimum_edge_evidence", 0.45) or 0.45) > 1.0:
        reasons.append("minimum_edge_evidence_out_of_bounds")
    if float(values.get("minimum_diagnosis_confidence", 0.45) or 0.45) < 0.0 or float(values.get("minimum_diagnosis_confidence", 0.45) or 0.45) > 1.0:
        reasons.append("minimum_diagnosis_confidence_out_of_bounds")
    if float(values.get("maximum_graph_utility_contribution", 4.0) or 4.0) < 0.0 or float(values.get("maximum_graph_utility_contribution", 4.0) or 4.0) > 6.0:
        reasons.append("maximum_graph_utility_contribution_out_of_bounds")
    if float(values.get("edge_weight_max_adjustment", 0.10) or 0.10) < 0.0 or float(values.get("edge_weight_max_adjustment", 0.10) or 0.10) > 0.10:
        reasons.append("edge_weight_adjustment_out_of_bounds")
    if int(values.get("minimum_edge_support", 3) or 3) < 1:
        reasons.append("minimum_edge_support_out_of_bounds")
    if int(values.get("maximum_prerequisite_depth", 2) or 2) > 2:
        reasons.append("maximum_prerequisite_depth_out_of_bounds")
    if int(values.get("maximum_graph_candidates", 20) or 20) > 20:
        reasons.append("maximum_graph_candidates_out_of_bounds")
    if float(values.get("maximum_information_value_contribution", 6.0) or 6.0) < 0.0 or float(values.get("maximum_information_value_contribution", 6.0) or 6.0) > 8.0:
        reasons.append("maximum_information_value_contribution_out_of_bounds")
    if int(values.get("minimum_question_quality_samples", 10) or 10) < 1:
        reasons.append("minimum_question_quality_samples_out_of_bounds")
    if int(values.get("possible_bad_key_minimum_samples", 20) or 20) < int(values.get("minimum_question_quality_samples", 10) or 10):
        reasons.append("possible_bad_key_samples_out_of_bounds")
    if float(values.get("quality_risk_maximum", 4.0) or 4.0) < 0.0 or float(values.get("quality_risk_maximum", 4.0) or 4.0) > 6.0:
        reasons.append("quality_risk_maximum_out_of_bounds")
    return not reasons, reasons


def validate_policy(policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if policy.get("status") not in VALID_POLICY_STATUSES:
        reasons.append("invalid_status")
    if int(policy.get("policy_schema_version", 0) or 0) != POLICY_SCHEMA_VERSION:
        reasons.append("invalid_schema")
    ok, value_reasons = validate_policy_values(policy.get("policy_values") or {})
    reasons.extend(value_reasons)
    if policy.get("checksum") != policy_checksum(policy):
        reasons.append("checksum_mismatch")
    return ok and not reasons, reasons


def normalize_governance(governance: Mapping[str, Any] | None, created_at: str | None = None) -> dict[str, Any]:
    if not isinstance(governance, Mapping):
        return empty_governance(created_at=created_at)
    clean = {
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "active_policy_id": str(governance.get("active_policy_id") or ""),
        "policies": dict(governance.get("policies") or {}),
        "candidates": dict(governance.get("candidates") or {}),
        "shadow_decisions": dict(governance.get("shadow_decisions") or {}),
        "challenger_evaluations": dict(governance.get("challenger_evaluations") or {}),
        "drift_reports": dict(governance.get("drift_reports") or {}),
        "recovery_snapshots": dict(governance.get("recovery_snapshots") or {}),
        "audit_log": list(governance.get("audit_log") or []),
        "invalid_data_count": int(governance.get("invalid_data_count") or 0),
        "last_updated_at": str(governance.get("last_updated_at") or created_at or now_iso()),
    }
    active = clean["policies"].get(clean["active_policy_id"])
    valid_active = bool(active and validate_policy(active)[0] and active.get("status") == "active")
    if not valid_active:
        clean["invalid_data_count"] += 1
        valid = [
            policy
            for policy in clean["policies"].values()
            if validate_policy(policy)[0] and policy.get("status") in {"active", "archived", "rolled_back"}
        ]
        if valid:
            valid.sort(key=lambda p: (str(p.get("created_at") or ""), str(p.get("policy_id") or "")), reverse=True)
            for policy in clean["policies"].values():
                if isinstance(policy, dict) and policy.get("status") == "active":
                    policy["status"] = "archived"
            recovered = copy.deepcopy(valid[0])
            recovered["status"] = "active"
            clean["policies"][recovered["policy_id"]] = recovered
            clean["active_policy_id"] = recovered["policy_id"]
            append_audit(
                clean,
                audit_event(
                    "startup_recovered",
                    clean["last_updated_at"],
                    active_policy_after=recovered["policy_id"],
                    policy_checksum_value=recovered["checksum"],
                    reason="Recovered from malformed active policy.",
                ),
            )
        else:
            fallback = bootstrap_policy(created_at=created_at)
            clean["policies"][fallback["policy_id"]] = fallback
            clean["active_policy_id"] = fallback["policy_id"]
            append_audit(
                clean,
                audit_event(
                    "startup_recovered",
                    clean["last_updated_at"],
                    active_policy_after=fallback["policy_id"],
                    policy_checksum_value=fallback["checksum"],
                    reason="Bootstrapped because no valid stored policy was available.",
                ),
            )
    for policy_id, policy in list(clean["policies"].items()):
        if not isinstance(policy, Mapping):
            clean["invalid_data_count"] += 1
            clean["policies"].pop(policy_id, None)
    active_rows = [
        policy
        for policy in clean["policies"].values()
        if isinstance(policy, Mapping) and policy.get("status") == "active" and validate_policy(policy)[0]
    ]
    if len(active_rows) != 1:
        clean["invalid_data_count"] += 1
        valid = [
            policy
            for policy in clean["policies"].values()
            if isinstance(policy, Mapping)
            and validate_policy(policy)[0]
            and policy.get("status") in {"active", "archived", "rolled_back"}
        ]
        valid.sort(key=lambda p: (str(p.get("created_at") or ""), str(p.get("policy_id") or "")), reverse=True)
        if valid:
            recovered = copy.deepcopy(valid[0])
            for policy in clean["policies"].values():
                if isinstance(policy, dict) and policy.get("status") == "active":
                    policy["status"] = "archived"
            recovered["status"] = "active"
            clean["policies"][recovered["policy_id"]] = recovered
            clean["active_policy_id"] = recovered["policy_id"]
            append_audit(
                clean,
                audit_event(
                    "startup_recovered",
                    clean["last_updated_at"],
                    active_policy_after=recovered["policy_id"],
                    policy_checksum_value=recovered["checksum"],
                    reason="Recovered because active policy count was not exactly one.",
                ),
            )
    return clean


def active_policy(governance: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_governance(governance)
    return copy.deepcopy(normalized["policies"][normalized["active_policy_id"]])


def validate_recommendation(recommendation: Mapping[str, Any], active: Mapping[str, Any], applied_ids: set[str]) -> tuple[bool, str]:
    rec_id = str(recommendation.get("recommendation_id") or recommendation.get("target") or "")
    if recommendation.get("status") != "recommended":
        return False, "unsupported_recommendation"
    if rec_id in applied_ids:
        return False, "duplicate_recommendation"
    if recommendation.get("evaluated_policy_id") and recommendation.get("evaluated_policy_id") != active.get("policy_id"):
        return False, "stale_recommendation"
    if recommendation.get("measurement_report_id") in {"", None}:
        return False, "missing_measurement_report"
    max_change = abs(float(recommendation.get("maximum_allowed_change", 0.0) or 0.0))
    current = recommendation.get("current_value")
    new = recommendation.get("recommended_value")
    if new is None:
        return False, "missing_recommended_value"
    if current is not None and abs(float(new) - float(current)) > max_change + 1e-9:
        return False, "change_exceeds_bound"
    return True, ""


def set_nested_value(values: dict[str, Any], target: str, value: Any) -> tuple[Any, Any]:
    mapping = {
        "recall_probability_bias": ("prediction_calibration", "recall_probability_offset"),
        "source-risk penalty": ("source_risk_settings", "decayed_penalty"),
        "fatigue penalty": ("fatigue_settings", "high_burnout_difficulty_penalty"),
        "review interval multiplier": ("review_interval_multiplier",),
    }
    path = mapping.get(target, tuple(str(target).split(".")))
    if len(path) == 1:
        old = values.get(path[0])
        values[path[0]] = value
        return old, value
    parent = values.setdefault(path[0], {})
    old = parent.get(path[1])
    parent[path[1]] = value
    return old, value


def create_candidate_policy(
    governance: Mapping[str, Any],
    recommendations: list[Mapping[str, Any]],
    *,
    created_at: str,
    actor: str = "system",
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    gov = normalize_governance(governance, created_at=created_at)
    active = active_policy(gov)
    applied = {
        rid
        for policy in list(gov.get("candidates", {}).values()) + list(gov.get("policies", {}).values())
        for rid in policy.get("evidence_reference", {}).get("recommendation_ids", [])
    }
    reasons = []
    changes = []
    values = copy.deepcopy(active["policy_values"])
    recommendation_ids = []
    for rec in recommendations:
        ok, reason = validate_recommendation(rec, active, applied)
        if not ok:
            reasons.append(reason)
            continue
        target = str(rec.get("target") or "")
        old, new = set_nested_value(values, target, rec.get("recommended_value"))
        changes.append({"field": target, "old_value": old, "new_value": new})
        recommendation_ids.append(str(rec.get("recommendation_id") or target))
    if reasons:
        append_audit(
            gov,
            audit_event(
                "candidate_validation_failed",
                created_at,
                actor=actor,
                active_policy_before=active["policy_id"],
                recommendation_ids=recommendation_ids,
                reason=";".join(reasons),
                result="failed",
            ),
        )
        return None, gov, reasons
    ok, validation_reasons = validate_policy_values(values)
    if not ok:
        append_audit(gov, audit_event("candidate_validation_failed", created_at, actor=actor, active_policy_before=active["policy_id"], recommendation_ids=recommendation_ids, reason=";".join(validation_reasons), result="failed"))
        return None, gov, validation_reasons
    candidate_id = stable_id("policy", active["policy_id"], canonical_json(changes), created_at)
    candidate = make_policy(
        policy_id=candidate_id,
        policy_version=f"{active['policy_version']}+candidate.{len(gov['candidates']) + 1}",
        policy_name="Smart Practice Candidate",
        status="candidate",
        created_at=created_at,
        created_by=actor,
        parent_policy_id=active["policy_id"],
        policy_values=values,
        evidence_reference={
            "recommendation_ids": recommendation_ids,
            "measurement_report_ids": [str(rec.get("measurement_report_id")) for rec in recommendations],
        },
        change_summary=changes,
    )
    gov["candidates"][candidate_id] = candidate
    gov["policies"][candidate_id] = candidate
    append_audit(
        gov,
        audit_event(
            "candidate_created",
            created_at,
            actor=actor,
            active_policy_before=active["policy_id"],
            candidate_policy_id=candidate_id,
            recommendation_ids=recommendation_ids,
            evidence_summary={"change_count": len(changes)},
            policy_checksum_value=candidate["checksum"],
        ),
    )
    gov["last_updated_at"] = created_at
    return copy.deepcopy(candidate), gov, []


def role_counts(questions: list[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(q.get("smart_primary_role") or "") for q in questions))


def utility_summary(questions: list[Mapping[str, Any]]) -> dict[str, float]:
    values = [float(q.get("smart_utility", 0.0) or 0.0) for q in questions]
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4) if values else 0.0,
        "total": round(sum(values), 4),
    }


def create_shadow_decision(
    governance: Mapping[str, Any],
    champion_questions: list[Mapping[str, Any]],
    challenger_questions: list[Mapping[str, Any]],
    *,
    challenger_policy_id: str,
    created_at: str,
    learner_state_signature: str,
    candidate_snapshot_signature: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    gov = normalize_governance(governance, created_at=created_at)
    champion = active_policy(gov)
    champion_qnums = [int(q.get("question_number") or 0) for q in champion_questions]
    challenger_qnums = [int(q.get("question_number") or 0) for q in challenger_questions]
    decision_id = stable_id(
        "shadow",
        champion["policy_id"],
        challenger_policy_id,
        candidate_snapshot_signature,
        learner_state_signature,
        champion_qnums,
        challenger_qnums,
    )
    decision = {
        "shadow_decision_id": decision_id,
        "created_at": created_at,
        "champion_policy_id": champion["policy_id"],
        "challenger_policy_id": challenger_policy_id,
        "candidate_snapshot_signature": candidate_snapshot_signature,
        "learner_state_signature": learner_state_signature,
        "champion_question_numbers": champion_qnums,
        "challenger_question_numbers": challenger_qnums,
        "overlap_question_numbers": sorted(set(champion_qnums) & set(challenger_qnums)),
        "champion_role_counts": role_counts(champion_questions),
        "challenger_role_counts": role_counts(challenger_questions),
        "champion_utility_summary": utility_summary(champion_questions),
        "challenger_utility_summary": utility_summary(challenger_questions),
        "supported_outcome_question_numbers": [],
        "challenger_counterfactual_coverage_rate": 0.0,
    }
    gov["shadow_decisions"][decision_id] = decision
    append_audit(gov, audit_event("shadow_started", created_at, active_policy_before=champion["policy_id"], candidate_policy_id=challenger_policy_id, evidence_summary={"overlap": len(decision["overlap_question_numbers"])}))
    return copy.deepcopy(decision), gov


def evaluate_challenger(
    governance: Mapping[str, Any],
    challenger_policy_id: str,
    outcome_support: Mapping[str, Any],
    *,
    evaluated_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    gov = normalize_governance(governance, created_at=evaluated_at)
    support = dict(outcome_support or {})
    candidate = gov.get("policies", {}).get(challenger_policy_id) or {}
    thresholds = dict(
        ((candidate.get("policy_values") or {}).get("minimum_evidence_thresholds") or PROMOTION_THRESHOLDS)
    )
    supported = int(support.get("supported_challenger_outcomes", 0) or 0)
    h24 = int(support.get("24h_outcomes", 0) or 0)
    d7 = int(support.get("7d_outcomes", 0) or 0)
    coverage = float(support.get("counterfactual_coverage_rate", 0.0) or 0.0)
    age_days = float(support.get("observation_age_days", 0.0) or 0.0)
    reasons = []
    if supported < int(thresholds.get("minimum_supported_challenger_outcomes", PROMOTION_THRESHOLDS["minimum_supported_challenger_outcomes"]) or 0):
        reasons.append("insufficient_delayed_evidence")
    if h24 < int(thresholds.get("minimum_24h_outcomes", PROMOTION_THRESHOLDS["minimum_24h_outcomes"]) or 0):
        reasons.append("insufficient_24h_evidence")
    if d7 < int(thresholds.get("minimum_7d_outcomes", PROMOTION_THRESHOLDS["minimum_7d_outcomes"]) or 0):
        reasons.append("insufficient_7d_evidence")
    if age_days < float(thresholds.get("minimum_observation_age_days", PROMOTION_THRESHOLDS["minimum_observation_age_days"]) or 0):
        reasons.append("insufficient_observation_age")
    if coverage < float(thresholds.get("minimum_counterfactual_coverage_rate", PROMOTION_THRESHOLDS["minimum_counterfactual_coverage_rate"]) or 0.0):
        reasons.append("low_counterfactual_coverage")
    if int(support.get("shadow_decision_count", 0) or 0) < int(thresholds.get("minimum_shadow_decisions", PROMOTION_THRESHOLDS["minimum_shadow_decisions"]) or 0):
        reasons.append("insufficient_shadow_decisions")
    if int(support.get("invalid_data_count", 0) or 0) > 0:
        reasons.append("invalid_data_quality")
    regressions = regression_gate_failures(support)
    reasons.extend(regressions)
    improvement = bool(support.get("primary_metric_improved"))
    if reasons:
        status = "insufficient_data" if any(reason.startswith("insufficient") or reason == "low_counterfactual_coverage" for reason in reasons) else "rejection_recommended"
    elif improvement:
        status = "promotion_recommended"
    else:
        status = "eligible_for_review"
    evaluation_id = stable_id("eval", challenger_policy_id, evaluated_at, canonical_json(support))
    evaluation = {
        "evaluation_id": evaluation_id,
        "challenger_policy_id": challenger_policy_id,
        "evaluated_at": evaluated_at,
        "status": status,
        "rejection_reasons": reasons,
        "metrics": support,
        "aggregation_limits": {"prediction_window": 1, "concept_contribution": 1},
        "promotion_score": float(support.get("promotion_score", 0.0) or 0.0),
    }
    gov["challenger_evaluations"][evaluation_id] = evaluation
    append_audit(gov, audit_event("shadow_evaluated", evaluated_at, candidate_policy_id=challenger_policy_id, evidence_summary=support, result=status))
    if status == "promotion_recommended":
        append_audit(gov, audit_event("promotion_recommended", evaluated_at, candidate_policy_id=challenger_policy_id, evidence_summary=support, result=status))
    elif status == "rejection_recommended":
        append_audit(gov, audit_event("rejection_recommended", evaluated_at, candidate_policy_id=challenger_policy_id, evidence_summary=support, reason=";".join(reasons), result=status))
    return copy.deepcopy(evaluation), gov


def regression_gate_failures(metrics: Mapping[str, Any]) -> list[str]:
    failures = []
    checks = {
        "delayed_recall_regression": ("7d_concept_recall_delta", -REGRESSION_TOLERANCES["7d_concept_recall"]),
        "weakness_recovery_regression": ("weakness_recovery_delta", -REGRESSION_TOLERANCES["weakness_recovery"]),
        "repair_relapse_regression": ("repair_relapse_delta", REGRESSION_TOLERANCES["repair_relapse"]),
        "source_risk_regression": ("source_risk_delta", REGRESSION_TOLERANCES["source_risk"]),
        "repetition_regression": ("repetition_cost_delta", REGRESSION_TOLERANCES["repetition_cost"]),
        "due_backlog_regression": ("due_backlog_delta", REGRESSION_TOLERANCES["due_backlog"]),
        "calibration_regression": ("calibration_error_delta", REGRESSION_TOLERANCES["calibration_error"]),
        "fatigue_regression": ("fatigue_cost_delta", REGRESSION_TOLERANCES["fatigue_cost"]),
    }
    for reason, (field, tolerance) in checks.items():
        value = float(metrics.get(field, 0.0) or 0.0)
        if tolerance < 0 and value < tolerance:
            failures.append(reason)
        elif tolerance > 0 and value > tolerance:
            failures.append(reason)
    if metrics.get("role_floor_compliance") is False:
        failures.append("role_floor_regression")
    return failures


def latest_evaluation_for(governance: Mapping[str, Any], candidate_policy_id: str) -> Mapping[str, Any] | None:
    evaluations = [
        ev
        for ev in normalize_governance(governance).get("challenger_evaluations", {}).values()
        if ev.get("challenger_policy_id") == candidate_policy_id
    ]
    if not evaluations:
        return None
    evaluations.sort(key=lambda ev: (str(ev.get("evaluated_at") or ""), str(ev.get("evaluation_id") or "")), reverse=True)
    return evaluations[0]


def exactly_one_active(governance: Mapping[str, Any]) -> bool:
    return sum(1 for policy in governance.get("policies", {}).values() if policy.get("status") == "active") == 1


def activate_candidate_policy(
    governance: Mapping[str, Any],
    candidate_policy_id: str,
    expected_active_policy_id: str,
    approval_reference: str,
    activated_at: str,
    actor: str = "user",
) -> tuple[bool, dict[str, Any], str]:
    gov = normalize_governance(governance, created_at=activated_at)
    before = copy.deepcopy(gov)
    active_id = gov.get("active_policy_id")
    candidate = gov.get("policies", {}).get(candidate_policy_id)
    try:
        if active_id != expected_active_policy_id:
            return False, gov, "expected_active_policy_mismatch"
        if not candidate:
            return False, gov, "candidate_not_found"
        if candidate.get("parent_policy_id") != active_id:
            return False, gov, "candidate_parent_mismatch"
        valid, reasons = validate_policy(candidate)
        if not valid:
            return False, gov, "invalid_policy:" + ";".join(reasons)
        if candidate.get("status") not in {"candidate", "shadow"}:
            return False, gov, "invalid_candidate_status"
        evaluation = latest_evaluation_for(gov, candidate_policy_id)
        if not evaluation or evaluation.get("status") != "promotion_recommended":
            return False, gov, "required_evidence_missing"
        snapshot_id = stable_id("recovery", active_id, candidate_policy_id, activated_at)
        gov.setdefault("recovery_snapshots", {})[snapshot_id] = {
            "snapshot_id": snapshot_id,
            "created_at": activated_at,
            "active_policy_id": active_id,
            "candidate_policy_id": candidate_policy_id,
            "governance": copy.deepcopy(gov),
        }
        for policy in gov["policies"].values():
            if policy.get("status") == "active":
                policy["status"] = "archived"
        gov["policies"][candidate_policy_id]["status"] = "active"
        gov["active_policy_id"] = candidate_policy_id
        gov["last_updated_at"] = activated_at
        append_audit(
            gov,
            audit_event(
                "policy_activated",
                activated_at,
                actor=actor,
                active_policy_before=active_id,
                active_policy_after=candidate_policy_id,
                candidate_policy_id=candidate_policy_id,
                evidence_summary={"approval_reference": approval_reference},
                policy_checksum_value=candidate["checksum"],
            ),
        )
        if not exactly_one_active(gov):
            gov = before
            return False, gov, "activation_integrity_failed"
        return True, gov, ""
    except (KeyError, TypeError, ValueError) as exc:
        gov = before
        append_audit(gov, audit_event("activation_failed", activated_at, actor=actor, active_policy_before=active_id, candidate_policy_id=candidate_policy_id, reason=str(exc), result="failed"))
        return False, gov, "activation_failed"


def rollback_policy(
    governance: Mapping[str, Any],
    target_policy_id: str,
    expected_active_policy_id: str,
    reason: str,
    rolled_back_at: str,
    actor: str = "user",
) -> tuple[bool, dict[str, Any], str]:
    gov = normalize_governance(governance, created_at=rolled_back_at)
    active_id = gov.get("active_policy_id")
    target = gov.get("policies", {}).get(target_policy_id)
    if active_id != expected_active_policy_id:
        return False, gov, "expected_active_policy_mismatch"
    if not target:
        return False, gov, "target_policy_not_found"
    valid, reasons = validate_policy(target)
    if not valid and reasons != ["invalid_status"]:
        return False, gov, "invalid_target_policy"
    for policy in gov["policies"].values():
        if policy.get("status") == "active":
            policy["status"] = "rolled_back"
    gov["policies"][target_policy_id]["status"] = "active"
    gov["active_policy_id"] = target_policy_id
    gov["last_updated_at"] = rolled_back_at
    append_audit(
        gov,
        audit_event(
            "policy_rolled_back",
            rolled_back_at,
            actor=actor,
            active_policy_before=active_id,
            active_policy_after=target_policy_id,
            reason=reason,
            policy_checksum_value=target["checksum"],
        ),
    )
    return exactly_one_active(gov), gov, "" if exactly_one_active(gov) else "rollback_integrity_failed"


def detect_drift(
    baseline: Mapping[str, float],
    recent: Mapping[str, float],
    *,
    sample_count: int,
    detected_at: str,
    minimum_required_sample: int = 50,
) -> list[dict[str, Any]]:
    reports = []
    field_map = {
        "calibration_drift": "calibration_error",
        "performance_drift": "delayed_recall",
        "learner_skill_drift": "accuracy",
        "domain_weakness_drift": "domain_weakness",
        "question_bank_drift": "bank_signature",
        "source_quality_drift": "source_risk",
        "role_distribution_drift": "role_deviation",
        "repair_effectiveness_drift": "repair_success",
    }
    for drift_type in DRIFT_TYPES:
        field = field_map[drift_type]
        base = baseline.get(field)
        now = recent.get(field)
        if sample_count < minimum_required_sample or base is None or now is None:
            reports.append({
                "drift_type": drift_type,
                "detected": False,
                "severity": "none",
                "recent_value": now,
                "baseline_value": base,
                "absolute_change": None,
                "relative_change": None,
                "sample_count": sample_count,
                "minimum_required_sample": minimum_required_sample,
                "status": "insufficient_data",
                "reason": "Not enough eligible outcomes.",
                "detected_at": detected_at,
            })
            continue
        if field == "bank_signature" and not isinstance(now, (int, float)) or field == "bank_signature" and not isinstance(base, (int, float)):
            absolute = 1.0 if now != base else 0.0
            relative = absolute
        else:
            absolute = float(now) - float(base)
            relative = absolute / abs(float(base) or 1.0)
        detected = abs(absolute) >= 0.08
        severity = "high" if abs(absolute) >= 0.2 else "medium" if abs(absolute) >= 0.12 else "low" if detected else "none"
        reports.append({
            "drift_type": drift_type,
            "detected": detected,
            "severity": severity,
            "recent_value": now,
            "baseline_value": base,
            "absolute_change": round(absolute, 4),
            "relative_change": round(relative, 4),
            "sample_count": sample_count,
            "minimum_required_sample": minimum_required_sample,
            "status": "ok",
            "reason": "Drift threshold crossed." if detected else "Within drift tolerance.",
            "detected_at": detected_at,
        })
    return reports


def policy_diff(active: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes = []
    active_values = active.get("policy_values") or {}
    candidate_values = candidate.get("policy_values") or {}
    for key in sorted(set(active_values) | set(candidate_values)):
        if active_values.get(key) != candidate_values.get(key):
            changes.append({"field": key, "old_value": active_values.get(key), "new_value": candidate_values.get(key)})
    return changes


def build_policy_review_report(
    governance: Mapping[str, Any],
    candidate_policy_id: str,
    *,
    generated_at: str,
) -> dict[str, Any]:
    gov = normalize_governance(governance, created_at=generated_at)
    active = active_policy(gov)
    candidate = gov.get("policies", {}).get(candidate_policy_id)
    if not candidate:
        recommendation = "invalid_candidate"
        evaluation = {}
        gates = {"status": "invalid", "reasons": ["invalid_policy"]}
        diff = []
    else:
        evaluation = latest_evaluation_for(gov, candidate_policy_id) or {}
        status = evaluation.get("status")
        recommendation = (
            "approve_for_manual_activation" if status == "promotion_recommended"
            else "reject_candidate" if status == "rejection_recommended"
            else "continue_collecting" if status in {"collecting_data", "insufficient_data", None}
            else "invalid_candidate" if status == "invalid"
            else "continue_collecting"
        )
        gates = {"status": status or "collecting_data", "reasons": list(evaluation.get("rejection_reasons") or [])}
        diff = policy_diff(active, candidate)
    limitations = []
    metrics = dict((evaluation or {}).get("metrics") or {})
    if int(metrics.get("7d_outcomes", 0) or 0) < PROMOTION_THRESHOLDS["minimum_7d_outcomes"]:
        limitations.append("Too few 7-day outcomes.")
    if float(metrics.get("counterfactual_coverage_rate", 0.0) or 0.0) < PROMOTION_THRESHOLDS["minimum_counterfactual_coverage_rate"]:
        limitations.append("Low counterfactual coverage.")
    report = {
        "report_id": stable_id("policy_report", candidate_policy_id, generated_at, canonical_json(gates)),
        "generated_at": generated_at,
        "active_policy": {"policy_id": active.get("policy_id"), "checksum": active.get("checksum")},
        "candidate_policy": {"policy_id": candidate_policy_id, "checksum": (candidate or {}).get("checksum")},
        "policy_diff": diff,
        "evidence_summary": metrics,
        "shadow_summary": {"decision_count": sum(1 for row in gov.get("shadow_decisions", {}).values() if row.get("challenger_policy_id") == candidate_policy_id)},
        "champion_metrics": {},
        "challenger_metrics": metrics,
        "counterfactual_coverage": metrics.get("counterfactual_coverage_rate"),
        "promotion_gates": gates,
        "regression_gates": regression_gate_failures(metrics),
        "drift_summary": list(gov.get("drift_reports", {}).values()),
        "recommendation": recommendation,
        "limitations": limitations,
    }
    return report


def expire_candidate(governance: Mapping[str, Any], candidate_policy_id: str, *, expired_at: str, reason: str) -> dict[str, Any]:
    gov = normalize_governance(governance, created_at=expired_at)
    if candidate_policy_id in gov.get("policies", {}):
        gov["policies"][candidate_policy_id]["status"] = "expired"
        if candidate_policy_id in gov.get("candidates", {}):
            gov["candidates"][candidate_policy_id]["status"] = "expired"
        append_audit(gov, audit_event("candidate_expired", expired_at, candidate_policy_id=candidate_policy_id, reason=reason))
    return gov
