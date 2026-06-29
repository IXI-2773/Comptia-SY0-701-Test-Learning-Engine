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


def normalize_progress_meta(meta: MutableMapping[str, Any] | Mapping[str, Any] | None) -> ProgressMeta:
    payload: MutableMapping[str, Any]
    if isinstance(meta, MutableMapping):
        payload = meta
    else:
        payload = dict(meta or {})

    payload["xp"] = int(payload.get("xp", 0) or 0)
    payload["level"] = max(1, int(payload.get("level", 1) or 1))
    payload["badges"] = [str(value) for value in payload.get("badges", []) if str(value).strip()]
    payload["milestones"] = [str(value) for value in payload.get("milestones", []) if str(value).strip()]

    raw_session_history = payload.get("session_history", [])
    session_history: list[SessionHistoryEntry] = []
    for item in raw_session_history if isinstance(raw_session_history, list) else []:
        row = dict(item or {})
        session_history.append(
            {
                "at": str(row.get("at") or ""),
                "mode": str(row.get("mode") or ""),
                "source": str(row.get("source") or ""),
                "answered": int(row.get("answered", 0) or 0),
                "correct": int(row.get("correct", 0) or 0),
                "accuracy": float(row.get("accuracy", 0.0) or 0.0),
                "recoveries": int(row.get("recoveries", 0) or 0),
                "medal": str(row.get("medal") or ""),
                "xp_gained": int(row.get("xp_gained", 0) or 0),
                "quest_key": str(row.get("quest_key") or ""),
                "quests_completed": int(row.get("quests_completed", 0) or 0),
                "boss_hits": int(row.get("boss_hits", 0) or 0),
                "speed_risk": int(row.get("speed_risk", 0) or 0),
            }
        )
    payload["session_history"] = session_history

    raw_quest_stats = payload.get("quest_stats", {})
    quest_stats: dict[str, QuestStat] = {}
    if isinstance(raw_quest_stats, Mapping):
        for key, value in raw_quest_stats.items():
            stat = dict(value or {})
            quest_stats[str(key)] = {
                "offered": int(stat.get("offered", 0) or 0),
                "completed": int(stat.get("completed", 0) or 0),
            }
    payload["quest_stats"] = quest_stats

    raw_issue_reports = payload.get("issue_reports", [])
    issue_reports: list[IssueReport] = []
    for item in raw_issue_reports if isinstance(raw_issue_reports, list) else []:
        row = dict(item or {})
        issue_reports.append(
            {
                "question_number": int(row.get("question_number", 0) or 0),
                "source_page": str(row.get("source_page") or ""),
                "domain": str(row.get("domain") or ""),
                "prompt": str(row.get("prompt") or ""),
                "reported_at": str(row.get("reported_at") or ""),
                "status": str(row.get("status") or "open"),
                "exclude_from_scoring": bool(row.get("exclude_from_scoring")),
                "source_notes": [str(note) for note in row.get("source_notes", []) if str(note).strip()],
                "reviewed_at": str(row.get("reviewed_at") or ""),
                "restored_scoring": bool(row.get("restored_scoring")) if "restored_scoring" in row else False,
            }
        )
    payload["issue_reports"] = issue_reports

    raw_stats = payload.get("stats", {})
    stats_source = dict(raw_stats or {}) if isinstance(raw_stats, Mapping) else {}
    stats = blank_progress_stats()
    stats["total_answered"] = int(stats_source.get("total_answered", 0) or 0)
    stats["total_correct"] = int(stats_source.get("total_correct", 0) or 0)
    stats["total_recovered"] = int(stats_source.get("total_recovered", 0) or 0)
    stats["sessions_completed"] = int(stats_source.get("sessions_completed", 0) or 0)
    stats["perfect_sessions"] = int(stats_source.get("perfect_sessions", 0) or 0)
    stats["domains_seen"] = [str(value) for value in stats_source.get("domains_seen", []) if str(value).strip()]
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
