from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SmartPracticeWorkerSnapshot:
    master_questions: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    progress_data: dict[str, Any]
    session_answer_history: list[dict[str, Any]]
    active_session_mode: str
    smart_practice_signal_cache_key: Any
    smart_practice_signal_cache_payload: Any
    smart_practice_pool_cache: dict[Any, Any]
    progress_meta_cache_raw: dict[str, Any]
    progress_meta_cache_value: Any
    base_pool: list[dict[str, Any]] | None


class DetachedSmartPracticeContext:
    def __init__(self, owner_cls: type, snapshot: SmartPracticeWorkerSnapshot):
        self._owner_cls = owner_cls
        self.master_questions = snapshot.master_questions
        self.questions = snapshot.questions
        self.progress_data = snapshot.progress_data
        self.session_answer_history = snapshot.session_answer_history
        self.active_session_mode = snapshot.active_session_mode
        self.smart_practice_signal_cache_key = snapshot.smart_practice_signal_cache_key
        self.smart_practice_signal_cache_payload = snapshot.smart_practice_signal_cache_payload
        self.smart_practice_pool_cache = snapshot.smart_practice_pool_cache
        self.progress_meta_cache_raw = snapshot.progress_meta_cache_raw
        self.progress_meta_cache_value = snapshot.progress_meta_cache_value
        self.base_pool = snapshot.base_pool
        self.smart_practice_prewarm = None
        self.render_cache = None
        self.root = None

    def __getattr__(self, name: str):
        owner_attr = getattr(self._owner_cls, name)
        if callable(owner_attr):
            return owner_attr.__get__(self, self.__class__)
        return owner_attr


def create_detached_context(owner_cls: type, snapshot: SmartPracticeWorkerSnapshot) -> DetachedSmartPracticeContext:
    return DetachedSmartPracticeContext(owner_cls, snapshot)


def build_detached_signal_payload(owner_cls: type, snapshot: SmartPracticeWorkerSnapshot):
    return create_detached_context(owner_cls, snapshot)._build_smart_practice_signal_payload()


def build_detached_pool(
    owner_cls: type,
    snapshot: SmartPracticeWorkerSnapshot,
    *,
    count: str,
    randomize: bool,
    base_pool: list[dict[str, Any]] | None,
):
    context = create_detached_context(owner_cls, snapshot)
    return context._build_smart_practice_pool_compat(count, randomize=randomize, base_pool=base_pool)
