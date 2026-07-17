import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from app_constants import MODE_EXAM, MODE_PRACTICE, MODE_SMART_PRACTICE
from session_models import (
    AnswerState,
    BuilderContext,
    QuestProgressState,
    SessionAnswerEvent,
    SessionSnapshot,
    answer_state_from_question,
)

SESSION_SCHEMA_VERSION = 3
SUPPORTED_SESSION_MODES = {MODE_PRACTICE, MODE_SMART_PRACTICE, MODE_EXAM}


def calculate_session_question_limit(base_count: int) -> int:
    try:
        base = max(0, int(base_count or 0))
    except (TypeError, ValueError):
        base = 0
    return base


def session_signature(mode: str, question_numbers: list[Any]) -> str:
    raw = f"{str(mode or '').strip()}|{'/'.join(str(qnum) for qnum in question_numbers)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def runtime_bank_stem(bank_path: Path) -> str:
    stem = bank_path.stem
    for suffix in ("_clean", "_plus_studyguide"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def session_file_path(user_data_dir: Path, bank_path: Path, mode: str, question_numbers: list[Any]) -> Path:
    safe_mode = str(mode or "").lower().replace(" ", "_").replace("/", "_")
    count = len(question_numbers)
    signature = session_signature(mode, question_numbers)
    return user_data_dir / f"{runtime_bank_stem(bank_path)}_{safe_mode}_session_{count}_{signature}.json"


def checkpoint_file_path(checkpoint_dir: Path, bank_path: Path, mode: str, answered_count: int) -> Path:
    safe_mode = str(mode or "").lower().replace(" ", "_")
    return checkpoint_dir / f"{runtime_bank_stem(bank_path)}_{safe_mode}_checkpoint_{answered_count}.json"


def progress_file_path(user_data_dir: Path, bank_path: Path) -> Path:
    return user_data_dir / f"{runtime_bank_stem(bank_path)}_progress.json"


def legacy_session_file_path(bank_path: Path, mode: str) -> Path:
    safe_mode = str(mode or "").lower().replace(" ", "_").replace("/", "_")
    return bank_path.with_name(f"{runtime_bank_stem(bank_path)}_{safe_mode}_session.json")


def legacy_progress_file_path(bank_path: Path) -> Path:
    return bank_path.with_name(f"{runtime_bank_stem(bank_path)}_progress.json")


def serialize_answer_state(question: Mapping[str, Any]) -> AnswerState:
    return answer_state_from_question(question)


def normalize_builder_context(
    raw: Mapping[str, Any] | None, *, mode: str = "", source_label: str = "", question_count: int = 0
) -> BuilderContext:
    payload = dict(raw or {})
    return {
        "mode": str(payload.get("mode") or mode or ""),
        "count": str(payload.get("count") or question_count or ""),
        "source_label": str(payload.get("source_label") or source_label or ""),
        "session_source": str(payload.get("session_source") or ""),
        "randomize": bool(payload.get("randomize")),
        "domain_filter": str(payload.get("domain_filter") or "All domains"),
        "topic_filter": str(payload.get("topic_filter") or "All topics"),
        "status_filter": str(payload.get("status_filter") or "All questions"),
    }


def _coerce_int(value: Any, *, field: str, default: int = 0, minimum: int | None = None) -> int:
    if value in (None, ""):
        number = default
    else:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid integer for {field}: {value!r}") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"Invalid integer for {field}: {number!r}")
    return number


def _coerce_str_list(value: Any, *, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid list for {field}")
    return [str(item) for item in value]


def _coerce_int_list(value: Any, *, field: str, minimum: int = 0) -> list[int]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid list for {field}")
    return [_coerce_int(item, field=field, minimum=minimum) for item in value]


def migrate_session_snapshot(
    saved: Mapping[str, Any] | None, mode: str, question_numbers: list[Any]
) -> SessionSnapshot:
    payload = dict(saved or {})
    current_qnums = [
        _coerce_int(qnum, field="question_numbers", minimum=1) for qnum in question_numbers if str(qnum).strip()
    ]
    saved_mode = str(payload.get("mode") or mode or "")
    if saved_mode not in SUPPORTED_SESSION_MODES:
        raise ValueError(f"Unsupported session mode: {saved_mode!r}")
    raw_saved_qnums = payload.get("question_numbers", [])
    if raw_saved_qnums not in (None, "") and not isinstance(raw_saved_qnums, list):
        raise ValueError("Session question_numbers must be a list.")
    saved_qnums = [
        _coerce_int(qnum, field="question_numbers", minimum=1) for qnum in raw_saved_qnums if str(qnum).strip()
    ]
    raw_restore_qnums = payload.get("restore_question_numbers", [])
    if raw_restore_qnums not in (None, "") and not isinstance(raw_restore_qnums, list):
        raise ValueError("Session restore_question_numbers must be a list.")
    restore_qnums = (
        [
            _coerce_int(qnum, field="restore_question_numbers", minimum=1)
            for qnum in raw_restore_qnums
            if str(qnum).strip()
        ]
        or saved_qnums
        or current_qnums
    )
    if current_qnums:
        available_qnums = set(current_qnums)
        for qnum in saved_qnums + restore_qnums:
            if qnum not in available_qnums:
                raise ValueError(f"Unknown question reference in session snapshot: {qnum}")
    base_count = _coerce_int(
        payload.get("session_base_question_count") or len(restore_qnums) or len(saved_qnums) or len(current_qnums),
        field="session_base_question_count",
        minimum=0,
    )
    limit = payload.get("session_question_limit")
    try:
        session_limit = int(limit or 0)
    except (TypeError, ValueError):
        session_limit = 0
    if session_limit <= 0:
        session_limit = calculate_session_question_limit(base_count)
    raw_answers = payload.get("answers", [])
    raw_answer_history = payload.get("session_answer_history", [])
    raw_quests = payload.get("current_quests", [])
    if raw_answers not in (None, "") and not isinstance(raw_answers, list):
        raise ValueError("Session answers must be a list.")
    if raw_answer_history not in (None, "") and not isinstance(raw_answer_history, list):
        raise ValueError("Session session_answer_history must be a list.")
    if raw_quests not in (None, "") and not isinstance(raw_quests, list):
        raise ValueError("Session current_quests must be a list.")
    answers = []
    for answer in raw_answers if isinstance(raw_answers, list) else []:
        if not isinstance(answer, Mapping):
            raise ValueError("Session answer row must be a mapping.")
        answers.append(cast(AnswerState, dict(answer)))
    answer_history = []
    for event in raw_answer_history if isinstance(raw_answer_history, list) else []:
        if not isinstance(event, Mapping):
            raise ValueError("Session answer history row must be a mapping.")
        answer_history.append(cast(SessionAnswerEvent, dict(event)))
    quests = []
    for quest in raw_quests if isinstance(raw_quests, list) else []:
        if not isinstance(quest, Mapping):
            raise ValueError("Session quest row must be a mapping.")
        quests.append(cast(QuestProgressState, dict(quest)))
    raw_builder_context = payload.get("builder_context")
    if raw_builder_context not in (None, "") and not isinstance(raw_builder_context, Mapping):
        raise ValueError("Session builder_context must be a mapping.")
    builder_context_payload = raw_builder_context if isinstance(raw_builder_context, Mapping) else None
    builder_context = normalize_builder_context(
        builder_context_payload,
        mode=saved_mode,
        source_label=str(payload.get("source_label") or ""),
        question_count=base_count,
    )
    current_index = _coerce_int(payload.get("current_index", 0), field="current_index", minimum=0)
    max_index = max(0, len(saved_qnums or current_qnums) - 1)
    if current_index > max_index:
        raise ValueError(f"Session current_index is out of bounds: {current_index}")
    elapsed_seconds = _coerce_int(payload.get("elapsed_seconds", 0), field="elapsed_seconds", minimum=0)
    return {
        "schema_version": _coerce_int(payload.get("schema_version") or 1, field="schema_version", default=1, minimum=1),
        "app_version": str(payload.get("app_version") or ""),
        "bank_file": str(payload.get("bank_file") or ""),
        "mode": saved_mode,
        "builder_context": builder_context,
        "source_label": str(payload.get("source_label") or ""),
        "question_count": _coerce_int(
            payload.get("question_count") or len(saved_qnums) or len(current_qnums),
            field="question_count",
            minimum=0,
        ),
        "question_numbers": saved_qnums or current_qnums,
        "restore_question_numbers": restore_qnums,
        "session_base_question_count": base_count,
        "session_question_limit": session_limit,
        "restore_signature": str(payload.get("restore_signature") or session_signature(mode, restore_qnums)),
        "session_signature": str(
            payload.get("session_signature") or session_signature(mode, saved_qnums or current_qnums)
        ),
        "current_index": current_index,
        "elapsed_seconds": elapsed_seconds,
        "exam_reveal": bool(payload.get("exam_reveal", mode != "Exam")),
        "checkpoints_saved": _coerce_str_list(payload.get("checkpoints_saved", []), field="checkpoints_saved"),
        "session_rewards": _coerce_str_list(payload.get("session_rewards", []), field="session_rewards"),
        "unlocked_rewards": _coerce_str_list(payload.get("unlocked_rewards", []), field="unlocked_rewards"),
        "session_answer_history": answer_history,
        "current_quests": quests,
        "quest_completion_keys": _coerce_str_list(
            payload.get("quest_completion_keys", []), field="quest_completion_keys"
        ),
        "session_boss_markers": _coerce_int_list(
            payload.get("session_boss_markers", []), field="session_boss_markers", minimum=0
        ),
        "session_stealth_markers": _coerce_int_list(
            payload.get("session_stealth_markers", []), field="session_stealth_markers", minimum=0
        ),
        "session_xp_gained": _coerce_int(payload.get("session_xp_gained", 0), field="session_xp_gained", minimum=0),
        "answers": answers,
    }


def build_session_snapshot(
    *,
    app_version: str,
    bank_file: str,
    mode: str,
    builder_context: BuilderContext,
    source_label: str,
    question_numbers: list[int],
    restore_question_numbers: list[int],
    session_base_question_count: int,
    session_question_limit: int,
    current_index: int,
    elapsed_seconds: int,
    exam_reveal: bool,
    checkpoints_saved: list[str],
    session_rewards: list[str],
    unlocked_rewards: list[str],
    session_answer_history: list[SessionAnswerEvent],
    current_quests: list[QuestProgressState],
    quest_completion_keys: list[str],
    session_boss_markers: list[int],
    session_stealth_markers: list[int],
    session_xp_gained: int,
    answers: list[AnswerState],
) -> SessionSnapshot:
    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        "app_version": app_version,
        "bank_file": bank_file,
        "mode": mode,
        "builder_context": normalize_builder_context(
            builder_context,
            mode=mode,
            source_label=source_label,
            question_count=session_base_question_count,
        ),
        "source_label": source_label,
        "question_count": len(question_numbers),
        "question_numbers": list(question_numbers),
        "restore_question_numbers": list(restore_question_numbers),
        "session_base_question_count": int(session_base_question_count),
        "session_question_limit": int(session_question_limit),
        "restore_signature": session_signature(mode, restore_question_numbers),
        "session_signature": session_signature(mode, question_numbers),
        "current_index": int(current_index),
        "elapsed_seconds": int(elapsed_seconds),
        "exam_reveal": bool(exam_reveal),
        "checkpoints_saved": list(checkpoints_saved),
        "session_rewards": list(session_rewards),
        "unlocked_rewards": list(unlocked_rewards),
        "session_answer_history": list(session_answer_history),
        "current_quests": list(current_quests),
        "quest_completion_keys": list(quest_completion_keys),
        "session_boss_markers": list(session_boss_markers),
        "session_stealth_markers": list(session_stealth_markers),
        "session_xp_gained": int(session_xp_gained),
        "answers": list(answers),
    }


def saved_session_matches_current(
    saved: Mapping[str, Any] | None, mode: str, current_question_numbers: list[Any], restore_question_numbers: list[Any]
) -> bool:
    if not isinstance(saved, Mapping):
        return False
    raw_restore_signature = str(saved.get("restore_signature") or "").strip()
    if raw_restore_signature:
        return raw_restore_signature == session_signature(mode, list(restore_question_numbers))
    raw_session_signature = str(saved.get("session_signature") or "").strip()
    if raw_session_signature:
        return raw_session_signature == session_signature(mode, list(current_question_numbers))
    try:
        saved_qnums = [
            _coerce_int(qnum, field="question_numbers", minimum=1)
            for qnum in saved.get("question_numbers", [])
            if str(qnum).strip()
        ]
        current_qnums = [
            _coerce_int(qnum, field="current_question_numbers", minimum=1) for qnum in current_question_numbers
        ]
    except (TypeError, ValueError):
        return False
    return bool(saved_qnums) and saved_qnums == current_qnums
