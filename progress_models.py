from collections.abc import Mapping, MutableMapping
from typing import Any, NotRequired, TypedDict, cast


class ProgressStats(TypedDict):
    total_answered: int
    total_correct: int
    total_recovered: int
    sessions_completed: int
    perfect_sessions: int
    domains_seen: list[str]


class QuestStat(TypedDict):
    offered: int
    completed: int


class SessionHistoryEntry(TypedDict):
    at: str
    mode: str
    source: str
    answered: int
    correct: int
    accuracy: float
    recoveries: int
    medal: str
    xp_gained: int
    quest_key: str
    quests_completed: int
    boss_hits: int
    speed_risk: int


class IssueReport(TypedDict):
    question_number: int
    source_page: str
    domain: str
    prompt: str
    reported_at: str
    status: str
    exclude_from_scoring: bool
    source_notes: list[str]
    reviewed_at: NotRequired[str]
    restored_scoring: NotRequired[bool]


class ProgressMeta(TypedDict):
    xp: int
    level: int
    badges: list[str]
    milestones: list[str]
    session_history: list[SessionHistoryEntry]
    quest_stats: dict[str, QuestStat]
    issue_reports: list[IssueReport]
    stats: ProgressStats
    repair_state: dict[str, dict[str, Any]]
    smart_practice_measurement: dict[str, Any]
    smart_practice_policy_governance: dict[str, Any]
    smart_practice_concept_graph: dict[str, Any]
    smart_practice_question_calibration: dict[str, Any]
    smart_practice_rotation: dict[str, Any]


class ProgressSummary(TypedDict):
    attempted: int
    due: int
    flagged: int
    wrong: int
    recovered: int
    ever_wrong: int
    mastered: int


def blank_progress_stats() -> ProgressStats:
    return {
        "total_answered": 0,
        "total_correct": 0,
        "total_recovered": 0,
        "sessions_completed": 0,
        "perfect_sessions": 0,
        "domains_seen": [],
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


def _coerce_float(value: Any, *, field: str, default: float = 0.0, minimum: float | None = None) -> float:
    if value in (None, ""):
        number = default
    else:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid float for {field}: {value!r}") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"Invalid float for {field}: {number!r}")
    return number


def _coerce_str_list(value: Any, *, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid list for {field}")
    return [str(item) for item in value if str(item).strip()]


def _normalize_positive_int_list(value: Any, *, field: str, limit: int = 64) -> list[int]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return []
    clean: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            clean.append(number)
    return clean[-limit:]


def normalize_progress_meta(meta: MutableMapping[str, Any] | Mapping[str, Any] | None) -> ProgressMeta:
    payload: MutableMapping[str, Any]
    if isinstance(meta, MutableMapping):
        payload = meta
    else:
        payload = dict(meta or {})

    payload["xp"] = _coerce_int(payload.get("xp", 0), field="meta.xp", minimum=0)
    payload["level"] = max(1, _coerce_int(payload.get("level", 1), field="meta.level", default=1))
    payload["badges"] = _coerce_str_list(payload.get("badges", []), field="meta.badges")
    payload["milestones"] = _coerce_str_list(payload.get("milestones", []), field="meta.milestones")
    repair_state = payload.get("repair_state", {})
    payload["repair_state"] = dict(repair_state) if isinstance(repair_state, Mapping) else {}
    measurement = payload.get("smart_practice_measurement", {})
    payload["smart_practice_measurement"] = dict(measurement) if isinstance(measurement, Mapping) else {}
    governance = payload.get("smart_practice_policy_governance", {})
    payload["smart_practice_policy_governance"] = dict(governance) if isinstance(governance, Mapping) else {}
    graph = payload.get("smart_practice_concept_graph", {})
    payload["smart_practice_concept_graph"] = dict(graph) if isinstance(graph, Mapping) else {}
    calibration = payload.get("smart_practice_question_calibration", {})
    payload["smart_practice_question_calibration"] = dict(calibration) if isinstance(calibration, Mapping) else {}
    rotation = payload.get("smart_practice_rotation", {})
    rotation_payload = dict(rotation) if isinstance(rotation, Mapping) else {}
    payload["smart_practice_rotation"] = {
        "epoch": _coerce_int(rotation_payload.get("epoch", 0), field="meta.smart_practice_rotation.epoch", minimum=0),
        "last_membership_qnums": _normalize_positive_int_list(
            rotation_payload.get("last_membership_qnums", []),
            field="meta.smart_practice_rotation.last_membership_qnums",
        ),
        "pending_reference_qnums": _normalize_positive_int_list(
            rotation_payload.get("pending_reference_qnums", []),
            field="meta.smart_practice_rotation.pending_reference_qnums",
        ),
    }

    raw_session_history = payload.get("session_history", [])
    if raw_session_history not in (None, "") and not isinstance(raw_session_history, list):
        raise ValueError("Invalid list for meta.session_history")
    session_history: list[SessionHistoryEntry] = []
    for item in raw_session_history if isinstance(raw_session_history, list) else []:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid session history row")
        row = dict(item or {})
        session_history.append(
            {
                "at": str(row.get("at") or ""),
                "mode": str(row.get("mode") or ""),
                "source": str(row.get("source") or ""),
                "answered": _coerce_int(row.get("answered", 0), field="meta.session_history.answered", minimum=0),
                "correct": _coerce_int(row.get("correct", 0), field="meta.session_history.correct", minimum=0),
                "accuracy": _coerce_float(row.get("accuracy", 0.0), field="meta.session_history.accuracy", minimum=0.0),
                "recoveries": _coerce_int(row.get("recoveries", 0), field="meta.session_history.recoveries", minimum=0),
                "medal": str(row.get("medal") or ""),
                "xp_gained": _coerce_int(row.get("xp_gained", 0), field="meta.session_history.xp_gained", minimum=0),
                "quest_key": str(row.get("quest_key") or ""),
                "quests_completed": _coerce_int(
                    row.get("quests_completed", 0), field="meta.session_history.quests_completed", minimum=0
                ),
                "boss_hits": _coerce_int(row.get("boss_hits", 0), field="meta.session_history.boss_hits", minimum=0),
                "speed_risk": _coerce_int(row.get("speed_risk", 0), field="meta.session_history.speed_risk", minimum=0),
            }
        )
    payload["session_history"] = session_history

    raw_quest_stats = payload.get("quest_stats", {})
    if raw_quest_stats not in (None, "") and not isinstance(raw_quest_stats, Mapping):
        raise ValueError("Invalid mapping for meta.quest_stats")
    quest_stats: dict[str, QuestStat] = {}
    if isinstance(raw_quest_stats, Mapping):
        for key, value in raw_quest_stats.items():
            if not isinstance(value, Mapping):
                raise ValueError("Invalid quest stat row")
            stat = dict(value or {})
            quest_stats[str(key)] = {
                "offered": _coerce_int(stat.get("offered", 0), field=f"meta.quest_stats.{key}.offered", minimum=0),
                "completed": _coerce_int(
                    stat.get("completed", 0), field=f"meta.quest_stats.{key}.completed", minimum=0
                ),
            }
    payload["quest_stats"] = quest_stats

    raw_issue_reports = payload.get("issue_reports", [])
    if raw_issue_reports not in (None, "") and not isinstance(raw_issue_reports, list):
        raise ValueError("Invalid list for meta.issue_reports")
    issue_reports: list[IssueReport] = []
    for item in raw_issue_reports if isinstance(raw_issue_reports, list) else []:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid issue report row")
        row = dict(item or {})
        source_notes = row.get("source_notes", [])
        if source_notes not in (None, "") and not isinstance(source_notes, list):
            raise ValueError("Invalid list for meta.issue_reports.source_notes")
        issue_reports.append(
            {
                "question_number": _coerce_int(
                    row.get("question_number", 0), field="meta.issue_reports.question_number", minimum=0
                ),
                "source_page": str(row.get("source_page") or ""),
                "domain": str(row.get("domain") or ""),
                "prompt": str(row.get("prompt") or ""),
                "reported_at": str(row.get("reported_at") or ""),
                "status": str(row.get("status") or "open"),
                "exclude_from_scoring": bool(row.get("exclude_from_scoring")),
                "source_notes": [str(note) for note in source_notes if str(note).strip()],
                "reviewed_at": str(row.get("reviewed_at") or ""),
                "restored_scoring": bool(row.get("restored_scoring")) if "restored_scoring" in row else False,
            }
        )
    payload["issue_reports"] = issue_reports

    raw_stats = payload.get("stats", {})
    stats_source = dict(raw_stats or {}) if isinstance(raw_stats, Mapping) else {}
    stats = blank_progress_stats()
    stats["total_answered"] = _coerce_int(
        stats_source.get("total_answered", 0), field="meta.stats.total_answered", minimum=0
    )
    stats["total_correct"] = _coerce_int(
        stats_source.get("total_correct", 0), field="meta.stats.total_correct", minimum=0
    )
    stats["total_recovered"] = _coerce_int(
        stats_source.get("total_recovered", 0), field="meta.stats.total_recovered", minimum=0
    )
    stats["sessions_completed"] = _coerce_int(
        stats_source.get("sessions_completed", 0), field="meta.stats.sessions_completed", minimum=0
    )
    stats["perfect_sessions"] = _coerce_int(
        stats_source.get("perfect_sessions", 0), field="meta.stats.perfect_sessions", minimum=0
    )
    stats["domains_seen"] = _coerce_str_list(stats_source.get("domains_seen", []), field="meta.stats.domains_seen")
    payload["stats"] = stats

    return cast(ProgressMeta, payload)


def issue_report_from_question(
    question: Mapping[str, Any], *, exclude_from_scoring: bool, reported_at: str
) -> IssueReport:
    return {
        "question_number": int(question.get("question_number", 0) or 0),
        "source_page": str(question.get("source_page", "") or ""),
        "domain": str(question.get("domain", "") or ""),
        "prompt": str(question.get("prompt", "") or "")[:220],
        "reported_at": str(reported_at or ""),
        "status": "open",
        "exclude_from_scoring": bool(exclude_from_scoring),
        "source_notes": [str(note) for note in question.get("flagged_issues", []) if str(note).strip()],
    }


def session_history_entry_from_summary(
    *,
    at: str,
    mode: str,
    source: str,
    answered: int,
    correct: int,
    accuracy: float,
    recoveries: int,
    medal: str,
    xp_gained: int,
    quest_key: str,
    quests_completed: int,
    boss_hits: int,
    speed_risk: int,
) -> SessionHistoryEntry:
    return {
        "at": str(at or ""),
        "mode": str(mode or ""),
        "source": str(source or ""),
        "answered": int(answered or 0),
        "correct": int(correct or 0),
        "accuracy": float(accuracy or 0.0),
        "recoveries": int(recoveries or 0),
        "medal": str(medal or ""),
        "xp_gained": int(xp_gained or 0),
        "quest_key": str(quest_key or ""),
        "quests_completed": int(quests_completed or 0),
        "boss_hits": int(boss_hits or 0),
        "speed_risk": int(speed_risk or 0),
    }
