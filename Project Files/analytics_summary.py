from typing import TypedDict

from analytics_models import AnalyticsPayload


class AnalyticsSummaryCard(TypedDict):
    title: str
    headline: str
    detail: str
    tone: str


class AnalyticsSummaryViewModel(TypedDict):
    readiness: AnalyticsSummaryCard
    next_move: AnalyticsSummaryCard
    retention: AnalyticsSummaryCard
    momentum: AnalyticsSummaryCard
    source_health: AnalyticsSummaryCard


def _card(title: str, headline: str, detail: str, tone: str = "neutral") -> AnalyticsSummaryCard:
    return {"title": title, "headline": headline, "detail": detail, "tone": tone}


def build_analytics_summary(payload: AnalyticsPayload) -> AnalyticsSummaryViewModel:
    overall = payload["overall"]
    progress = payload["progress"]
    prediction = payload.get("pass_prediction") or {}
    readiness = float(prediction.get("score") or overall.get("pass_prediction_score") or 0.0)
    readiness_floor = float(prediction.get("readiness_floor") or 0.0)
    readiness_label = str(prediction.get("label") or overall.get("pass_prediction_label") or "Not ready")
    readiness_tone = "good" if readiness >= 75 else ("watch" if readiness >= 60 else "risk")

    remediation = payload.get("remediation_cards") or []
    roi = payload.get("roi_questions") or []
    recommendations = payload.get("recommendations") or []
    if remediation:
        first = remediation[0]
        next_headline = str(first.get("concept") or "Target weak concepts")
        next_detail = str(first.get("action") or first.get("diagnosis") or "")
    elif roi:
        first_roi = roi[0]
        next_headline = f"Review Q{first_roi.get('question_number', '?')}"
        next_detail = f"{first_roi.get('domain', 'Priority review')} | ROI {first_roi.get('roi', 0)}"
    else:
        next_headline = "Keep building coverage"
        next_detail = (
            str(recommendations[0]) if recommendations else "Answer more questions to unlock a focused recommendation."
        )

    due = int(progress.get("due") or 0)
    weak = int(progress.get("wrong") or 0)
    recovered = int(progress.get("recovered") or 0)
    mastered = int(progress.get("mastered") or 0)
    retention_tone = "risk" if weak > recovered + mastered else ("watch" if due else "good")

    recent_accuracy = float(overall.get("recent50_accuracy") or 0.0)
    stability = float(overall.get("stability_score") or 0.0)
    streak = int(overall.get("current_streak") or 0)
    momentum_tone = (
        "good" if recent_accuracy >= 80 and stability >= 70 else ("watch" if recent_accuracy >= 65 else "risk")
    )

    trust_rows = payload.get("source_trust") or []
    weakest = min(trust_rows, key=lambda row: float(row.get("trust_score") or 0.0), default=None)
    conflict_count = sum(int(row.get("conflict_count") or 0) for row in trust_rows)
    issue_count = sum(int(row.get("issue_count") or 0) for row in trust_rows)
    if weakest:
        source_headline = f"{weakest.get('source_name', 'Unknown source')} | {weakest.get('trust_score', 0)}%"
        source_detail = f"{conflict_count} conflicts | {issue_count} reported issues"
        source_tone = "risk" if weakest.get("label") == "Decayed" or conflict_count else "good"
    else:
        source_headline = "No source risk detected"
        source_detail = "Trust signals will appear as source evidence accumulates."
        source_tone = "good"

    return {
        "readiness": _card(
            "Exam readiness",
            f"{readiness_label} | {readiness:.1f}%",
            f"Readiness floor {readiness_floor:.1f}%",
            readiness_tone,
        ),
        "next_move": _card("Next best move", next_headline, next_detail, "focus"),
        "retention": _card(
            "Retention",
            f"{due} due | {weak} active weak",
            f"{recovered} recovered | {mastered} mastered",
            retention_tone,
        ),
        "momentum": _card(
            "Momentum",
            f"{recent_accuracy:.1f}% recent | streak {streak}",
            f"Stability {stability:.1f}%",
            momentum_tone,
        ),
        "source_health": _card("Source health", source_headline, source_detail, source_tone),
    }
