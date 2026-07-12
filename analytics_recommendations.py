from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalyticsRecommendationInputs:
    progress: dict[str, Any]
    decision_quality: float
    volatile_rows: list[dict[str, Any]]
    concept_clusters: list[dict[str, Any]]
    confusion_pairs: list[dict[str, Any]]
    interference_map_rows: list[dict[str, Any]]
    coverage_gaps: list[dict[str, Any]]
    objective_mastery_rows: list[dict[str, Any]]
    prerequisite_debt_rows: list[dict[str, Any]]
    knowledge_trace_rows: list[dict[str, Any]]
    concept_memory_state_rows: list[dict[str, Any]]
    wrong_answer_memory_rows: list[dict[str, Any]]
    concept_half_life_rows: list[dict[str, Any]]
    blind_spot_rows: list[dict[str, Any]]
    expected_learning_gain_rows: list[dict[str, Any]]
    confidence_compression_rows: list[dict[str, Any]]
    compression_point_rows: list[dict[str, Any]]
    abstraction_ladder_rows: list[dict[str, Any]]
    recognition_retrieval_rows: list[dict[str, Any]]
    robustness_rows: list[dict[str, Any]]
    leverage_ranking_rows: list[dict[str, Any]]
    generalization_rows: list[dict[str, Any]]
    error_boundary_rows: list[dict[str, Any]]
    counterfactual_distractor_rows: list[dict[str, Any]]
    counterexample_training_rows: list[dict[str, Any]]
    difficulty_rows: list[dict[str, Any]]
    phrasing_rows: list[dict[str, Any]]
    misconception_fingerprints: list[dict[str, Any]]
    effort_efficiency_rows: list[dict[str, Any]]
    decision_latency_rows: list[dict[str, Any]]
    answer_latency_rows: list[dict[str, Any]]
    confidence_mismatch_rows: list[dict[str, Any]]
    cue_dependence_rows: list[dict[str, Any]]
    latent_weakness_rows: list[dict[str, Any]]
    transfer_strength_rows: list[dict[str, Any]]
    reinforcement_distance_rows: list[dict[str, Any]]
    delayed_probe_rows: list[dict[str, Any]]
    synthesis_check_rows: list[dict[str, Any]]
    contrast_rule_rows: list[dict[str, Any]]
    retention_stress_rows: list[dict[str, Any]]
    failure_mode_rows: list[dict[str, Any]]
    concept_state_rows: list[dict[str, Any]]
    source_trust_rows: list[dict[str, Any]]
    burnout_risk: dict[str, Any]
    source_agreement_rows: list[dict[str, Any]]
    weak_domains: list[dict[str, Any]]
    weak_topics: list[dict[str, Any]]


def build_analytics_recommendations(inputs: AnalyticsRecommendationInputs) -> list[str]:
    recs: list[str] = []
    progress = inputs.progress
    if progress["due"]:
        recs.append(f"Start Due review with {min(progress['due'], 25)} questions due today.")
    if progress["wrong"]:
        recs.append(f"Run Weak retest for {progress['wrong']} active weak questions that still need recovery.")
    if progress["recovered"]:
        recs.append(
            f"{progress['recovered']} previously missed questions are now recovered and moved out of the weak bucket."
        )
    if inputs.decision_quality:
        recs.append(
            f"Decision quality is {inputs.decision_quality}%. Keep pushing 'Sure' accuracy higher than guessed wins."
        )
    if inputs.volatile_rows:
        hottest = inputs.volatile_rows[0]
        recs.append(
            f"Q{hottest['question_number']} is highly volatile at {hottest['score']} with {hottest['flips']} right/wrong flips. Recheck the underlying concept, not just the answer letter."
        )
    if inputs.concept_clusters:
        cluster = inputs.concept_clusters[0]
        recs.append(
            f"Top concept cluster: {cluster['concept']} with {cluster['misses']} misses, {cluster['active_weak']} active weak, and {cluster['volatility']} stability drag."
        )
    if inputs.confusion_pairs:
        pair = inputs.confusion_pairs[0]
        recs.append(
            f"Confusion pair in rotation: {pair['pair']} has shown up {pair['count']} times. The engine will quietly feed you contrast questions for it."
        )
    if inputs.interference_map_rows:
        pair = inputs.interference_map_rows[0]
        recs.append(
            f"Interference map: {pair['pair']} is creating {pair['pressure']} pressure, so the engine will keep separating those concepts in the background."
        )
    if inputs.coverage_gaps:
        gap = inputs.coverage_gaps[0]
        recs.append(
            f"Coverage gap: {gap['kind']} {gap['unit']} is only {gap['attempted']}/{gap['available']} covered, so Smart Practice will bias into it automatically."
        )
    if inputs.objective_mastery_rows:
        objective = inputs.objective_mastery_rows[0]
        recs.append(
            f"Objective autopilot: {objective['objective_code']} is only {objective['mastery_score']}% mastered across {objective['stem_style_count']} stem styles, so Smart Practice will quietly keep feeding it."
        )
    if inputs.prerequisite_debt_rows:
        row = inputs.prerequisite_debt_rows[0]
        recs.append(
            f"Prerequisite debt: {row['kind']} {row['unit']} is carrying severity {row['severity']} and quietly dragging nearby work, so the engine will stabilize that root before chasing symptoms."
        )
    if inputs.knowledge_trace_rows:
        row = inputs.knowledge_trace_rows[0]
        recs.append(
            f"Knowledge tracing: {row['kind']} {row['unit']} is only {row['mastery_prob']}% learned with {row['uncertainty']}% uncertainty, so the engine will keep sampling it for better evidence."
        )
    if inputs.concept_memory_state_rows:
        row = next(
            (item for item in inputs.concept_memory_state_rows if item["state"] in ("recognizable", "retrievable")),
            inputs.concept_memory_state_rows[0],
        )
        recs.append(
            f"Concept memory: {row['kind']} {row['unit']} is {row['state']}; next ramp is {row['next_ramp']}, so Smart Practice can lift it without adding clicks."
        )
    if inputs.wrong_answer_memory_rows:
        row = inputs.wrong_answer_memory_rows[0]
        recs.append(
            f"Wrong-answer memory: '{row['tempting_distractor']}' keeps competing with '{row['correct_concept']}' for {row['unit']}, so the engine will add counterexample checks."
        )
    if inputs.concept_half_life_rows:
        row = inputs.concept_half_life_rows[0]
        recs.append(
            f"Concept half-life: {row['kind']} {row['unit']} is only holding for about {row['half_life_days']} day(s), so reinforcement spacing will tighten automatically."
        )
    if inputs.blind_spot_rows:
        row = inputs.blind_spot_rows[0]
        recs.append(
            f"Blind-spot inference: {row['kind']} {row['unit']} looks under-tested with severity {row['severity']}, so Smart Practice will probe it before it becomes a visible weakness."
        )
    if inputs.expected_learning_gain_rows:
        row = inputs.expected_learning_gain_rows[0]
        recs.append(
            f"Learning-gain scheduler: Q{row['question_number']} has expected gain {row['expected_gain']}, so the engine will quietly surface it sooner than lower-payoff items."
        )
    if inputs.confidence_compression_rows:
        row = inputs.confidence_compression_rows[0]
        recs.append(
            f"Confidence compression: {row['kind']} {row['unit']} has {row['compression']} compression because {row['note'].lower()}"
        )
    if inputs.compression_point_rows:
        row = inputs.compression_point_rows[0]
        recs.append(
            f"Compression point: {row['kind']} {row['unit']} drops {row['gap']} points when the abstraction level rises, so the engine will add applied checks before granting mastery."
        )
    if inputs.abstraction_ladder_rows:
        row = inputs.abstraction_ladder_rows[0]
        missing = ", ".join(row["missing_styles"][:3]) or "none"
        recs.append(
            f"Abstraction ladder: {row['kind']} {row['unit']} is only {row['score']}% integrated and still missing styles like {missing}."
        )
    if inputs.recognition_retrieval_rows:
        row = inputs.recognition_retrieval_rows[0]
        recs.append(
            f"Recognition vs retrieval: {row['kind']} {row['unit']} has a {row['gap']} point cue-to-retrieval gap, so the engine will test it with less obvious stems."
        )
    if inputs.robustness_rows:
        row = inputs.robustness_rows[0]
        recs.append(
            f"Robustness score: {row['kind']} {row['unit']} is still {row['label'].lower()} at {row['score']}%, so the engine will keep checking it across sources and stem styles."
        )
    if inputs.leverage_ranking_rows:
        row = inputs.leverage_ranking_rows[0]
        recs.append(
            f"Leverage ranking: {row['kind']} {row['unit']} influences a lot of downstream performance ({row['leverage']} leverage), so improving it should pay back broadly."
        )
    if inputs.generalization_rows:
        row = inputs.generalization_rows[0]
        recs.append(
            f"Generalization score: {row['kind']} {row['unit']} is only {row['score']} across source and stem variation, so the engine will keep rotating scenario angles."
        )
    if inputs.error_boundary_rows:
        row = inputs.error_boundary_rows[0]
        recs.append(
            f"Error-boundary tracing: {row['kind']} {row['unit']} holds at {row['strong_style'].lower()} but breaks at {row['weak_style'].lower()} with a {row['gap']} point gap, so the engine will quietly target that transfer edge."
        )
    if inputs.counterfactual_distractor_rows:
        row = inputs.counterfactual_distractor_rows[0]
        recs.append(
            f"Counterfactual distractor memory: in {row['kind']} {row['unit']}, '{row['distractor']}' keeps beating '{row['correct']}' with pressure {row['pressure']}. The engine will quietly recycle that contrast."
        )
    if inputs.counterexample_training_rows:
        row = inputs.counterexample_training_rows[0]
        recs.append(
            f"Counterexample trainer: Q{row['question_number']} can break the wrong rule around {row['cue']}, so the engine will recycle it as a misconception check."
        )
    if inputs.difficulty_rows:
        row = inputs.difficulty_rows[0]
        recs.append(
            f"Difficulty calibration: Q{row['question_number']} is scoring {row['score']} as a {row['label'].lower()} item from real user data, so Smart Practice will pace around it more carefully."
        )
    if inputs.phrasing_rows:
        row = inputs.phrasing_rows[0]
        if row["label"] == "Noisy":
            recs.append(
                f"Source phrasing normalization: Q{row['question_number']} is noisy at {row['score']}%, so readiness will downweight wording friction behind the scenes."
            )
    if inputs.misconception_fingerprints:
        row = inputs.misconception_fingerprints[0]
        recs.append(
            f"Misconception fingerprint: {row['fingerprint']} is recurring across {len(row['affected_units'])} unit(s), so the engine will target the underlying model rather than only the missed item."
        )
    if inputs.effort_efficiency_rows:
        row = inputs.effort_efficiency_rows[0]
        recs.append(
            f"Effort efficiency: {row['kind']} {row['unit']} is only {row['score']} efficient, so the engine will quietly revisit it until answers become cleaner and faster."
        )
    if inputs.decision_latency_rows:
        row = inputs.decision_latency_rows[0]
        recs.append(
            f"Decision latency: {row['kind']} {row['unit']} costs {row['drag']} extra seconds under confusion, so the engine will treat that as a thinking bottleneck, not just a miss."
        )
    if inputs.answer_latency_rows:
        row = inputs.answer_latency_rows[0]
        recs.append(
            f"Answer latency diagnosis: {row['kind']} {row['unit']} shows {row['label'].lower()} at pressure {row['pressure']}. {row['note']}"
        )
    if inputs.confidence_mismatch_rows:
        row = inputs.confidence_mismatch_rows[0]
        recs.append(
            f"Confidence mismatch: {row['kind']} {row['unit']} has {row['sure_wrong']} confident miss(es) across {row['sure_attempts']} sure attempts. The engine will treat that confidence as fragile."
        )
    if inputs.cue_dependence_rows:
        row = inputs.cue_dependence_rows[0]
        recs.append(
            f"Cue dependence: Q{row['question_number']} is in {row['stage'].lower()} cue-support mode at {row['score']}%, so the engine will stop over-crediting easy recognition there."
        )
    if inputs.latent_weakness_rows:
        latent = inputs.latent_weakness_rows[0]
        recs.append(
            f"Latent weakness watch: Q{latent['question_number']} looks right-on-paper but still scores {latent['score']} for hidden fragility ({', '.join(latent['reasons'])})."
        )
    if inputs.transfer_strength_rows:
        transfer = inputs.transfer_strength_rows[0]
        recs.append(
            f"Transfer strength: {transfer['kind']} {transfer['unit']} is only {transfer['score']}% portable across exposures, so the engine will keep interleaving it."
        )
    if inputs.reinforcement_distance_rows:
        row = inputs.reinforcement_distance_rows[0]
        recs.append(
            f"Adaptive reinforcement distance: Q{row['question_number']} is due for another high-value check in about {row['recommended_days']} day(s), so the engine will quietly time that revisit."
        )
    if inputs.delayed_probe_rows:
        row = inputs.delayed_probe_rows[0]
        recs.append(
            f"Surprise delayed probe: Q{row['question_number']} has probe pressure {row['pressure']} after {row['days_since_seen']} day(s), so the engine will recheck it without warning."
        )
    if inputs.synthesis_check_rows:
        row = inputs.synthesis_check_rows[0]
        recs.append(
            f"Cross-objective synthesis: Q{row['question_number']} blends {row['topic_mix']} with a {row['stem_style'].lower()} stem, so it is being used as a deeper integration check."
        )
    if inputs.contrast_rule_rows:
        row = inputs.contrast_rule_rows[0]
        recs.append(
            f"Contrasting-rule library: '{row['rule']}' is active with pressure {row['pressure']}, so the engine will keep separating those ideas until the distinction is automatic."
        )
    if inputs.retention_stress_rows:
        row = inputs.retention_stress_rows[0]
        recs.append(
            f"Retention stress testing: Q{row['question_number']} is ready for a harder delayed recheck at pressure {row['pressure']}."
        )
    if inputs.failure_mode_rows:
        row = inputs.failure_mode_rows[0]
        recs.append(
            f"Failure-mode simulation: {row['kind']} {row['unit']} is mostly failing through {row['mode']}, so practice will shift toward that error shape."
        )
    if inputs.concept_state_rows:
        row = inputs.concept_state_rows[0]
        recs.append(
            f"Concept-state graph: {row['kind']} {row['unit']} is currently {row['state']}, not fully stable, so the engine will keep treating it as evidence-in-progress."
        )
    if inputs.source_trust_rows:
        weakest_source = inputs.source_trust_rows[0]
        if weakest_source["label"] == "Decayed":
            recs.append(
                f"Source trust decay: {weakest_source['source_name']} is down to {weakest_source['trust_score']}% trust and will be weighted down behind the scenes."
            )
    if inputs.burnout_risk["label"] != "Low":
        recs.append(
            f"Micro-burnout detector: current session risk is {inputs.burnout_risk['label'].lower()} at {inputs.burnout_risk['score']}%, so Smart Practice will flatten difficulty and bonus inserts."
        )
    conflict_count = sum(1 for row in inputs.source_agreement_rows if row["label"] == "Source conflict")
    if conflict_count:
        recs.append(f"{conflict_count} questions show source conflicts and are being downweighted behind the scenes.")
    for row in inputs.weak_domains:
        trend_word = "up" if row["trend"] >= 0 else "down"
        recs.append(
            f"{row['domain']}: readiness {row['readiness']}%, stability {row['stability']}%, heat {row['heat']}, trend {trend_word} {abs(row['trend']):.1f}, active weak {row['progress_active_weak']}, due {row['progress_due']}."
        )
    for row in inputs.weak_topics[:3]:
        trend_word = "up" if row["trend"] >= 0 else "down"
        recs.append(
            f"Topic '{row['topic']}' readiness {row['readiness']}%, stability {row['stability']}%, trend {trend_word} {abs(row['trend']):.1f}, active weak {row['progress_active_weak']}, due {row['progress_due']}."
        )
    if not recs:
        recs.append("Answer more questions to unlock stronger recommendations.")
    return recs
