from dataclasses import dataclass

SMART_PRACTICE_POLICY_VERSION = "smart-practice-9"
SMART_PRACTICE_PRIMARY_ROLES = (
    "due_retention",
    "weak_repair",
    "blueprint_coverage",
    "transfer",
    "controlled_stretch",
)
UTILITY_COMPONENT_BOUNDS = {
    "retention_risk": (0.0, 25.0),
    "expected_learning_gain": (0.0, 20.0),
    "blueprint_importance": (0.0, 15.0),
    "misconception_repair_value": (0.0, 20.0),
    "exploration_value": (0.0, 10.0),
    "repetition_cost": (0.0, 15.0),
    "source_quality_risk": (0.0, 15.0),
    "fatigue_cost": (0.0, 10.0),
}


def clamp_utility_component(name: str, value: float) -> float:
    low, high = UTILITY_COMPONENT_BOUNDS[name]
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if number != number:
        number = low
    return round(max(low, min(high, number)), 3)


def smart_practice_utility_total(components: dict[str, float]) -> float:
    clean = {name: clamp_utility_component(name, components.get(name, 0.0)) for name in UTILITY_COMPONENT_BOUNDS}
    total = (
        clean["retention_risk"]
        + clean["expected_learning_gain"]
        + clean["blueprint_importance"]
        + clean["misconception_repair_value"]
        + clean["exploration_value"]
        - clean["repetition_cost"]
        - clean["source_quality_risk"]
        - clean["fatigue_cost"]
    )
    return round(total, 3)


@dataclass(frozen=True)
class SmartPracticeScoringProfile:
    gap_weight: float = 0.45
    source_score_weight: float = 12.0
    source_trust_baseline: float = 85.0
    source_trust_penalty_weight: float = 0.16
    transfer_baseline: float = 72.0
    transfer_weight: float = 0.18
    compression_weight: float = 0.2
    ladder_baseline: float = 74.0
    ladder_weight: float = 0.16
    ladder_missing_rung_bonus: float = 2.6
    boundary_weight: float = 0.12
    boundary_style_bonus: float = 4.0
    counterfactual_weight: float = 0.14
    prerequisite_debt_weight: float = 0.16
    blind_spot_weight: float = 0.12
    robustness_baseline: float = 72.0
    robustness_weight: float = 0.16
    leverage_weight: float = 0.06
    misconception_weight: float = 0.1
    half_life_target_days: float = 6.0
    half_life_weight: float = 0.22
    effort_efficiency_baseline: float = 76.0
    effort_efficiency_weight: float = 0.1
    reinforcement_priority_weight: float = 0.1
    synthesis_weight: float = 0.08
    knowledge_trace_baseline: float = 70.0
    knowledge_trace_weight: float = 0.16
    knowledge_uncertainty_weight: float = 0.18
    learning_gain_weight: float = 0.16
    delayed_probe_weight: float = 0.08
    counterexample_weight: float = 0.1
    recognition_gap_weight: float = 0.12
    cue_dependence_weight: float = 0.08
    retention_stress_weight: float = 0.08
    failure_mode_weight: float = 0.08
    decision_latency_weight: float = 0.06
    contrast_rule_weight: float = 0.08
    concept_state_weight: float = 0.1
    concept_memory_weight: float = 0.16
    wrong_answer_memory_weight: float = 0.14
    wrong_answer_recycle_weight: float = 0.18
    wrong_answer_recycle_example_penalty: float = 9.0
    wrong_answer_recycle_focus_min: float = 20.0
    near_miss_focus_min: float = 20.0
    near_miss_weight: float = 0.16
    intent_coverage_weight: float = 0.12
    intent_repair_weight: float = 0.16
    intent_retention_weight: float = 0.14
    intent_readiness_weight: float = 0.08
    durable_memory_penalty: float = 4.0
    generalization_baseline: float = 72.0
    generalization_weight: float = 0.12
    objective_mastery_baseline: float = 76.0
    objective_mastery_weight: float = 0.24
    objective_stem_bonus: float = 2.8
    objective_new_source_bonus: float = 6.0
    objective_new_style_bonus: float = 8.0
    latent_weight: float = 0.32
    interference_weight: float = 0.14
    difficulty_weight_positive: float = 0.10
    difficulty_weight_negative: float = 0.04
    source_agreement_bonus: float = 4.0
    source_supported_bonus: float = 2.0
    source_conflict_penalty: float = 4.0
    source_decayed_penalty: float = 3.0
    noisy_phrasing_penalty: float = 5.0
    phrasing_baseline: float = 82.0
    phrasing_penalty_weight: float = 0.12
    freshness_penalty_weight: float = 1.35
    screenshot_source_priority_bonus: float = 10.0
    screenshot_unseen_priority_bonus: float = 6.0
    imported_chapter_burst_unseen_min_ratio: float = 0.45
    imported_chapter_burst_quota_ratio: float = 0.48
    imported_chapter_burst_bonus: float = 8.0
    recent_concept_cooldown_window: int = 8
    recent_concept_cooldown_min_count: int = 2
    recent_concept_cooldown_penalty: float = 7.0
    negative_momentum_difficulty_floor: float = 55.0
    negative_momentum_difficulty_weight: float = 0.18
    positive_momentum_difficulty_floor: float = 45.0
    positive_momentum_difficulty_weight: float = 0.08
    burnout_difficulty_floor: float = 40.0
    burnout_difficulty_weight: float = 0.2
    active_weak_bonus: float = 8.0
    due_bonus: float = 5.0
    unseen_bonus: float = 3.0
    correct_streak_penalty: float = 0.9
    coverage_focus_gap_min: float = 45.0
    objective_focus_mastery_max: float = 68.0
    objective_focus_stem_count_max: int = 1
    interference_focus_min: float = 20.0
    compression_focus_min: float = 24.0
    ladder_focus_score_max: float = 66.0
    boundary_focus_gap_min: float = 12.0
    counterfactual_focus_min: float = 22.0
    prerequisite_focus_min: float = 46.0
    blind_spot_focus_min: float = 50.0
    robustness_focus_max: float = 60.0
    reinforcement_focus_min: float = 64.0
    synthesis_focus_min: float = 54.0
    knowledge_trace_focus_max: float = 62.0
    uncertainty_focus_min: float = 52.0
    learning_gain_focus_min: float = 56.0
    delayed_probe_focus_min: float = 24.0
    cue_dependence_focus_min: float = 40.0
    recognition_gap_focus_min: float = 16.0
    retention_stress_focus_min: float = 24.0
    failure_mode_focus_min: float = 28.0
    generalization_focus_max: float = 60.0
    decision_latency_focus_min: float = 7.0
    contrast_rule_focus_min: float = 22.0
    concept_state_focus_states: tuple[str, ...] = ("unknown", "fragile", "recognizable", "retrievable")
    freshness_suppression_min: float = 12.0
    screenshot_focus_ratio: float = 0.34
    interleave_source_label_bonus: float = 3.5
    interleave_recent_source_penalty: float = 2.5
    interleave_recent_topic_penalty: float = 1.5
    variety_min_topics: int = 4
    variety_min_domains: int = 2
    variety_source_label_cap_ratio: float = 0.35
    variety_min_target_size: int = 10
    variety_pinned_ratio: float = 0.2
    variety_pinned_min: int = 3
    minimum_unseen_ratio: float = 0.7
    build_coverage_unseen_ratio: float = 0.8
    fresh_question_target_ratio: float = 0.7
    fresh_question_quality_penalty: float = 3.0
    recent_selection_rotation_penalty: float = 4.0
    set_quality_retry_threshold: float = 82.0
    set_quality_retry_margin: float = 2.0
    advanced_focus_ratio: float = 0.12
    objective_focus_ratio: float = 0.16
    objective_cap_ratio: float = 0.2
    objective_cap_min: int = 2


SMART_PRACTICE_SCORING = SmartPracticeScoringProfile()


def smart_practice_objective_cap(target: int, profile: SmartPracticeScoringProfile = SMART_PRACTICE_SCORING) -> int:
    return max(profile.objective_cap_min, round(max(0, int(target)) * profile.objective_cap_ratio))


def smart_practice_role_allocation(target: int, role_shares: dict[str, float] | None = None) -> dict[str, int]:
    target = max(0, int(target or 0))
    ratios = dict(
        role_shares
        or {
            "due_retention": 0.25,
            "weak_repair": 0.25,
            "blueprint_coverage": 0.25,
            "transfer": 0.15,
            "controlled_stretch": 0.10,
        }
    )
    total = sum(float(ratios.get(role, 0.0) or 0.0) for role in SMART_PRACTICE_PRIMARY_ROLES) or 1.0
    ratios = {role: max(0.0, float(ratios.get(role, 0.0) or 0.0) / total) for role in SMART_PRACTICE_PRIMARY_ROLES}
    if target == 0:
        return {role: 0 for role in SMART_PRACTICE_PRIMARY_ROLES}
    allocation = {role: int(target * ratios[role]) for role in SMART_PRACTICE_PRIMARY_ROLES}
    remaining = target - sum(allocation.values())
    priority = ["weak_repair", "due_retention", "blueprint_coverage", "transfer", "controlled_stretch"]
    fractions = sorted(
        (
            (target * ratios[role] - allocation[role], -priority.index(role), role)
            for role in SMART_PRACTICE_PRIMARY_ROLES
        ),
        reverse=True,
    )
    for _fraction, _priority, role in fractions[:remaining]:
        allocation[role] += 1
    if target <= len(priority):
        allocation = {role: 0 for role in SMART_PRACTICE_PRIMARY_ROLES}
        for role in priority[:target]:
            allocation[role] = 1
    return allocation
