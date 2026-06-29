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


class QuestionHistoryEvent(TypedDict):
    at: str
    day: str
    question_number: int
    correct: bool
    confidence: str
    miss_reason: str
    domain: str
    topics: list[str]
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
    was_due: bool
    was_active_weak: bool
    session_tag: str


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
    session_tag: str


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
