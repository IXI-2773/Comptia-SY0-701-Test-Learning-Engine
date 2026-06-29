from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, TypedDict, cast

PROGRESS_VERSION = 2
REVIEW_INTERVAL_DAYS = [1, 3, 7, 14, 30]
MAX_HISTORY_EVENTS = 4000
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
    }


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
    record: Mapping[str, Any] | None, selected, is_correct, seen_on=None, confidence=None, miss_reason=None
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
        interval = review_interval_for_streak(record["correct_streak"])
        record["next_review"] = (date.fromisoformat(seen_on) + timedelta(days=interval)).isoformat()
    else:
        record["wrong_count"] = int(record.get("wrong_count", 0)) + 1
        record["correct_streak"] = 0
        record["next_review"] = seen_on
        if miss_reason:
            record["miss_reason_counts"][miss_reason] = int(record["miss_reason_counts"].get(miss_reason, 0)) + 1
    return record


def set_progress_flag(record: Mapping[str, Any] | None, flagged) -> ProgressRecord:
    record = normalize_progress_record(record)
    record["flagged"] = bool(flagged)
    return record


def set_progress_suspended(record: Mapping[str, Any] | None, suspended) -> ProgressRecord:
    record = normalize_progress_record(record)
    record["suspended"] = bool(suspended)
    return record


def is_review_due(record: Mapping[str, Any] | None, on_date=None) -> bool:
    record = record or {}
    next_review = record.get("next_review")
    if not next_review:
        return False
    try:
        review_day = date.fromisoformat(str(next_review))
    except ValueError:
        return False
    on_date = date.fromisoformat(on_date) if isinstance(on_date, str) else (on_date or date.today())
    return review_day <= on_date


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
