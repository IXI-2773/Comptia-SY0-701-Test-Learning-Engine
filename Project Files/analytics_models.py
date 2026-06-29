from typing import TypedDict

from progress_models import ProgressSummary


class AnalyticsOverall(TypedDict):
    total: int
    answered: int
    unanswered: int
    correct: int
    wrong: int
    accuracy: float
    flagged: int
    with_issues: int
    elapsed_seconds: int
    recent50_accuracy: float
    recent50_count: int
    current_streak: int
    mode: str
    decision_quality: float
    stability_score: float
    pass_prediction_score: float
    pass_prediction_label: str


class AnalyticsDomainRow(TypedDict):
    domain: str
    total: int
    answered: int
    correct: int
    wrong: int
    flagged: int
    issues: int
    progress_attempted: int
    progress_wrong: int
    progress_due: int
    progress_flagged: int
    progress_active_weak: int
    progress_recovered: int
    confidence_score: float
    confidence_seen: int
    accuracy: float
    coverage: float
    heat: float
    readiness: float
    stability: float
    trend: float


class AnalyticsTopicRow(TypedDict):
    topic: str
    seen: int
    correct: int
    wrong: int
    progress_attempted: int
    progress_wrong: int
    progress_due: int
    progress_active_weak: int
    progress_recovered: int
    confidence_score: float
    confidence_seen: int
    accuracy: float
    readiness: float
    stability: float
    trend: float


class AnalyticsRoiRow(TypedDict):
    question_number: int
    domain: str
    topic: str
    roi: float
    reasons: str


class AnalyticsVolatilityRow(TypedDict):
    question_number: int
    domain: str
    topic: str
    score: float
    label: str
    attempts: int
    flips: int
    last_outcome: str


class ConfidenceCalibrationRow(TypedDict):
    confidence: str
    attempts: int
    correct: int
    accuracy: float


class AnswerLatencyDiagnosisRow(TypedDict):
    kind: str
    unit: str
    label: str
    fast_wrong: int
    slow_wrong: int
    fast_correct: int
    slow_correct: int
    avg_seconds: float
    pressure: float
    note: str


class ConfidenceMismatchRow(TypedDict):
    kind: str
    unit: str
    sure_attempts: int
    sure_wrong: int
    sure_wrong_rate: float
    example_question_numbers: list[int]
    pressure: float
    note: str


class MasteryMapRow(TypedDict):
    topic: str
    new: int
    active_weak: int
    recovered: int
    due: int
    mastered: int
    in_progress: int
    flagged: int
    readiness: float


class ConceptAnchorNoteRow(TypedDict):
    topic: str
    note: str
    active_weak: int
    readiness: float


class WrongAnswerFamilyRow(TypedDict):
    family: str
    count: int
    domains: str
    topics: str
    examples: str
    coaching: str


class TrapWordPatternRow(TypedDict):
    trap_word: str
    count: int


class RecallFailureRow(TypedDict):
    failure: str
    count: int
    accuracy_drag: float
    domains: str
    clues: str
    note: str


class DecidingClueRow(TypedDict):
    clue: str
    seen: int
    misses: int
    fragile_correct: int
    mastery_signal: float
    domains: str
    note: str


class ConceptMemoryStateRow(TypedDict):
    concept_id: str
    kind: str
    unit: str
    state: str
    evidence_count: int
    confidence_quality: float
    transfer_evidence: int
    durability_signal: float
    next_ramp: str
    note: str


class WrongAnswerMemoryRow(TypedDict):
    concept_id: str
    kind: str
    unit: str
    tempting_distractor: str
    correct_concept: str
    count: int
    last_seen: str
    pressure: float
    example_question_numbers: list[int]
    note: str


class PassPrediction(TypedDict):
    label: str
    score: float
    confidence_honesty: float
    readiness_floor: float
    reasons: list[str]


class ConceptClusterRow(TypedDict):
    concept: str
    domain: str
    misses: int
    active_weak: int
    due: int
    volatility: float
    top_miss_reason: str
    top_trap_word: str
    wrong_family: str
    question_numbers: list[int]
    severity: float


class RemediationCardRow(TypedDict):
    concept: str
    diagnosis: str
    action: str
    anchor: str
    focus_questions: list[int]
    severity: float


class SourceAgreementRow(TypedDict):
    question_number: int
    source_name: str
    label: str
    score: float
    support_sources: list[str]
    objective_code: str
    topic: str


class CoverageGapRow(TypedDict):
    unit: str
    kind: str
    available: int
    attempted: int
    accuracy: float
    severity: float
    sources: list[str]


class ConfusionPairRow(TypedDict):
    pair: str
    left: str
    right: str
    count: int
    domains: str
    topics: str
    question_numbers: list[int]
    action: str


class LatentWeaknessRow(TypedDict):
    question_number: int
    domain: str
    topic: str
    source_name: str
    score: float
    stability: float
    confidence_signal: str
    reasons: list[str]


class SourceTrustRow(TypedDict):
    source_name: str
    trust_score: float
    label: str
    question_count: int
    agreement_count: int
    supported_count: int
    single_source_count: int
    conflict_count: int
    issue_count: int
    decay: float


class TransferStrengthRow(TypedDict):
    kind: str
    unit: str
    score: float
    label: str
    exposure: int
    source_count: int
    stem_style_count: int
    stem_styles: list[str]
    stability: float
    confidence: float
    active_weak: int
    due: int


class ObjectiveMasteryRow(TypedDict):
    objective_code: str
    available: int
    attempted: int
    readiness: float
    stability: float
    trend: float
    source_count: int
    stem_style_count: int
    active_weak: int
    due: int
    mastery_score: float


class InterferenceMapRow(TypedDict):
    pair: str
    left: str
    right: str
    count: int
    pressure: float
    domains: str
    topics: str
    question_numbers: list[int]
    action: str


class ConfidenceCompressionRow(TypedDict):
    kind: str
    unit: str
    compression: float
    correct_total: int
    fragile_correct: int
    sure_correct: int
    stability: float
    note: str


class AbstractionLadderRow(TypedDict):
    kind: str
    unit: str
    score: float
    label: str
    rung_count: int
    available_style_count: int
    source_count: int
    seen_styles: list[str]
    missing_styles: list[str]
    confidence: float
    stability: float


class ErrorBoundaryRow(TypedDict):
    kind: str
    unit: str
    weak_style: str
    strong_style: str
    gap: float
    weak_accuracy: float
    strong_accuracy: float
    attempts: int
    note: str


class CounterfactualDistractorRow(TypedDict):
    kind: str
    unit: str
    distractor: str
    correct: str
    count: int
    pressure: float
    domains: str
    topics: str
    question_numbers: list[int]
    note: str


class DifficultyCalibrationRow(TypedDict):
    question_number: int
    domain: str
    topic: str
    score: float
    label: str
    wrong_rate: float
    fragile_rate: float
    volatility: float
    source_support: str


class PhrasingNormalizationRow(TypedDict):
    question_number: int
    source_name: str
    score: float
    label: str
    note: str


class BurnoutRiskRow(TypedDict):
    label: str
    score: float
    accuracy_drop: float
    response_drag: float
    fragile_rate: float
    note: str


class PrerequisiteDebtRow(TypedDict):
    kind: str
    unit: str
    severity: float
    mastery_score: float
    active_weak: int
    due: int
    dependent_units: list[str]
    note: str


class ConceptHalfLifeRow(TypedDict):
    kind: str
    unit: str
    half_life_days: float
    label: str
    stability: float
    volatility: float
    confidence: float
    note: str


class BlindSpotInferenceRow(TypedDict):
    kind: str
    unit: str
    severity: float
    evidence: list[str]
    supporting_units: list[str]
    note: str


class RobustnessScoreRow(TypedDict):
    kind: str
    unit: str
    score: float
    label: str
    source_count: int
    stem_style_count: int
    half_life_days: float
    stability: float


class LeverageRankingRow(TypedDict):
    kind: str
    unit: str
    leverage: float
    dependent_count: int
    related_objectives: int
    note: str


class MisconceptionFingerprintRow(TypedDict):
    fingerprint: str
    count: int
    affected_units: list[str]
    evidence: str
    note: str


class EffortEfficiencyRow(TypedDict):
    kind: str
    unit: str
    score: float
    avg_response_seconds: float
    fragile_correct_rate: float
    note: str


class ReinforcementDistanceRow(TypedDict):
    question_number: int
    kind: str
    unit: str
    recommended_days: float
    priority: float
    note: str


class SynthesisCheckRow(TypedDict):
    question_number: int
    objective_code: str
    topic_mix: str
    score: float
    label: str
    stem_style: str
    note: str


class KnowledgeTraceRow(TypedDict):
    kind: str
    unit: str
    mastery_prob: float
    uncertainty: float
    evidence_count: int
    canonical_concept_id: str
    note: str


class ExpectedLearningGainRow(TypedDict):
    question_number: int
    kind: str
    unit: str
    expected_gain: float
    uncertainty: float
    leverage: float
    note: str


class DelayedProbeRow(TypedDict):
    question_number: int
    kind: str
    unit: str
    days_since_seen: float
    pressure: float
    note: str


class CounterexampleTrainingRow(TypedDict):
    question_number: int
    kind: str
    unit: str
    pressure: float
    cue: str
    note: str


class RecognitionRetrievalRow(TypedDict):
    kind: str
    unit: str
    recognition_score: float
    retrieval_score: float
    gap: float
    note: str


class CueDependenceRow(TypedDict):
    question_number: int
    kind: str
    unit: str
    score: float
    stage: str
    note: str


class ConceptStateRow(TypedDict):
    kind: str
    unit: str
    canonical_concept_id: str
    state: str
    mastery_prob: float
    robustness: float
    generalization: float
    half_life_days: float


class ContrastRuleRow(TypedDict):
    kind: str
    unit: str
    rule: str
    pressure: float
    note: str


class RetentionStressRow(TypedDict):
    question_number: int
    kind: str
    unit: str
    pressure: float
    label: str
    note: str


class FailureModeRow(TypedDict):
    kind: str
    unit: str
    mode: str
    pressure: float
    evidence: str
    note: str


class CompressionPointRow(TypedDict):
    kind: str
    unit: str
    basic_score: float
    applied_score: float
    gap: float
    note: str


class DecisionLatencyRow(TypedDict):
    kind: str
    unit: str
    productive_seconds: float
    confusion_seconds: float
    drag: float
    note: str


class GeneralizationScoreRow(TypedDict):
    kind: str
    unit: str
    score: float
    source_count: int
    stem_style_count: int
    note: str


class AnalyticsPayload(TypedDict):
    overall: AnalyticsOverall
    progress: ProgressSummary
    domains: list[AnalyticsDomainRow]
    topics: list[AnalyticsTopicRow]
    recommendations: list[str]
    roi_questions: list[AnalyticsRoiRow]
    volatile_questions: list[AnalyticsVolatilityRow]
    confidence_calibration: list[ConfidenceCalibrationRow]
    answer_latency_diagnosis: list[AnswerLatencyDiagnosisRow]
    confidence_mismatch: list[ConfidenceMismatchRow]
    anti_patterns: list[str]
    topic_mastery_map: list[MasteryMapRow]
    concept_anchor_notes: list[ConceptAnchorNoteRow]
    wrong_answer_families: list[WrongAnswerFamilyRow]
    trap_word_patterns: list[TrapWordPatternRow]
    recall_failures: list[RecallFailureRow]
    deciding_clues: list[DecidingClueRow]
    concept_memory_states: list[ConceptMemoryStateRow]
    wrong_answer_memory: list[WrongAnswerMemoryRow]
    recovery_ladder: dict[str, int]
    pass_prediction: PassPrediction
    concept_clusters: list[ConceptClusterRow]
    remediation_cards: list[RemediationCardRow]
    source_agreement: list[SourceAgreementRow]
    coverage_gaps: list[CoverageGapRow]
    confusion_pairs: list[ConfusionPairRow]
    latent_weakness: list[LatentWeaknessRow]
    source_trust: list[SourceTrustRow]
    transfer_strength: list[TransferStrengthRow]
    objective_mastery: list[ObjectiveMasteryRow]
    interference_map: list[InterferenceMapRow]
    confidence_compression: list[ConfidenceCompressionRow]
    abstraction_ladder: list[AbstractionLadderRow]
    error_boundaries: list[ErrorBoundaryRow]
    counterfactual_distractors: list[CounterfactualDistractorRow]
    difficulty_calibration: list[DifficultyCalibrationRow]
    phrasing_normalization: list[PhrasingNormalizationRow]
    burnout_risk: BurnoutRiskRow
    prerequisite_debt: list[PrerequisiteDebtRow]
    concept_half_life: list[ConceptHalfLifeRow]
    blind_spot_inference: list[BlindSpotInferenceRow]
    robustness_scores: list[RobustnessScoreRow]
    leverage_ranking: list[LeverageRankingRow]
    misconception_fingerprints: list[MisconceptionFingerprintRow]
    effort_efficiency: list[EffortEfficiencyRow]
    reinforcement_distance: list[ReinforcementDistanceRow]
    synthesis_checks: list[SynthesisCheckRow]
    knowledge_trace: list[KnowledgeTraceRow]
    expected_learning_gain: list[ExpectedLearningGainRow]
    delayed_probes: list[DelayedProbeRow]
    counterexample_training: list[CounterexampleTrainingRow]
    recognition_retrieval: list[RecognitionRetrievalRow]
    cue_dependence: list[CueDependenceRow]
    concept_states: list[ConceptStateRow]
    contrast_rules: list[ContrastRuleRow]
    retention_stress: list[RetentionStressRow]
    failure_modes: list[FailureModeRow]
    compression_points: list[CompressionPointRow]
    decision_latency: list[DecisionLatencyRow]
    generalization_scores: list[GeneralizationScoreRow]
