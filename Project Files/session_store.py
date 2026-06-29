import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from session_models import (
    AnswerState,
    BuilderContext,
    QuestProgressState,
    SessionAnswerEvent,
    SessionSnapshot,
    answer_state_from_question,
)

SESSION_SCHEMA_VERSION = 3


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


def migrate_session_snapshot(
    saved: Mapping[str, Any] | None, mode: str, question_numbers: list[Any]
) -> SessionSnapshot:
    payload = dict(saved or {})
    current_qnums = [int(qnum) for qnum in question_numbers]
    saved_qnums = [int(qnum) for qnum in payload.get("question_numbers", []) if str(qnum).strip()]
    restore_qnums = (
        [int(qnum) for qnum in payload.get("restore_question_numbers", []) if str(qnum).strip()]
        or saved_qnums
        or current_qnums
    )
    base_count = int(
        payload.get("session_base_question_count") or len(restore_qnums) or len(saved_qnums) or len(current_qnums)
    )
    limit = payload.get("session_question_limit")
    try:
        session_limit = int(limit or 0)
    except (TypeError, ValueError):
        session_limit = 0
    if session_limit <= 0:
        session_limit = calculate_session_question_limit(base_count)
    answers = [cast(AnswerState, dict(answer)) for answer in payload.get("answers", [])]
    answer_history = [cast(SessionAnswerEvent, dict(event)) for event in payload.get("session_answer_history", [])]
    quests = [cast(QuestProgressState, dict(quest)) for quest in payload.get("current_quests", [])]
    builder_context = normalize_builder_context(
        payload.get("builder_context"),
        mode=str(payload.get("mode") or mode),
        source_label=str(payload.get("source_label") or ""),
        question_count=base_count,
    )
    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "app_version": str(payload.get("app_version") or ""),
        "bank_file": str(payload.get("bank_file") or ""),
        "mode": str(payload.get("mode") or mode),
        "builder_context": builder_context,
        "source_label": str(payload.get("source_label") or ""),
        "question_count": int(payload.get("question_count") or len(saved_qnums) or len(current_qnums)),
        "question_numbers": saved_qnums or current_qnums,
        "restore_question_numbers": restore_qnums,
        "session_base_question_count": base_count,
        "session_question_limit": session_limit,
        "restore_signature": str(payload.get("restore_signature") or session_signature(mode, restore_qnums)),
        "session_signature": str(
            payload.get("session_signature") or session_signature(mode, saved_qnums or current_qnums)
        ),
        "current_index": int(payload.get("current_index", 0) or 0),
        "elapsed_seconds": int(payload.get("elapsed_seconds", 0) or 0),
        "exam_reveal": bool(payload.get("exam_reveal", mode != "Exam")),
        "checkpoints_saved": [str(value) for value in payload.get("checkpoints_saved", [])],
        "session_rewards": [str(value) for value in payload.get("session_rewards", [])],
        "unlocked_rewards": [str(value) for value in payload.get("unlocked_rewards", [])],
        "session_answer_history": answer_history,
        "current_quests": quests,
        "quest_completion_keys": [str(value) for value in payload.get("quest_completion_keys", [])],
        "session_boss_markers": [int(value) for value in payload.get("session_boss_markers", [])],
        "session_stealth_markers": [int(value) for value in payload.get("session_stealth_markers", [])],
        "session_xp_gained": int(payload.get("session_xp_gained", 0) or 0),
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
    saved_qnums = [int(qnum) for qnum in saved.get("question_numbers", []) if str(qnum).strip()]
    return bool(saved_qnums) and saved_qnums == [int(qnum) for qnum in current_question_numbers]
