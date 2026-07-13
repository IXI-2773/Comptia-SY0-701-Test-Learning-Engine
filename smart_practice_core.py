from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil
from typing import Any

from progress_store import is_active_weak, is_review_due, is_super_confident_active
from smart_practice_concept_graph import GRAPH_VERSION, diagnose_root_cause
from smart_practice_profile import (
    SMART_PRACTICE_POLICY_VERSION,
    SmartPracticeScoringProfile,
    clamp_utility_component,
    smart_practice_role_allocation,
    smart_practice_utility_total,
)
from smart_practice_question_value import information_value, question_quality_record


@dataclass(frozen=True)
class SmartPracticeScoreResult:
    priority: float
    primary_role: str
    question_updates: dict[str, Any]
    question_quality: dict[str, Any]
    information_history_entry: dict[str, Any]
    diagnosis: dict[str, Any]


@dataclass(frozen=True)
class SmartPracticeCandidate:
    question: dict[str, Any]
    qnum: int
    priority: float
    selection_bonus: float
    primary_role: str
    objective_code: str
    source_label: str
    primary_topic: str
    normalized_domain: str
    raw_domain: str
    attempts: int
    is_unseen: bool
    is_active_weak: bool
    is_due: bool
    is_mastered: bool
    is_super_confident: bool
    last_seen: str
    recent_selection_pressure: float
    eligibility_tier: int
    duplicate_group_key: str


@dataclass(frozen=True)
class SmartPracticeSelectionResult:
    ordered_questions: list[dict[str, Any]]
    role_seed_questions: list[dict[str, Any]]
    quality_score: float
    retry_used: bool
    audit: dict[str, Any]


def _normalize_duplicate_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"^\s*(?:q(?:uestion)?\s*)?\d+[\s\)\]\.\-:]+", "", text, flags=re.IGNORECASE)
    text = text.casefold().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def duplicate_group_key_for_question(question: Mapping[str, Any]) -> str:
    source_record_id = str(question.get("source_record_id") or question.get("record_id") or "").strip()
    if source_record_id:
        return f"source::{source_record_id.casefold()}"
    duplicate_group_id = str(question.get("duplicate_group_id") or question.get("duplicate_group_key") or "").strip()
    if duplicate_group_id:
        return f"group::{duplicate_group_id.casefold()}"
    prompt_key = _normalize_duplicate_text(question.get("prompt") or "")
    choice_signature = tuple(
        _normalize_duplicate_text(text)
        for _letter, text in sorted((question.get("choices") or {}).items(), key=lambda item: str(item[0]))
        if _normalize_duplicate_text(text)
    )
    if prompt_key and choice_signature:
        return f"stem_choice::{prompt_key}||{'|'.join(choice_signature)}"
    if prompt_key and len(prompt_key.split()) >= 8:
        return f"stem::{prompt_key}"
    return f"qnum::{int(question.get('question_number') or 0)}"


def validate_smart_practice_selection(
    selected: list[SmartPracticeCandidate],
    candidates: list[SmartPracticeCandidate],
    *,
    target: int,
    explicit_history_filter: str,
    unseen_target: int,
) -> dict[str, Any]:
    eligible_candidates = [candidate for candidate in candidates if candidate.eligibility_tier < 90]
    eligible_qnums = {candidate.qnum for candidate in eligible_candidates}
    selected_qnums = [candidate.qnum for candidate in selected]
    duplicate_qnums = len(selected_qnums) != len(set(selected_qnums))
    duplicate_groups = [
        candidate.duplicate_group_key
        for candidate in selected
        if candidate.duplicate_group_key and not candidate.duplicate_group_key.startswith("qnum::")
    ]
    selected_mastered = [candidate for candidate in selected if candidate.is_mastered]
    available_higher_tier = [
        candidate
        for candidate in eligible_candidates
        if candidate.qnum not in set(selected_qnums) and candidate.eligibility_tier < 3
    ]
    reasons: list[str] = []
    if any(qnum not in eligible_qnums for qnum in selected_qnums):
        reasons.append("selection_outside_eligible_pool")
    if duplicate_qnums:
        reasons.append("duplicate_question_numbers")
    if len(duplicate_groups) != len(set(duplicate_groups)):
        reasons.append("duplicate_groups_present")
    if any(candidate.is_super_confident for candidate in selected):
        reasons.append("active_super_confident_selected")
    if explicit_history_filter == "Unseen" and any(not candidate.is_unseen for candidate in selected):
        reasons.append("explicit_unseen_filter_violated")
    if unseen_target > 0 and sum(1 for candidate in selected if candidate.is_unseen) < unseen_target:
        reasons.append("unseen_target_not_met")
    if len(selected) > target:
        reasons.append("selection_exceeds_requested_count")
    if selected_mastered and available_higher_tier:
        reasons.append("mastered_displaced_higher_tier_candidate")
    return {
        "valid": not reasons,
        "reasons": reasons,
    }


def _is_screenshot_import(question: Mapping[str, Any]) -> bool:
    source_label = str(question.get("source_label") or "").lower()
    return "screenshot" in source_label or bool(question.get("source_image"))


def build_smart_practice_score(
    question: Mapping[str, Any],
    *,
    qnum: int,
    meta: Mapping[str, Any],
    context: Mapping[str, Any],
) -> SmartPracticeScoreResult:
    profile: SmartPracticeScoringProfile = context["profile"]
    rec = dict(meta.get("record") or {})
    attempts = int(rec.get("attempts", 0) or 0)
    is_unseen = attempts <= 0
    source_row = (context.get("source_map") or {}).get(qnum, {"score": 0.8, "label": "Single-source only"})
    source_name_key = str(meta.get("source_name") or "Unknown source").strip()
    source_trust_map = context.get("source_trust_map") or {}
    normalized_source_trust_map = context.get("normalized_source_trust_map") or {}
    source_trust = source_trust_map.get(source_name_key)
    if source_trust is None:
        source_trust = normalized_source_trust_map.get(source_name_key.casefold())
    if source_trust is None:
        source_trust = {"trust_score": 82.0, "label": "Watch"}
    active_smart_policy = context["active_smart_policy"]
    graph_enabled = bool(context.get("graph_enabled", True))
    if graph_enabled:
        concept_graph = context.get("concept_graph") or {}
        diagnosis = diagnose_root_cause(
            dict(question),
            concept_graph,
            context.get("concept_states") or {},
            context.get("progress_history") or [],
            source_trust=source_trust,
            policy=active_smart_policy,
        )
    else:
        diagnosis = {
            "diagnosis": "insufficient_evidence",
            "confidence": 0.0,
            "target_concept_key": str(meta.get("base_concept_key") or ""),
            "supporting_concept_keys": [],
            "graph_version": GRAPH_VERSION,
        }
    graph_max_utility = float(context.get("graph_max_utility", 4.0) or 4.0)
    graph_pressure = min(graph_max_utility, graph_max_utility * float(diagnosis.get("confidence", 0.0) or 0.0))
    qnum_outcomes = (context.get("outcomes_by_qnum") or {}).get(qnum, [])
    quality_enabled = bool(context.get("quality_enabled", True))
    if quality_enabled:
        quality = question_quality_record(
            dict(question),
            qnum_outcomes,
            minimum_samples=int(context.get("quality_min_samples", 10) or 10),
            possible_bad_key_minimum_samples=int(context.get("bad_key_min_samples", 20) or 20),
        )
    else:
        quality = {"status": "healthy", "source_risk": 0.0, "confidence": 0.0}
    concept_key = str(diagnosis.get("target_concept_key") or meta.get("base_concept_key") or "")
    dependent_concepts = (context.get("dependent_concepts_by_source") or {}).get(concept_key, [])
    information_enabled = bool(context.get("information_enabled", True))
    if information_enabled:
        info = information_value(
            dict(question),
            (context.get("concept_states") or {}).get(concept_key, {}),
            {**(context.get("graph_audit") or {}), "dependent_concepts": dependent_concepts},
            context.get("session_context") or {},
            quality,
            policy=active_smart_policy,
        )
    else:
        info = {"total": 0.0, "reasons": []}
    info_max = float(context.get("info_max", 6.0) or 6.0)
    info_pressure = max(-info_max, min(info_max, float(info.get("total", 0.0) or 0.0)))
    unit_key = str(meta.get("unit_key") or "")
    gap_score = float((context.get("gap_map") or {}).get(unit_key, 0.0))
    transfer_row = (context.get("transfer_map") or {}).get(unit_key, {"score": 72.0})
    misconception_pressure = float((context.get("misconception_pressure_map") or {}).get(unit_key, 0.0))
    knowledge_row = (context.get("knowledge_trace_map") or {}).get(
        unit_key, {"mastery_prob": profile.knowledge_trace_baseline, "uncertainty": 50.0}
    )
    concept_memory_row = (context.get("concept_memory_map") or {}).get(
        unit_key, {"state": "new", "next_ramp": "recognition", "durability_signal": 0.0}
    )
    memory_state = str(concept_memory_row.get("state") or "new")
    wrong_memory_pressure = float((context.get("wrong_answer_memory_pressure_map") or {}).get(unit_key, 0.0))
    wrong_recycle_pressure = float((context.get("wrong_answer_recycling_map") or {}).get(qnum, 0.0))
    near_miss_pressure = max(
        float((context.get("near_miss_unit_map") or {}).get(unit_key, 0.0)),
        float((context.get("near_miss_question_map") or {}).get(qnum, 0.0)),
    )
    compression_row = (context.get("confidence_compression_map") or {}).get(unit_key, {"compression": 0.0})
    boundary_row = (context.get("error_boundary_map") or {}).get(unit_key, {"gap": 0.0, "weak_style": ""})
    counterfactual_pressure = float((context.get("counterfactual_pressure_map") or {}).get(unit_key, 0.0))
    objective_row = (context.get("objective_map") or {}).get(
        str(meta.get("objective_code") or ""), {"mastery_score": 72.0, "stem_style_count": 1}
    )
    objective_mastery_score = float(objective_row.get("mastery_score", 72.0))
    latent_row = (context.get("latent_map") or {}).get(qnum, {"score": 0.0})
    difficulty_row = (context.get("difficulty_map") or {}).get(qnum, {"score": 0.0, "label": "Stable"})
    phrasing_row = (context.get("phrasing_map") or {}).get(qnum, {"score": 100.0, "label": "Clean"})
    generalization_row = (context.get("generalization_map") or {}).get(
        unit_key, {"score": profile.generalization_baseline}
    )
    expected_gain_row = (context.get("expected_learning_gain_map") or {}).get(qnum, {"expected_gain": 0.0})
    retention_stress_row = (context.get("retention_stress_map") or {}).get(qnum, {"pressure": 0.0})
    freshness_penalty = float((context.get("freshness_map") or {}).get(qnum, 0.0))
    difficulty_score = float(difficulty_row.get("score", 0.0))
    phrasing_penalty = max(0.0, 82.0 - float(phrasing_row.get("score", 100.0)))
    momentum_bias = float((context.get("momentum_profile") or {}).get("difficulty_bias", 0.0))
    trust_score = max(0.0, min(100.0, float(source_trust.get("trust_score", 82.0))))
    trust_label = str(source_trust.get("label") or "Watch")
    source_label = str(source_row.get("label") or "")
    memory_due = is_review_due(rec)
    memory = dict((rec or {}).get("learner_memory") or {})
    retrievability = max(0.0, min(1.0, float(memory.get("retrievability", 0.0) or 0.0)))
    source_risk_settings = dict(context.get("source_risk_settings") or {})
    trust_risk = max(0.0, (profile.source_trust_baseline - trust_score) / profile.source_trust_baseline)
    if trust_label.casefold() == "decayed":
        trust_risk += float(source_risk_settings.get("decayed_penalty", 0.22) or 0.22)
    if source_label == "Source conflict":
        trust_risk += float(source_risk_settings.get("conflict_penalty", 0.28) or 0.28)
    if str(question.get("import_status") or "") == "screenshot_review_needed":
        trust_risk += float(source_risk_settings.get("decayed_penalty", 0.22) or 0.22)
    trust_risk = max(0.0, min(1.0, trust_risk))
    explicit_source_penalty = 0.0
    if trust_score < profile.source_trust_baseline:
        explicit_source_penalty += (profile.source_trust_baseline - trust_score) * 0.12
    if trust_label.casefold() == "decayed":
        explicit_source_penalty += 3.0
    if source_name_key.casefold() == "decayed":
        explicit_source_penalty += 3.0
    review_interval_multiplier = float(context.get("review_interval_multiplier", 1.0) or 1.0)
    retention_risk = (
        min(
            25.0,
            (18.0 if memory_due else 0.0)
            + (float(retention_stress_row.get("pressure", 0.0)) * 0.12 if attempts > 0 else 0.0)
            + (max(0.0, 1.0 - retrievability) * 8.0 if attempts > 0 else 0.0),
        )
        * review_interval_multiplier
    )
    learning_gain = min(
        20.0,
        float(expected_gain_row.get("expected_gain", 0.0)) * 0.16
        + float(knowledge_row.get("uncertainty", 0.0)) * 0.06
        + max(0.0, profile.knowledge_trace_baseline - float(knowledge_row.get("mastery_prob", 70.0))) * 0.08,
    )
    blueprint_importance = min(
        15.0,
        gap_score * 0.13
        + (5.0 if is_unseen else 0.0)
        + max(0.0, profile.objective_mastery_baseline - objective_mastery_score) * 0.08,
    )
    misconception_repair = min(
        20.0,
        (8.0 if is_active_weak(rec) else 0.0)
        + misconception_pressure * 0.08
        + wrong_memory_pressure * 0.1
        + wrong_recycle_pressure * 0.22
        + near_miss_pressure * 0.12
        + float(latent_row.get("score", 0.0)) * 0.12
        + float(compression_row.get("compression", 0.0)) * 0.06,
    )
    if diagnosis["diagnosis"] in {"missing_prerequisite", "target_concept_weakness", "concept_confusion"}:
        misconception_repair += graph_pressure
        learning_gain += graph_pressure * 0.5
    learning_gain += max(0.0, info_pressure) * 0.4
    blueprint_importance += (
        max(0.0, info.get("graph_bottleneck_value", 0.0)) * 0.2 + max(0.0, info.get("coverage_value", 0.0)) * 0.2
    )
    objective_exposure = (context.get("objective_exposure_map") or {}).get(
        str(meta.get("objective_code") or ""), {"sources": set(), "styles": set()}
    )
    exploration_settings = dict(context.get("exploration_settings") or {})
    exploration_value = min(
        10.0,
        max(0.0, profile.transfer_baseline - float(transfer_row.get("score", 72.0))) * 0.06
        + max(0.0, profile.generalization_baseline - float(generalization_row.get("score", 72.0))) * 0.05
        + (2.5 if source_label == "Cross-source agreement" else 0.0)
        + (2.0 if str(meta.get("source_name") or "") not in objective_exposure.get("sources", set()) else 0.0)
        + (2.0 if str(meta.get("stem_style") or "") not in objective_exposure.get("styles", set()) else 0.0),
    )
    novelty_bonus = 0.0
    if is_unseen:
        objective_code = str(meta.get("objective_code") or "")
        attempted_by_unit = context.get("attempted_by_unit") or {}
        attempted_by_objective = context.get("attempted_by_objective") or {}
        if attempted_by_unit.get(unit_key, 0) > 0 or (
            objective_code and attempted_by_objective.get(objective_code, 0) > 0
        ):
            novelty_bonus += 6.0
        if _is_screenshot_import(question) and context.get("imported_chapter_burst_active"):
            novelty_bonus += 6.0
        if gap_score >= profile.coverage_focus_gap_min:
            novelty_bonus += 11.0
        if objective_mastery_score < profile.objective_focus_mastery_max:
            novelty_bonus += 7.0
        if wrong_recycle_pressure >= profile.wrong_answer_recycle_focus_min:
            novelty_bonus += 12.0
        elif near_miss_pressure >= profile.near_miss_focus_min:
            novelty_bonus += 3.0
    boundary_bonus = 0.0
    if str(boundary_row.get("weak_style") or "") == str(meta.get("stem_style") or ""):
        boundary_bonus += min(8.0, float(boundary_row.get("gap", 0.0)) * 0.16)
    counterfactual_bonus = min(4.0, counterfactual_pressure * 0.12)
    exploration_value = min(10.0, exploration_value + novelty_bonus * 0.35 + boundary_bonus * 0.3)
    exploration_value += max(0.0, float(exploration_settings.get("transfer_min_value", 4.0) or 4.0) - 4.0) * 0.2
    if diagnosis["diagnosis"] == "transfer_failure":
        exploration_value += graph_pressure
        learning_gain += graph_pressure * 0.5
    exploration_value += max(0.0, info.get("transfer_evidence_value", 0.0)) * 0.2
    learning_gain = min(20.0, learning_gain + novelty_bonus * 0.2 + boundary_bonus + counterfactual_bonus)
    blueprint_importance = min(15.0, blueprint_importance + novelty_bonus * 0.25 + boundary_bonus * 0.6)
    misconception_repair = min(20.0, misconception_repair + novelty_bonus * 0.3 + boundary_bonus * 0.5)
    repetition_settings = dict(context.get("repetition_settings") or {})
    recent_concept_cooldown_map = context.get("recent_concept_cooldown_map") or {}
    repetition_cost = min(
        15.0,
        freshness_penalty * 0.18
        + int(rec.get("correct_streak", 0)) * float(repetition_settings.get("correct_streak_penalty", 1.4) or 1.4)
        + max(0, int(recent_concept_cooldown_map.get(unit_key, 0) or 0) - 1)
        * float(repetition_settings.get("recent_concept_penalty", 2.0) or 2.0),
    )
    if diagnosis["diagnosis"] == "item_specific_failure":
        repetition_cost += graph_pressure
    repetition_cost += max(0.0, info.get("redundancy_cost", 0.0)) * 0.2
    quality_risk_max = float(context.get("quality_risk_max", 4.0) or 4.0)
    source_quality_risk = min(
        15.0,
        trust_risk * 15.0
        + phrasing_penalty * 0.06
        + max(0.0, float(source_risk_settings.get("baseline", 85.0) or 85.0) - 85.0) * 0.01,
    )
    source_quality_risk = min(15.0, source_quality_risk + explicit_source_penalty)
    if diagnosis["diagnosis"] == "source_quality_problem":
        source_quality_risk += graph_pressure
    source_quality_risk += min(
        quality_risk_max, max(0.0, info.get("item_quality_risk", 0.0) + info.get("source_risk", 0.0)) * 0.2
    )
    fatigue_cost = 0.0
    burnout_risk = context.get("burnout_risk") or {}
    fatigue_settings = dict(context.get("fatigue_settings") or {})
    if burnout_risk.get("label") == "High":
        fatigue_cost += max(0.0, difficulty_score - profile.burnout_difficulty_floor) * float(
            fatigue_settings.get("high_burnout_difficulty_penalty", 0.12) or 0.12
        )
    if momentum_bias < 0:
        fatigue_cost += max(0.0, difficulty_score - profile.negative_momentum_difficulty_floor) * float(
            fatigue_settings.get("negative_momentum_penalty", 0.08) or 0.08
        )
    fatigue_cost = min(10.0, fatigue_cost)
    wrong_surplus = max(0, int(rec.get("wrong_count", 0) or 0) - int(rec.get("correct_count", 0) or 0))
    weakness_thresholds = dict(context.get("weakness_thresholds") or {})
    policy_active_weak = is_active_weak(rec) or wrong_surplus >= int(
        weakness_thresholds.get("active_weak_wrong_surplus", 1) or 1
    )
    objective_code = str(meta.get("objective_code") or "")
    unseen_by_unit = context.get("unseen_by_unit") or {}
    unseen_by_objective = context.get("unseen_by_objective") or {}
    unseen_sibling_exists = (
        unseen_by_unit.get(unit_key, 0) - (1 if is_unseen else 0) > 0
        or bool(objective_code)
        and unseen_by_objective.get(objective_code, 0) - (1 if is_unseen else 0) > 0
    )
    if unseen_sibling_exists and (policy_active_weak or str(rec.get("last_confidence") or "").casefold() == "guessed"):
        repetition_cost = min(15.0, repetition_cost + 10.0)
    if is_super_confident_active(rec) and not memory_due and not policy_active_weak:
        repetition_cost = 15.0
    repair_spacing_settings = dict(context.get("repair_spacing_settings") or {})
    repair_recent_delay = int(repair_spacing_settings.get("contrast_delay", 2) or 2)
    if (
        int(recent_concept_cooldown_map.get(unit_key, 0) or 0)
        and int(recent_concept_cooldown_map.get(unit_key, 0) or 0) < repair_recent_delay
    ):
        misconception_repair *= 0.5
    repair_trigger_settings = dict(context.get("repair_trigger_settings") or {})
    if (
        policy_active_weak
        or diagnosis["diagnosis"] in {"missing_prerequisite", "target_concept_weakness", "concept_confusion"}
        or wrong_memory_pressure >= float(repair_trigger_settings.get("wrong_memory_min_pressure", 35.0) or 35.0)
        or near_miss_pressure >= float(repair_trigger_settings.get("weak_repair_min_pressure", 20.0) or 20.0)
    ):
        primary_role = "weak_repair"
    elif memory_due or float(retention_stress_row.get("pressure", 0.0)) >= 24.0:
        primary_role = "due_retention"
    elif int(rec.get("attempts", 0)) <= 0 or gap_score >= profile.coverage_focus_gap_min:
        primary_role = "blueprint_coverage"
    elif (
        diagnosis["diagnosis"] == "transfer_failure"
        or exploration_value >= float(exploration_settings.get("transfer_min_value", 4.0) or 4.0)
        or memory_state in {"retrievable", "transferable"}
    ):
        primary_role = "transfer"
    elif burnout_risk.get("label") != "High" and not memory_due:
        primary_role = "controlled_stretch"
    else:
        primary_role = "blueprint_coverage"
    utility_scales = dict(context.get("utility_scales") or {})
    breakdown = {
        "retention_risk": clamp_utility_component(
            "retention_risk", retention_risk * float(utility_scales.get("retention_risk", 1.0))
        ),
        "expected_learning_gain": clamp_utility_component(
            "expected_learning_gain", learning_gain * float(utility_scales.get("expected_learning_gain", 1.0))
        ),
        "blueprint_importance": clamp_utility_component(
            "blueprint_importance", blueprint_importance * float(utility_scales.get("blueprint_importance", 1.0))
        ),
        "misconception_repair_value": clamp_utility_component(
            "misconception_repair_value",
            misconception_repair * float(utility_scales.get("misconception_repair_value", 1.0)),
        ),
        "exploration_value": clamp_utility_component(
            "exploration_value", exploration_value * float(utility_scales.get("exploration_value", 1.0))
        ),
        "repetition_cost": clamp_utility_component(
            "repetition_cost", repetition_cost * float(utility_scales.get("repetition_cost", 1.0))
        ),
        "source_quality_risk": clamp_utility_component(
            "source_quality_risk", source_quality_risk * float(utility_scales.get("source_quality_risk", 1.0))
        ),
        "fatigue_cost": clamp_utility_component(
            "fatigue_cost", fatigue_cost * float(utility_scales.get("fatigue_cost", 1.0))
        ),
    }
    breakdown["source_quality_risk"] = clamp_utility_component(
        "source_quality_risk",
        max(
            float(breakdown.get("source_quality_risk", 0.0) or 0.0),
            explicit_source_penalty * float(utility_scales.get("source_quality_risk", 1.0)),
        ),
    )
    total = smart_practice_utility_total(breakdown)
    positive_reasons = [
        ("retention", retention_risk),
        ("learning gain", learning_gain),
        ("coverage", blueprint_importance),
        ("repair", misconception_repair),
        ("transfer", exploration_value),
    ]
    cost_reasons = [
        ("recent repetition", repetition_cost),
        ("source risk", source_quality_risk),
        ("fatigue guard", fatigue_cost),
    ]
    reasons = [label for label, value in sorted(positive_reasons, key=lambda row: row[1], reverse=True) if value > 1.0][
        :2
    ]
    reasons.extend(
        f"penalty: {label}"
        for label, value in sorted(cost_reasons, key=lambda row: row[1], reverse=True)
        if value > 2.0
    )
    prediction_calibration = dict(context.get("prediction_calibration") or {})
    active_policy_values = dict(context.get("active_policy_values") or {})
    runtime_policy_controls = {
        "role_shares": dict(context.get("role_shares") or {}),
        "utility_component_scales": utility_scales,
        "utility_component_bounds": dict(context.get("utility_bounds") or {}),
        "source_risk_settings": source_risk_settings,
        "fatigue_settings": fatigue_settings,
        "review_interval_multiplier": review_interval_multiplier,
        "repair_trigger_settings": repair_trigger_settings,
        "repair_spacing_settings": repair_spacing_settings,
        "weakness_thresholds": weakness_thresholds,
        "prediction_calibration": prediction_calibration,
        "exploration_settings": exploration_settings,
        "repetition_settings": repetition_settings,
        "minimum_evidence_thresholds": dict(active_policy_values.get("minimum_evidence_thresholds") or {}),
    }
    question_updates = {
        "smart_primary_role": primary_role,
        "smart_selection_reasons": reasons[:3],
        "smart_utility": round(total, 3),
        "smart_utility_breakdown": breakdown,
        "smart_policy_version": SMART_PRACTICE_POLICY_VERSION,
        "smart_policy_id": str(active_smart_policy.get("policy_id") or ""),
        "smart_concept_key": str(diagnosis.get("target_concept_key") or ""),
        "smart_root_cause": str(diagnosis.get("diagnosis") or ""),
        "smart_root_cause_confidence": float(diagnosis.get("confidence", 0.0) or 0.0),
        "smart_supporting_concepts": [str(value) for value in diagnosis.get("supporting_concept_keys", [])],
        "smart_graph_version": str(diagnosis.get("graph_version") or GRAPH_VERSION),
        "smart_information_value": round(float(info.get("total", 0.0) or 0.0), 4),
        "smart_information_breakdown": dict(info),
        "smart_question_quality_status": str(quality.get("status") or "insufficient_data"),
        "smart_question_quality_confidence": float(quality.get("confidence", 0.0) or 0.0),
        "smart_graph_bottleneck": float(info.get("graph_bottleneck_value", 0.0) or 0.0),
        "smart_prediction_offset": float(prediction_calibration.get("recall_probability_offset", 0.0) or 0.0),
        "smart_runtime_policy_controls": runtime_policy_controls,
    }
    info_id = f"{qnum}:{active_smart_policy.get('policy_id', '')}"
    information_history_entry = {
        "record_id": info_id,
        "question_number": qnum,
        "smart_policy_id": str(active_smart_policy.get("policy_id") or ""),
        "information_value": question_updates["smart_information_value"],
        "breakdown": dict(info),
    }
    return SmartPracticeScoreResult(
        priority=round(total, 3),
        primary_role=primary_role,
        question_updates=question_updates,
        question_quality=quality,
        information_history_entry=information_history_entry,
        diagnosis=diagnosis,
    )


def build_smart_practice_selection(
    working_candidates: list[SmartPracticeCandidate],
    fallback_candidates: list[SmartPracticeCandidate],
    *,
    target: int,
    role_shares: Mapping[str, float],
    objective_cap: int,
    profile: SmartPracticeScoringProfile,
    high_signal_qnums: set[int],
    freshness_map: Mapping[int, float],
    explicit_history_filter: str,
    session_intent: Mapping[str, Any] | None,
) -> SmartPracticeSelectionResult:
    allocations = smart_practice_role_allocation(target, role_shares=dict(role_shares))
    intent_label = str((session_intent or {}).get("label") or "Build coverage")

    def unique_candidates(*groups: list[SmartPracticeCandidate]) -> list[SmartPracticeCandidate]:
        unique: list[SmartPracticeCandidate] = []
        used_qnums: set[int] = set()
        for group in groups:
            for candidate in group:
                if candidate.qnum in used_qnums:
                    continue
                used_qnums.add(candidate.qnum)
                unique.append(candidate)
        return unique

    def candidate_value(candidate: SmartPracticeCandidate) -> float:
        return candidate.priority + candidate.selection_bonus - candidate.recent_selection_pressure

    def candidate_rank(candidate: SmartPracticeCandidate) -> tuple[float, int]:
        return (-candidate_value(candidate), candidate.qnum)

    def is_non_mastered_attempt(candidate: SmartPracticeCandidate) -> bool:
        return candidate.attempts > 0 and not candidate.is_mastered

    excluded_super_confident = sum(1 for candidate in working_candidates if candidate.is_super_confident)
    eligible_working = sorted(
        [candidate for candidate in unique_candidates(working_candidates) if candidate.eligibility_tier < 90],
        key=candidate_rank,
    )
    selected: list[SmartPracticeCandidate] = []
    selected_qnums: set[int] = set()
    selected_duplicate_groups: set[str] = set()
    objective_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    max_source = max(1, int(target * profile.variety_source_label_cap_ratio + 0.999))

    def can_add(candidate: SmartPracticeCandidate, *, strict_source: bool, strict_objective: bool) -> bool:
        if candidate.qnum in selected_qnums or len(selected) >= target:
            return False
        if (
            strict_objective
            and candidate.objective_code
            and objective_counts.get(candidate.objective_code, 0) >= objective_cap
        ):
            return False
        if candidate.duplicate_group_key and candidate.duplicate_group_key in selected_duplicate_groups:
            return False
        if strict_source and source_counts.get(candidate.source_label, 0) >= max_source:
            return False
        return True

    def add_candidate(candidate: SmartPracticeCandidate, *, strict_source: bool, strict_objective: bool) -> bool:
        if not can_add(candidate, strict_source=strict_source, strict_objective=strict_objective):
            return False
        selected.append(candidate)
        selected_qnums.add(candidate.qnum)
        if candidate.duplicate_group_key:
            selected_duplicate_groups.add(candidate.duplicate_group_key)
        if candidate.objective_code:
            objective_counts[candidate.objective_code] = objective_counts.get(candidate.objective_code, 0) + 1
        source_counts[candidate.source_label] = source_counts.get(candidate.source_label, 0) + 1
        return True

    def fill_from_pool(pool: list[SmartPracticeCandidate], *, limit: int | None = None) -> None:
        for strict_source, strict_objective in ((True, True), (False, True), (False, False)):
            for candidate in pool:
                if limit is not None and len(selected) >= limit:
                    return
                add_candidate(candidate, strict_source=strict_source, strict_objective=strict_objective)

    available_unseen = sum(1 for candidate in eligible_working if candidate.is_unseen)
    if explicit_history_filter == "Unseen":
        unseen_target = min(target, available_unseen)
    elif explicit_history_filter != "All":
        unseen_target = 0
    else:
        unseen_ratio = profile.minimum_unseen_ratio
        if intent_label == "Build coverage":
            unseen_ratio = max(unseen_ratio, profile.build_coverage_unseen_ratio)
        unseen_target = min(target, available_unseen, int(ceil(target * unseen_ratio)))

    unseen_candidates = sorted(
        [candidate for candidate in eligible_working if candidate.is_unseen],
        key=candidate_rank,
    )
    fill_from_pool(unseen_candidates, limit=unseen_target)

    def fill_priority(candidate: SmartPracticeCandidate) -> tuple[int, int, float, int]:
        if explicit_history_filter == "Unseen":
            bucket = 0 if candidate.is_unseen else 9
        elif intent_label == "Retain old material":
            if candidate.is_due:
                bucket = 0
            elif candidate.is_active_weak:
                bucket = 1
            elif is_non_mastered_attempt(candidate):
                bucket = 2
            elif candidate.primary_role == "transfer":
                bucket = 3
            elif candidate.is_unseen:
                bucket = 4
            else:
                bucket = 5
        elif intent_label == "Repair weak spots":
            if candidate.is_active_weak:
                bucket = 0
            elif candidate.is_due:
                bucket = 1
            elif is_non_mastered_attempt(candidate):
                bucket = 2
            elif candidate.primary_role == "transfer":
                bucket = 3
            elif candidate.is_unseen:
                bucket = 4
            else:
                bucket = 5
        else:
            if candidate.is_active_weak:
                bucket = 0
            elif candidate.is_due:
                bucket = 1
            elif is_non_mastered_attempt(candidate):
                bucket = 2
            elif candidate.primary_role == "transfer":
                bucket = 3
            elif candidate.is_unseen:
                bucket = 4
            else:
                bucket = 5
        return (candidate.eligibility_tier, bucket, -candidate_value(candidate), candidate.qnum)

    remaining_candidates = sorted(
        [candidate for candidate in eligible_working if candidate.qnum not in selected_qnums],
        key=fill_priority,
    )
    fill_from_pool(remaining_candidates, limit=target)

    def final_order_key(candidate: SmartPracticeCandidate) -> tuple[float, float, int]:
        return (
            -float(candidate.question.get("smart_utility", 0.0) or 0.0),
            -candidate_value(candidate),
            candidate.qnum,
        )

    ordered = sorted(selected[:target], key=final_order_key)
    validation = validate_smart_practice_selection(
        ordered,
        eligible_working,
        target=target,
        explicit_history_filter=explicit_history_filter,
        unseen_target=unseen_target,
    )
    all_candidates = unique_candidates(ordered, fallback_candidates, working_candidates)

    def set_quality(selection: list[SmartPracticeCandidate]) -> float:
        if not selection:
            return 0.0
        selected_qnums_local = {candidate.qnum for candidate in selection}
        topics = {candidate.primary_topic for candidate in selection if candidate.primary_topic}
        domains = {candidate.raw_domain for candidate in selection if candidate.raw_domain}
        source_counts_local: dict[str, int] = {}
        for candidate in selection:
            source_counts_local[candidate.source_label] = source_counts_local.get(candidate.source_label, 0) + 1
        max_source_count = max(source_counts_local.values()) if source_counts_local else 0
        available_sources = {candidate.source_label for candidate in all_candidates}
        desired_high_signal = min(len(high_signal_qnums), max(1, round(target * 0.25))) if high_signal_qnums else 0
        high_signal_hits = len(selected_qnums_local & high_signal_qnums)
        freshness_average = sum(float(freshness_map.get(qnum, 0.0)) for qnum in selected_qnums_local) / max(
            1, len(selected_qnums_local)
        )
        fresh_question_target = round(target * profile.fresh_question_target_ratio)
        fresh_question_hits = sum(
            1
            for qnum in selected_qnums_local
            if float(freshness_map.get(qnum, 0.0)) < profile.freshness_suppression_min or qnum in high_signal_qnums
        )
        desired_topics = min(profile.variety_min_topics, target)
        desired_domains = min(profile.variety_min_domains, target)
        score = 100.0
        score -= max(0, target - len(selected_qnums_local)) * 8.0
        if desired_high_signal:
            score -= max(0, desired_high_signal - high_signal_hits) * 10.0
        score -= max(0, fresh_question_target - fresh_question_hits) * profile.fresh_question_quality_penalty
        score -= max(0, desired_topics - len(topics)) * 4.0
        score -= max(0, desired_domains - len(domains)) * 6.0
        if len(available_sources) > 1 and max_source_count > max_source:
            score -= (max_source_count - max_source) * 5.0
        score -= min(18.0, freshness_average * 0.15)
        return round(max(0.0, min(100.0, score)), 2)

    primary_quality = set_quality(ordered)
    selected_unseen = sum(1 for candidate in ordered if candidate.is_unseen)
    selected_active_weak = sum(1 for candidate in ordered if candidate.is_active_weak)
    selected_due = sum(1 for candidate in ordered if candidate.is_due)
    selected_attempted_non_mastered = sum(1 for candidate in ordered if is_non_mastered_attempt(candidate))
    selected_mastered = sum(1 for candidate in ordered if candidate.is_mastered)
    duplicate_groups_excluded = sum(
        1
        for candidate in eligible_working
        if candidate.qnum not in selected_qnums
        and candidate.duplicate_group_key in selected_duplicate_groups
        and not candidate.duplicate_group_key.startswith("qnum::")
    )
    undersized_reason = ""
    if len(ordered) < target:
        if explicit_history_filter == "Unseen":
            undersized_reason = "unseen_filter_exhausted"
        elif excluded_super_confident and not ordered:
            undersized_reason = "only_super_confident_candidates_excluded"
        else:
            undersized_reason = "insufficient_eligible_candidates"
    audit = {
        "requested_count": int(target),
        "final_count": len(ordered),
        "candidate_count": len(eligible_working),
        "explicit_history_filter": str(explicit_history_filter or "All"),
        "session_intent": intent_label,
        "available_unseen": available_unseen,
        "selected_unseen": selected_unseen,
        "selected_active_weak": selected_active_weak,
        "selected_due": selected_due,
        "selected_attempted_non_mastered": selected_attempted_non_mastered,
        "selected_mastered": selected_mastered,
        "selected_super_confident": 0,
        "unseen_target": unseen_target,
        "unseen_target_met": selected_unseen >= unseen_target,
        "excluded_super_confident": excluded_super_confident,
        "excluded_recent_repetition": 0,
        "duplicate_groups_excluded": duplicate_groups_excluded,
        "cache_hit": False,
        "resumed_saved_set": False,
        "undersized_reason": undersized_reason,
        "post_selection_validation_passed": validation["valid"],
        "post_selection_validation_reasons": list(validation["reasons"]),
        "role_allocations": allocations,
    }
    return SmartPracticeSelectionResult(
        ordered_questions=[candidate.question for candidate in ordered[:target]],
        role_seed_questions=[candidate.question for candidate in ordered[:target]],
        quality_score=primary_quality,
        retry_used=False,
        audit=audit,
    )
