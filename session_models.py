from collections.abc import Mapping, MutableMapping
from typing import Any, TypedDict, cast

from bank_models import BankQuestion


class AnswerState(TypedDict):
    selected: list[str]
    pending: list[str]
    answered: bool
    flagged: bool
    suspended: bool
    last_confidence: str
    last_miss_reason: str
    recall_ready: bool
    session_tag: str
    smart_primary_role: str
    smart_selection_reasons: list[str]
    smart_utility: float
    smart_utility_breakdown: dict[str, float]
    smart_policy_version: str
    smart_policy_id: str
    smart_concept_key: str
    smart_root_cause: str
    smart_root_cause_confidence: float
    smart_supporting_concepts: list[str]
    smart_graph_version: str
    smart_information_value: float
    smart_information_breakdown: dict[str, Any]
    smart_question_quality_status: str
    smart_question_quality_confidence: float
    smart_graph_bottleneck: float
    repair_stage: str
    repair_concept_key: str
    legacy_repair_concept_key: str
    prediction_id: str
    prediction_snapshot: dict[str, Any]


class QuestionHistoryEvent(TypedDict):
    at: str
    day: str
    question_number: int
    correct: bool
    confidence: str
    miss_reason: str
    domain: str
    topics: list[str]
    objective_code: str
    source_label: str
    mode: str
    trap_words: list[str]
    selected: list[str]
    correct_letters: list[str]
    selected_texts: list[str]
    correct_texts: list[str]
    wrong_answer_family: str
    recall_failure: str
    deciding_clue: str
    response_seconds: float
    raw_response_seconds: float
    effective_response_seconds: float
    response_time_contaminated: bool
    was_due: bool
    was_active_weak: bool
    session_tag: str
    smart_primary_role: str
    smart_selection_reasons: list[str]
    smart_utility: float
    repair_stage: str
    repair_concept_key: str
    prediction_id: str
    predicted_recall_probability: float
    predicted_success_probability: float
    predicted_learning_gain: float


class SessionAnswerEvent(TypedDict):
    question_number: int
    domain: str
    correct: bool
    confidence: str
    miss_reason: str
    recall_failure: str
    deciding_clue: str
    was_active_weak: bool
    was_due: bool
    response_seconds: float
    raw_response_seconds: float
    effective_response_seconds: float
    response_time_contaminated: bool
    session_tag: str
    smart_primary_role: str
    smart_selection_reasons: list[str]
    smart_utility: float
    repair_stage: str
    repair_concept_key: str
    prediction_id: str


class QuestProgressState(TypedDict):
    key: str
    title: str
    kind: str
    target: int
    progress: int
    completed: bool


class BuilderContext(TypedDict):
    mode: str
    count: str
    source_label: str
    session_source: str
    randomize: bool
    domain_filter: str
    topic_filter: str
    status_filter: str


class SessionSnapshot(TypedDict):
    schema_version: int
    app_version: str
    bank_file: str
    mode: str
    builder_context: BuilderContext
    source_label: str
    question_count: int
    question_numbers: list[int]
    restore_question_numbers: list[int]
    session_base_question_count: int
    session_question_limit: int
    restore_signature: str
    session_signature: str
    current_index: int
    elapsed_seconds: int
    exam_reveal: bool
    checkpoints_saved: list[str]
    session_rewards: list[str]
    unlocked_rewards: list[str]
    session_answer_history: list[SessionAnswerEvent]
    current_quests: list[QuestProgressState]
    quest_completion_keys: list[str]
    session_boss_markers: list[int]
    session_stealth_markers: list[int]
    session_xp_gained: int
    answers: list[AnswerState]


class QuestionRuntimeState(BankQuestion, total=False):
    selected: list[str]
    pending: list[str]
    answered: bool
    flagged: bool
    suspended: bool
    last_confidence: str
    last_miss_reason: str
    recall_ready: bool
    session_tag: str
    smart_primary_role: str
    smart_selection_reasons: list[str]
    smart_utility: float
    smart_utility_breakdown: dict[str, float]
    smart_policy_version: str
    smart_policy_id: str
    smart_concept_key: str
    smart_root_cause: str
    smart_root_cause_confidence: float
    smart_supporting_concepts: list[str]
    smart_graph_version: str
    smart_information_value: float
    smart_information_breakdown: dict[str, Any]
    smart_question_quality_status: str
    smart_question_quality_confidence: float
    smart_graph_bottleneck: float
    repair_stage: str
    repair_concept_key: str
    legacy_repair_concept_key: str
    prediction_id: str
    prediction_snapshot: dict[str, Any]


RuntimeQuestionMapping = MutableMapping[str, Any]


def as_runtime_question(question: Mapping[str, Any] | MutableMapping[str, Any]) -> QuestionRuntimeState:
    return cast(QuestionRuntimeState, question)


def answer_state_from_question(question: Mapping[str, Any]) -> AnswerState:
    runtime = as_runtime_question(question)
    selected = list(runtime.get("selected", []))
    return {
        "selected": selected,
        "pending": list(runtime.get("pending", selected)),
        "answered": bool(runtime.get("answered")),
        "flagged": bool(runtime.get("flagged")),
        "suspended": bool(runtime.get("suspended")),
        "last_confidence": str(runtime.get("last_confidence", "") or ""),
        "last_miss_reason": str(runtime.get("last_miss_reason", "") or ""),
        "recall_ready": bool(runtime.get("recall_ready")),
        "session_tag": str(runtime.get("session_tag", "") or ""),
        "smart_primary_role": str(runtime.get("smart_primary_role", "") or ""),
        "smart_selection_reasons": [str(value) for value in runtime.get("smart_selection_reasons", [])],
        "smart_utility": float(runtime.get("smart_utility", 0.0) or 0.0),
        "smart_utility_breakdown": dict(runtime.get("smart_utility_breakdown") or {}),
        "smart_policy_version": str(runtime.get("smart_policy_version", "") or ""),
        "smart_policy_id": str(runtime.get("smart_policy_id", "") or ""),
        "smart_concept_key": str(runtime.get("smart_concept_key", "") or ""),
        "smart_root_cause": str(runtime.get("smart_root_cause", "") or ""),
        "smart_root_cause_confidence": float(runtime.get("smart_root_cause_confidence", 0.0) or 0.0),
        "smart_supporting_concepts": [str(value) for value in runtime.get("smart_supporting_concepts", [])],
        "smart_graph_version": str(runtime.get("smart_graph_version", "") or ""),
        "smart_information_value": float(runtime.get("smart_information_value", 0.0) or 0.0),
        "smart_information_breakdown": dict(runtime.get("smart_information_breakdown") or {}),
        "smart_question_quality_status": str(runtime.get("smart_question_quality_status", "") or ""),
        "smart_question_quality_confidence": float(runtime.get("smart_question_quality_confidence", 0.0) or 0.0),
        "smart_graph_bottleneck": float(runtime.get("smart_graph_bottleneck", 0.0) or 0.0),
        "repair_stage": str(runtime.get("repair_stage", "") or ""),
        "repair_concept_key": str(runtime.get("repair_concept_key", "") or ""),
        "legacy_repair_concept_key": str(runtime.get("legacy_repair_concept_key", "") or ""),
        "prediction_id": str(runtime.get("prediction_id", "") or ""),
        "prediction_snapshot": dict(runtime.get("prediction_snapshot") or {}),
    }


def apply_answer_state(question: RuntimeQuestionMapping, state: Mapping[str, Any]) -> QuestionRuntimeState:
    runtime = as_runtime_question(question)
    answer_state = dict(state or {})
    selected = [str(letter) for letter in answer_state.get("selected", [])]
    runtime["selected"] = selected
    runtime["pending"] = [str(letter) for letter in answer_state.get("pending", selected)]
    runtime["answered"] = bool(answer_state.get("answered"))
    runtime["flagged"] = bool(answer_state.get("flagged"))
    runtime["suspended"] = bool(answer_state.get("suspended"))
    runtime["last_confidence"] = str(answer_state.get("last_confidence", "") or "")
    runtime["last_miss_reason"] = str(answer_state.get("last_miss_reason", "") or "")
    runtime["recall_ready"] = bool(answer_state.get("recall_ready"))
    runtime["session_tag"] = str(answer_state.get("session_tag", "") or "")
    runtime["smart_primary_role"] = str(answer_state.get("smart_primary_role", "") or "")
    runtime["smart_selection_reasons"] = [str(value) for value in answer_state.get("smart_selection_reasons", [])]
    runtime["smart_utility"] = float(answer_state.get("smart_utility", 0.0) or 0.0)
    runtime["smart_utility_breakdown"] = dict(answer_state.get("smart_utility_breakdown") or {})
    runtime["smart_policy_version"] = str(answer_state.get("smart_policy_version", "") or "")
    runtime["smart_policy_id"] = str(answer_state.get("smart_policy_id", "") or "")
    runtime["smart_concept_key"] = str(answer_state.get("smart_concept_key", "") or "")
    runtime["smart_root_cause"] = str(answer_state.get("smart_root_cause", "") or "")
    runtime["smart_root_cause_confidence"] = float(answer_state.get("smart_root_cause_confidence", 0.0) or 0.0)
    runtime["smart_supporting_concepts"] = [str(value) for value in answer_state.get("smart_supporting_concepts", [])]
    runtime["smart_graph_version"] = str(answer_state.get("smart_graph_version", "") or "")
    runtime["smart_information_value"] = float(answer_state.get("smart_information_value", 0.0) or 0.0)
    runtime["smart_information_breakdown"] = dict(answer_state.get("smart_information_breakdown") or {})
    runtime["smart_question_quality_status"] = str(answer_state.get("smart_question_quality_status", "") or "")
    runtime["smart_question_quality_confidence"] = float(answer_state.get("smart_question_quality_confidence", 0.0) or 0.0)
    runtime["smart_graph_bottleneck"] = float(answer_state.get("smart_graph_bottleneck", 0.0) or 0.0)
    runtime["repair_stage"] = str(answer_state.get("repair_stage", "") or "")
    runtime["repair_concept_key"] = str(answer_state.get("repair_concept_key", "") or "")
    runtime["legacy_repair_concept_key"] = str(answer_state.get("legacy_repair_concept_key", "") or "")
    runtime["prediction_id"] = str(answer_state.get("prediction_id", "") or "")
    runtime["prediction_snapshot"] = dict(answer_state.get("prediction_snapshot") or {})
    return runtime


def reset_runtime_question_state(question: RuntimeQuestionMapping) -> QuestionRuntimeState:
    runtime = as_runtime_question(question)
    runtime["selected"] = []
    runtime["pending"] = []
    runtime["answered"] = False
    runtime["flagged"] = bool(runtime.get("flagged", False))
    runtime["suspended"] = bool(runtime.get("suspended", False))
    runtime["last_confidence"] = str(runtime.get("last_confidence", "") or "")
    runtime["last_miss_reason"] = str(runtime.get("last_miss_reason", "") or "")
    runtime["recall_ready"] = bool(runtime.get("recall_ready", False))
    runtime["session_tag"] = str(runtime.get("session_tag", "") or "")
    runtime["smart_primary_role"] = str(runtime.get("smart_primary_role", "") or "")
    runtime["smart_selection_reasons"] = [str(value) for value in runtime.get("smart_selection_reasons", [])]
    runtime["smart_utility"] = float(runtime.get("smart_utility", 0.0) or 0.0)
    runtime["smart_utility_breakdown"] = dict(runtime.get("smart_utility_breakdown") or {})
    runtime["smart_policy_version"] = str(runtime.get("smart_policy_version", "") or "")
    runtime["smart_policy_id"] = str(runtime.get("smart_policy_id", "") or "")
    runtime["smart_concept_key"] = str(runtime.get("smart_concept_key", "") or "")
    runtime["smart_root_cause"] = str(runtime.get("smart_root_cause", "") or "")
    runtime["smart_root_cause_confidence"] = float(runtime.get("smart_root_cause_confidence", 0.0) or 0.0)
    runtime["smart_supporting_concepts"] = [str(value) for value in runtime.get("smart_supporting_concepts", [])]
    runtime["smart_graph_version"] = str(runtime.get("smart_graph_version", "") or "")
    runtime["smart_information_value"] = float(runtime.get("smart_information_value", 0.0) or 0.0)
    runtime["smart_information_breakdown"] = dict(runtime.get("smart_information_breakdown") or {})
    runtime["smart_question_quality_status"] = str(runtime.get("smart_question_quality_status", "") or "")
    runtime["smart_question_quality_confidence"] = float(runtime.get("smart_question_quality_confidence", 0.0) or 0.0)
    runtime["smart_graph_bottleneck"] = float(runtime.get("smart_graph_bottleneck", 0.0) or 0.0)
    runtime["repair_stage"] = str(runtime.get("repair_stage", "") or "")
    runtime["repair_concept_key"] = str(runtime.get("repair_concept_key", "") or "")
    runtime["legacy_repair_concept_key"] = str(runtime.get("legacy_repair_concept_key", "") or "")
    runtime["prediction_id"] = str(runtime.get("prediction_id", "") or "")
    runtime["prediction_snapshot"] = dict(runtime.get("prediction_snapshot") or {})
    return runtime


def clear_runtime_answer_state(
    question: RuntimeQuestionMapping, *, clear_flagged: bool = False
) -> QuestionRuntimeState:
    runtime = as_runtime_question(question)
    runtime["selected"] = []
    runtime["pending"] = []
    runtime["answered"] = False
    runtime["last_confidence"] = ""
    runtime["last_miss_reason"] = ""
    runtime["recall_ready"] = False
    if clear_flagged:
        runtime["flagged"] = False
    return runtime
