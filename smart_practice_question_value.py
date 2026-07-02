import hashlib
from collections import Counter
from typing import Any, Mapping

from progress_store import now_iso

CALIBRATION_SCHEMA_VERSION = 1
QUALITY_STATUSES = {
    "healthy",
    "needs_review",
    "ambiguous",
    "source_conflicted",
    "poor_discriminator",
    "possible_bad_key",
    "insufficient_data",
}
INFO_BOUNDS = {
    "diagnostic_discrimination": (0.0, 20.0),
    "graph_bottleneck_value": (0.0, 10.0),
    "uncertainty_reduction": (0.0, 20.0),
    "transfer_evidence_value": (0.0, 15.0),
    "coverage_value": (0.0, 15.0),
    "redundancy_cost": (0.0, 15.0),
    "item_quality_risk": (0.0, 15.0),
    "source_risk": (0.0, 15.0),
}


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def clamp_component(name: str, value: float) -> float:
    low, high = INFO_BOUNDS[name]
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if number != number:
        number = low
    return round(max(low, min(high, number)), 4)


def empty_calibration_store(created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or now_iso()
    return {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "edge_calibration": {},
        "graph_audits": {},
        "question_quality": {},
        "information_value_history": {},
        "last_updated_at": created_at,
        "invalid_records": {},
    }


def normalize_calibration_store(store: Mapping[str, Any] | None, created_at: str | None = None) -> dict[str, Any]:
    if not isinstance(store, Mapping):
        return empty_calibration_store(created_at)
    clean = empty_calibration_store(created_at or str(store.get("last_updated_at") or now_iso()))
    for key in ("edge_calibration", "graph_audits", "question_quality", "information_value_history"):
        clean[key] = dict(store.get(key) or {}) if isinstance(store.get(key) or {}, Mapping) else {}
    clean["invalid_records"] = dict(store.get("invalid_records") or {}) if isinstance(store.get("invalid_records") or {}, Mapping) else {}
    return clean


def question_quality_record(
    question: Mapping[str, Any],
    outcomes: list[Mapping[str, Any]],
    *,
    evaluated_at: str | None = None,
    minimum_samples: int = 10,
    possible_bad_key_minimum_samples: int = 20,
) -> dict[str, Any]:
    evaluated_at = evaluated_at or now_iso()
    qnum = int(question.get("question_number") or 0)
    eligible = [row for row in outcomes if int(row.get("question_number") or 0) == qnum]
    groups = {str(row.get("session_id") or row.get("group_id") or row.get("at") or idx) for idx, row in enumerate(eligible)}
    sample_count = len(groups)
    correct = sum(1 for row in eligible if row.get("correct"))
    wrong = sum(1 for row in eligible if row.get("correct") is False)
    high_conf_wrong = sum(1 for row in eligible if row.get("correct") is False and str(row.get("confidence") or "") == "Sure")
    misread = sum(1 for row in eligible if str(row.get("miss_reason") or "").casefold() == "misread")
    stronger = [row for row in eligible if float(row.get("concept_retrievability", 0.0) or 0.0) >= 0.7]
    weaker = [row for row in eligible if float(row.get("concept_retrievability", 0.0) or 0.0) < 0.7]
    strong_acc = sum(1 for row in stronger if row.get("correct")) / max(1, len(stronger))
    weak_acc = sum(1 for row in weaker if row.get("correct")) / max(1, len(weaker))
    discrimination = round(max(-1.0, min(1.0, strong_acc - weak_acc)), 4)
    ambiguity_rate = round((misread + high_conf_wrong) / max(1, len(eligible)), 4)
    repeat_concentration = round(max(Counter(str(row.get("selected") or "") for row in eligible).values() or [0]) / max(1, len(eligible)), 4)
    source_conflict = bool(question.get("source_conflict") or str(question.get("source_label") or "") == "Source conflict")
    healthy_alt_success = sum(1 for row in eligible if row.get("healthy_alternative_success"))
    answer_key_suspicion = 0.0
    status = "insufficient_data"
    if sample_count >= minimum_samples:
        if source_conflict and healthy_alt_success >= 3:
            status = "source_conflicted"
        elif ambiguity_rate >= 0.35:
            status = "ambiguous"
        elif sample_count >= 15 and discrimination <= 0.0:
            status = "poor_discriminator"
        else:
            status = "healthy"
    if sample_count >= possible_bad_key_minimum_samples and high_conf_wrong >= 8 and healthy_alt_success >= 5 and source_conflict:
        status = "possible_bad_key"
        answer_key_suspicion = min(1.0, high_conf_wrong / max(1, len(eligible)))
    source_risk = 0.4 if status == "source_conflicted" else 0.7 if status == "possible_bad_key" else 0.2 if status in {"ambiguous", "poor_discriminator"} else 0.0
    return {
        "question_number": qnum,
        "status": status,
        "sample_count": sample_count,
        "distinct_session_count": sample_count,
        "distinct_concept_outcome_count": len({str(row.get("concept_key") or "") for row in eligible if row.get("concept_key")}),
        "difficulty_consistency": round(1.0 - abs((correct / max(1, len(eligible))) - float(question.get("predicted_success", 0.5) or 0.5)), 4),
        "item_discrimination": discrimination,
        "ambiguity_rate": ambiguity_rate,
        "misread_rate": round(misread / max(1, len(eligible)), 4),
        "high_confidence_wrong_rate": round(high_conf_wrong / max(1, len(eligible)), 4),
        "cross_source_agreement": round(healthy_alt_success / max(1, len(eligible)), 4),
        "concept_agreement": round(correct / max(1, len(eligible)), 4),
        "repeat_failure_concentration": repeat_concentration,
        "answer_key_suspicion": round(answer_key_suspicion, 4),
        "source_risk": round(source_risk, 4),
        "confidence": round(min(1.0, sample_count / max(1, possible_bad_key_minimum_samples)), 4),
        "last_evaluated_at": evaluated_at,
    }


def information_value(
    question: Mapping[str, Any],
    concept_state: Mapping[str, Any] | None = None,
    graph_audit: Mapping[str, Any] | None = None,
    session_context: Mapping[str, Any] | None = None,
    quality: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values = dict((policy or {}).get("policy_values") or {})
    max_contribution = float(values.get("maximum_information_value_contribution", 6.0) or 6.0)
    concept_state = dict(concept_state or {})
    graph_audit = dict(graph_audit or {})
    session_context = dict(session_context or {})
    quality = dict(quality or {})
    reasons = []
    diagnostic = 14.0 if question.get("smart_root_cause") not in {"", None, "insufficient_evidence"} else 4.0
    bottleneck = min(10.0, len(graph_audit.get("dependent_concepts", []) or []) * 2.0)
    uncertainty_raw = concept_state.get("uncertainty", 1.0)
    uncertainty = float(1.0 if uncertainty_raw is None else uncertainty_raw) * 18.0
    transfer = 12.0 if question.get("is_transfer_item") or question.get("stem_style") not in set(session_context.get("seen_stem_styles", []) or []) else 1.0
    coverage = 12.0 if question.get("objective_code") not in set(session_context.get("seen_objectives", []) or []) else 3.0
    same_q = int(question.get("question_number") or 0) in set(session_context.get("seen_question_numbers", []) or [])
    same_concept = question.get("smart_concept_key") in set(session_context.get("seen_concepts", []) or [])
    redundancy = (8.0 if same_q else 0.0) + (4.0 if same_concept else 0.0)
    item_risk = float(quality.get("source_risk", 0.0) or 0.0) * 15.0
    source_risk = 8.0 if str(question.get("source_label") or "") in {"Source conflict", "Decayed"} else 0.0
    components = {
        "diagnostic_discrimination": clamp_component("diagnostic_discrimination", diagnostic),
        "graph_bottleneck_value": clamp_component("graph_bottleneck_value", bottleneck),
        "uncertainty_reduction": clamp_component("uncertainty_reduction", uncertainty),
        "transfer_evidence_value": clamp_component("transfer_evidence_value", transfer),
        "coverage_value": clamp_component("coverage_value", coverage),
        "redundancy_cost": clamp_component("redundancy_cost", redundancy),
        "item_quality_risk": clamp_component("item_quality_risk", item_risk),
        "source_risk": clamp_component("source_risk", source_risk),
    }
    total = (
        components["diagnostic_discrimination"]
        + components["graph_bottleneck_value"]
        + components["uncertainty_reduction"]
        + components["transfer_evidence_value"]
        + components["coverage_value"]
        - components["redundancy_cost"]
        - components["item_quality_risk"]
        - components["source_risk"]
    )
    bounded_total = max(-max_contribution, min(max_contribution, total))
    risk_drag = min(max_contribution, (components["item_quality_risk"] + components["source_risk"]) * 0.1)
    bounded_total = round(max(-max_contribution, bounded_total - risk_drag), 4)
    if components["diagnostic_discrimination"] > 10:
        reasons.append("diagnostic")
    if components["redundancy_cost"] > 0:
        reasons.append("redundancy")
    if components["item_quality_risk"] > 0:
        reasons.append("quality risk")
    return {"total": bounded_total, **components, "reasons": reasons}


def quality_measurement(records: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row.get("status") or "insufficient_data") for row in records.values())
    total = max(1, sum(counts.values()))
    return {
        "healthy_count": counts.get("healthy", 0),
        "needs_review_count": counts.get("needs_review", 0),
        "ambiguous_count": counts.get("ambiguous", 0),
        "source_conflicted_count": counts.get("source_conflicted", 0),
        "poor_discriminator_count": counts.get("poor_discriminator", 0),
        "possible_bad_key_count": counts.get("possible_bad_key", 0),
        "insufficient_data_count": counts.get("insufficient_data", 0),
        "later_confirmation_rate": "unobserved",
        "false_positive_rate": round((counts.get("needs_review", 0) + counts.get("ambiguous", 0)) / total, 4),
    }
