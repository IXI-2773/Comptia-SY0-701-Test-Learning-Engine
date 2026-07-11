from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, TypedDict, cast

PROGRESS_VERSION = 3
REVIEW_INTERVAL_DAYS = [1, 3, 7, 14, 30]
LEARNER_MEMORY_DEFAULT = {
    "retrievability": 0.0,
    "stability": 0.0,
    "last_grade": "new",
    "next_review_at": "",
    "success_count": 0,
    "lapse_count": 0,
    "last_updated": "",
}
MAX_HISTORY_EVENTS = 4000
SUPER_CONFIDENT_COOLDOWN_DAYS = 120
CONFIDENCE_OPTIONS = ["Sure", "Unsure", "Guessed"]
MISS_REASON_OPTIONS = ["Did not know", "Misread", "Narrowed to two", "Changed answer"]
SESSION_SOURCE_ALIASES = {
    "All visible": "All",
    "Unseen only": "Unseen",
    "Answered before": "Previously answered",
    "Wrong before": "Previously wrong",
    "Flagged or due": "Due/flagged weak",
}


class ProgressRecord(TypedDict):
    attempts: int
    correct_count: int
    wrong_count: int
    correct_streak: int
    last_seen: str
    next_review: str
    last_selected: list[str]
    last_correct: bool | None
    last_confidence: str
    last_miss_reason: str
    confidence_counts: dict[str, int]
    miss_reason_counts: dict[str, int]
    flagged: bool
    suspended: bool
    super_confident_until: str
    learner_memory: dict[str, Any]


ProgressQuestionMap = dict[str, ProgressRecord]


def today_iso():
    return date.today().isoformat()


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def blank_progress(bank_name="", app_version=""):
    stamp = now_iso()
    return {
        "version": PROGRESS_VERSION,
        "app_version": app_version,
        "bank_file": bank_name,
        "created_at": stamp,
        "updated_at": stamp,
        "questions": {},
        "history": [],
    }


def default_progress_record() -> ProgressRecord:
    return {
        "attempts": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "correct_streak": 0,
        "last_seen": "",
        "next_review": "",
        "last_selected": [],
        "last_correct": None,
        "last_confidence": "",
        "last_miss_reason": "",
        "confidence_counts": {option: 0 for option in CONFIDENCE_OPTIONS},
        "miss_reason_counts": {option: 0 for option in MISS_REASON_OPTIONS},
        "flagged": False,
        "suspended": False,
        "super_confident_until": "",
        "learner_memory": dict(LEARNER_MEMORY_DEFAULT),
    }


def clamp_float(value, low=0.0, high=1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if number != number:
        number = low
    return max(low, min(high, number))


def normalize_learner_memory(memory: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(memory or {}) if isinstance(memory, Mapping) else {}
    merged = {**LEARNER_MEMORY_DEFAULT, **source}
    merged["retrievability"] = clamp_float(merged.get("retrievability"))
    merged["stability"] = clamp_float(merged.get("stability"))
    merged["last_grade"] = str(merged.get("last_grade") or "new")
    merged["next_review_at"] = str(merged.get("next_review_at") or "")
    merged["success_count"] = max(0, int(merged.get("success_count") or 0))
    merged["lapse_count"] = max(0, int(merged.get("lapse_count") or 0))
    merged["last_updated"] = str(merged.get("last_updated") or "")
    return merged


def sanitize_response_time(raw_seconds, recent_effective_seconds=None) -> dict[str, Any]:
    try:
        raw = float(raw_seconds or 0.0)
    except (TypeError, ValueError):
        raw = 0.0
    if raw != raw or raw < 0:
        raw = 0.0
    recent = sorted(
        float(value)
        for value in (recent_effective_seconds or [])
        if isinstance(value, (int, float)) and 0.7 <= float(value) <= 240.0
    )
    median = recent[len(recent) // 2] if recent else 60.0
    idle_cap = max(90.0, min(240.0, median * 3.0))
    effective = min(max(0.7, raw or 0.7), idle_cap)
    contaminated = raw <= 0 or raw > idle_cap
    return {
        "raw_response_seconds": round(raw, 1),
        "effective_response_seconds": round(effective, 1),
        "response_time_contaminated": bool(contaminated),
    }


def infer_review_grade(
    correct,
    confidence="",
    miss_reason="",
    effective_response_seconds=0.0,
    session_tag="",
    recall_failure="",
) -> str:
    confidence = normalize_confidence(confidence)
    recall_failure = str(recall_failure or "").casefold()
    session_tag = str(session_tag or "").casefold()
    if not correct:
        if confidence == "Sure" or "blank" in recall_failure:
            return "lapse_strong"
        return "lapse"
    if confidence == "Guessed":
        return "recognition"
    if confidence == "Unsure" or miss_reason:
        return "partial"
    if "transfer" in session_tag:
        return "transfer"
    if "retrieval" in session_tag or "delayed" in session_tag:
        return "retrieval"
    if float(effective_response_seconds or 0.0) >= 45.0:
        return "slow_success"
    return "confident"


def calculate_next_review(memory: Mapping[str, Any], grade: str, seen_on=None) -> str:
    day = date.fromisoformat(seen_on) if isinstance(seen_on, str) else (seen_on or date.today())
    memory = normalize_learner_memory(memory)
    stability = clamp_float(memory.get("stability"))
    days = review_days_for_grade(grade, stability)
    return (day + timedelta(days=days)).isoformat()


def review_days_for_grade(grade: str, stability=0.0) -> int:
    stability = clamp_float(stability)
    grade = str(grade or "").strip().casefold()
    if grade in {"lapse", "lapse_strong", "hard"}:
        return 0 if grade.startswith("lapse") else 1
    if grade in {"recognition", "partial", "slow_success"}:
        return 1
    if grade in {"good", "confident"}:
        return 2 + round(stability * 6)
    if grade == "retrieval":
        return 3 + round(stability * 4)
    if grade in {"easy", "transfer"}:
        return 7 + round(stability * 7)
    return 2 + round(stability * 4)


def update_learner_memory(
    memory: Mapping[str, Any] | None,
    correct,
    confidence="",
    miss_reason="",
    effective_response_seconds=0.0,
    session_tag="",
    recall_failure="",
    seen_on=None,
) -> dict[str, Any]:
    memory = normalize_learner_memory(memory)
    grade = infer_review_grade(
        correct,
        confidence=confidence,
        miss_reason=miss_reason,
        effective_response_seconds=effective_response_seconds,
        session_tag=session_tag,
        recall_failure=recall_failure,
    )
    retrievability = float(memory.get("retrievability", 0.0))
    stability = float(memory.get("stability", 0.0))
    if correct:
        delta = {
            "recognition": 0.08,
            "partial": 0.1,
            "slow_success": 0.11,
            "confident": 0.18,
            "retrieval": 0.24,
            "transfer": 0.3,
        }.get(grade, 0.14)
        retrievability = clamp_float(retrievability + delta)
        stability = clamp_float(stability + delta * 0.75)
        memory["success_count"] = int(memory.get("success_count", 0)) + 1
    else:
        reason = normalize_miss_reason(miss_reason)
        penalty = 0.26 if grade == "lapse_strong" else 0.18
        if reason == "Did not know":
            penalty += 0.08
        elif reason == "Misread":
            penalty -= 0.04
        retrievability = clamp_float(retrievability - penalty)
        stability = clamp_float(stability - penalty * 0.8)
        memory["lapse_count"] = int(memory.get("lapse_count", 0)) + 1
    memory["retrievability"] = round(retrievability, 3)
    memory["stability"] = round(stability, 3)
    memory["last_grade"] = grade
    memory["next_review_at"] = calculate_next_review(memory, grade, seen_on=seen_on)
    memory["last_updated"] = str(seen_on or today_iso())
    return memory


def normalize_progress_record(record: Mapping[str, Any] | None) -> ProgressRecord:
    merged = {**default_progress_record(), **(record or {})}
    merged["confidence_counts"] = {
        **default_progress_record()["confidence_counts"],
        **dict(merged.get("confidence_counts") or {}),
    }
    merged["miss_reason_counts"] = {
        **default_progress_record()["miss_reason_counts"],
        **dict(merged.get("miss_reason_counts") or {}),
    }
    merged["attempts"] = int(merged.get("attempts", 0) or 0)
    merged["correct_count"] = int(merged.get("correct_count", 0) or 0)
    merged["wrong_count"] = int(merged.get("wrong_count", 0) or 0)
    merged["correct_streak"] = int(merged.get("correct_streak", 0) or 0)
    merged["last_seen"] = str(merged.get("last_seen", "") or "")
    merged["next_review"] = str(merged.get("next_review", "") or "")
    merged["last_selected"] = [str(value) for value in merged.get("last_selected", [])]
    merged["last_correct"] = None if merged.get("last_correct") is None else bool(merged.get("last_correct"))
    merged["last_confidence"] = str(merged.get("last_confidence", "") or "")
    merged["last_miss_reason"] = str(merged.get("last_miss_reason", "") or "")
    merged["confidence_counts"] = {str(key): int(value or 0) for key, value in merged["confidence_counts"].items()}
    merged["miss_reason_counts"] = {str(key): int(value or 0) for key, value in merged["miss_reason_counts"].items()}
    merged["flagged"] = bool(merged.get("flagged"))
    merged["suspended"] = bool(merged.get("suspended"))
    merged["super_confident_until"] = str(merged.get("super_confident_until", "") or "")
    legacy_next_review = str(merged.get("next_review", "") or "")
    had_learner_memory = isinstance(merged.get("learner_memory"), Mapping)
    learner_memory = normalize_learner_memory(merged.get("learner_memory"))
    if not had_learner_memory and int(merged.get("attempts", 0) or 0) > 0:
        streak = max(0, int(merged.get("correct_streak", 0) or 0))
        wrong = max(0, int(merged.get("wrong_count", 0) or 0))
        learner_memory["retrievability"] = clamp_float(min(0.65, 0.18 + streak * 0.12 - wrong * 0.05))
        learner_memory["stability"] = clamp_float(min(0.55, 0.12 + streak * 0.1))
    if not learner_memory.get("next_review_at") and legacy_next_review:
        learner_memory["next_review_at"] = legacy_next_review
    merged["learner_memory"] = learner_memory
    merged["next_review"] = str(learner_memory.get("next_review_at") or legacy_next_review)
    return cast(ProgressRecord, merged)


def review_interval_for_streak(correct_streak):
    if correct_streak <= 0:
        return 0
    idx = min(correct_streak - 1, len(REVIEW_INTERVAL_DAYS) - 1)
    return REVIEW_INTERVAL_DAYS[idx]


def is_ever_wrong(record: Mapping[str, Any] | None) -> bool:
    record = record or {}
    return int(record.get("wrong_count", 0)) > 0


def is_suspended(record: Mapping[str, Any] | None) -> bool:
    record = record or {}
    return bool(record.get("suspended"))


def is_active_weak(record: Mapping[str, Any] | None) -> bool:
    record = record or {}
    if is_suspended(record):
        return False
    wrong = int(record.get("wrong_count", 0))
    if wrong <= 0:
        return False
    if record.get("last_correct") is False:
        return True
    return wrong > int(record.get("correct_count", 0))


def normalize_confidence(value):
    value = str(value or "").strip().title()
    return value if value in CONFIDENCE_OPTIONS else "Sure"


def normalize_miss_reason(value):
    value = str(value or "").strip()
    return value if value in MISS_REASON_OPTIONS else ""


def study_status_name(record: Mapping[str, Any] | None, on_date=None) -> str:
    record = record or {}
    if is_suspended(record):
        return "Suspended"
    attempts = int(record.get("attempts", 0))
    if attempts <= 0:
        return "New"
    if bool(record.get("flagged")):
        return "Flagged"
    if is_active_weak(record):
        return "Active weak"
    if is_review_due(record, on_date=on_date) and is_ever_wrong(record):
        return "Recovered - due"
    if is_review_due(record, on_date=on_date):
        return "Due review"
    if is_ever_wrong(record):
        return "Recovered"
    if int(record.get("correct_streak", 0)) >= 4:
        return "Mastered"
    return "In progress"


def recovery_ladder_stage(record: Mapping[str, Any] | None, on_date=None) -> str:
    record = record or {}
    if is_suspended(record):
        return "Suspended"
    attempts = int(record.get("attempts", 0))
    if attempts <= 0:
        return "New"
    streak = int(record.get("correct_streak", 0))
    wrong = int(record.get("wrong_count", 0))
    if is_active_weak(record):
        if wrong >= 3 or record.get("last_correct") is False:
            return "Fragile"
        return "Recovering"
    if wrong > 0:
        if streak >= 4:
            return "Mastered"
        if streak >= 3:
            return "Trusted"
        if streak >= 2:
            return "Stable"
        return "Recovering"
    if streak >= 4:
        return "Mastered"
    if streak >= 3:
        return "Trusted"
    if streak >= 2:
        return "Stable"
    return "Building"


def update_progress_record(
    record: Mapping[str, Any] | None,
    selected,
    is_correct,
    seen_on=None,
    confidence=None,
    miss_reason=None,
    effective_response_seconds=0.0,
    session_tag="",
    recall_failure="",
) -> ProgressRecord:
    record = normalize_progress_record(record)
    seen_on = seen_on or today_iso()
    selected = sorted(list(selected or []))
    confidence = normalize_confidence(confidence)
    miss_reason = normalize_miss_reason(miss_reason) if not is_correct else ""
    record["attempts"] = int(record.get("attempts", 0)) + 1
    record["last_seen"] = seen_on
    record["last_selected"] = selected
    record["last_correct"] = bool(is_correct)
    record["last_confidence"] = confidence
    record["last_miss_reason"] = miss_reason
    record["confidence_counts"][confidence] = int(record["confidence_counts"].get(confidence, 0)) + 1
    if is_correct:
        record["correct_count"] = int(record.get("correct_count", 0)) + 1
        record["correct_streak"] = int(record.get("correct_streak", 0)) + 1
    else:
        record["wrong_count"] = int(record.get("wrong_count", 0)) + 1
        record["correct_streak"] = 0
        if miss_reason:
            record["miss_reason_counts"][miss_reason] = int(record["miss_reason_counts"].get(miss_reason, 0)) + 1
    record["learner_memory"] = update_learner_memory(
        record.get("learner_memory"),
        is_correct,
        confidence=confidence,
        miss_reason=miss_reason,
        effective_response_seconds=effective_response_seconds,
        session_tag=session_tag,
        recall_failure=recall_failure,
        seen_on=seen_on,
    )
    record["next_review"] = str(record["learner_memory"].get("next_review_at") or "")
    return record


def set_progress_flag(record: Mapping[str, Any] | None, flagged) -> ProgressRecord:
    record = normalize_progress_record(record)
    record["flagged"] = bool(flagged)
    return record


def set_progress_suspended(record: Mapping[str, Any] | None, suspended) -> ProgressRecord:
    record = normalize_progress_record(record)
    record["suspended"] = bool(suspended)
    return record


def is_super_confident_active(record: Mapping[str, Any] | None, on_date=None) -> bool:
    record = record or {}
    until = str(record.get("super_confident_until", "") or "").strip()
    if not until:
        return False
    try:
        until_day = date.fromisoformat(until)
    except ValueError:
        return False
    on_date = date.fromisoformat(on_date) if isinstance(on_date, str) else (on_date or date.today())
    return until_day >= on_date


def set_progress_super_confident(
    record: Mapping[str, Any] | None,
    *,
    seen_on=None,
    cooldown_days: int = SUPER_CONFIDENT_COOLDOWN_DAYS,
) -> ProgressRecord:
    record = normalize_progress_record(record)
    day = date.fromisoformat(seen_on) if isinstance(seen_on, str) else (seen_on or date.today())
    until = day + timedelta(days=max(1, int(cooldown_days or SUPER_CONFIDENT_COOLDOWN_DAYS)))
    confidence = normalize_confidence(record.get("last_confidence") or "Sure")
    if confidence != "Sure":
        counts = dict(record.get("confidence_counts") or {})
        counts[confidence] = max(0, int(counts.get(confidence, 0)) - 1)
        counts["Sure"] = int(counts.get("Sure", 0)) + 1
        record["confidence_counts"] = counts
    record["last_confidence"] = "Sure"
    record["last_miss_reason"] = ""
    record["correct_streak"] = max(6, int(record.get("correct_streak", 0) or 0))
    record["last_correct"] = True
    memory = normalize_learner_memory(record.get("learner_memory"))
    memory["retrievability"] = max(0.995, float(memory.get("retrievability", 0.0) or 0.0))
    memory["stability"] = max(0.98, float(memory.get("stability", 0.0) or 0.0))
    memory["last_grade"] = "easy"
    memory["next_review_at"] = until.isoformat()
    memory["last_updated"] = day.isoformat()
    record["learner_memory"] = memory
    record["next_review"] = until.isoformat()
    record["super_confident_until"] = until.isoformat()
    return record


def is_review_due(record: Mapping[str, Any] | None, on_date=None) -> bool:
    record = record or {}
    memory = normalize_learner_memory(record.get("learner_memory"))
    next_review = memory.get("next_review_at") or record.get("next_review")
    if int(record.get("attempts", 0) or 0) > 0 and float(memory.get("retrievability", 0.0) or 0.0) <= 0.05:
        return True
    if not next_review:
        return False
    try:
        review_day = date.fromisoformat(str(next_review))
    except ValueError:
        return False
    on_date = date.fromisoformat(on_date) if isinstance(on_date, str) else (on_date or date.today())
    return review_day <= on_date


def aggregate_concept_memory(records: Mapping[str, Mapping[str, Any]], questions) -> dict[str, dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for question in questions:
        qnum = str(question.get("question_number"))
        objective = str(question.get("objective_code") or "").strip()
        topics = [str(topic).strip() for topic in question.get("topics", []) if str(topic).strip()]
        domain = str(question.get("domain") or "Unsorted").strip()
        key = f"Objective::{objective}" if objective else f"Topic::{topics[0]}" if topics else f"Domain::{domain}"
        rec = normalize_progress_record(records.get(qnum, {}))
        memory = normalize_learner_memory(rec.get("learner_memory"))
        row = aggregates.setdefault(
            key,
            {
                "stability": 0.0,
                "lowest_retrievability": 1.0,
                "uncertainty": 1.0,
                "supporting_question_count": 0,
                "distinct_source_count": 0,
                "distinct_stem_style_count": 0,
                "_sources": set(),
                "_styles": set(),
            },
        )
        row["supporting_question_count"] += 1
        row["stability"] += float(memory.get("stability", 0.0) or 0.0)
        row["lowest_retrievability"] = min(
            float(row["lowest_retrievability"]), float(memory.get("retrievability", 0.0) or 0.0)
        )
        row["_sources"].add(str(question.get("source_name") or question.get("source_label") or "Unknown source"))
        row["_styles"].add(str(question.get("stem_style") or question.get("question_type") or "unknown"))
    for row in aggregates.values():
        count = max(1, int(row["supporting_question_count"]))
        row["stability"] = round(clamp_float(float(row["stability"]) / count), 3)
        row["uncertainty"] = round(1.0 - row["stability"], 3)
        row["distinct_source_count"] = len(row.pop("_sources"))
        row["distinct_stem_style_count"] = len(row.pop("_styles"))
    return aggregates


def question_key(q):
    return str(q.get("question_number"))


def select_due_review_questions(questions, records: Mapping[str, Mapping[str, Any]], on_date=None):
    def due_sort(q):
        rec = records.get(question_key(q), {})
        return (
            rec.get("next_review") or "9999-12-31",
            -int(rec.get("wrong_count", 0)),
            int(q.get("question_number", 0)),
        )

    return sorted(
        [
            q
            for q in questions
            if not q.get("suspended")
            and not is_suspended(records.get(question_key(q), {}))
            and is_review_due(records.get(question_key(q), {}), on_date=on_date)
        ],
        key=due_sort,
    )


def select_questions_by_history(questions, records: Mapping[str, Mapping[str, Any]], source, on_date=None):
    source = SESSION_SOURCE_ALIASES.get(source, source)
    if source == "All visible":
        return list(questions)
    if source == "All":
        return list(questions)

    out = []
    for q in questions:
        rec = records.get(question_key(q), {}) or {}
        if q.get("suspended") or is_suspended(rec):
            continue
        attempts = int(rec.get("attempts", 0))
        flagged = bool(rec.get("flagged")) or bool(q.get("flagged"))
        due = is_review_due(rec, on_date=on_date)
        weak = is_active_weak(rec)

        if source == "Unseen" and attempts == 0:
            out.append(q)
        elif source == "Previously answered" and attempts > 0:
            out.append(q)
        elif source == "Previously wrong" and weak:
            out.append(q)
        elif source == "Due/flagged weak" and (flagged or due or weak):
            out.append(q)

    return out


def append_progress_history(progress_data, event):
    progress_data = progress_data or {}
    history = list(progress_data.get("history") or [])
    history.append(dict(event))
    if len(history) > MAX_HISTORY_EVENTS:
        history = history[-MAX_HISTORY_EVENTS:]
    progress_data["history"] = history
    return history
