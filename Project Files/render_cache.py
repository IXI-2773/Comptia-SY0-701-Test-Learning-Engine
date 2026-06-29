from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChoiceRenderSnapshot:
    letter: str
    text: str
    state: str
    detail: str
    detail_emphasis: bool


@dataclass(frozen=True)
class QuestionRenderSnapshot:
    question_number: int
    header_text: str
    meta_text: str
    meta_background: str
    meta_foreground: str
    prompt: str
    issue_notes: tuple[str, ...]
    choices: tuple[ChoiceRenderSnapshot, ...]
    answered: bool
    correct: bool
    flagged: bool
    suspended: bool
    show_exam_feedback: bool
    dense: bool
    width: int
    confidence: str
    miss_reason: str
    session_tag: str
    ladder_stage: str


class QuestionRenderCache:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[Any, ...], QuestionRenderSnapshot] = {}

    def get(self, key: tuple[Any, ...]) -> QuestionRenderSnapshot | None:
        return self._snapshots.get(key)

    def put(self, key: tuple[Any, ...], snapshot: QuestionRenderSnapshot) -> QuestionRenderSnapshot:
        self._snapshots[key] = snapshot
        if len(self._snapshots) > 256:
            oldest_key = next(iter(self._snapshots))
            self._snapshots.pop(oldest_key, None)
        return snapshot

    def clear(self) -> None:
        self._snapshots.clear()
