import hashlib
import math
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from progress_store import now_iso
from smart_practice_concept_graph import (
    audit_graph,
    diagnosis_measurement,
    normalize_graph,
)
from smart_practice_concept_graph import (
    concept_key_for_question as graph_concept_key_for_question,
)
from smart_practice_profile import SMART_PRACTICE_POLICY_VERSION, smart_practice_role_allocation
from smart_practice_question_value import quality_measurement

MEASUREMENT_SCHEMA_VERSION = 1
REPORT_LIMIT = 50
PROBABILITY_LOW = 0.01
PROBABILITY_HIGH = 0.99
WINDOWS = {
    "24h": (18 * 3600, 36 * 3600),
    "7d": (5 * 24 * 3600, 9 * 24 * 3600),
}
ROLES = ("due_retention", "weak_repair", "blueprint_coverage", "transfer", "controlled_stretch")


def clamp(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if number != number:
        number = low
    return max(low, min(high, number))


def clamp_probability(value):
    return round(clamp(value, PROBABILITY_LOW, PROBABILITY_HIGH), 4)


def parse_timestamp(value):
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def stable_id(*parts) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def concept_key_for_question(question: Mapping[str, Any]) -> str:
    return graph_concept_key_for_question(question)[0]


def concept_key_for_event(event: Mapping[str, Any]) -> str:
    clean_event = dict(event or {})
    clean_event.pop("repair_concept_key", None)
    canonical_key = graph_concept_key_for_question(clean_event)[0]
    raw_key = str(event.get("repair_concept_key") or "").strip()
    canonical_prefixes = (
        "coverage::",
        "objective_topic::",
        "repair::",
        "group::",
        "domain_topic::",
        "question::",
    )
    if canonical_key and not canonical_key.startswith("repair::") and not canonical_key.startswith("question::"):
        return canonical_key
    if raw_key and raw_key.casefold().startswith(canonical_prefixes):
        return raw_key
    return canonical_key or raw_key


def empty_measurement_store() -> dict[str, Any]:
    return {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "predictions": {},
        "outcome_links": {},
        "measurement_reports": [],
        "calibration_recommendations": [],
        "active_policy": {"policy_version": SMART_PRACTICE_POLICY_VERSION},
        "last_evaluated_at": "",
        "invalid_data": 0,
    }


def normalize_measurement_store(store: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(store, Mapping):
        return empty_measurement_store()
    clean = empty_measurement_store()
    clean.update(dict(store))
    clean["schema_version"] = MEASUREMENT_SCHEMA_VERSION
    clean["predictions"] = dict(clean.get("predictions") or {})
    clean["outcome_links"] = dict(clean.get("outcome_links") or {})
    clean["measurement_reports"] = list(clean.get("measurement_reports") or [])[-REPORT_LIMIT:]
    clean["calibration_recommendations"] = list(clean.get("calibration_recommendations") or [])
    clean["active_policy"] = dict(clean.get("active_policy") or {"policy_version": SMART_PRACTICE_POLICY_VERSION})
    clean["invalid_data"] = max(0, int(clean.get("invalid_data") or 0))
    return clean


def prediction_from_question(
    question: Mapping[str, Any], record: Mapping[str, Any] | None, created_at: str | None = None
) -> dict[str, Any]:
    created_at = created_at or now_iso()
    memory = dict((record or {}).get("learner_memory") or {})
    retrievability = clamp(memory.get("retrievability", 0.35), 0.0, 1.0)
    stability = clamp(memory.get("stability", 0.25), 0.0, 1.0)
    uncertainty = round(1.0 - stability, 4)
    breakdown = dict(question.get("smart_utility_breakdown") or {})
    retention_risk = clamp(breakdown.get("retention_risk", 0.0), 0.0, 25.0)
    repair_value = clamp(breakdown.get("misconception_repair_value", 0.0), 0.0, 20.0)
    learning_gain = clamp(breakdown.get("expected_learning_gain", 0.0), 0.0, 20.0) / 20.0
    attempts = int((record or {}).get("attempts", 0) or 0)
    exact_familiarity = 0.12 if attempts > 0 else -0.06
    policy_offset = clamp(question.get("smart_prediction_offset", 0.0), -0.05, 0.05)
    predicted_recall = clamp_probability(retrievability - retention_risk / 80.0 + policy_offset)
    predicted_success = clamp_probability(predicted_recall + exact_familiarity + stability * 0.08)
    policy_version = str(question.get("smart_policy_version") or SMART_PRACTICE_POLICY_VERSION)
    policy_id = str(question.get("smart_policy_id") or "")
    qnum = int(question.get("question_number") or 0)
    prediction_id = str(
        question.get("prediction_id")
        or stable_id(policy_version, created_at, qnum, question.get("smart_primary_role", ""))
    )
    concept_key = str(question.get("repair_concept_key") or concept_key_for_question(question))
    if any(marker in concept_key for marker in ("(", ")", "[", "]", "{", "}", "<", ">", ",")):
        raise ValueError(f"Malformed Smart Practice concept identity: {concept_key}")
    return {
        "prediction_id": prediction_id,
        "prediction_created_at": created_at,
        "question_number": qnum,
        "concept_key": concept_key,
        "objective_code": str(question.get("objective_code") or ""),
        "domain": str(question.get("domain") or "Unsorted"),
        "smart_primary_role": str(question.get("smart_primary_role") or ""),
        "smart_policy_version": policy_version,
        "smart_policy_id": policy_id,
        "predicted_recall_probability": predicted_recall,
        "predicted_success_probability": predicted_success,
        "predicted_learning_gain": round(clamp(learning_gain, 0.0, 1.0), 4),
        "predicted_misconception_repair_probability": round(clamp(repair_value / 20.0, 0.0, 1.0), 4),
        "predicted_response_seconds": round(clamp(10.0 + uncertainty * 18.0 + retention_risk * 0.4, 2.0, 180.0), 1),
        "learner_stability_at_selection": round(stability, 4),
        "learner_retrievability_at_selection": round(retrievability, 4),
        "learner_uncertainty_at_selection": uncertainty,
        "utility_total": float(question.get("smart_utility", 0.0) or 0.0),
        "utility_breakdown": breakdown,
        "selection_reasons": [str(value) for value in question.get("smart_selection_reasons", [])],
    }


def attach_prediction_to_question(
    question: dict[str, Any], store: dict[str, Any], record: Mapping[str, Any] | None, created_at: str | None = None
) -> dict[str, Any]:
    if question.get("prediction_id") and question.get("prediction_id") in store.get("predictions", {}):
        return dict(store["predictions"][question["prediction_id"]])
    prediction = prediction_from_question(question, record, created_at=created_at)
    predictions = store.setdefault("predictions", {})
    if prediction["prediction_id"] in predictions:
        base_prediction_id = str(prediction["prediction_id"] or "")
        collision_index = 1
        next_prediction_id = base_prediction_id
        while next_prediction_id in predictions:
            next_prediction_id = stable_id(base_prediction_id, collision_index)
            collision_index += 1
        prediction = dict(prediction)
        prediction["prediction_id"] = next_prediction_id
    predictions[prediction["prediction_id"]] = prediction
    question["prediction_id"] = prediction["prediction_id"]
    question["prediction_snapshot"] = prediction
    return prediction


def event_prediction_fields(question: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = dict(question.get("prediction_snapshot") or {})
    fields: dict[str, Any] = {
        "prediction_id": str(question.get("prediction_id") or snapshot.get("prediction_id") or ""),
        "smart_policy_id": str(question.get("smart_policy_id") or snapshot.get("smart_policy_id") or ""),
        "smart_policy_version": str(
            question.get("smart_policy_version")
            or snapshot.get("smart_policy_version")
            or SMART_PRACTICE_POLICY_VERSION
        ),
    }
    for key in (
        "predicted_recall_probability",
        "predicted_success_probability",
        "predicted_learning_gain",
        "predicted_misconception_repair_probability",
        "predicted_response_seconds",
        "utility_total",
    ):
        fields[key] = snapshot.get(key)
    return fields


def event_id(event: Mapping[str, Any]) -> str:
    return str(
        event.get("event_id")
        or stable_id(
            event.get("at", ""),
            event.get("question_number", ""),
            event.get("prediction_id", ""),
            event.get("selected", ""),
        )
    )


def _normalize_key_fragment(value: Any) -> str:
    return "".join(character if character.isalnum() else "_" for character in str(value or "").casefold()).strip("_")


def _legacy_repair_key_match(prediction: Mapping[str, Any], raw_repair_key: str) -> tuple[bool, str]:
    lowered = raw_repair_key.casefold().strip()
    if not lowered:
        return False, ""
    if lowered.startswith("topic::"):
        topic_value = raw_repair_key.split("::", 1)[1].strip()
        normalized_topic = _normalize_key_fragment(topic_value)
        if not normalized_topic:
            return False, ""
        prediction_topics = [
            _normalize_key_fragment(topic)
            for topic in (prediction.get("topics") or [])
            if _normalize_key_fragment(topic)
        ]
        if normalized_topic in prediction_topics:
            return True, "legacy_topic"
        prediction_concept = _normalize_key_fragment(str(prediction.get("concept_key") or ""))
        if prediction_concept and normalized_topic == prediction_concept.split("__")[-1]:
            return True, "legacy_topic"
        return False, ""
    if lowered.startswith("objective::"):
        objective_value = raw_repair_key.split("::", 1)[1].strip()
        normalized_objective = _normalize_key_fragment(objective_value)
        if normalized_objective and normalized_objective == _normalize_key_fragment(prediction.get("objective_code")):
            return True, "legacy_objective"
        return False, ""
    if lowered.startswith("domain::"):
        domain_value = raw_repair_key.split("::", 1)[1].strip()
        normalized_domain = _normalize_key_fragment(domain_value)
        if not normalized_domain:
            return False, ""
        if normalized_domain == _normalize_key_fragment(prediction.get("domain")):
            return True, "legacy_domain"
        prediction_concept = _normalize_key_fragment(str(prediction.get("concept_key") or ""))
        if prediction_concept and normalized_domain in prediction_concept:
            return True, "legacy_domain"
        return False, ""
    return False, ""


def same_concept(prediction: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[bool, str]:
    if int(prediction.get("question_number") or 0) == int(event.get("question_number") or 0):
        return True, "same_question"
    raw_repair_key = str(event.get("repair_concept_key") or "").strip()
    legacy_match, legacy_basis = _legacy_repair_key_match(prediction, raw_repair_key)
    if legacy_match:
        return True, legacy_basis
    if raw_repair_key:
        lowered_repair_key = raw_repair_key.casefold()
        if lowered_repair_key.startswith(("topic::", "objective::", "domain::")):
            return False, ""
        if "::" in raw_repair_key:
            return False, ""
    event_concept_key = concept_key_for_event(event)
    prediction_concept_key = str(prediction.get("concept_key") or "")
    if prediction_concept_key and prediction_concept_key == event_concept_key:
        return True, "repair_concept"
    if str(prediction.get("objective_code") or "") and str(prediction.get("objective_code") or "") == str(
        event.get("objective_code") or ""
    ):
        pred_topic = str(prediction.get("concept_key") or "").casefold()
        event_topics = " ".join(str(topic) for topic in event.get("topics", [])).casefold()
        if event_topics and any(part and part in event_topics for part in pred_topic.split("::")[-1:]):
            return True, "same_objective_topic"
    return False, ""


def outcome_detail(prediction, event, delay_seconds, match_basis):
    return {
        "status": "observed",
        "correct": bool(event.get("correct")),
        "review_grade": str(event.get("review_grade") or event.get("confidence") or ""),
        "confidence": str(event.get("confidence") or ""),
        "effective_response_seconds": float(
            event.get("effective_response_seconds", event.get("response_seconds", 0.0)) or 0.0
        ),
        "response_time_contaminated": bool(event.get("response_time_contaminated")),
        "miss_reason": str(event.get("miss_reason") or ""),
        "question_number": int(event.get("question_number") or 0),
        "event_timestamp": str(event.get("at") or ""),
        "delay_seconds": int(delay_seconds),
        "match_basis": match_basis,
        "same_source": str(prediction.get("source_label") or "") == str(event.get("source_label") or ""),
        "same_stem_style": str(prediction.get("stem_style") or "") == str(event.get("stem_style") or ""),
        "same_question": int(prediction.get("question_number") or 0) == int(event.get("question_number") or 0),
        "repair_stage": str(event.get("repair_stage") or ""),
    }


def find_future_outcome(prediction, history, window_name, concept=False):
    created = parse_timestamp(prediction.get("prediction_created_at"))
    if created is None:
        return {"status": "invalid_data"}
    minimum, maximum = WINDOWS[window_name]
    candidates = []
    for event in history:
        event_time = parse_timestamp(event.get("at"))
        if event_time is None:
            continue
        delay = (event_time - created).total_seconds()
        if delay <= 0 or delay < minimum or delay > maximum:
            continue
        if not concept and int(event.get("question_number") or 0) != int(prediction.get("question_number") or 0):
            continue
        if concept:
            matched, basis = same_concept(prediction, event)
            if not matched:
                continue
        else:
            basis = "same_question"
        candidates.append((event_time, int(event.get("question_number") or 0), event_id(event), event, delay, basis))
    if not candidates:
        return {"status": "not_observed"}
    candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    _time, _qnum, _eid, event, delay, basis = candidates[0]
    return outcome_detail(prediction, event, delay, basis)


def link_prediction_outcomes(prediction, history):
    future_history = [event for event in history if event_id(event) != str(prediction.get("prediction_id"))]
    immediate = next(
        (
            outcome_detail(prediction, event, 0, "same_question")
            for event in sorted(
                future_history, key=lambda e: (str(e.get("at") or ""), int(e.get("question_number") or 0), event_id(e))
            )
            if str(event.get("prediction_id") or "") == str(prediction.get("prediction_id") or "")
        ),
        {"status": "not_observed"},
    )
    return {
        "prediction_id": str(prediction.get("prediction_id") or ""),
        "immediate_item_outcome": immediate,
        "delayed_24h_item_outcome": find_future_outcome(prediction, future_history, "24h", concept=False),
        "delayed_24h_concept_outcome": find_future_outcome(prediction, future_history, "24h", concept=True),
        "delayed_7d_item_outcome": find_future_outcome(prediction, future_history, "7d", concept=False),
        "delayed_7d_concept_outcome": find_future_outcome(prediction, future_history, "7d", concept=True),
    }


def observed_pairs(predictions, links, outcome_key):
    rows = []
    for prediction in predictions:
        outcome = (links.get(prediction.get("prediction_id")) or {}).get(outcome_key) or {}
        if outcome.get("status") == "observed":
            rows.append(
                (float(prediction.get("predicted_recall_probability", 0.5)), 1.0 if outcome.get("correct") else 0.0)
            )
    return rows


def metric_result(value, sample_count, eligible_count=None, unobserved_count=0, minimum=20):
    eligible_count = sample_count if eligible_count is None else eligible_count
    if eligible_count <= 0:
        status = "no_eligible_samples"
    elif sample_count < minimum:
        status = "insufficient_data"
    else:
        status = "ok"
    return {
        "value": value,
        "sample_count": sample_count,
        "eligible_count": eligible_count,
        "unobserved_count": unobserved_count,
        "status": status,
    }


def brier_score(pairs):
    if not pairs:
        return metric_result(None, 0, 0)
    value = sum((p - actual) ** 2 for p, actual in pairs) / len(pairs)
    return metric_result(round(value, 6), len(pairs))


def log_loss(pairs):
    if not pairs:
        return metric_result(None, 0, 0)
    value = -sum(
        actual * math.log(clamp_probability(p)) + (1 - actual) * math.log(1 - clamp_probability(p))
        for p, actual in pairs
    ) / len(pairs)
    return metric_result(round(value, 6), len(pairs))


def calibration_bins(pairs, bins=5):
    out = []
    ece_total = 0.0
    for idx in range(bins):
        low = idx / bins
        high = (idx + 1) / bins
        bucket = [(p, actual) for p, actual in pairs if (p >= low and (p < high or idx == bins - 1))]
        if bucket:
            mean_pred = sum(p for p, _actual in bucket) / len(bucket)
            observed = sum(actual for _p, actual in bucket) / len(bucket)
            gap = abs(mean_pred - observed)
        else:
            mean_pred = observed = gap = None
        if gap is not None:
            ece_total += gap * len(bucket)
        out.append(
            {
                "range": [round(low, 2), round(high, 2)],
                "mean_predicted_probability": None if mean_pred is None else round(mean_pred, 4),
                "observed_success_rate": None if observed is None else round(observed, 4),
                "sample_count": len(bucket),
                "calibration_gap": None if gap is None else round(gap, 4),
            }
        )
    ece = round(ece_total / max(1, len(pairs)), 6) if pairs else None
    return out, metric_result(ece, len(pairs))


def pairwise_discrimination(pairs):
    comparable = []
    for i, left in enumerate(pairs):
        for right in pairs[i + 1 :]:
            if left[1] == right[1]:
                continue
            comparable.append((left, right))
    if not comparable:
        return metric_result(None, 0, 0)
    wins = 0.0
    for left, right in comparable:
        correct = left if left[1] > right[1] else right
        incorrect = right if left[1] > right[1] else left
        if correct[0] > incorrect[0]:
            wins += 1.0
        elif correct[0] == incorrect[0]:
            wins += 0.5
    return metric_result(round(wins / len(comparable), 6), len(comparable))


def safe_accuracy(outcomes):
    observed = [outcome for outcome in outcomes if outcome.get("status") == "observed"]
    if not observed:
        return {"value": None, "sample_count": 0, "unobserved_count": len(outcomes), "status": "no_eligible_samples"}
    return {
        "value": round(sum(1 for row in observed if row.get("correct")) / len(observed), 4),
        "sample_count": len(observed),
        "unobserved_count": len(outcomes) - len(observed),
        "status": "ok",
    }


def repair_performance(repair_state, history):
    rows = list((repair_state or {}).values())
    triggered = len(rows)
    contrast = sum(1 for row in rows if row.get("stage") in {"contrast", "transfer", "spaced_retrieval"})
    transfer = sum(
        1 for row in rows if row.get("scheduled_transfer_qnums") or row.get("stage") in {"transfer", "spaced_retrieval"}
    )
    spaced = sum(1 for row in rows if row.get("spaced_retrieval_due") or row.get("stage") == "spaced_retrieval")
    resolved = [row for row in rows if row.get("status") == "resolved"]
    blocked = [row for row in rows if row.get("status") == "blocked"]
    relapse = 0
    for row in resolved:
        key = str(row.get("concept_key") or "")
        last_qnum = int(row.get("last_question_number") or 0)
        for event in history:
            event_repair_key = str(event.get("repair_concept_key") or "").strip()
            if event.get("correct") is False and (
                (key and (concept_key_for_event(event) == key or event_repair_key == key))
                or (last_qnum and int(event.get("question_number") or 0) == last_qnum)
            ):
                relapse += 1
                break
    return {
        "repairs_triggered": triggered,
        "contrast_scheduled": contrast,
        "contrast_success": sum(
            1 for event in history if event.get("repair_stage") == "contrast" and event.get("correct")
        ),
        "transfer_scheduled": transfer,
        "transfer_success": sum(
            1 for event in history if event.get("repair_stage") == "transfer" and event.get("correct")
        ),
        "spaced_retrieval_due": spaced,
        "spaced_retrieval_observed": sum(1 for event in history if event.get("repair_stage") == "spaced_retrieval"),
        "spaced_retrieval_success": sum(
            1 for event in history if event.get("repair_stage") == "spaced_retrieval" and event.get("correct")
        ),
        "provisional_rate": round(sum(1 for row in rows if row.get("status") == "provisional") / max(1, triggered), 4),
        "resolved_rate": round(len(resolved) / max(1, triggered), 4),
        "blocked_rate": round(len(blocked) / max(1, triggered), 4),
        "relapse_rate": round(relapse / max(1, len(resolved)), 4),
    }


def weakness_precision(predictions, links, history):
    weak = [p for p in predictions if p.get("smart_primary_role") == "weak_repair"]
    immediate = [(links.get(p["prediction_id"]) or {}).get("immediate_item_outcome", {}) for p in weak]
    delayed = [(links.get(p["prediction_id"]) or {}).get("delayed_24h_concept_outcome", {}) for p in weak]
    stable_success: Counter[int] = Counter()
    for event in history:
        if event.get("correct") and str(event.get("confidence") or "") == "Sure":
            stable_success[int(event.get("question_number") or 0)] += 1
    return {
        "weak_role_immediate_error_rate": (
            None
            if not immediate
            else round(
                sum(1 for row in immediate if row.get("status") == "observed" and not row.get("correct"))
                / max(1, sum(1 for row in immediate if row.get("status") == "observed")),
                4,
            )
        ),
        "weak_role_delayed_error_rate": (
            None
            if not delayed
            else round(
                sum(1 for row in delayed if row.get("status") == "observed" and not row.get("correct"))
                / max(1, sum(1 for row in delayed if row.get("status") == "observed")),
                4,
            )
        ),
        "weak_role_high_confidence_error_rate": round(
            sum(
                1
                for event in history
                if event.get("smart_primary_role") == "weak_repair"
                and not event.get("correct")
                and event.get("confidence") == "Sure"
            )
            / max(1, sum(1 for event in history if event.get("smart_primary_role") == "weak_repair")),
            4,
        ),
        "weak_role_recovery_rate": round(
            sum(1 for row in delayed if row.get("status") == "observed" and row.get("correct"))
            / max(1, sum(1 for row in delayed if row.get("status") == "observed")),
            4,
        ),
        "false_weakness_candidates": sorted(qnum for qnum, count in stable_success.items() if count >= 2),
    }


def role_performance(predictions, links, history):
    result = {}
    for role in ROLES:
        role_predictions = [p for p in predictions if p.get("smart_primary_role") == role]
        immediate = [(links.get(p["prediction_id"]) or {}).get("immediate_item_outcome", {}) for p in role_predictions]
        h24 = [(links.get(p["prediction_id"]) or {}).get("delayed_24h_concept_outcome", {}) for p in role_predictions]
        d7 = [(links.get(p["prediction_id"]) or {}).get("delayed_7d_concept_outcome", {}) for p in role_predictions]
        times = [
            float(e.get("effective_response_seconds", e.get("response_seconds", 0.0)) or 0.0)
            for e in history
            if e.get("smart_primary_role") == role
        ]
        result[role] = {
            "selection_count": len(role_predictions),
            "immediate_accuracy": safe_accuracy(immediate),
            "24h_accuracy": safe_accuracy(h24),
            "7d_accuracy": safe_accuracy(d7),
            "mean_effective_response_seconds": round(sum(times) / len(times), 2) if times else None,
            "mean_predicted_recall": (
                round(
                    sum(float(p.get("predicted_recall_probability", 0.0)) for p in role_predictions)
                    / len(role_predictions),
                    4,
                )
                if role_predictions
                else None
            ),
            "calibration_gap": None,
            "mean_learning_gain": (
                round(
                    sum(float(p.get("predicted_learning_gain", 0.0)) for p in role_predictions) / len(role_predictions),
                    4,
                )
                if role_predictions
                else None
            ),
            "repeat_rate": round(
                (len(role_predictions) - len({p.get("question_number") for p in role_predictions}))
                / max(1, len(role_predictions)),
                4,
            ),
        }
    return result


def session_composition(predictions, requested_count=None):
    actual = Counter(str(p.get("smart_primary_role") or "") for p in predictions)
    requested = smart_practice_role_allocation(requested_count or len(predictions))
    qnums = [p.get("question_number") for p in predictions]
    concepts = [p.get("concept_key") for p in predictions]
    sources = [p.get("source_label") or p.get("source_name") or "missing" for p in predictions]
    domains = [p.get("domain") or "Unsorted" for p in predictions]
    return {
        "requested_role_counts": requested,
        "actual_role_counts": dict(actual),
        "role_deviation": {role: int(actual.get(role, 0)) - int(requested.get(role, 0)) for role in requested},
        "weak_due_floor_preserved": actual.get("weak_repair", 0) + actual.get("due_retention", 0)
        >= min(len(predictions), requested.get("weak_repair", 0) + requested.get("due_retention", 0)),
        "duplicate_question_rate": round((len(qnums) - len(set(qnums))) / max(1, len(qnums)), 4),
        "same_concept_clustering_rate": round(max(Counter(concepts).values() or [0]) / max(1, len(concepts)), 4),
        "same_source_concentration": round(max(Counter(sources).values() or [0]) / max(1, len(sources)), 4),
        "same_domain_concentration": round(max(Counter(domains).values() or [0]) / max(1, len(domains)), 4),
        "unseen_share": round(
            sum(1 for p in predictions if p.get("smart_primary_role") == "blueprint_coverage")
            / max(1, len(predictions)),
            4,
        ),
        "repair_share": round(
            sum(1 for p in predictions if p.get("smart_primary_role") == "weak_repair") / max(1, len(predictions)), 4
        ),
    }


def source_band(event):
    label = str(event.get("source_trust_label") or event.get("source_trust") or "").casefold()
    score = event.get("source_trust_score")
    if "decayed" in label or "conflict" in label:
        return "decayed_or_conflicted"
    if score is None:
        return "missing_trust"
    score = float(score)
    if score >= 85:
        return "high_trust"
    if score >= 65:
        return "medium_trust"
    return "low_trust"


def source_performance(history):
    buckets: dict[str, list[Mapping[str, Any]]] = {
        band: [] for band in ("high_trust", "medium_trust", "low_trust", "missing_trust", "decayed_or_conflicted")
    }
    for event in history:
        buckets[source_band(event)].append(event)
    return {
        band: {
            "sample_count": len(rows),
            "accuracy": None if not rows else round(sum(1 for row in rows if row.get("correct")) / len(rows), 4),
        }
        for band, rows in buckets.items()
    }


def timing_quality(history):
    raw = [float(e.get("raw_response_seconds", 0.0) or 0.0) for e in history]
    effective = [float(e.get("effective_response_seconds", e.get("response_seconds", 0.0)) or 0.0) for e in history]
    contaminated = sum(1 for e in history if e.get("response_time_contaminated"))
    sorted_effective = sorted(value for value in effective if value > 0)
    median = sorted_effective[len(sorted_effective) // 2] if sorted_effective else None
    return {
        "raw_time_contamination_rate": round(contaminated / max(1, len(history)), 4),
        "effective_time_cap_rate": round(
            sum(1 for r, e in zip(raw, effective, strict=False) if r > e) / max(1, len(history)),
            4,
        ),
        "median_effective_response_seconds": median,
        "role_adjusted_response_time": {},
        "confidence_adjusted_response_time": {},
    }


def baseline_comparison(predictions, links):
    observed = sum(
        1
        for p in predictions
        if (links.get(p.get("prediction_id")) or {}).get("immediate_item_outcome", {}).get("status") == "observed"
    )
    coverage = round(observed / max(1, len(predictions)), 4)
    base = {
        "eligible_decisions": len(predictions),
        "estimated_immediate_accuracy": (
            "not_available"
            if not observed
            else safe_accuracy(
                [(links.get(p.get("prediction_id")) or {}).get("immediate_item_outcome", {}) for p in predictions]
            )["value"]
        ),
        "estimated_24h_recall": "not_available",
        "estimated_7d_recall": "not_available",
        "estimated_learning_gain": "not_available",
        "weakness_repair_coverage": "not_available",
        "blueprint_coverage": "not_available",
        "repetition_cost": "not_available",
        "source_risk": "not_available",
        "counterfactual_coverage_rate": coverage,
        "comparison_type": "retrospective_shadow_comparison",
    }
    return {
        name: dict(base) for name in ("smart_practice", "random_blueprint", "due_only", "weakest_only", "coverage_only")
    }


def calibration_recommendations(calibration):
    sample_count = int(calibration.get("brier", {}).get("sample_count") or 0)
    ece = calibration.get("expected_calibration_error", {}).get("value")
    if sample_count < 50:
        return [
            {
                "target": "recall_probability_bias",
                "current_value": 0.0,
                "recommended_value": None,
                "maximum_allowed_change": 0.05,
                "sample_count": sample_count,
                "evidence": {"expected_calibration_error": ece},
                "confidence": "low",
                "reason": "Not enough delayed outcomes for a numeric policy change.",
                "status": "insufficient_data",
            }
        ]
    offset = -0.05 if ece and ece > 0.08 else 0.0
    return [
        {
            "target": "recall_probability_bias",
            "current_value": 0.0,
            "recommended_value": offset,
            "maximum_allowed_change": 0.05,
            "sample_count": sample_count,
            "evidence": {"expected_calibration_error": ece},
            "confidence": "medium" if offset else "high",
            "reason": (
                "Predicted recall is overconfident."
                if offset
                else "Predictions are within the monitored calibration band."
            ),
            "status": "recommended" if offset else "no_change",
        }
    ]


def build_measurement_report(store, history, evaluation_at=None, requested_count=None):
    store = normalize_measurement_store(store)
    evaluation_at = evaluation_at or now_iso()
    predictions = sorted(
        store["predictions"].values(),
        key=lambda p: (
            str(p.get("prediction_created_at") or ""),
            int(p.get("question_number") or 0),
            str(p.get("prediction_id") or ""),
        ),
    )
    links = {}
    invalid = 0
    for prediction in predictions:
        if parse_timestamp(prediction.get("prediction_created_at")) is None:
            invalid += 1
            continue
        links[prediction["prediction_id"]] = link_prediction_outcomes(prediction, history)
    pairs = observed_pairs(predictions, links, "delayed_24h_concept_outcome")
    bins, ece = calibration_bins(pairs)
    calibration = {
        "brier": brier_score(pairs),
        "log_loss": log_loss(pairs),
        "bins": bins,
        "expected_calibration_error": ece,
        "pairwise_discrimination": pairwise_discrimination(pairs),
    }
    recommendations = calibration_recommendations(calibration)
    unobserved = sum(1 for link in links.values() if link["delayed_24h_concept_outcome"].get("status") != "observed")
    report = {
        "report_id": stable_id(evaluation_at, len(predictions), len(history), SMART_PRACTICE_POLICY_VERSION),
        "generated_at": evaluation_at,
        "policy_version": SMART_PRACTICE_POLICY_VERSION,
        "evaluation_start": str(predictions[0].get("prediction_created_at")) if predictions else "",
        "evaluation_end": evaluation_at,
        "prediction_count": len(predictions),
        "eligible_outcome_count": len(pairs),
        "data_quality": {
            "missing_prediction_count": sum(1 for event in history if not event.get("prediction_id")),
            "unmatched_answer_count": sum(
                1
                for event in history
                if event.get("prediction_id") and event.get("prediction_id") not in store["predictions"]
            ),
            "invalid_timestamp_count": invalid
            + sum(1 for event in history if parse_timestamp(event.get("at")) is None),
            "contaminated_response_count": sum(1 for event in history if event.get("response_time_contaminated")),
            "insufficient_window_count": unobserved,
            "duplicate_event_count": len(history) - len({event_id(event) for event in history}),
            "counterfactual_coverage_rate": round(len(pairs) / max(1, len(predictions)), 4),
        },
        "recall_calibration": calibration,
        "delayed_recall": {
            "24h_item": safe_accuracy([link["delayed_24h_item_outcome"] for link in links.values()]),
            "24h_concept": safe_accuracy([link["delayed_24h_concept_outcome"] for link in links.values()]),
            "7d_item": safe_accuracy([link["delayed_7d_item_outcome"] for link in links.values()]),
            "7d_concept": safe_accuracy([link["delayed_7d_concept_outcome"] for link in links.values()]),
        },
        "learning_gain": {
            "immediate_excluded": True,
            "transfer_evidence_count": sum(
                1
                for link in links.values()
                if link["delayed_24h_concept_outcome"].get("status") == "observed"
                and not link["delayed_24h_concept_outcome"].get("same_question")
            ),
        },
        "repair_performance": repair_performance((store.get("repair_state") or {}), history),
        "diagnosis_performance": diagnosis_measurement(normalize_graph(store.get("concept_graph") or {}), history),
        "edge_calibration": dict((store.get("question_calibration") or {}).get("edge_calibration") or {}),
        "graph_coverage": audit_graph(normalize_graph(store.get("concept_graph") or {})),
        "question_information_value": {
            "history_count": len((store.get("question_calibration") or {}).get("information_value_history") or {}),
            "mean_value": round(
                sum(
                    float(row.get("information_value", 0.0) or 0.0)
                    for row in (
                        (store.get("question_calibration") or {}).get("information_value_history") or {}
                    ).values()
                )
                / max(1, len((store.get("question_calibration") or {}).get("information_value_history") or {})),
                4,
            ),
        },
        "question_quality": quality_measurement(
            (store.get("question_calibration") or {}).get("question_quality") or {}
        ),
        "weakness_precision": weakness_precision(predictions, links, history),
        "role_performance": role_performance(predictions, links, history),
        "session_composition": session_composition(predictions, requested_count=requested_count),
        "source_performance": source_performance(history),
        "timing_quality": timing_quality(history),
        "baseline_comparison": baseline_comparison(predictions, links),
        "calibration_recommendations": recommendations,
        "limitations": [],
    }
    if len(pairs) < 20:
        report["limitations"].append("Insufficient 24-hour delayed outcomes.")
    if report["delayed_recall"]["7d_concept"]["sample_count"] < 20:
        report["limitations"].append("Insufficient 7-day outcomes.")
    if report["baseline_comparison"]["smart_practice"]["counterfactual_coverage_rate"] < 0.5:
        report["limitations"].append("Baseline comparison has low counterfactual coverage.")
    store["outcome_links"].update(links)
    existing_reports = {report.get("report_id") for report in store["measurement_reports"]}
    if report["report_id"] not in existing_reports:
        store["measurement_reports"].append(report)
        store["measurement_reports"] = store["measurement_reports"][-REPORT_LIMIT:]
    store["calibration_recommendations"] = recommendations
    store["last_evaluated_at"] = evaluation_at
    return report, store
