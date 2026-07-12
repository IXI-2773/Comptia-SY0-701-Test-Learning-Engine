import copy
import re
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

from analytics_models import (
    AbstractionLadderRow,
    AnalyticsDomainRow,
    AnalyticsOverall,
    AnalyticsPayload,
    AnalyticsRoiRow,
    AnalyticsTopicRow,
    AnalyticsVolatilityRow,
    AnswerLatencyDiagnosisRow,
    BlindSpotInferenceRow,
    BurnoutRiskRow,
    CompressionPointRow,
    ConceptAnchorNoteRow,
    ConceptClusterRow,
    ConceptHalfLifeRow,
    ConceptMemoryStateRow,
    ConceptStateRow,
    ConfidenceCalibrationRow,
    ConfidenceCompressionRow,
    ConfidenceMismatchRow,
    ConfusionPairRow,
    ContrastRuleRow,
    CounterexampleTrainingRow,
    CounterfactualDistractorRow,
    CoverageGapRow,
    CueDependenceRow,
    DecidingClueRow,
    DecisionLatencyRow,
    DelayedProbeRow,
    DifficultyCalibrationRow,
    EffortEfficiencyRow,
    ErrorBoundaryRow,
    ExpectedLearningGainRow,
    FailureModeRow,
    GeneralizationScoreRow,
    InterferenceMapRow,
    KnowledgeTraceRow,
    LatentWeaknessRow,
    LeverageRankingRow,
    MasteryMapRow,
    MisconceptionFingerprintRow,
    ObjectiveMasteryRow,
    PassPrediction,
    PhrasingNormalizationRow,
    PrerequisiteDebtRow,
    RecallFailureRow,
    RecognitionRetrievalRow,
    ReinforcementDistanceRow,
    RemediationCardRow,
    RetentionStressRow,
    RobustnessScoreRow,
    SourceAgreementRow,
    SourceTrustRow,
    SynthesisCheckRow,
    TransferStrengthRow,
    TrapWordPatternRow,
    WrongAnswerFamilyRow,
    WrongAnswerMemoryRow,
)
from analytics_recommendations import AnalyticsRecommendationInputs, build_analytics_recommendations
from analytics_summary import AnalyticsSummaryCard, build_analytics_summary
from app_constants import MODE_EXAM
from config_store import DEFAULT_CONFIG
from progress_models import ProgressSummary
from progress_store import (
    CONFIDENCE_OPTIONS,
    is_active_weak,
    is_ever_wrong,
    is_review_due,
    is_suspended,
    recovery_ladder_stage,
    study_status_name,
)
from question_bank import sanitize_text
from session_models import QuestionHistoryEvent
from smart_practice_measurement import build_measurement_report, normalize_measurement_store
from smart_practice_policy import (
    activate_candidate_policy as activate_policy_governance,
)
from smart_practice_policy import (
    build_policy_review_report as build_policy_governance_review_report,
)
from smart_practice_policy import (
    create_candidate_policy,
    create_shadow_decision,
    detect_drift,
    evaluate_challenger,
    normalize_governance,
)
from smart_practice_policy import (
    rollback_policy as rollback_policy_governance,
)
from storage_utils import safe_write_json
from study_question_utils import (
    coverage_unit_for_question,
    normalized_study_label,
    primary_topic_label,
    question_mentions_label,
    stem_style_for_question,
)
from widget_models import AnalyticsWidgetRegistry

BLUE = "#0b4b88"
BG = "#ececec"
CARD = "#ffffff"
TEXT = "#1f1f1f"


class AnalyticsMixin:
    STEM_STYLE_LADDER = ("Definition", "Scenario", "Troubleshooting", "Best fit", "Order", "Exception", "General")

    def _analytics_runtime_cache(self):
        cache = getattr(self, "_analytics_runtime_cache_store", None)
        if cache is None:
            cache = {}
            self._analytics_runtime_cache_store = cache
        return cache

    def policy_governance(self):
        meta = self.progress_data.setdefault("meta", {})
        governance = normalize_governance(meta.get("smart_practice_policy_governance"))
        meta["smart_practice_policy_governance"] = governance
        return governance

    def _save_policy_governance(self, governance, *, invalidate=True):
        self.progress_data.setdefault("meta", {})["smart_practice_policy_governance"] = governance
        if invalidate:
            self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=250)
        self.schedule_progress_save()

    def create_smart_practice_candidate_policy(self, recommendations, *, created_at=None, actor="user"):
        candidate, governance, rejected = create_candidate_policy(
            self.policy_governance(),
            recommendations,
            created_at=created_at,
            actor=actor,
        )
        self._save_policy_governance(governance, invalidate=False)
        return candidate, rejected

    def record_smart_practice_shadow_decision(
        self,
        champion_questions,
        challenger_questions,
        *,
        challenger_policy_id,
        created_at,
        learner_state_signature,
        candidate_snapshot_signature,
    ):
        decision, governance = create_shadow_decision(
            self.policy_governance(),
            champion_questions,
            challenger_questions,
            challenger_policy_id=challenger_policy_id,
            created_at=created_at,
            learner_state_signature=learner_state_signature,
            candidate_snapshot_signature=candidate_snapshot_signature,
        )
        self._save_policy_governance(governance, invalidate=False)
        return decision

    def evaluate_smart_practice_challenger(self, candidate_policy_id, outcome_support, *, evaluated_at):
        evaluation, governance = evaluate_challenger(
            self.policy_governance(),
            candidate_policy_id,
            outcome_support,
            evaluated_at=evaluated_at,
        )
        self._save_policy_governance(governance, invalidate=False)
        return evaluation

    def activate_smart_practice_policy(
        self, candidate_policy_id, *, expected_active_policy_id, approval_reference, activated_at=None
    ):
        ok, governance, reason = activate_policy_governance(
            self.policy_governance(),
            candidate_policy_id,
            expected_active_policy_id=expected_active_policy_id,
            approval_reference=approval_reference,
            activated_at=activated_at,
        )
        self._save_policy_governance(governance, invalidate=ok)
        return ok, reason

    def rollback_smart_practice_policy(
        self, target_policy_id, *, expected_active_policy_id, reason, rolled_back_at=None
    ):
        ok, governance, failure = rollback_policy_governance(
            self.policy_governance(),
            target_policy_id,
            expected_active_policy_id=expected_active_policy_id,
            reason=reason,
            rolled_back_at=rolled_back_at,
        )
        self._save_policy_governance(governance, invalidate=ok)
        return ok, failure

    def detect_smart_practice_policy_drift(self, baseline, recent, *, sample_count, detected_at):
        return detect_drift(baseline, recent, sample_count=sample_count, detected_at=detected_at)

    def smart_practice_policy_review_report(self, candidate_policy_id, *, generated_at):
        return build_policy_governance_review_report(
            self.policy_governance(),
            candidate_policy_id,
            generated_at=generated_at,
        )

    def generate_smart_practice_measurement_report(self, evaluation_at=None):
        meta = self.progress_data.setdefault("meta", {})
        store = normalize_measurement_store(meta.get("smart_practice_measurement"))
        store["repair_state"] = dict(meta.get("repair_state") or {})
        store["concept_graph"] = dict(meta.get("smart_practice_concept_graph") or {})
        store["question_calibration"] = dict(meta.get("smart_practice_question_calibration") or {})
        report, store = build_measurement_report(
            store,
            self._progress_history(),
            evaluation_at=evaluation_at,
            requested_count=len(getattr(self, "questions", []) or []),
        )
        meta["smart_practice_measurement"] = store
        self.schedule_progress_save()
        return report

    def _effective_response_seconds(self, event: dict[str, Any]) -> float:
        try:
            return float(event.get("effective_response_seconds", event.get("response_seconds", 0.0)) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _confidence_weight(self, confidence):
        return {
            "Sure": 1.0,
            "Unsure": 0.8,
            "Guessed": 0.55,
        }.get(str(confidence or "").strip(), 0.85)

    def _history_cutoff(self, days):
        return datetime.now() - timedelta(days=days)

    def _recent_history(self, days=14) -> list[QuestionHistoryEvent]:
        cutoff = self._history_cutoff(days)
        history = []
        for event in self._progress_history():
            try:
                event_time = datetime.fromisoformat(str(event.get("at")))
            except Exception:
                continue
            if event_time >= cutoff:
                history.append(event)
        return history

    def _trend_delta_for_group(self, events: list[QuestionHistoryEvent]) -> float:
        now = datetime.now()
        current_cutoff = now - timedelta(days=7)
        previous_cutoff = now - timedelta(days=14)
        current = [event for event in events if self._parse_event_time(event) >= current_cutoff]
        previous = [event for event in events if previous_cutoff <= self._parse_event_time(event) < current_cutoff]
        if not current:
            return 0.0

        def weighted_accuracy(group):
            if not group:
                return None
            weights = [self._confidence_weight(event.get("confidence")) for event in group]
            total_weight = sum(weights) or 1.0
            earned = 0.0
            for event, weight in zip(group, weights, strict=False):
                if event.get("correct"):
                    earned += weight
            return (earned / total_weight) * 100.0

        current_score = weighted_accuracy(current)
        previous_score = weighted_accuracy(previous)
        if previous_score is None:
            return 0.0
        return current_score - previous_score

    def _parse_event_time(self, event: QuestionHistoryEvent):
        try:
            return datetime.fromisoformat(str(event.get("at")))
        except Exception:
            return datetime.min

    def _date_within_days(self, value, days: int) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        try:
            target = datetime.fromisoformat(raw)
        except Exception:
            try:
                target = datetime.strptime(raw, "%Y-%m-%d")
            except Exception:
                return False
        now = datetime.now()
        return now <= target <= (now + timedelta(days=days))

    def _normalized_prompt_key(self, prompt: str) -> str:
        prompt = str(prompt or "")
        cache = self._analytics_runtime_cache().setdefault("normalized_prompt_key", {})
        cached = cache.get(prompt)
        if cached is not None:
            return cached
        text = sanitize_text(prompt).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        normalized = re.sub(r"\s+", " ", text).strip()
        cache[prompt] = normalized
        return normalized

    def _normalized_study_label(self, value: str) -> str:
        return normalized_study_label(value)

    def _primary_topic_label(self, q) -> str:
        topics_tuple = tuple(str(topic).strip() for topic in q.get("topics", []) if str(topic).strip())
        domain = str(q.get("domain") or "Unsorted")
        cache_key = (int(q.get("question_number") or 0), topics_tuple, domain)
        cache = self._analytics_runtime_cache().setdefault("primary_topic_label", {})
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        label = primary_topic_label(q)
        cache[cache_key] = label
        return label

    def _coverage_unit_for_question(self, q) -> tuple[str, str]:
        objective_code = str(q.get("objective_code") or "").strip()
        topics_tuple = tuple(str(topic).strip() for topic in q.get("topics", []) if str(topic).strip())
        domain = str(q.get("domain") or "Unsorted")
        cache_key = (int(q.get("question_number") or 0), objective_code, topics_tuple, domain)
        cache = self._analytics_runtime_cache().setdefault("coverage_unit", {})
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        unit = coverage_unit_for_question(q)
        cache[cache_key] = unit
        return unit

    def _canonical_concept_id(self, q_or_kind, unit: str | None = None) -> str:
        if isinstance(q_or_kind, dict):
            q = q_or_kind
            kind, resolved_unit = self._coverage_unit_for_question(q)
        else:
            kind = str(q_or_kind or "")
            resolved_unit = str(unit or "")
        normalized = self._normalized_prompt_key(resolved_unit).replace(" ", "-")
        return f"{kind.lower()}::{normalized or 'unsorted'}"

    def _stem_style_for_question(self, q) -> str:
        prompt_raw = str((q or {}).get("prompt") or "")
        cache_key = (int((q or {}).get("question_number") or 0), prompt_raw)
        cache = self._analytics_runtime_cache().setdefault("stem_style", {})
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        style = stem_style_for_question(q)
        cache[cache_key] = style
        return style

    def _choice_concept_label(self, text: str) -> str:
        text = str(text or "")
        cache = self._analytics_runtime_cache().setdefault("choice_concept_label", {})
        cached = cache.get(text)
        if cached is not None:
            return cached
        cleaned = sanitize_text(text)
        if not cleaned:
            cache[text] = ""
            return ""
        acronym_match = re.search(r"\(([A-Z0-9]{2,8})\)", cleaned)
        if acronym_match:
            label = acronym_match.group(1).upper()
            cache[text] = label
            return label
        caps_tokens = [token for token in re.findall(r"\b[A-Z0-9]{2,8}\b", cleaned) if not token.isdigit()]
        if caps_tokens:
            label = caps_tokens[0].upper()
            cache[text] = label
            return label
        words = re.sub(r"[^A-Za-z0-9 ]+", " ", cleaned).split()
        label = " ".join(words[:4]).title()
        cache[text] = label
        return label

    def _question_mentions_label(self, q, label: str) -> bool:
        return question_mentions_label(q, label)

    def _build_source_agreement_rows(
        self, questions=None
    ) -> tuple[list[SourceAgreementRow], dict[int, SourceAgreementRow]]:
        question_list = list(questions or self.master_questions)
        prompt_groups: dict[str, list[Any]] = {}
        objective_sources: dict[str, set[str]] = {}
        topic_sources: dict[str, set[str]] = {}
        for q in question_list:
            prompt_key = self._normalized_prompt_key(str(q.get("prompt") or ""))
            if prompt_key:
                prompt_groups.setdefault(prompt_key, []).append(q)
            source_name = str(q.get("source_name") or "Unknown source")
            objective_code = str(q.get("objective_code") or "").strip()
            if objective_code:
                objective_sources.setdefault(objective_code, set()).add(source_name)
            topic_sources.setdefault(self._primary_topic_label(q), set()).add(source_name)

        rows: list[SourceAgreementRow] = []
        row_map: dict[int, SourceAgreementRow] = {}
        for q in question_list:
            qnum = int(q.get("question_number") or 0)
            prompt_key = self._normalized_prompt_key(str(q.get("prompt") or ""))
            prompt_group = prompt_groups.get(prompt_key, [])
            prompt_sources = sorted({str(item.get("source_name") or "Unknown source") for item in prompt_group})
            correct_signatures = {
                tuple(sorted(str(letter) for letter in item.get("correct", []))) for item in prompt_group
            }
            objective_code = str(q.get("objective_code") or "").strip()
            topic = self._primary_topic_label(q)
            support_sources = prompt_sources
            if len(prompt_sources) > 1 and len(correct_signatures) == 1:
                label = "Cross-source agreement"
                score = 1.0
            elif len(prompt_sources) > 1 and len(correct_signatures) > 1:
                label = "Source conflict"
                score = 0.58
            else:
                support_sources = sorted(
                    objective_sources.get(objective_code)
                    or topic_sources.get(topic)
                    or {str(q.get("source_name") or "Unknown source")}
                )
                if len(support_sources) > 1:
                    label = "Cross-source supported"
                    score = 0.92 if objective_code else 0.88
                else:
                    label = "Single-source only"
                    score = 0.8
            row: SourceAgreementRow = {
                "question_number": qnum,
                "source_name": str(q.get("source_name") or "Unknown source"),
                "label": label,
                "score": round(score, 2),
                "support_sources": support_sources,
                "objective_code": objective_code,
                "topic": topic,
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda row: (row["score"], row["question_number"]), reverse=True)
        return rows, row_map

    def _build_source_trust_rows(
        self, questions, source_agreement_rows: list[SourceAgreementRow]
    ) -> tuple[list[SourceTrustRow], dict[str, SourceTrustRow]]:
        question_list = list(questions or self.master_questions)
        agreement_by_qnum = {int(row["question_number"]): row for row in source_agreement_rows}
        grouped: dict[str, dict[str, Any]] = {}
        for q in question_list:
            source_name = str(q.get("source_name") or "Unknown source")
            qnum = int(q.get("question_number") or 0)
            agreement = agreement_by_qnum.get(qnum, {"label": "Single-source only", "score": 0.8})
            bucket = grouped.setdefault(
                source_name,
                {
                    "question_count": 0,
                    "agreement_count": 0,
                    "supported_count": 0,
                    "single_source_count": 0,
                    "conflict_count": 0,
                    "issue_count": 0,
                    "score_total": 0.0,
                },
            )
            bucket["question_count"] += 1
            bucket["score_total"] += float(agreement.get("score", 0.8))
            label = str(agreement.get("label") or "")
            if label == "Cross-source agreement":
                bucket["agreement_count"] += 1
            elif label == "Cross-source supported":
                bucket["supported_count"] += 1
            elif label == "Source conflict":
                bucket["conflict_count"] += 1
            else:
                bucket["single_source_count"] += 1
            if self.question_has_any_issue(q):
                bucket["issue_count"] += 1

        rows: list[SourceTrustRow] = []
        row_map: dict[str, SourceTrustRow] = {}
        for source_name, bucket in grouped.items():
            question_count = max(1, int(bucket["question_count"]))
            avg_score = float(bucket["score_total"]) / question_count
            agreement_ratio = int(bucket["agreement_count"]) / question_count
            supported_ratio = int(bucket["supported_count"]) / question_count
            single_ratio = int(bucket["single_source_count"]) / question_count
            conflict_ratio = int(bucket["conflict_count"]) / question_count
            issue_ratio = int(bucket["issue_count"]) / question_count
            decay = round(conflict_ratio * 28.0 + issue_ratio * 18.0 + single_ratio * 8.0, 1)
            trust_score = (avg_score * 100.0) + agreement_ratio * 7.0 + supported_ratio * 3.0 - decay
            trust_score = round(max(45.0, min(99.0, trust_score)), 1)
            if trust_score >= 88:
                label = "High trust"
            elif trust_score >= 75:
                label = "Watch"
            else:
                label = "Decayed"
            row: SourceTrustRow = {
                "source_name": source_name,
                "trust_score": trust_score,
                "label": label,
                "question_count": question_count,
                "agreement_count": int(bucket["agreement_count"]),
                "supported_count": int(bucket["supported_count"]),
                "single_source_count": int(bucket["single_source_count"]),
                "conflict_count": int(bucket["conflict_count"]),
                "issue_count": int(bucket["issue_count"]),
                "decay": decay,
            }
            rows.append(row)
            row_map[source_name] = row
        rows.sort(key=lambda row: (row["trust_score"], -row["question_count"], row["source_name"]))
        return rows, row_map

    def _build_latent_weakness_rows(
        self,
        records,
        question_stability: dict[int, float],
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        source_agreement_map: dict[int, SourceAgreementRow],
        source_trust_map: dict[str, SourceTrustRow],
        questions=None,
    ) -> list[LatentWeaknessRow]:
        rows: list[LatentWeaknessRow] = []
        for q in list(questions or self.master_questions):
            qnum = int(q.get("question_number") or 0)
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0 or is_active_weak(rec):
                continue
            qnum = int(q.get("question_number") or 0)
            history_events = question_history_map.get(qnum, [])
            if not history_events:
                continue
            guessed_correct = sum(
                1
                for event in history_events
                if event.get("correct") and str(event.get("confidence") or "").strip() == "Guessed"
            )
            unsure_correct = sum(
                1
                for event in history_events
                if event.get("correct") and str(event.get("confidence") or "").strip() == "Unsure"
            )
            last_confidence = str(rec.get("last_confidence") or "")
            stability = float(question_stability.get(qnum, 0.0))
            volatility = self.question_volatility(q)
            source_row = source_agreement_map.get(qnum, {"label": "Single-source only", "score": 0.8})
            source_trust = source_trust_map.get(str(q.get("source_name") or "Unknown source"), {"trust_score": 82.0})
            reasons = []
            score = 0.0
            if guessed_correct:
                score += guessed_correct * 14.0
                reasons.append(f"guessed-correct {guessed_correct}x")
            if unsure_correct:
                score += unsure_correct * 8.0
                reasons.append(f"unsure-correct {unsure_correct}x")
            if last_confidence == "Guessed":
                score += 6.0
            elif last_confidence == "Unsure":
                score += 4.0
            if stability and stability < 72:
                score += (72.0 - stability) * 0.35
                reasons.append(f"stability {round(stability, 1)}")
            if self._date_within_days(rec.get("next_review"), 3):
                score += 9.0
                reasons.append("review due soon")
            if float(volatility.get("score", 0.0)) >= 35.0:
                score += float(volatility.get("score", 0.0)) * 0.18
                reasons.append("volatile")
            source_label = str(source_row.get("label") or "")
            if source_label == "Single-source only":
                score += 4.0
                reasons.append("single-source")
            elif source_label == "Source conflict":
                score += 7.0
                reasons.append("source conflict")
            trust_score = float(source_trust.get("trust_score", 82.0))
            if trust_score < 80.0:
                score += (80.0 - trust_score) * 0.22
                reasons.append(f"low source trust {round(trust_score, 1)}")
            score -= min(int(rec.get("correct_streak", 0)), 4) * 1.6
            if score < 18.0:
                continue
            rows.append(
                {
                    "question_number": qnum,
                    "domain": str(q.get("domain") or "Unsorted"),
                    "topic": ", ".join([str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()][:2]),
                    "source_name": str(q.get("source_name") or "Unknown source"),
                    "score": round(score, 1),
                    "stability": round(stability, 1),
                    "confidence_signal": last_confidence or "Mixed",
                    "reasons": reasons[:4],
                }
            )
        rows.sort(key=lambda row: (row["score"], -row["stability"], row["question_number"]), reverse=True)
        return rows[:20]

    def _build_transfer_strength_rows(
        self,
        records,
        question_stability: dict[int, float],
        questions=None,
    ) -> tuple[list[TransferStrengthRow], dict[str, TransferStrengthRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "exposure": 0,
                    "sources": set(),
                    "stem_styles": set(),
                    "stability_total": 0.0,
                    "confidence_total": 0.0,
                    "confidence_seen": 0,
                    "active_weak": 0,
                    "due": 0,
                },
            )
            bucket["exposure"] += 1
            bucket["sources"].add(str(q.get("source_name") or "Unknown source"))
            bucket["stem_styles"].add(self._stem_style_for_question(q))
            bucket["stability_total"] += float(question_stability.get(int(q.get("question_number") or 0), 0.0))
            last_confidence = str(rec.get("last_confidence") or "")
            if last_confidence:
                bucket["confidence_total"] += self._confidence_weight(last_confidence)
                bucket["confidence_seen"] += 1
            bucket["active_weak"] += 1 if is_active_weak(rec) else 0
            bucket["due"] += 1 if is_review_due(rec) else 0

        rows: list[TransferStrengthRow] = []
        row_map: dict[str, TransferStrengthRow] = {}
        for key, bucket in grouped.items():
            exposure = max(1, int(bucket["exposure"]))
            source_count = len(bucket["sources"])
            stem_styles = sorted(bucket["stem_styles"])
            stem_style_count = len(stem_styles)
            stability = float(bucket["stability_total"]) / exposure
            confidence = (
                (float(bucket["confidence_total"]) / max(int(bucket["confidence_seen"]), 1))
                if int(bucket["confidence_seen"])
                else 0.72
            )
            score = (
                stability * 0.52
                + confidence * 100.0 * 0.18
                + min(exposure, 4) / 4.0 * 14.0
                + min(source_count, 3) / 3.0 * 16.0
                + min(stem_style_count, 4) / 4.0 * 12.0
                - int(bucket["active_weak"]) * 4.4
                - int(bucket["due"]) * 2.2
            )
            score = round(max(0.0, min(100.0, score)), 1)
            if score >= 78:
                label = "Portable"
            elif score >= 62:
                label = "Developing"
            else:
                label = "Fragile"
            row: TransferStrengthRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "score": score,
                "label": label,
                "exposure": exposure,
                "source_count": source_count,
                "stem_style_count": stem_style_count,
                "stem_styles": stem_styles,
                "stability": round(stability, 1),
                "confidence": round(confidence * 100.0, 1),
                "active_weak": int(bucket["active_weak"]),
                "due": int(bucket["due"]),
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["score"], -row["active_weak"], -row["due"], row["unit"]))
        return rows, row_map

    def _build_objective_mastery_rows(
        self,
        records,
        question_stability: dict[int, float],
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        source_agreement_map: dict[int, SourceAgreementRow],
        questions=None,
    ) -> tuple[list[ObjectiveMasteryRow], dict[str, ObjectiveMasteryRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            objective_code = str(q.get("objective_code") or "").strip()
            if not objective_code:
                continue
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            bucket = grouped.setdefault(
                objective_code,
                {
                    "available": 0,
                    "attempted": 0,
                    "sources": set(),
                    "stem_styles": set(),
                    "readiness_total": 0.0,
                    "stability_total": 0.0,
                    "trend_events": [],
                    "active_weak": 0,
                    "due": 0,
                },
            )
            qnum = int(q.get("question_number") or 0)
            bucket["available"] += 1
            bucket["sources"].add(str(q.get("source_name") or "Unknown source"))
            bucket["stem_styles"].add(self._stem_style_for_question(q))
            attempts = int(rec.get("attempts", 0))
            if attempts > 0:
                bucket["attempted"] += 1
                bucket["readiness_total"] += max(
                    0.0,
                    min(
                        100.0,
                        float(question_stability.get(qnum, 0.0)) * 0.58
                        + self._confidence_weight(rec.get("last_confidence")) * 22.0
                        + min(int(rec.get("correct_count", 0)), 4) * 4.5
                        - int(rec.get("wrong_count", 0)) * 5.0,
                    ),
                )
                bucket["stability_total"] += float(question_stability.get(qnum, 0.0))
            if is_active_weak(rec):
                bucket["active_weak"] += 1
            if is_review_due(rec):
                bucket["due"] += 1
            bucket["trend_events"].extend(question_history_map.get(qnum, []))

        rows: list[ObjectiveMasteryRow] = []
        row_map: dict[str, ObjectiveMasteryRow] = {}
        for objective_code, bucket in grouped.items():
            available = int(bucket["available"])
            attempted = int(bucket["attempted"])
            source_count = len(bucket["sources"])
            stem_style_count = len(bucket["stem_styles"])
            readiness = round(float(bucket["readiness_total"]) / attempted, 1) if attempted else 0.0
            stability = round(float(bucket["stability_total"]) / attempted, 1) if attempted else 0.0
            trend = round(self._trend_delta_for_group(bucket["trend_events"]), 1) if bucket["trend_events"] else 0.0
            coverage = (attempted / max(available, 1)) * 100.0
            agreement_bonus = 0.0
            for q in list(questions or self.master_questions):
                if str(q.get("objective_code") or "").strip() != objective_code:
                    continue
                qnum = int(q.get("question_number") or 0)
                agreement_bonus += float((source_agreement_map.get(qnum) or {}).get("score", 0.8)) * 3.0
            agreement_bonus = agreement_bonus / max(available, 1)
            mastery_score = (
                readiness * 0.34
                + stability * 0.28
                + coverage * 0.18
                + min(source_count, 3) / 3.0 * 10.0
                + min(stem_style_count, 4) / 4.0 * 10.0
                + agreement_bonus
                - int(bucket["active_weak"]) * 5.0
                - int(bucket["due"]) * 2.5
            )
            row: ObjectiveMasteryRow = {
                "objective_code": objective_code,
                "available": available,
                "attempted": attempted,
                "readiness": round(readiness, 1),
                "stability": round(stability, 1),
                "trend": trend,
                "source_count": source_count,
                "stem_style_count": stem_style_count,
                "active_weak": int(bucket["active_weak"]),
                "due": int(bucket["due"]),
                "mastery_score": round(max(0.0, min(100.0, mastery_score)), 1),
            }
            rows.append(row)
            row_map[objective_code] = row
        rows.sort(key=lambda row: (row["mastery_score"], -row["active_weak"], -row["due"], row["objective_code"]))
        return rows, row_map

    def _build_interference_map_rows(self, history: list[QuestionHistoryEvent]) -> list[InterferenceMapRow]:
        pair_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for event in history:
            if event.get("correct"):
                continue
            selected_labels = [self._choice_concept_label(text) for text in event.get("selected_texts") or []]
            correct_labels = [self._choice_concept_label(text) for text in event.get("correct_texts") or []]
            confidence = str(event.get("confidence") or "").strip()
            for wrong_label in selected_labels:
                for correct_label in correct_labels:
                    if not wrong_label or not correct_label or wrong_label == correct_label:
                        continue
                    left, right = sorted((wrong_label, correct_label), key=str.lower)
                    row = pair_rows.setdefault(
                        (left, right),
                        {
                            "left": left,
                            "right": right,
                            "count": 0,
                            "fragile_hits": 0,
                            "domains": set(),
                            "topics": set(),
                            "question_numbers": set(),
                        },
                    )
                    row["count"] += 1
                    if confidence in ("Guessed", "Unsure"):
                        row["fragile_hits"] += 1
                    row["domains"].add(str(event.get("domain") or "Unsorted"))
                    for topic in event.get("topics") or []:
                        topic_text = str(topic).strip()
                        if topic_text:
                            row["topics"].add(topic_text)
                    row["question_numbers"].add(int(event.get("question_number") or 0))
        rows: list[InterferenceMapRow] = []
        for row in pair_rows.values():
            pressure = row["count"] * 12.0 + len(row["question_numbers"]) * 3.5 + row["fragile_hits"] * 4.0
            rows.append(
                {
                    "pair": f"{row['left']} vs {row['right']}",
                    "left": row["left"],
                    "right": row["right"],
                    "count": int(row["count"]),
                    "pressure": round(min(100.0, pressure), 1),
                    "domains": ", ".join(sorted(row["domains"])[:2]),
                    "topics": ", ".join(sorted(row["topics"])[:2]),
                    "question_numbers": sorted(row["question_numbers"]),
                    "action": f"Keep separating {row['left']} from {row['right']} until the deciding clue is automatic.",
                }
            )
        rows.sort(key=lambda item: (item["pressure"], item["count"], item["pair"]), reverse=True)
        return rows[:10]

    def _build_confidence_compression_rows(
        self,
        records,
        question_stability: dict[int, float],
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        questions=None,
    ) -> tuple[list[ConfidenceCompressionRow], dict[str, ConfidenceCompressionRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "correct_total": 0,
                    "fragile_correct": 0,
                    "sure_correct": 0,
                    "stability_total": 0.0,
                    "stability_seen": 0,
                },
            )
            qnum = int(q.get("question_number") or 0)
            for event in question_history_map.get(qnum, []):
                if not event.get("correct"):
                    continue
                bucket["correct_total"] += 1
                confidence = str(event.get("confidence") or "").strip()
                if confidence in ("Guessed", "Unsure"):
                    bucket["fragile_correct"] += 1
                elif confidence == "Sure":
                    bucket["sure_correct"] += 1
            bucket["stability_total"] += float(question_stability.get(qnum, 0.0))
            bucket["stability_seen"] += 1

        rows: list[ConfidenceCompressionRow] = []
        row_map: dict[str, ConfidenceCompressionRow] = {}
        for key, bucket in grouped.items():
            correct_total = int(bucket["correct_total"])
            if correct_total <= 0:
                continue
            fragile_correct = int(bucket["fragile_correct"])
            sure_correct = int(bucket["sure_correct"])
            fragile_rate = fragile_correct / max(correct_total, 1)
            stability = float(bucket["stability_total"]) / max(int(bucket["stability_seen"]), 1)
            compression = fragile_rate * 70.0 + max(0.0, 74.0 - stability) * 0.28
            note = f"{fragile_correct}/{correct_total} correct answers were still unsure or guessed."
            row: ConfidenceCompressionRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "compression": round(min(100.0, compression), 1),
                "correct_total": correct_total,
                "fragile_correct": fragile_correct,
                "sure_correct": sure_correct,
                "stability": round(stability, 1),
                "note": note,
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda item: (item["compression"], item["fragile_correct"], item["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_abstraction_ladder_rows(
        self,
        records,
        question_stability: dict[int, float],
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        questions=None,
    ) -> tuple[list[AbstractionLadderRow], dict[str, AbstractionLadderRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            style = self._stem_style_for_question(q)
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "available_styles": set(),
                    "seen_styles": set(),
                    "source_count": set(),
                    "confidence_total": 0.0,
                    "confidence_seen": 0,
                    "stability_total": 0.0,
                    "stability_seen": 0,
                },
            )
            bucket["available_styles"].add(style)
            bucket["source_count"].add(str(q.get("source_name") or "Unknown source"))
            bucket["stability_total"] += float(question_stability.get(int(q.get("question_number") or 0), 0.0))
            bucket["stability_seen"] += 1
            history_events = question_history_map.get(int(q.get("question_number") or 0), [])
            if history_events:
                if any(event.get("correct") for event in history_events):
                    bucket["seen_styles"].add(style)
                for event in history_events:
                    if not event.get("correct"):
                        continue
                    bucket["confidence_total"] += self._confidence_weight(event.get("confidence"))
                    bucket["confidence_seen"] += 1

        rows: list[AbstractionLadderRow] = []
        row_map: dict[str, AbstractionLadderRow] = {}
        for key, bucket in grouped.items():
            available_styles = sorted(
                bucket["available_styles"],
                key=(
                    self.STEM_STYLE_LADDER.index
                    if all(style in self.STEM_STYLE_LADDER for style in bucket["available_styles"])
                    else str
                ),
            )
            seen_styles = sorted(
                bucket["seen_styles"],
                key=(
                    self.STEM_STYLE_LADDER.index
                    if all(style in self.STEM_STYLE_LADDER for style in bucket["seen_styles"])
                    else str
                ),
            )
            missing_styles = [style for style in available_styles if style not in seen_styles]
            rung_count = len(seen_styles)
            available_style_count = max(1, len(available_styles))
            source_count = len(bucket["source_count"])
            confidence = (
                (float(bucket["confidence_total"]) / max(int(bucket["confidence_seen"]), 1))
                if int(bucket["confidence_seen"])
                else 0.72
            )
            stability = float(bucket["stability_total"]) / max(int(bucket["stability_seen"]), 1)
            score = (
                min(rung_count, available_style_count) / available_style_count * 46.0
                + confidence * 100.0 * 0.18
                + stability * 0.24
                + min(source_count, 3) / 3.0 * 12.0
            )
            score = round(max(0.0, min(100.0, score)), 1)
            if score >= 78:
                label = "Integrated"
            elif score >= 60:
                label = "Developing"
            else:
                label = "Flat"
            row: AbstractionLadderRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "score": score,
                "label": label,
                "rung_count": rung_count,
                "available_style_count": available_style_count,
                "source_count": source_count,
                "seen_styles": seen_styles,
                "missing_styles": missing_styles,
                "confidence": round(confidence * 100.0, 1),
                "stability": round(stability, 1),
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda item: (item["score"], -item["rung_count"], item["unit"]))
        return rows, row_map

    def _build_error_boundary_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[ErrorBoundaryRow], dict[str, ErrorBoundaryRow]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            style = self._stem_style_for_question(q)
            bucket = grouped.setdefault(key, {"kind": kind, "unit": unit, "styles": {}})
            style_bucket = bucket["styles"].setdefault(style, {"attempts": 0, "correct": 0})
            style_bucket["attempts"] += 1
            style_bucket["correct"] += 1 if event.get("correct") else 0

        rows: list[ErrorBoundaryRow] = []
        row_map: dict[str, ErrorBoundaryRow] = {}
        for key, bucket in grouped.items():
            style_rows = []
            total_attempts = 0
            for style, counts in bucket["styles"].items():
                attempts = int(counts["attempts"])
                if attempts <= 0:
                    continue
                accuracy = (int(counts["correct"]) / attempts) * 100.0
                style_rows.append((style, attempts, accuracy))
                total_attempts += attempts
            if len(style_rows) < 2:
                continue
            weak_style, weak_attempts, weak_accuracy = min(style_rows, key=lambda item: (item[2], item[1], item[0]))
            strong_style, strong_attempts, strong_accuracy = max(
                style_rows, key=lambda item: (item[2], item[1], item[0])
            )
            gap = round(max(0.0, strong_accuracy - weak_accuracy), 1)
            if gap < 12.0:
                continue
            note = f"You handle {strong_style.lower()} better than {weak_style.lower()} here; the concept is breaking at the transfer point."
            row: ErrorBoundaryRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "weak_style": weak_style,
                "strong_style": strong_style,
                "gap": gap,
                "weak_accuracy": round(weak_accuracy, 1),
                "strong_accuracy": round(strong_accuracy, 1),
                "attempts": total_attempts,
                "note": note,
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda item: (item["gap"], item["attempts"], item["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_counterfactual_distractor_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[CounterfactualDistractorRow], dict[str, float]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        distractor_pressure: dict[str, float] = {}
        for event in history:
            if event.get("correct"):
                continue
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            confidence = str(event.get("confidence") or "").strip()
            for selected_text in event.get("selected_texts") or []:
                distractor = self._choice_concept_label(selected_text) or str(selected_text).strip()[:48]
                if not distractor:
                    continue
                for correct_text in event.get("correct_texts") or []:
                    correct = self._choice_concept_label(correct_text) or str(correct_text).strip()[:48]
                    if not correct or correct == distractor:
                        continue
                    key = (kind, unit, distractor, correct)
                    row = grouped.setdefault(
                        key,
                        {
                            "kind": kind,
                            "unit": unit,
                            "distractor": distractor,
                            "correct": correct,
                            "count": 0,
                            "fragile": 0,
                            "domains": set(),
                            "topics": set(),
                            "question_numbers": set(),
                        },
                    )
                    row["count"] += 1
                    if confidence in ("Guessed", "Unsure"):
                        row["fragile"] += 1
                    row["domains"].add(str(event.get("domain") or "Unsorted"))
                    for topic in event.get("topics") or []:
                        topic_text = str(topic).strip()
                        if topic_text:
                            row["topics"].add(topic_text)
                    row["question_numbers"].add(int(event.get("question_number") or 0))

        rows: list[CounterfactualDistractorRow] = []
        for row in grouped.values():
            pressure = row["count"] * 11.0 + row["fragile"] * 5.0 + len(row["question_numbers"]) * 3.0
            key = f"{row['kind']}::{row['unit']}"
            distractor_pressure[key] = max(distractor_pressure.get(key, 0.0), pressure)
            rows.append(
                {
                    "kind": str(row["kind"]),
                    "unit": str(row["unit"]),
                    "distractor": str(row["distractor"]),
                    "correct": str(row["correct"]),
                    "count": int(row["count"]),
                    "pressure": round(min(100.0, pressure), 1),
                    "domains": ", ".join(sorted(row["domains"])[:2]),
                    "topics": ", ".join(sorted(row["topics"])[:2]),
                    "question_numbers": sorted(row["question_numbers"]),
                    "note": f"The distractor '{row['distractor']}' keeps beating the correct idea '{row['correct']}'.",
                }
            )
        rows.sort(key=lambda item: (item["pressure"], item["count"], item["distractor"]), reverse=True)
        return rows[:12], distractor_pressure

    def _build_question_freshness_map(
        self, history: list[QuestionHistoryEvent], records, questions=None
    ) -> dict[int, float]:
        now = datetime.now()
        recent_events: dict[int, list[QuestionHistoryEvent]] = {}
        for event in history:
            qnum = int(event.get("question_number") or 0)
            if qnum:
                recent_events.setdefault(qnum, []).append(event)
        freshness_map: dict[int, float] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            qnum = int(q.get("question_number") or 0)
            events = recent_events.get(qnum, [])
            penalty = 0.0
            if events:
                last_seen = max(self._parse_event_time(event) for event in events)
                days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
                penalty += max(0.0, 3.5 - days) * 14.0
                penalty += (
                    max(0, len([event for event in events if (now - self._parse_event_time(event)).days <= 7]) - 1)
                    * 6.0
                )
            else:
                raw_seen = str(rec.get("last_seen") or "").strip()
                if raw_seen:
                    try:
                        seen_at = datetime.strptime(raw_seen, "%Y-%m-%d")
                    except Exception:
                        seen_at = None
                    if seen_at is not None:
                        days = max(0.0, (now - seen_at).total_seconds() / 86400.0)
                        penalty += max(0.0, 2.0 - days) * 10.0
            if is_active_weak(rec) or is_review_due(rec):
                penalty *= 0.25
            elif is_ever_wrong(rec):
                penalty *= 0.55
            freshness_map[qnum] = round(min(100.0, penalty), 1)
        return freshness_map

    def _build_difficulty_calibration_rows(
        self,
        records,
        question_stability: dict[int, float],
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        source_agreement_map: dict[int, SourceAgreementRow],
        questions=None,
    ) -> tuple[list[DifficultyCalibrationRow], dict[int, DifficultyCalibrationRow]]:
        rows: list[DifficultyCalibrationRow] = []
        row_map: dict[int, DifficultyCalibrationRow] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0:
                continue
            qnum = int(q.get("question_number") or 0)
            wrong_rate = int(rec.get("wrong_count", 0)) / max(attempts, 1)
            confidence_counts = dict(rec.get("confidence_counts") or {})
            fragile = int(confidence_counts.get("Guessed", 0)) + int(confidence_counts.get("Unsure", 0))
            fragile_rate = fragile / max(sum(int(value or 0) for value in confidence_counts.values()) or attempts, 1)
            volatility = float(self.question_volatility(q).get("score", 0.0))
            source_support = source_agreement_map.get(qnum, {"score": 0.8, "label": "Single-source only"})
            stability = float(question_stability.get(qnum, 0.0))
            score = wrong_rate * 52.0 + fragile_rate * 18.0 + volatility * 0.22 + max(0.0, 76.0 - stability) * 0.18
            if source_support.get("label") == "Source conflict":
                score += 6.0
            elif source_support.get("label") == "Cross-source agreement":
                score -= 2.0
            score = round(max(0.0, min(100.0, score)), 1)
            label = "Hard" if score >= 65 else "Moderate" if score >= 42 else "Stable"
            row: DifficultyCalibrationRow = {
                "question_number": qnum,
                "domain": str(q.get("domain") or "Unsorted"),
                "topic": ", ".join([str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()][:2]),
                "score": score,
                "label": label,
                "wrong_rate": round(wrong_rate * 100.0, 1),
                "fragile_rate": round(fragile_rate * 100.0, 1),
                "volatility": volatility,
                "source_support": str(source_support.get("label") or "Single-source only"),
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda item: (item["score"], item["volatility"], item["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_phrasing_normalization_rows(
        self,
        questions=None,
    ) -> tuple[list[PhrasingNormalizationRow], dict[int, PhrasingNormalizationRow]]:
        rows: list[PhrasingNormalizationRow] = []
        row_map: dict[int, PhrasingNormalizationRow] = {}
        for q in list(questions or self.master_questions):
            qnum = int(q.get("question_number") or 0)
            prompt = sanitize_text(str(q.get("prompt") or ""))
            explanation = sanitize_text(str(q.get("general_explanation") or ""))
            note_count = len(q.get("source_notes", []) or [])
            odd_punct = len(re.findall(r"[/|]{2,}|[?]{2,}|[!]{2,}|[_]{2,}", prompt))
            long_prompt = max(0, len(prompt.split()) - 42)
            long_explanation = max(0, len(explanation.split()) - 110)
            acronym_density = len(re.findall(r"\b[A-Z]{5,}\b", prompt))
            score = (
                100.0
                - note_count * 9.0
                - odd_punct * 12.0
                - long_prompt * 0.8
                - long_explanation * 0.18
                - acronym_density * 2.5
            )
            score = round(max(0.0, min(100.0, score)), 1)
            if score >= 82:
                label = "Clean"
            elif score >= 62:
                label = "Watch"
            else:
                label = "Noisy"
            note = f"Prompt/explanation wording scored {score}% normalized for study use."
            row: PhrasingNormalizationRow = {
                "question_number": qnum,
                "source_name": str(q.get("source_name") or "Unknown source"),
                "score": score,
                "label": label,
                "note": note,
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda item: (item["score"], item["question_number"]))
        return rows[:20], row_map

    def _build_burnout_risk_row(
        self, session_history: list[QuestionHistoryEvent] | list[dict[str, Any]]
    ) -> BurnoutRiskRow:
        events = [event for event in list(session_history or []) if event]
        if len(events) < 6:
            return {
                "label": "Low",
                "score": 0.0,
                "accuracy_drop": 0.0,
                "response_drag": 0.0,
                "fragile_rate": 0.0,
                "note": "Not enough recent answers to assess burnout risk yet.",
            }
        sample = events[-10:]
        split = max(3, len(sample) // 2)
        early = sample[:split]
        late = sample[split:]

        def accuracy(group):
            return (sum(1 for event in group if event.get("correct")) / max(len(group), 1)) * 100.0

        def response(group):
            values = [
                self._effective_response_seconds(event)
                for event in group
                if self._effective_response_seconds(event) > 0
            ]
            return (sum(values) / len(values)) if values else 0.0

        def fragile(group):
            return sum(
                1 for event in group if str(event.get("confidence") or "").strip() in ("Guessed", "Unsure")
            ) / max(len(group), 1)

        accuracy_drop = max(0.0, accuracy(early) - accuracy(late))
        response_drag = max(0.0, response(late) - response(early))
        fragile_rate = fragile(late)
        score = accuracy_drop * 0.9 + response_drag * 7.5 + fragile_rate * 42.0
        score = round(max(0.0, min(100.0, score)), 1)
        if score >= 62:
            label = "High"
        elif score >= 34:
            label = "Watch"
        else:
            label = "Low"
        note = (
            "Recent answers show fatigue drift, so the engine will flatten difficulty and reduce bonus insertions."
            if label != "Low"
            else "Recent answer quality looks stable."
        )
        return {
            "label": label,
            "score": score,
            "accuracy_drop": round(accuracy_drop, 1),
            "response_drag": round(response_drag, 1),
            "fragile_rate": round(fragile_rate * 100.0, 1),
            "note": note,
        }

    def _build_momentum_profile(
        self,
        session_history: list[QuestionHistoryEvent] | list[dict[str, Any]],
        burnout_risk: BurnoutRiskRow | None = None,
    ) -> dict[str, Any]:
        events = [event for event in list(session_history or []) if event]
        burnout_risk = burnout_risk or self._build_burnout_risk_row(events)
        if not events:
            return {"label": "Balanced", "difficulty_bias": 0.0, "note": "No session momentum yet."}
        sample = events[-8:]
        accuracy = (sum(1 for event in sample if event.get("correct")) / max(len(sample), 1)) * 100.0
        fragile_rate = sum(
            1 for event in sample if str(event.get("confidence") or "").strip() in ("Guessed", "Unsure")
        ) / max(len(sample), 1)
        if burnout_risk.get("label") == "High" or accuracy < 50.0:
            return {
                "label": "Stabilize",
                "difficulty_bias": -1.0,
                "note": "Recent answers show drag, so the engine should stabilize and reduce hard insertions.",
                "accuracy": round(accuracy, 1),
                "fragile_rate": round(fragile_rate * 100.0, 1),
            }
        if burnout_risk.get("label") == "Low" and accuracy >= 78.0 and fragile_rate <= 0.35:
            return {
                "label": "Press",
                "difficulty_bias": 1.0,
                "note": "Recent answers are strong and stable, so the engine can press challenge slightly.",
                "accuracy": round(accuracy, 1),
                "fragile_rate": round(fragile_rate * 100.0, 1),
            }
        return {
            "label": "Balanced",
            "difficulty_bias": 0.0,
            "note": "Recent answers are mixed, so the engine should keep a balanced pace.",
            "accuracy": round(accuracy, 1),
            "fragile_rate": round(fragile_rate * 100.0, 1),
        }

    def _build_prerequisite_debt_rows(
        self,
        records,
        question_stability: dict[int, float],
        coverage_gaps: list[CoverageGapRow],
        objective_mastery_map: dict[str, ObjectiveMasteryRow],
        error_boundary_map: dict[str, ErrorBoundaryRow],
        counterfactual_pressure_map: dict[str, float],
        questions=None,
    ) -> tuple[list[PrerequisiteDebtRow], dict[str, PrerequisiteDebtRow]]:
        question_list = list(questions or self.master_questions)
        coverage_gap_map = self._coverage_gap_priority_map(coverage_gaps)
        grouped: dict[str, dict[str, Any]] = {}
        domain_units: dict[str, set[str]] = {}
        for q in question_list:
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            domain = str(q.get("domain") or "Unsorted")
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "domain": domain,
                    "available": 0,
                    "attempted": 0,
                    "stability_total": 0.0,
                    "stability_seen": 0,
                    "active_weak": 0,
                    "due": 0,
                },
            )
            bucket["available"] += 1
            attempts = int(rec.get("attempts", 0))
            if attempts > 0:
                bucket["attempted"] += 1
                bucket["stability_total"] += float(question_stability.get(int(q.get("question_number") or 0), 0.0))
                bucket["stability_seen"] += 1
            if is_active_weak(rec):
                bucket["active_weak"] += 1
            if is_review_due(rec):
                bucket["due"] += 1
            domain_units.setdefault(domain, set()).add(key)

        rows: list[PrerequisiteDebtRow] = []
        row_map: dict[str, PrerequisiteDebtRow] = {}
        for key, bucket in grouped.items():
            objective_row = (
                objective_mastery_map.get(str(bucket["unit"]), {"mastery_score": 70.0})
                if bucket["kind"] == "Objective"
                else None
            )
            stability = (
                float(bucket["stability_total"]) / max(int(bucket["stability_seen"]), 1)
                if int(bucket["stability_seen"])
                else 0.0
            )
            attempt_rate = int(bucket["attempted"]) / max(int(bucket["available"]), 1)
            mastery_score = float(
                (objective_row or {}).get("mastery_score", max(0.0, min(100.0, stability * 0.78 + attempt_rate * 22.0)))
            )
            severity = max(0.0, 82.0 - mastery_score)
            severity += float(coverage_gap_map.get(key, 0.0)) * 0.18
            severity += float((error_boundary_map.get(key) or {}).get("gap", 0.0)) * 0.12
            severity += float(counterfactual_pressure_map.get(key, 0.0)) * 0.06
            severity += int(bucket["active_weak"]) * 7.5
            severity += int(bucket["due"]) * 3.2
            dependent_units = sorted(
                unit_key.split("::", 1)[1]
                for unit_key in domain_units.get(str(bucket["domain"]), set())
                if unit_key != key
            )[:3]
            row: PrerequisiteDebtRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "severity": round(min(100.0, severity), 1),
                "mastery_score": round(max(0.0, min(100.0, mastery_score)), 1),
                "active_weak": int(bucket["active_weak"]),
                "due": int(bucket["due"]),
                "dependent_units": dependent_units,
                "note": f"{bucket['unit']} is acting like a root weakness that can drag related work in {bucket['domain']}.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["severity"], row["active_weak"], row["due"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_concept_half_life_rows(
        self,
        records,
        question_stability: dict[int, float],
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        questions=None,
    ) -> tuple[list[ConceptHalfLifeRow], dict[str, ConceptHalfLifeRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "stability_total": 0.0,
                    "volatility_total": 0.0,
                    "confidence_total": 0.0,
                    "correct_streak_total": 0,
                    "seen": 0,
                    "active_weak": 0,
                    "due": 0,
                },
            )
            qnum = int(q.get("question_number") or 0)
            bucket["stability_total"] += float(question_stability.get(qnum, 0.0))
            bucket["volatility_total"] += float(self.question_volatility(q).get("score", 0.0))
            history_events = question_history_map.get(qnum, [])
            correct_events = [event for event in history_events if event.get("correct")]
            if correct_events:
                bucket["confidence_total"] += sum(
                    self._confidence_weight(event.get("confidence")) for event in correct_events
                ) / len(correct_events)
            else:
                bucket["confidence_total"] += self._confidence_weight(rec.get("last_confidence"))
            bucket["correct_streak_total"] += int(rec.get("correct_streak", 0))
            bucket["seen"] += 1
            if is_active_weak(rec):
                bucket["active_weak"] += 1
            if is_review_due(rec):
                bucket["due"] += 1

        rows: list[ConceptHalfLifeRow] = []
        row_map: dict[str, ConceptHalfLifeRow] = {}
        for key, bucket in grouped.items():
            seen = max(int(bucket["seen"]), 1)
            stability = float(bucket["stability_total"]) / seen
            volatility = float(bucket["volatility_total"]) / seen
            confidence = float(bucket["confidence_total"]) / seen
            correct_streak = float(bucket["correct_streak_total"]) / seen
            half_life_days = 1.4 + stability / 13.5 + confidence * 4.2 + min(correct_streak, 4.0) * 0.8
            half_life_days -= volatility / 18.0
            half_life_days -= int(bucket["active_weak"]) * 1.2
            half_life_days -= int(bucket["due"]) * 0.9
            half_life_days = round(max(0.5, min(28.0, half_life_days)), 1)
            if half_life_days >= 9.0:
                label = "Long"
            elif half_life_days >= 4.5:
                label = "Medium"
            else:
                label = "Short"
            row: ConceptHalfLifeRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "half_life_days": half_life_days,
                "label": label,
                "stability": round(stability, 1),
                "volatility": round(volatility, 1),
                "confidence": round(confidence * 100.0, 1),
                "note": f"{bucket['unit']} is estimated to hold for about {half_life_days} day(s) before reinforcement should matter again.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["half_life_days"], row["stability"], row["unit"]))
        return rows[:12], row_map

    def _build_leverage_ranking_rows(
        self,
        records,
        prerequisite_debt_map: dict[str, PrerequisiteDebtRow],
        questions=None,
    ) -> tuple[list[LeverageRankingRow], dict[str, LeverageRankingRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        domain_objectives: dict[str, set[str]] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            domain = str(q.get("domain") or "Unsorted")
            topic_count = len([str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()])
            style = self._stem_style_for_question(q)
            objective_code = str(q.get("objective_code") or "").strip()
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "available": 0,
                    "scenario_hits": 0,
                    "topic_mix": 0,
                    "related_objectives": set(),
                    "domain": domain,
                },
            )
            bucket["available"] += 1
            bucket["scenario_hits"] += 1 if style in ("Scenario", "Troubleshooting", "Best fit") else 0
            bucket["topic_mix"] += max(0, topic_count - 1)
            if objective_code:
                bucket["related_objectives"].add(objective_code)
                domain_objectives.setdefault(domain, set()).add(objective_code)

        rows: list[LeverageRankingRow] = []
        row_map: dict[str, LeverageRankingRow] = {}
        for key, bucket in grouped.items():
            dependent_count = len(
                {
                    unit_key
                    for unit_key, debt in prerequisite_debt_map.items()
                    if unit_key != key
                    and unit_key.split("::", 1)[0] == bucket["kind"]
                    and debt["severity"] >= 45.0
                    and str(debt["unit"]) != str(bucket["unit"])
                }
            )
            related_objectives = len(
                bucket["related_objectives"] or domain_objectives.get(str(bucket["domain"]), set())
            )
            leverage = (
                float(bucket["available"]) * 9.0
                + float(bucket["scenario_hits"]) * 6.0
                + float(bucket["topic_mix"]) * 5.0
                + dependent_count * 7.5
                + related_objectives * 4.0
            )
            row: LeverageRankingRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "leverage": round(min(100.0, leverage), 1),
                "dependent_count": dependent_count,
                "related_objectives": related_objectives,
                "note": f"{bucket['unit']} influences multiple question angles, so strengthening it can unlock broader gains.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["leverage"], row["dependent_count"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_blind_spot_inference_rows(
        self,
        coverage_gaps: list[CoverageGapRow],
        prerequisite_debt_map: dict[str, PrerequisiteDebtRow],
        leverage_map: dict[str, LeverageRankingRow],
        questions=None,
    ) -> tuple[list[BlindSpotInferenceRow], dict[str, BlindSpotInferenceRow]]:
        question_list = list(questions or self.master_questions)
        unit_domains: dict[str, set[str]] = {}
        for q in question_list:
            kind, unit = self._coverage_unit_for_question(q)
            unit_domains.setdefault(f"{kind}::{unit}", set()).add(str(q.get("domain") or "Unsorted"))
        coverage_gap_map = {f"{row['kind']}::{row['unit']}": row for row in coverage_gaps}
        rows: list[BlindSpotInferenceRow] = []
        row_map: dict[str, BlindSpotInferenceRow] = {}
        for key, gap_row in coverage_gap_map.items():
            if int(gap_row["attempted"]) > 0 and float(gap_row["severity"]) < 55.0:
                continue
            supporting = []
            support_score = 0.0
            for other_key, debt in prerequisite_debt_map.items():
                if other_key == key:
                    continue
                if unit_domains.get(key, set()) & unit_domains.get(other_key, set()):
                    if debt["severity"] >= 45.0:
                        supporting.append(str(debt["unit"]))
                        support_score = max(support_score, float(debt["severity"]))
            leverage = float((leverage_map.get(key) or {}).get("leverage", 0.0))
            severity = float(gap_row["severity"]) * 0.56 + support_score * 0.28 + leverage * 0.12
            evidence = []
            if float(gap_row["severity"]) >= 55.0:
                evidence.append("low coverage")
            if support_score >= 45.0:
                evidence.append("neighbor weakness")
            if leverage >= 40.0:
                evidence.append("high leverage")
            if not evidence:
                continue
            row: BlindSpotInferenceRow = {
                "kind": str(gap_row["kind"]),
                "unit": str(gap_row["unit"]),
                "severity": round(min(100.0, severity), 1),
                "evidence": evidence,
                "supporting_units": sorted(set(supporting))[:3],
                "note": f"{gap_row['unit']} looks under-tested relative to nearby weak material, so the engine will probe it before it becomes an obvious miss.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["severity"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_robustness_score_rows(
        self,
        transfer_strength_rows: list[TransferStrengthRow],
        abstraction_ladder_map: dict[str, AbstractionLadderRow],
        half_life_map: dict[str, ConceptHalfLifeRow],
    ) -> tuple[list[RobustnessScoreRow], dict[str, RobustnessScoreRow]]:
        rows: list[RobustnessScoreRow] = []
        row_map: dict[str, RobustnessScoreRow] = {}
        for transfer_row in transfer_strength_rows:
            key = f"{transfer_row['kind']}::{transfer_row['unit']}"
            ladder_row = abstraction_ladder_map.get(key, {"score": 60.0, "source_count": 1, "stem_style_count": 1})
            half_life_row = half_life_map.get(key, {"half_life_days": 4.0, "stability": transfer_row["stability"]})
            score = float(transfer_row["score"]) * 0.44
            score += float(ladder_row.get("score", 60.0)) * 0.24
            score += min(float(half_life_row.get("half_life_days", 4.0)), 14.0) / 14.0 * 18.0
            score += min(int(transfer_row["source_count"]), 3) / 3.0 * 8.0
            score += min(int(transfer_row["stem_style_count"]), 4) / 4.0 * 6.0
            score = round(max(0.0, min(100.0, score)), 1)
            if score >= 78.0:
                label = "Robust"
            elif score >= 60.0:
                label = "Developing"
            else:
                label = "Brittle"
            row: RobustnessScoreRow = {
                "kind": str(transfer_row["kind"]),
                "unit": str(transfer_row["unit"]),
                "score": score,
                "label": label,
                "source_count": int(transfer_row["source_count"]),
                "stem_style_count": int(transfer_row["stem_style_count"]),
                "half_life_days": float(half_life_row.get("half_life_days", 4.0)),
                "stability": float(half_life_row.get("stability", transfer_row["stability"])),
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["score"], row["unit"]))
        return rows[:12], row_map

    def _build_misconception_fingerprint_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[MisconceptionFingerprintRow], dict[str, float]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        pressure_map: dict[str, float] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            trap_words = {str(word).strip() for word in event.get("trap_words") or [] if str(word).strip()}
            family = str(event.get("wrong_answer_family") or "").strip()
            reason = str(event.get("miss_reason") or "").strip()
            confidence = str(event.get("confidence") or "").strip()
            labels = []
            if reason == "Misread" or trap_words:
                labels.append(("Qualifier drift", "qualifier words keep bending the read"))
            if family in (
                "Near-synonym / look-alike distractor",
                "Technically true but not best",
                "Order-of-operations trap",
            ):
                labels.append(("Concept boundary blur", family or "look-alike distractors keep winning"))
            if family == "Too-broad distractor":
                labels.append(("Security-sounding overreach", "broad safe-sounding answers are pulling attention"))
            if confidence in ("Guessed", "Unsure"):
                labels.append(("Fragile recall", "correctness is still leaning on low-confidence recall"))
            if not labels and not event.get("correct"):
                labels.append(("Plausible distractor pull", family or "tempting distractors still feel right"))
            for fingerprint, evidence in labels:
                row = grouped.setdefault(
                    fingerprint,
                    {
                        "fingerprint": fingerprint,
                        "count": 0,
                        "affected_units": set(),
                        "evidence": {},
                    },
                )
                row["count"] += 1
                row["affected_units"].add(unit)
                row["evidence"][evidence] = row["evidence"].get(evidence, 0) + 1
                pressure_map[unit_key] = max(pressure_map.get(unit_key, 0.0), row["count"] * 10.0)
        rows: list[MisconceptionFingerprintRow] = []
        for row in grouped.values():
            evidence = (
                max(row["evidence"].items(), key=lambda item: item[1])[0] if row["evidence"] else "recurring pattern"
            )
            rows.append(
                {
                    "fingerprint": str(row["fingerprint"]),
                    "count": int(row["count"]),
                    "affected_units": sorted(str(unit) for unit in row["affected_units"])[:5],
                    "evidence": evidence,
                    "note": f"{row['fingerprint']} is recurring, so the engine should teach the rule behind it instead of repeating letters.",
                }
            )
        rows.sort(key=lambda row: (row["count"], row["fingerprint"]), reverse=True)
        return rows[:8], pressure_map

    def _build_effort_efficiency_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[EffortEfficiencyRow], dict[str, EffortEfficiencyRow]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "earned_total": 0.0,
                    "time_total": 0.0,
                    "time_seen": 0,
                    "fragile_correct": 0,
                    "correct_total": 0,
                    "seen": 0,
                },
            )
            confidence = str(event.get("confidence") or "").strip()
            if event.get("correct"):
                earned = 1.0 if confidence == "Sure" else 0.78 if confidence == "Unsure" else 0.58
                bucket["correct_total"] += 1
                if confidence in ("Guessed", "Unsure"):
                    bucket["fragile_correct"] += 1
            else:
                earned = 0.25 if confidence == "Sure" else 0.18 if confidence == "Unsure" else 0.1
            bucket["earned_total"] += earned
            response_seconds = self._effective_response_seconds(event)
            if response_seconds > 0:
                bucket["time_total"] += response_seconds
                bucket["time_seen"] += 1
            bucket["seen"] += 1
        rows: list[EffortEfficiencyRow] = []
        row_map: dict[str, EffortEfficiencyRow] = {}
        for key, bucket in grouped.items():
            seen = max(int(bucket["seen"]), 1)
            avg_time = (
                float(bucket["time_total"]) / max(int(bucket["time_seen"]), 1) if int(bucket["time_seen"]) else 0.0
            )
            fragile_rate = (
                int(bucket["fragile_correct"]) / max(int(bucket["correct_total"]), 1)
                if int(bucket["correct_total"])
                else 0.0
            )
            score = (float(bucket["earned_total"]) / seen) * 100.0
            score -= max(0.0, avg_time - 8.0) * 3.8
            score -= fragile_rate * 18.0
            score = round(max(0.0, min(100.0, score)), 1)
            row: EffortEfficiencyRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "score": score,
                "avg_response_seconds": round(avg_time, 1),
                "fragile_correct_rate": round(fragile_rate * 100.0, 1),
                "note": f"{bucket['unit']} is being answered at {round(avg_time, 1)}s on average with {round(fragile_rate * 100.0, 1)}% fragile corrects.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["score"], row["avg_response_seconds"], row["unit"]))
        return rows[:12], row_map

    def _build_reinforcement_distance_rows(
        self,
        records,
        question_stability: dict[int, float],
        concept_half_life_map: dict[str, ConceptHalfLifeRow],
        questions=None,
    ) -> tuple[list[ReinforcementDistanceRow], dict[int, ReinforcementDistanceRow]]:
        rows: list[ReinforcementDistanceRow] = []
        row_map: dict[int, ReinforcementDistanceRow] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            attempts = int(rec.get("attempts", 0))
            if attempts <= 0:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            half_life_row = concept_half_life_map.get(unit_key, {"half_life_days": 4.0})
            qnum = int(q.get("question_number") or 0)
            volatility = float(self.question_volatility(q).get("score", 0.0))
            stability = float(question_stability.get(qnum, 0.0))
            confidence = self._confidence_weight(rec.get("last_confidence"))
            recommended_days = (
                float(half_life_row.get("half_life_days", 4.0)) * 0.72 + min(int(rec.get("correct_streak", 0)), 4) * 0.7
            )
            recommended_days += confidence * 1.6
            recommended_days -= volatility / 24.0
            if is_active_weak(rec):
                recommended_days -= 2.4
            if is_review_due(rec):
                recommended_days -= 1.2
            recommended_days = round(max(0.5, min(21.0, recommended_days)), 1)
            priority = max(0.0, 100.0 - recommended_days * 4.0 + max(0.0, 76.0 - stability) * 0.24)
            row: ReinforcementDistanceRow = {
                "question_number": qnum,
                "kind": kind,
                "unit": unit,
                "recommended_days": recommended_days,
                "priority": round(min(100.0, priority), 1),
                "note": f"Next useful reinforcement for Q{qnum} is about {recommended_days} day(s) out.",
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda row: (row["priority"], -row["recommended_days"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_synthesis_check_rows(
        self,
        objective_mastery_map: dict[str, ObjectiveMasteryRow],
        questions=None,
    ) -> tuple[list[SynthesisCheckRow], dict[int, SynthesisCheckRow]]:
        rows: list[SynthesisCheckRow] = []
        row_map: dict[int, SynthesisCheckRow] = {}
        for q in list(questions or self.master_questions):
            qnum = int(q.get("question_number") or 0)
            topics = [str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()]
            stem_style = self._stem_style_for_question(q)
            objective_code = str(q.get("objective_code") or "").strip()
            objective_row = objective_mastery_map.get(objective_code, {"mastery_score": 72.0})
            concept_labels = {
                self._choice_concept_label(text)
                for text in (q.get("choices") or {}).values()
                if self._choice_concept_label(text)
            }
            score = max(0, len(topics) - 1) * 18.0
            score += 14.0 if stem_style in ("Scenario", "Troubleshooting", "Best fit") else 0.0
            score += min(len(concept_labels), 4) * 4.0
            score += max(0.0, 74.0 - float(objective_row.get("mastery_score", 72.0))) * 0.16
            score = round(max(0.0, min(100.0, score)), 1)
            if score < 20.0:
                continue
            label = "High" if score >= 54.0 else "Medium"
            row: SynthesisCheckRow = {
                "question_number": qnum,
                "objective_code": objective_code,
                "topic_mix": ", ".join(topics[:3]) or str(q.get("domain") or "Unsorted"),
                "score": score,
                "label": label,
                "stem_style": stem_style,
                "note": f"Q{qnum} blends multiple concept angles, so it is useful for checking real integration instead of single-fact recall.",
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda row: (row["score"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _knowledge_trace_probability(self, history_events: list[QuestionHistoryEvent]) -> tuple[float, float]:
        if not history_events:
            return 0.38, 1.0
        posterior = 0.38
        for event in sorted(history_events, key=self._parse_event_time):
            confidence = str(event.get("confidence") or "").strip()
            if event.get("correct"):
                known = {"Sure": 0.91, "Unsure": 0.79, "Guessed": 0.64}.get(confidence, 0.76)
                unknown = {"Sure": 0.24, "Unsure": 0.37, "Guessed": 0.48}.get(confidence, 0.41)
            else:
                known = {"Sure": 0.09, "Unsure": 0.21, "Guessed": 0.36}.get(confidence, 0.24)
                unknown = {"Sure": 0.76, "Unsure": 0.63, "Guessed": 0.52}.get(confidence, 0.59)
            numerator = posterior * known
            denominator = numerator + (1.0 - posterior) * unknown
            if denominator <= 0:
                continue
            posterior = numerator / denominator
        uncertainty = 1.0 - abs(2.0 * posterior - 1.0)
        return posterior, uncertainty

    def _build_knowledge_trace_rows(
        self,
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        questions=None,
    ) -> tuple[list[KnowledgeTraceRow], dict[str, KnowledgeTraceRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "events": [],
                    "canonical_concept_id": self._canonical_concept_id(q),
                },
            )["events"].extend(question_history_map.get(int(q.get("question_number") or 0), []))

        rows: list[KnowledgeTraceRow] = []
        row_map: dict[str, KnowledgeTraceRow] = {}
        for key, bucket in grouped.items():
            posterior, uncertainty = self._knowledge_trace_probability(bucket["events"])
            if posterior >= 0.82:
                state = "stable"
            elif posterior >= 0.68:
                state = "transferable"
            elif posterior >= 0.54:
                state = "retrievable"
            elif posterior >= 0.42:
                state = "recognizable"
            else:
                state = "fragile"
            row: KnowledgeTraceRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "mastery_prob": round(posterior * 100.0, 1),
                "uncertainty": round(uncertainty * 100.0, 1),
                "evidence_count": len(bucket["events"]),
                "canonical_concept_id": str(bucket["canonical_concept_id"]),
                "note": f"{bucket['unit']} currently traces to a {state} concept belief with {round(uncertainty * 100.0, 1)}% uncertainty.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["mastery_prob"], -row["uncertainty"], row["unit"]))
        return rows[:20], row_map

    def _build_generalization_score_rows(
        self,
        transfer_strength_rows: list[TransferStrengthRow],
        abstraction_ladder_map: dict[str, AbstractionLadderRow],
        robustness_map: dict[str, RobustnessScoreRow] | None = None,
    ) -> tuple[list[GeneralizationScoreRow], dict[str, GeneralizationScoreRow]]:
        robustness_map = robustness_map or {}
        rows: list[GeneralizationScoreRow] = []
        row_map: dict[str, GeneralizationScoreRow] = {}
        for transfer_row in transfer_strength_rows:
            key = f"{transfer_row['kind']}::{transfer_row['unit']}"
            ladder = abstraction_ladder_map.get(key, {"score": 60.0})
            robustness = robustness_map.get(key, {"score": transfer_row["score"]})
            score = (
                float(transfer_row["score"]) * 0.52
                + float(ladder.get("score", 60.0)) * 0.24
                + float(robustness.get("score", transfer_row["score"])) * 0.24
            )
            row: GeneralizationScoreRow = {
                "kind": str(transfer_row["kind"]),
                "unit": str(transfer_row["unit"]),
                "score": round(max(0.0, min(100.0, score)), 1),
                "source_count": int(transfer_row["source_count"]),
                "stem_style_count": int(transfer_row["stem_style_count"]),
                "note": f"{transfer_row['unit']} is generalizing across {transfer_row['source_count']} source(s) and {transfer_row['stem_style_count']} stem style(s).",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["score"], row["unit"]))
        return rows[:12], row_map

    def _build_recognition_retrieval_rows(
        self,
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        questions=None,
    ) -> tuple[list[RecognitionRetrievalRow], dict[str, RecognitionRetrievalRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            style = self._stem_style_for_question(q)
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "recognition_total": 0,
                    "recognition_correct": 0,
                    "retrieval_total": 0,
                    "retrieval_correct": 0,
                },
            )
            events = question_history_map.get(int(q.get("question_number") or 0), [])
            for event in events:
                if style in ("Definition", "General"):
                    bucket["recognition_total"] += 1
                    bucket["recognition_correct"] += 1 if event.get("correct") else 0
                else:
                    bucket["retrieval_total"] += 1
                    bucket["retrieval_correct"] += 1 if event.get("correct") else 0
        rows: list[RecognitionRetrievalRow] = []
        row_map: dict[str, RecognitionRetrievalRow] = {}
        for key, bucket in grouped.items():
            recognition_score = (
                (int(bucket["recognition_correct"]) / max(int(bucket["recognition_total"]), 1)) * 100.0
                if int(bucket["recognition_total"])
                else 0.0
            )
            retrieval_score = (
                (int(bucket["retrieval_correct"]) / max(int(bucket["retrieval_total"]), 1)) * 100.0
                if int(bucket["retrieval_total"])
                else 0.0
            )
            gap = round(max(0.0, recognition_score - retrieval_score), 1)
            row: RecognitionRetrievalRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "recognition_score": round(recognition_score, 1),
                "retrieval_score": round(retrieval_score, 1),
                "gap": gap,
                "note": f"{bucket['unit']} is {'recognition-heavy' if gap >= 12.0 else 'fairly balanced'} across visible-cue vs retrieval-style stems.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["gap"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_compression_point_rows(
        self,
        recognition_retrieval_map: dict[str, RecognitionRetrievalRow],
        abstraction_ladder_map: dict[str, AbstractionLadderRow],
    ) -> tuple[list[CompressionPointRow], dict[str, CompressionPointRow]]:
        rows: list[CompressionPointRow] = []
        row_map: dict[str, CompressionPointRow] = {}
        for key, rr_row in recognition_retrieval_map.items():
            ladder_row = abstraction_ladder_map.get(key, {"score": 60.0})
            basic_score = float(rr_row["recognition_score"])
            applied_score = min(float(rr_row["retrieval_score"]), float(ladder_row.get("score", 60.0)))
            gap = round(max(0.0, basic_score - applied_score), 1)
            row: CompressionPointRow = {
                "kind": str(rr_row["kind"]),
                "unit": str(rr_row["unit"]),
                "basic_score": round(basic_score, 1),
                "applied_score": round(applied_score, 1),
                "gap": gap,
                "note": f"{rr_row['unit']} holds under basic framing more than applied framing, which marks the compression point.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["gap"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_decision_latency_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[DecisionLatencyRow], dict[str, DecisionLatencyRow]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            response_seconds = self._effective_response_seconds(event)
            if response_seconds <= 0:
                continue
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "productive_total": 0.0,
                    "productive_seen": 0,
                    "confusion_total": 0.0,
                    "confusion_seen": 0,
                },
            )
            confidence = str(event.get("confidence") or "").strip()
            if event.get("correct") and confidence == "Sure":
                bucket["productive_total"] += response_seconds
                bucket["productive_seen"] += 1
            else:
                bucket["confusion_total"] += response_seconds
                bucket["confusion_seen"] += 1
        rows: list[DecisionLatencyRow] = []
        row_map: dict[str, DecisionLatencyRow] = {}
        for key, bucket in grouped.items():
            productive = (
                float(bucket["productive_total"]) / max(int(bucket["productive_seen"]), 1)
                if int(bucket["productive_seen"])
                else 0.0
            )
            confusion = (
                float(bucket["confusion_total"]) / max(int(bucket["confusion_seen"]), 1)
                if int(bucket["confusion_seen"])
                else 0.0
            )
            drag = round(max(0.0, confusion - productive), 1)
            row: DecisionLatencyRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "productive_seconds": round(productive, 1),
                "confusion_seconds": round(confusion, 1),
                "drag": drag,
                "note": f"{bucket['unit']} takes {drag}s longer under confusion than under clean reasoning.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["drag"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_answer_latency_diagnosis_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> list[AnswerLatencyDiagnosisRow]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            response_seconds = self._effective_response_seconds(event)
            if response_seconds <= 0:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "fast_wrong": 0,
                    "slow_wrong": 0,
                    "fast_correct": 0,
                    "slow_correct": 0,
                    "seconds_total": 0.0,
                    "seen": 0,
                },
            )
            is_correct = bool(event.get("correct"))
            if is_correct and response_seconds <= 7.0:
                bucket["fast_correct"] += 1
            elif is_correct and response_seconds >= 16.0:
                bucket["slow_correct"] += 1
            elif not is_correct and response_seconds <= 7.0:
                bucket["fast_wrong"] += 1
            elif not is_correct and response_seconds >= 16.0:
                bucket["slow_wrong"] += 1
            bucket["seconds_total"] += response_seconds
            bucket["seen"] += 1
        rows: list[AnswerLatencyDiagnosisRow] = []
        for bucket in grouped.values():
            fast_wrong = int(bucket["fast_wrong"])
            slow_wrong = int(bucket["slow_wrong"])
            fast_correct = int(bucket["fast_correct"])
            slow_correct = int(bucket["slow_correct"])
            if not any((fast_wrong, slow_wrong, fast_correct, slow_correct)):
                continue
            if fast_wrong >= max(1, slow_wrong):
                label = "Speed risk"
                note = "Fast misses suggest the answer is being chosen before the prompt is fully processed."
            elif slow_wrong:
                label = "Overthinking risk"
                note = "Slow misses suggest uncertainty is dragging the decision without improving accuracy."
            elif slow_correct:
                label = "Slow but accurate"
                note = "Correct answers are landing, but recall is still effort-heavy."
            else:
                label = "Fast stable"
                note = "Fast correct answers look fluent, but keep occasional delayed checks."
            pressure = round(fast_wrong * 28.0 + slow_wrong * 22.0 + slow_correct * 8.0 - fast_correct * 3.0, 1)
            pressure = max(0.0, min(100.0, pressure))
            rows.append(
                {
                    "kind": str(bucket["kind"]),
                    "unit": str(bucket["unit"]),
                    "label": label,
                    "fast_wrong": fast_wrong,
                    "slow_wrong": slow_wrong,
                    "fast_correct": fast_correct,
                    "slow_correct": slow_correct,
                    "avg_seconds": round(float(bucket["seconds_total"]) / max(int(bucket["seen"]), 1), 1),
                    "pressure": pressure,
                    "note": note,
                }
            )
        rows.sort(key=lambda row: (row["pressure"], row["fast_wrong"], row["slow_wrong"], row["unit"]), reverse=True)
        return rows[:12]

    def _build_confidence_mismatch_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> list[ConfidenceMismatchRow]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            if str(event.get("confidence") or "").strip() != "Sure":
                continue
            qnum = int(event.get("question_number") or 0)
            q = question_lookup.get(qnum)
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {"kind": kind, "unit": unit, "sure_attempts": 0, "sure_wrong": 0, "examples": set()},
            )
            bucket["sure_attempts"] += 1
            if not event.get("correct"):
                bucket["sure_wrong"] += 1
                bucket["examples"].add(qnum)
        rows: list[ConfidenceMismatchRow] = []
        for bucket in grouped.values():
            sure_attempts = int(bucket["sure_attempts"])
            sure_wrong = int(bucket["sure_wrong"])
            if sure_attempts < 2 or sure_wrong <= 0:
                continue
            wrong_rate = round((sure_wrong / max(sure_attempts, 1)) * 100.0, 1)
            pressure = round(min(100.0, wrong_rate * 0.9 + sure_wrong * 12.0), 1)
            rows.append(
                {
                    "kind": str(bucket["kind"]),
                    "unit": str(bucket["unit"]),
                    "sure_attempts": sure_attempts,
                    "sure_wrong": sure_wrong,
                    "sure_wrong_rate": wrong_rate,
                    "example_question_numbers": sorted(bucket["examples"])[:6],
                    "pressure": pressure,
                    "note": f"{bucket['unit']} has confident misses; treat 'Sure' here as unverified until recovered by delayed checks.",
                }
            )
        rows.sort(key=lambda row: (row["pressure"], row["sure_wrong"], row["unit"]), reverse=True)
        return rows[:12]

    def _build_cue_dependence_rows(
        self,
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        recognition_retrieval_map: dict[str, RecognitionRetrievalRow],
        phrasing_map: dict[int, PhrasingNormalizationRow],
        questions=None,
    ) -> tuple[list[CueDependenceRow], dict[int, CueDependenceRow]]:
        rows: list[CueDependenceRow] = []
        row_map: dict[int, CueDependenceRow] = {}
        for q in list(questions or self.master_questions):
            qnum = int(q.get("question_number") or 0)
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            rr_row = recognition_retrieval_map.get(unit_key, {"gap": 0.0})
            phrasing_row = phrasing_map.get(qnum, {"score": 100.0})
            correct_choice_lengths = [
                len(str((q.get("choices") or {}).get(letter, "")).strip()) for letter in q.get("correct", [])
            ]
            all_choice_lengths = [
                len(str(text or "").strip()) for text in (q.get("choices") or {}).values() if str(text or "").strip()
            ]
            cue_score = float(rr_row.get("gap", 0.0)) * 0.52
            if correct_choice_lengths and all_choice_lengths:
                longest = max(all_choice_lengths)
                if max(correct_choice_lengths) >= longest:
                    cue_score += 10.0
            if re.search(
                r"\([A-Z0-9]{2,8}\)",
                " ".join(str((q.get("choices") or {}).get(letter, "")) for letter in q.get("correct", [])),
            ):
                cue_score += 8.0
            cue_score += max(0.0, 84.0 - float(phrasing_row.get("score", 100.0))) * 0.22
            style = self._stem_style_for_question(q)
            if style in ("Definition", "General"):
                cue_score += 6.0
            cue_score = round(min(100.0, cue_score), 1)
            stage = "Pressure" if cue_score >= 55.0 else "Reduced" if cue_score >= 32.0 else "Normal"
            row: CueDependenceRow = {
                "question_number": qnum,
                "kind": kind,
                "unit": unit,
                "score": cue_score,
                "stage": stage,
                "note": f"Q{qnum} currently looks {stage.lower()} on cue dependence, so it should not over-credit surface recognition.",
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda row: (row["score"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_contrast_rule_rows(
        self,
        counterfactual_rows: list[CounterfactualDistractorRow],
        confusion_pairs: list[ConfusionPairRow],
        questions=None,
    ) -> tuple[list[ContrastRuleRow], dict[str, float]]:
        rows: list[ContrastRuleRow] = []
        pressure_map: dict[str, float] = {}
        for row in counterfactual_rows[:8]:
            key = f"{row['kind']}::{row['unit']}"
            pressure = float(row["pressure"])
            pressure_map[key] = max(pressure_map.get(key, 0.0), pressure)
            rows.append(
                {
                    "kind": str(row["kind"]),
                    "unit": str(row["unit"]),
                    "rule": f"{row['correct']} != {row['distractor']}",
                    "pressure": pressure,
                    "note": f"The engine should keep contrasting {row['correct']} against {row['distractor']} until the deciding clue is automatic.",
                }
            )
        for pair in confusion_pairs[:8]:
            key = f"Topic::{pair['topics'].split(',')[0].strip()}" if pair.get("topics") else ""
            if key:
                pressure_map[key] = max(pressure_map.get(key, 0.0), float(pair["count"]) * 12.0)
            rows.append(
                {
                    "kind": "Concept",
                    "unit": str(pair["pair"]),
                    "rule": f"{pair['left']} != {pair['right']}",
                    "pressure": round(min(100.0, float(pair["count"]) * 12.0), 1),
                    "note": pair["action"],
                }
            )
        rows.sort(key=lambda row: (row["pressure"], row["rule"]), reverse=True)
        return rows[:12], pressure_map

    def _build_counterexample_training_rows(
        self,
        counterfactual_rows: list[CounterfactualDistractorRow],
        contrast_pressure_map: dict[str, float],
        questions=None,
    ) -> tuple[list[CounterexampleTrainingRow], dict[int, CounterexampleTrainingRow]]:
        rows: list[CounterexampleTrainingRow] = []
        row_map: dict[int, CounterexampleTrainingRow] = {}
        question_list = list(questions or self.master_questions)
        for q in question_list:
            qnum = int(q.get("question_number") or 0)
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            cue = ""
            pressure = float(contrast_pressure_map.get(unit_key, 0.0))
            for row in counterfactual_rows:
                if str(row["kind"]) == kind and str(row["unit"]) == unit:
                    cue = str(row["distractor"])
                    pressure = max(pressure, float(row["pressure"]))
            if pressure <= 0:
                continue
            training_row: CounterexampleTrainingRow = {
                "question_number": qnum,
                "kind": kind,
                "unit": unit,
                "pressure": round(min(100.0, pressure), 1),
                "cue": cue or "counterexample",
                "note": f"Q{qnum} is a good counterexample surface for {unit} because it can break the wrong rule anchored on {cue or 'a tempting distractor'}.",
            }
            rows.append(training_row)
            row_map[qnum] = training_row
        rows.sort(key=lambda row: (row["pressure"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_retention_stress_rows(
        self,
        records,
        concept_half_life_map: dict[str, ConceptHalfLifeRow],
        robustness_map: dict[str, RobustnessScoreRow],
        questions=None,
    ) -> tuple[list[RetentionStressRow], dict[int, RetentionStressRow]]:
        rows: list[RetentionStressRow] = []
        row_map: dict[int, RetentionStressRow] = {}
        now = datetime.now()
        for q in list(questions or self.master_questions):
            qnum = int(q.get("question_number") or 0)
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            if is_active_weak(rec) or is_review_due(rec):
                continue
            raw_seen = str(rec.get("last_seen") or "").strip()
            if not raw_seen:
                continue
            try:
                seen_at = datetime.strptime(raw_seen, "%Y-%m-%d")
            except Exception:
                continue
            days_since = max(0.0, (now - seen_at).total_seconds() / 86400.0)
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            half_life_row = concept_half_life_map.get(unit_key, {"half_life_days": 4.0})
            robustness_row = robustness_map.get(unit_key, {"score": 60.0})
            half_life_days = float(half_life_row.get("half_life_days", 4.0))
            pressure = (
                max(0.0, days_since - half_life_days) * 12.0
                + max(0.0, float(robustness_row.get("score", 60.0)) - 70.0) * 0.25
            )
            if pressure < 18.0:
                continue
            label = "Stress test" if pressure >= 36.0 else "Watch"
            row: RetentionStressRow = {
                "question_number": qnum,
                "kind": kind,
                "unit": unit,
                "pressure": round(min(100.0, pressure), 1),
                "label": label,
                "note": f"Q{qnum} has held for {round(days_since, 1)} day(s) and is ready for a harder delayed check.",
            }
            rows.append(row)
            row_map[qnum] = row
        rows.sort(key=lambda row: (row["pressure"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_failure_mode_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[FailureModeRow], dict[str, FailureModeRow]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(key, {"kind": kind, "unit": unit, "counts": {}})
            labels = []
            reason = str(event.get("miss_reason") or "").strip()
            family = str(event.get("wrong_answer_family") or "").strip()
            trap_words = {str(word).strip() for word in event.get("trap_words") or [] if str(word).strip()}
            if reason == "Misread" or trap_words:
                labels.append("scope failure")
            if family == "Order-of-operations trap":
                labels.append("timeline failure")
            if family in ("Near-synonym / look-alike distractor", "Technically true but not best"):
                labels.append("synonym failure")
            if family == "Too-broad distractor":
                labels.append("overgeneralization failure")
            if reason == "Changed answer":
                labels.append("decision reversal failure")
            if not labels and not event.get("correct"):
                labels.append("plausible distractor failure")
            for label in labels:
                bucket["counts"][label] = bucket["counts"].get(label, 0) + 1
        rows: list[FailureModeRow] = []
        row_map: dict[str, FailureModeRow] = {}
        for key, bucket in grouped.items():
            if not bucket["counts"]:
                continue
            mode, count = max(bucket["counts"].items(), key=lambda item: item[1])
            pressure = round(min(100.0, count * 14.0), 1)
            row: FailureModeRow = {
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "mode": mode,
                "pressure": pressure,
                "evidence": f"{count} recent event(s)",
                "note": f"{bucket['unit']} is mostly failing through {mode}, so the engine should target that exact failure shape.",
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["pressure"], row["unit"]), reverse=True)
        return rows[:12], row_map

    def _build_expected_learning_gain_rows(
        self,
        records,
        knowledge_trace_map: dict[str, KnowledgeTraceRow],
        leverage_map: dict[str, LeverageRankingRow],
        difficulty_map: dict[int, DifficultyCalibrationRow],
        questions=None,
    ) -> tuple[list[ExpectedLearningGainRow], dict[int, ExpectedLearningGainRow]]:
        rows: list[ExpectedLearningGainRow] = []
        row_map: dict[int, ExpectedLearningGainRow] = {}
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            knowledge = knowledge_trace_map.get(unit_key, {"mastery_prob": 40.0, "uncertainty": 60.0})
            leverage = leverage_map.get(unit_key, {"leverage": 0.0})
            difficulty = difficulty_map.get(int(q.get("question_number") or 0), {"score": 40.0})
            gain = (100.0 - float(knowledge.get("mastery_prob", 40.0))) * 0.34
            gain += float(knowledge.get("uncertainty", 60.0)) * 0.36
            gain += float(leverage.get("leverage", 0.0)) * 0.16
            gain += float(difficulty.get("score", 40.0)) * 0.12
            if is_active_weak(rec):
                gain += 8.0
            if is_review_due(rec):
                gain += 4.0
            row: ExpectedLearningGainRow = {
                "question_number": int(q.get("question_number") or 0),
                "kind": kind,
                "unit": unit,
                "expected_gain": round(min(100.0, gain), 1),
                "uncertainty": float(knowledge.get("uncertainty", 60.0)),
                "leverage": float(leverage.get("leverage", 0.0)),
                "note": f"Q{q.get('question_number')} should produce above-average learning gain because the concept is both uncertain and high value.",
            }
            rows.append(row)
            row_map[int(q.get("question_number") or 0)] = row
        rows.sort(key=lambda row: (row["expected_gain"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_delayed_probe_rows(
        self,
        records,
        concept_half_life_map: dict[str, ConceptHalfLifeRow],
        questions=None,
    ) -> tuple[list[DelayedProbeRow], dict[int, DelayedProbeRow]]:
        rows: list[DelayedProbeRow] = []
        row_map: dict[int, DelayedProbeRow] = {}
        now = datetime.now()
        for q in list(questions or self.master_questions):
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec) or is_active_weak(rec) or is_review_due(rec):
                continue
            raw_seen = str(rec.get("last_seen") or "").strip()
            if not raw_seen:
                continue
            try:
                seen_at = datetime.strptime(raw_seen, "%Y-%m-%d")
            except Exception:
                continue
            days_since_seen = max(0.0, (now - seen_at).total_seconds() / 86400.0)
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            half_life_days = float((concept_half_life_map.get(unit_key) or {}).get("half_life_days", 4.0))
            pressure = max(0.0, days_since_seen - half_life_days * 0.65) * 16.0
            if pressure < 14.0:
                continue
            row: DelayedProbeRow = {
                "question_number": int(q.get("question_number") or 0),
                "kind": kind,
                "unit": unit,
                "days_since_seen": round(days_since_seen, 1),
                "pressure": round(min(100.0, pressure), 1),
                "note": f"Q{q.get('question_number')} is ripe for a surprise delayed probe after {round(days_since_seen, 1)} day(s).",
            }
            rows.append(row)
            row_map[int(q.get("question_number") or 0)] = row
        rows.sort(key=lambda row: (row["pressure"], row["days_since_seen"], row["question_number"]), reverse=True)
        return rows[:20], row_map

    def _build_concept_state_rows(
        self,
        knowledge_trace_map: dict[str, KnowledgeTraceRow],
        generalization_map: dict[str, GeneralizationScoreRow],
        robustness_map: dict[str, RobustnessScoreRow],
        concept_half_life_map: dict[str, ConceptHalfLifeRow],
    ) -> tuple[list[ConceptStateRow], dict[str, ConceptStateRow]]:
        rows: list[ConceptStateRow] = []
        row_map: dict[str, ConceptStateRow] = {}
        for key, knowledge_row in knowledge_trace_map.items():
            generalization = generalization_map.get(key, {"score": float(knowledge_row["mastery_prob"])})
            robustness = robustness_map.get(key, {"score": float(knowledge_row["mastery_prob"])})
            half_life = concept_half_life_map.get(key, {"half_life_days": 4.0})
            mastery_prob = float(knowledge_row["mastery_prob"])
            generalization_score = float(generalization.get("score", mastery_prob))
            robustness_score = float(robustness.get("score", mastery_prob))
            if mastery_prob < 42.0:
                state = "unknown"
            elif mastery_prob < 58.0:
                state = "fragile"
            elif generalization_score < 56.0:
                state = "recognizable"
            elif robustness_score < 66.0:
                state = "retrievable"
            elif float(half_life.get("half_life_days", 4.0)) < 6.0:
                state = "transferable"
            else:
                state = "stable"
            row: ConceptStateRow = {
                "kind": str(knowledge_row["kind"]),
                "unit": str(knowledge_row["unit"]),
                "canonical_concept_id": str(knowledge_row["canonical_concept_id"]),
                "state": state,
                "mastery_prob": mastery_prob,
                "robustness": robustness_score,
                "generalization": generalization_score,
                "half_life_days": float(half_life.get("half_life_days", 4.0)),
            }
            rows.append(row)
            row_map[key] = row
        rows.sort(key=lambda row: (row["mastery_prob"], row["generalization"], row["unit"]))
        return rows[:20], row_map

    def _build_coverage_gap_rows(self, records, questions=None) -> list[CoverageGapRow]:
        question_list = list(questions or self.master_questions)
        unit_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for q in question_list:
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            kind, unit = self._coverage_unit_for_question(q)
            row = unit_rows.setdefault(
                (kind, unit),
                {
                    "kind": kind,
                    "unit": unit,
                    "available": 0,
                    "attempted": 0,
                    "correct_events": 0,
                    "attempt_events": 0,
                    "sources": set(),
                },
            )
            row["available"] += 1
            row["sources"].add(str(q.get("source_name") or "Unknown source"))
            attempts = int(rec.get("attempts", 0))
            row["attempted"] += 1 if attempts > 0 else 0
            row["attempt_events"] += attempts
            row["correct_events"] += int(rec.get("correct_count", 0))
        results: list[CoverageGapRow] = []
        for row in unit_rows.values():
            attempted = int(row["attempted"])
            available = int(row["available"])
            coverage = (attempted / max(available, 1)) * 100.0
            accuracy = (
                (int(row["correct_events"]) / max(int(row["attempt_events"]), 1)) * 100.0
                if int(row["attempt_events"])
                else 0.0
            )
            severity = max(0.0, 100.0 - coverage)
            severity += max(0.0, min(18.0, available * 2.2 - attempted * 1.4))
            if attempted:
                severity += max(0.0, 68.0 - accuracy) * 0.18
            results.append(
                {
                    "unit": row["unit"],
                    "kind": row["kind"],
                    "available": available,
                    "attempted": attempted,
                    "accuracy": round(accuracy, 1),
                    "severity": round(min(100.0, severity), 1),
                    "sources": sorted(row["sources"]),
                }
            )
        results.sort(key=lambda row: (row["severity"], row["available"], row["unit"]), reverse=True)
        return results[:12]

    def _build_confusion_pair_rows(self, history: list[QuestionHistoryEvent]) -> list[ConfusionPairRow]:
        pair_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for event in history:
            if event.get("correct"):
                continue
            selected_labels = [self._choice_concept_label(text) for text in event.get("selected_texts") or []]
            correct_labels = [self._choice_concept_label(text) for text in event.get("correct_texts") or []]
            for wrong_label in selected_labels:
                for correct_label in correct_labels:
                    if not wrong_label or not correct_label or wrong_label == correct_label:
                        continue
                    left, right = sorted((wrong_label, correct_label), key=str.lower)
                    row = pair_rows.setdefault(
                        (left, right),
                        {
                            "left": left,
                            "right": right,
                            "count": 0,
                            "domains": set(),
                            "topics": set(),
                            "question_numbers": set(),
                        },
                    )
                    row["count"] += 1
                    row["domains"].add(str(event.get("domain") or "Unsorted"))
                    for topic in event.get("topics") or []:
                        topic_text = str(topic).strip()
                        if topic_text:
                            row["topics"].add(topic_text)
                    row["question_numbers"].add(int(event.get("question_number") or 0))
        results: list[ConfusionPairRow] = []
        for row in pair_rows.values():
            action = (
                f"Drill the deciding difference between {row['left']} and {row['right']} until the clue is automatic."
            )
            results.append(
                {
                    "pair": f"{row['left']} vs {row['right']}",
                    "left": row["left"],
                    "right": row["right"],
                    "count": row["count"],
                    "domains": ", ".join(sorted(row["domains"])[:2]),
                    "topics": ", ".join(sorted(row["topics"])[:2]),
                    "question_numbers": sorted(row["question_numbers"]),
                    "action": action,
                }
            )
        results.sort(key=lambda row: (row["count"], row["pair"]), reverse=True)
        return results[:10]

    def _build_recall_failure_rows(self, history: list[QuestionHistoryEvent]) -> list[RecallFailureRow]:
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            failure = str(event.get("recall_failure") or "").strip()
            if not failure and not event.get("correct"):
                failure = self.classify_recall_failure({}, False, event)
            if not failure:
                continue
            row = grouped.setdefault(
                failure,
                {
                    "count": 0,
                    "misses": 0,
                    "domains": set(),
                    "clues": {},
                },
            )
            row["count"] += 1
            if not event.get("correct"):
                row["misses"] += 1
            domain = str(event.get("domain") or "Unsorted")
            row["domains"].add(domain)
            clue = str(event.get("deciding_clue") or "").strip()
            if clue:
                row["clues"][clue] = int(row["clues"].get(clue, 0)) + 1
        results: list[RecallFailureRow] = []
        for failure, row in grouped.items():
            clue_counts = sorted(row["clues"].items(), key=lambda item: (item[1], item[0]), reverse=True)
            accuracy_drag = round((int(row["misses"]) / max(int(row["count"]), 1)) * 100.0, 1)
            results.append(
                {
                    "failure": failure,
                    "count": int(row["count"]),
                    "accuracy_drag": accuracy_drag,
                    "domains": ", ".join(sorted(row["domains"])[:3]),
                    "clues": ", ".join(clue for clue, _count in clue_counts[:4]),
                    "note": f"{failure} appeared {row['count']} times; schedule retrieval drills around the listed clues.",
                }
            )
        results.sort(key=lambda row: (row["accuracy_drag"], row["count"], row["failure"]), reverse=True)
        return results[:8]

    def _build_deciding_clue_rows(self, history: list[QuestionHistoryEvent]) -> list[DecidingClueRow]:
        grouped: dict[str, dict[str, Any]] = {}
        for event in history:
            clue = str(event.get("deciding_clue") or "").strip()
            if not clue:
                continue
            row = grouped.setdefault(
                clue,
                {
                    "seen": 0,
                    "misses": 0,
                    "fragile_correct": 0,
                    "domains": set(),
                },
            )
            row["seen"] += 1
            confidence = str(event.get("confidence") or "").strip()
            if event.get("correct"):
                if confidence in ("Guessed", "Unsure"):
                    row["fragile_correct"] += 1
            else:
                row["misses"] += 1
            row["domains"].add(str(event.get("domain") or "Unsorted"))
        results: list[DecidingClueRow] = []
        for clue, row in grouped.items():
            seen = int(row["seen"])
            misses = int(row["misses"])
            fragile = int(row["fragile_correct"])
            mastery_signal = round(max(0.0, 100.0 - (misses * 70.0 + fragile * 35.0) / max(seen, 1)), 1)
            results.append(
                {
                    "clue": clue,
                    "seen": seen,
                    "misses": misses,
                    "fragile_correct": fragile,
                    "mastery_signal": mastery_signal,
                    "domains": ", ".join(sorted(row["domains"])[:3]),
                    "note": (
                        f"Clue '{clue}' needs stronger recall."
                        if mastery_signal < 72.0
                        else f"Clue '{clue}' is becoming reliable."
                    ),
                }
            )
        results.sort(key=lambda row: (row["mastery_signal"], -row["seen"], row["clue"]))
        return results[:12]

    def _concept_memory_next_ramp(self, state: str) -> str:
        return {
            "new": "recognition",
            "recognizable": "retrieval",
            "retrievable": "transfer",
            "transferable": "durability",
            "durable": "durability",
        }.get(str(state or "").strip(), "recognition")

    def _build_concept_memory_state_rows(
        self,
        question_history_map: dict[int, list[QuestionHistoryEvent]],
        questions=None,
    ) -> tuple[list[ConceptMemoryStateRow], dict[str, ConceptMemoryStateRow]]:
        grouped: dict[str, dict[str, Any]] = {}
        for q in list(questions or self.master_questions):
            rec = self._progress_record(q, create=False) or {}
            if is_suspended(rec):
                continue
            kind, unit = self._coverage_unit_for_question(q)
            key = f"{kind}::{unit}"
            bucket = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "unit": unit,
                    "concept_id": self._canonical_concept_id(q),
                    "events": [],
                    "styles": set(),
                    "sources": set(),
                    "correct_styles": set(),
                    "correct_sources": set(),
                    "last_correct_at": None,
                },
            )
            style = self._stem_style_for_question(q)
            source_name = str(q.get("source_name") or "Unknown source")
            bucket["styles"].add(style)
            bucket["sources"].add(source_name)
            events = question_history_map.get(int(q.get("question_number") or 0), [])
            bucket["events"].extend(events)
            for event in events:
                if event.get("correct"):
                    bucket["correct_styles"].add(style)
                    bucket["correct_sources"].add(source_name)
                    event_time = self._parse_event_time(event)
                    if event_time != datetime.min and (
                        bucket["last_correct_at"] is None or event_time > bucket["last_correct_at"]
                    ):
                        bucket["last_correct_at"] = event_time

        rows: list[ConceptMemoryStateRow] = []
        row_map: dict[str, ConceptMemoryStateRow] = {}
        now = datetime.now()
        for key, bucket in grouped.items():
            events = list(bucket["events"])
            evidence_count = len(events)
            correct_events = [event for event in events if event.get("correct")]
            wrong_events = [event for event in events if not event.get("correct")]
            fragile_correct = [
                event
                for event in correct_events
                if str(event.get("confidence") or "").strip() in ("Guessed", "Unsure")
                or str(event.get("recall_failure") or "").strip() in ("Recognition without recall", "Fragile retrieval")
            ]
            sure_correct = [event for event in correct_events if str(event.get("confidence") or "").strip() == "Sure"]
            weighted_confidence = sum(self._confidence_weight(event.get("confidence")) for event in correct_events)
            confidence_quality = (
                round((weighted_confidence / max(len(correct_events), 1)) * 100.0, 1) if correct_events else 0.0
            )
            transfer_evidence = len(bucket["correct_styles"]) + len(bucket["correct_sources"])
            last_correct_at = bucket.get("last_correct_at")
            days_since_correct = 0.0
            if last_correct_at:
                days_since_correct = max(0.0, (now - last_correct_at).total_seconds() / 86400.0)
            durability_signal = min(
                100.0,
                len(sure_correct) * 18.0
                + transfer_evidence * 10.0
                + min(28.0, days_since_correct * 4.0)
                - len(wrong_events) * 9.0
                - len(fragile_correct) * 6.0,
            )
            durability_signal = round(max(0.0, durability_signal), 1)
            if evidence_count <= 0:
                state = "new"
            elif not correct_events:
                state = "recognizable"
            elif len(correct_events) == 1 and fragile_correct:
                state = "recognizable"
            elif (
                len(sure_correct) >= 3
                and transfer_evidence >= 4
                and durability_signal >= 72.0
                and days_since_correct >= 1.0
            ):
                state = "durable"
            elif len(correct_events) >= 2 and transfer_evidence >= 3:
                state = "transferable"
            elif sure_correct:
                state = "retrievable"
            else:
                state = "recognizable"
            row: ConceptMemoryStateRow = {
                "concept_id": str(bucket["concept_id"]),
                "kind": str(bucket["kind"]),
                "unit": str(bucket["unit"]),
                "state": state,
                "evidence_count": evidence_count,
                "confidence_quality": confidence_quality,
                "transfer_evidence": int(transfer_evidence),
                "durability_signal": durability_signal,
                "next_ramp": self._concept_memory_next_ramp(state),
                "note": f"{bucket['unit']} is {state}; next best ramp is {self._concept_memory_next_ramp(state)}.",
            }
            rows.append(row)
            row_map[key] = row
        state_order = {"new": 0, "recognizable": 1, "retrievable": 2, "transferable": 3, "durable": 4}
        rows.sort(key=lambda row: (state_order.get(row["state"], 9), row["durability_signal"], row["unit"]))
        return rows, row_map

    def _build_wrong_answer_memory_rows(
        self,
        history: list[QuestionHistoryEvent],
        questions=None,
    ) -> tuple[list[WrongAnswerMemoryRow], dict[str, float]]:
        question_lookup = {int(q.get("question_number") or 0): q for q in list(questions or self.master_questions)}
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        recovery_counts: dict[str, int] = {}
        for event in history:
            q = question_lookup.get(int(event.get("question_number") or 0))
            if not q:
                continue
            rec = self._progress_record(q, create=False) or {}
            if is_suspended(rec):
                continue
            kind, unit = self._coverage_unit_for_question(q)
            concept_key = f"{kind}::{unit}"
            if event.get("correct"):
                recovery_counts[concept_key] = recovery_counts.get(concept_key, 0) + 1
                continue
            correct_labels = [
                self._choice_concept_label(text) or str(text).strip()[:48]
                for text in event.get("correct_texts") or []
                if str(text).strip()
            ]
            selected_labels = [
                self._choice_concept_label(text) or str(text).strip()[:48]
                for text in event.get("selected_texts") or []
                if str(text).strip()
            ]
            for distractor in selected_labels:
                for correct in correct_labels:
                    if not distractor or not correct or distractor == correct:
                        continue
                    key = (concept_key, distractor, correct)
                    row = grouped.setdefault(
                        key,
                        {
                            "concept_id": self._canonical_concept_id(kind, unit),
                            "kind": kind,
                            "unit": unit,
                            "tempting_distractor": distractor,
                            "correct_concept": correct,
                            "count": 0,
                            "last_seen": "",
                            "examples": set(),
                            "fragile": 0,
                        },
                    )
                    row["count"] += 1
                    if str(event.get("confidence") or "").strip() in ("Guessed", "Unsure"):
                        row["fragile"] += 1
                    row["examples"].add(int(event.get("question_number") or 0))
                    seen = str(event.get("at") or "")
                    if seen > str(row.get("last_seen") or ""):
                        row["last_seen"] = seen

        rows: list[WrongAnswerMemoryRow] = []
        pressure_map: dict[str, float] = {}
        for (concept_key, _distractor, _correct), row in grouped.items():
            pressure = int(row["count"]) * 22.0 + int(row["fragile"]) * 5.0 - recovery_counts.get(concept_key, 0) * 5.0
            pressure = round(max(8.0, min(100.0, pressure)), 1)
            pressure_map[concept_key] = max(pressure_map.get(concept_key, 0.0), pressure)
            rows.append(
                {
                    "concept_id": str(row["concept_id"]),
                    "kind": str(row["kind"]),
                    "unit": str(row["unit"]),
                    "tempting_distractor": str(row["tempting_distractor"]),
                    "correct_concept": str(row["correct_concept"]),
                    "count": int(row["count"]),
                    "last_seen": str(row["last_seen"]),
                    "pressure": pressure,
                    "example_question_numbers": sorted(row["examples"]),
                    "note": f"{row['tempting_distractor']} is repeatedly competing with {row['correct_concept']} for {row['unit']}.",
                }
            )
        rows.sort(key=lambda row: (row["pressure"], row["count"], row["unit"]), reverse=True)
        return rows[:20], pressure_map

    def _coverage_gap_priority_map(self, coverage_rows: list[CoverageGapRow]) -> dict[str, float]:
        return {f"{row['kind']}::{row['unit']}": float(row["severity"]) for row in coverage_rows}

    def _analytics_signature(self):
        session_rows = tuple(
            (
                q.get("question_number"),
                bool(q.get("answered")),
                tuple(q.get("selected", [])),
                bool(q.get("flagged")),
                bool(q.get("suspended")),
                str(q.get("last_confidence", "")),
                str(q.get("last_miss_reason", "")),
            )
            for q in self.questions
        )
        progress_rows = tuple(
            (
                key,
                int(rec.get("attempts", 0)),
                int(rec.get("correct_count", 0)),
                int(rec.get("wrong_count", 0)),
                int(rec.get("correct_streak", 0)),
                str(rec.get("last_seen", "")),
                str(rec.get("next_review", "")),
                bool(rec.get("flagged")),
                bool(rec.get("suspended")),
                rec.get("last_correct"),
                str(rec.get("last_confidence", "")),
                str(rec.get("last_miss_reason", "")),
            )
            for key, rec in sorted((self._progress_questions() or {}).items())
        )
        history_rows = tuple(
            (
                str(event.get("at", "")),
                int(event.get("question_number", 0)),
                bool(event.get("correct")),
                str(event.get("confidence", "")),
                str(event.get("miss_reason", "")),
                tuple(event.get("trap_words") or []),
                str(event.get("wrong_answer_family", "")),
                str(event.get("recall_failure", "")),
                str(event.get("deciding_clue", "")),
            )
            for event in self._progress_history()
        )
        return (
            self.active_session_mode,
            tuple(q.get("question_number") for q in self.master_questions),
            tuple(q.get("question_number") for q in self.questions),
            session_rows,
            progress_rows,
            history_rows,
        )

    def _decision_quality_score(self, history: list[QuestionHistoryEvent], progress: ProgressSummary) -> float:
        if not history:
            return 0.0
        earned = 0.0
        total = 0.0
        for event in history:
            confidence = str(event.get("confidence") or "").strip()
            weight = {
                "Sure": 1.0,
                "Unsure": 0.82,
                "Guessed": 0.62,
            }.get(confidence, 0.85)
            total += 1.0
            if event.get("correct"):
                earned += weight
                if confidence == "Sure":
                    earned += 0.08
            else:
                if confidence == "Sure":
                    earned -= 0.45
                elif confidence == "Guessed":
                    earned -= 0.1
                reason = str(event.get("miss_reason") or "").strip()
                if reason == "Changed answer":
                    earned -= 0.18
                elif reason == "Misread":
                    earned -= 0.12
        raw = (earned / max(total, 1.0)) * 100.0
        raw -= progress.get("wrong", 0) * 2.8
        raw -= progress.get("due", 0) * 1.1
        raw += progress.get("recovered", 0) * 0.9
        return round(max(0.0, min(100.0, raw)), 1)

    def _question_stability_score(self, q, rec, history_events: list[QuestionHistoryEvent]) -> float:
        attempts = int(rec.get("attempts", 0))
        if attempts <= 0:
            return 0.0
        correct = int(rec.get("correct_count", 0))
        accuracy = correct / max(attempts, 1)
        streak = min(int(rec.get("correct_streak", 0)), 4)
        confidence_counts = dict(rec.get("confidence_counts") or {})
        confidence_total = sum(int(value or 0) for value in confidence_counts.values()) or attempts
        confidence_score = (
            int(confidence_counts.get("Sure", 0)) * 1.0
            + int(confidence_counts.get("Unsure", 0)) * 0.72
            + int(confidence_counts.get("Guessed", 0)) * 0.42
        ) / max(confidence_total, 1)
        flips = 0
        last_outcome = None
        for event in history_events:
            current = bool(event.get("correct"))
            if last_outcome is not None and current != last_outcome:
                flips += 1
            last_outcome = current
        score = accuracy * 46.0
        score += (streak / 4.0) * 24.0
        score += confidence_score * 16.0
        score += min(correct, 4) * 2.5
        if rec.get("last_correct") is True:
            score += 4.0
        if is_review_due(rec):
            score -= 10.0
        if is_active_weak(rec):
            score -= 24.0
        score -= min(flips, 5) * 4.0
        return round(max(0.0, min(100.0, score)), 1)

    def _concept_label_for_question(self, q) -> tuple[str, str]:
        topics = [str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()]
        if topics:
            return topics[0], str(q.get("domain") or "Unsorted")
        return str(q.get("domain") or "Unsorted"), str(q.get("domain") or "Unsorted")

    def _build_concept_clusters(
        self,
        history: list[QuestionHistoryEvent],
        records,
        question_stability: dict[int, float],
    ) -> list[ConceptClusterRow]:
        concept_rows = {}
        question_lookup = {int(q.get("question_number") or 0): q for q in self.master_questions}
        for event in history:
            if event.get("correct"):
                continue
            qnum = int(event.get("question_number") or 0)
            question = question_lookup.get(qnum)
            if not question:
                continue
            concepts = [str(topic).strip() for topic in event.get("topics") or [] if str(topic).strip()]
            if not concepts:
                concepts = [str(event.get("domain") or "Unsorted")]
            for concept in concepts:
                row = concept_rows.setdefault(
                    concept,
                    {
                        "concept": concept,
                        "domain": str(event.get("domain") or "Unsorted"),
                        "misses": 0,
                        "active_weak": 0,
                        "due": 0,
                        "volatility": 0.0,
                        "question_numbers": set(),
                        "miss_reason_counts": {},
                        "trap_counts": {},
                        "family_counts": {},
                    },
                )
                row["misses"] += 1
                row["question_numbers"].add(qnum)
                reason = str(event.get("miss_reason") or "").strip()
                if reason:
                    row["miss_reason_counts"][reason] = row["miss_reason_counts"].get(reason, 0) + 1
                for trap_word in event.get("trap_words") or []:
                    trap_word = str(trap_word).strip()
                    if trap_word:
                        row["trap_counts"][trap_word] = row["trap_counts"].get(trap_word, 0) + 1
                family = str(event.get("wrong_answer_family") or "").strip()
                if family:
                    row["family_counts"][family] = row["family_counts"].get(family, 0) + 1
        for row in concept_rows.values():
            active_weak = 0
            due = 0
            volatility = 0.0
            for qnum in row["question_numbers"]:
                question = question_lookup.get(int(qnum))
                if not question:
                    continue
                rec = records.get(self._question_key(question), {})
                if is_active_weak(rec):
                    active_weak += 1
                if is_review_due(rec):
                    due += 1
                volatility += max(0.0, 100.0 - question_stability.get(int(qnum), 0.0))
            top_reason = (
                max(row["miss_reason_counts"].items(), key=lambda item: item[1])[0] if row["miss_reason_counts"] else ""
            )
            top_trap = max(row["trap_counts"].items(), key=lambda item: item[1])[0] if row["trap_counts"] else ""
            top_family = max(row["family_counts"].items(), key=lambda item: item[1])[0] if row["family_counts"] else ""
            severity = round(
                row["misses"] * 4.4
                + active_weak * 5.2
                + due * 2.6
                + (volatility / max(len(row["question_numbers"]), 1)) * 0.12,
                1,
            )
            row["active_weak"] = active_weak
            row["due"] = due
            row["volatility"] = round(volatility / max(len(row["question_numbers"]), 1), 1)
            row["top_miss_reason"] = top_reason
            row["top_trap_word"] = top_trap
            row["wrong_family"] = top_family
            row["severity"] = severity
        results: list[ConceptClusterRow] = []
        for row in concept_rows.values():
            results.append(
                {
                    "concept": row["concept"],
                    "domain": row["domain"],
                    "misses": row["misses"],
                    "active_weak": row["active_weak"],
                    "due": row["due"],
                    "volatility": row["volatility"],
                    "top_miss_reason": row["top_miss_reason"],
                    "top_trap_word": row["top_trap_word"],
                    "wrong_family": row["wrong_family"],
                    "question_numbers": sorted(int(value) for value in row["question_numbers"]),
                    "severity": row["severity"],
                }
            )
        results.sort(key=lambda row: (row["severity"], row["misses"], row["active_weak"], row["concept"]), reverse=True)
        return results[:10]

    def _build_remediation_cards(self, concept_clusters: list[ConceptClusterRow]) -> list[RemediationCardRow]:
        cards: list[RemediationCardRow] = []
        for cluster in concept_clusters[:6]:
            reason = cluster.get("top_miss_reason") or "Repeated misses"
            trap = cluster.get("top_trap_word") or ""
            family = cluster.get("wrong_family") or "Plausible distractor"
            if reason == "Did not know":
                action = "Rebuild the core definition first, then contrast it against the two nearest look-alikes."
                anchor = f"{cluster['concept']}: define it in one sentence before reviewing answer choices."
            elif reason == "Misread":
                action = "Read the ask first, circle the qualifier mentally, then eliminate answers that are true but not the best fit."
                anchor = f"{cluster['concept']}: slow down on wording cues like '{trap or 'best / most / first'}'."
            elif reason == "Narrowed to two":
                action = "Force a direct comparison between the last two answers and write the deciding clue in plain language."
                anchor = f"{cluster['concept']}: one clue must separate the key from the tempting distractor."
            else:
                action = "Stick with your first answer unless a later choice has direct evidence from the prompt."
                anchor = f"{cluster['concept']}: trust evidence over second-guessing."
            diagnosis = f"{reason}; most common distractor pattern is {family.lower()}."
            cards.append(
                {
                    "concept": cluster["concept"],
                    "diagnosis": diagnosis,
                    "action": action,
                    "anchor": anchor,
                    "focus_questions": list(cluster.get("question_numbers", []))[:4],
                    "severity": cluster["severity"],
                }
            )
        return cards

    def _build_pass_prediction(
        self,
        overall: AnalyticsOverall,
        progress: ProgressSummary,
        confidence_calibration: list[ConfidenceCalibrationRow],
        stability_score: float,
        volatile_rows: list[AnalyticsVolatilityRow],
        source_agreement_rows: list[SourceAgreementRow],
        coverage_gaps: list[CoverageGapRow],
    ) -> PassPrediction:
        sure_row = next((row for row in confidence_calibration if row["confidence"] == "Sure"), None)
        guessed_row = next((row for row in confidence_calibration if row["confidence"] == "Guessed"), None)
        sure_accuracy = sure_row["accuracy"] if sure_row else 0.0
        guessed_accuracy = guessed_row["accuracy"] if guessed_row else 0.0
        confidence_honesty = round(max(0.0, min(100.0, sure_accuracy - max(0.0, guessed_accuracy - 45.0))), 1)
        sample_strength = min(100.0, (progress.get("attempted", 0) / 180.0) * 100.0)
        volatility_penalty = min(18.0, len(volatile_rows[:8]) * 1.6)
        source_trust = (
            round(sum(row["score"] for row in source_agreement_rows) / len(source_agreement_rows) * 100.0, 1)
            if source_agreement_rows
            else 80.0
        )
        gap_penalty = (
            round(sum(row["severity"] for row in coverage_gaps[:3]) / max(len(coverage_gaps[:3]), 1), 1)
            if coverage_gaps
            else 0.0
        )
        score = (
            overall["recent50_accuracy"] * 0.28
            + overall["decision_quality"] * 0.24
            + stability_score * 0.24
            + sure_accuracy * 0.14
            + sample_strength * 0.10
        )
        score += max(0.0, source_trust - 75.0) * 0.05
        score -= progress.get("wrong", 0) * 1.5
        score -= progress.get("due", 0) * 0.8
        score -= volatility_penalty
        score -= gap_penalty * 0.08
        score = round(max(0.0, min(100.0, score)), 1)
        if score >= 78:
            label = "Likely ready"
        elif score >= 64:
            label = "Borderline"
        else:
            label = "Not ready"
        reasons = []
        if progress.get("attempted", 0) < 120:
            reasons.append(
                f"Only {progress.get('attempted', 0)} long-term answered questions are in the sample; confidence is still forming."
            )
        if progress.get("wrong", 0):
            reasons.append(f"{progress.get('wrong', 0)} active weak questions are still unresolved.")
        if progress.get("due", 0):
            reasons.append(f"{progress.get('due', 0)} questions are due for review and can still slip.")
        if sure_accuracy and sure_accuracy < 78:
            reasons.append(f"'Sure' answers are only {sure_accuracy}% accurate right now.")
        if stability_score < 70:
            reasons.append(
                f"Stability score is {stability_score}%, so knowledge is not holding consistently over time yet."
            )
        if source_trust < 84:
            reasons.append(
                f"Source agreement trust is {source_trust}%, so too much of your sample still relies on single-source-only items."
            )
        if coverage_gaps:
            top_gap = coverage_gaps[0]
            reasons.append(
                f"Coverage gap: {top_gap['kind']} {top_gap['unit']} is only {top_gap['attempted']}/{top_gap['available']} covered."
            )
        if not reasons:
            reasons.append("Recent accuracy, confidence honesty, and long-term stability are all holding up well.")
        return {
            "label": label,
            "score": score,
            "confidence_honesty": confidence_honesty,
            "readiness_floor": round(max(0.0, min(score, stability_score)), 1),
            "reasons": reasons[:4],
        }

    def _build_concept_anchor_notes(
        self, topic_rows: list[AnalyticsTopicRow], topic_history_map: dict[str, list[QuestionHistoryEvent]]
    ) -> list[ConceptAnchorNoteRow]:
        notes = []
        for row in topic_rows:
            events = [event for event in topic_history_map.get(row["topic"], []) if not event.get("correct")]
            if not events and not row.get("progress_active_weak"):
                continue
            reason_counts = {}
            trap_counts = {}
            for event in events:
                reason = str(event.get("miss_reason") or "").strip()
                if reason:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                for trap_word in event.get("trap_words") or []:
                    trap_counts[trap_word] = trap_counts.get(trap_word, 0) + 1
            top_reason = max(reason_counts.items(), key=lambda item: item[1])[0] if reason_counts else ""
            top_trap = max(trap_counts.items(), key=lambda item: item[1])[0] if trap_counts else ""
            if top_reason == "Did not know":
                note = "Say the core definition out loud before comparing answers."
            elif top_reason == "Misread":
                note = "Restate the ask first, then verify each qualifier before choosing."
            elif top_reason == "Narrowed to two":
                note = "Compare the last two choices and name the deciding clue."
            elif top_reason == "Changed answer":
                note = "Only change your first instinct when a choice has direct evidence."
            else:
                note = "Explain why the keyed answer wins over the tempting distractor."
            if top_trap:
                note += f" Watch for '{top_trap}' wording in this topic."
            notes.append(
                {
                    "topic": row["topic"],
                    "note": note,
                    "active_weak": row.get("progress_active_weak", 0),
                    "readiness": row.get("readiness", 0.0),
                }
            )
        notes.sort(key=lambda row: (row["active_weak"], -row["readiness"], row["topic"]), reverse=True)
        return notes[:8]

    def _build_wrong_answer_family_review(self, history: list[QuestionHistoryEvent]) -> list[WrongAnswerFamilyRow]:
        families = {}
        for event in history:
            if event.get("correct"):
                continue
            family = str(event.get("wrong_answer_family") or "").strip() or "Plausible distractor"
            row = families.setdefault(
                family, {"family": family, "count": 0, "domains": set(), "topics": set(), "examples": set()}
            )
            row["count"] += 1
            row["domains"].add(str(event.get("domain") or "Unsorted"))
            for topic in event.get("topics") or []:
                topic = str(topic).strip()
                if topic:
                    row["topics"].add(topic)
            for text in (event.get("selected_texts") or [])[:1]:
                text = str(text).strip()
                if text:
                    row["examples"].add(text[:80])
        coaching = {
            "Qualifier / exception trap": "Mark the reversal word first, then eliminate generally true answers.",
            "Technically true but not best": "Ask which choice is the best fit, not just a true statement.",
            "Order-of-operations trap": "Decide the timing before evaluating tools or controls.",
            "Near-synonym / look-alike distractor": "Name the one word that separates the two look-alike answers.",
            "Too-broad distractor": "Beware absolute language that sounds safe but overreaches.",
            "Plausible distractor": "Contrast why your pick is tempting with the specific clue supporting the key.",
        }
        rows = []
        for row in families.values():
            rows.append(
                {
                    "family": row["family"],
                    "count": row["count"],
                    "domains": ", ".join(sorted(row["domains"])[:2]),
                    "topics": ", ".join(sorted(row["topics"])[:2]),
                    "examples": "; ".join(sorted(row["examples"])[:2]),
                    "coaching": coaching.get(row["family"], coaching["Plausible distractor"]),
                }
            )
        rows.sort(key=lambda item: (item["count"], item["family"]), reverse=True)
        return rows[:6]

    def _build_analytics_payload(self, source=None) -> AnalyticsPayload:
        records = self._progress_questions()
        active_questions = [
            q for q in (source or self.questions) if not is_suspended(records.get(self._question_key(q), {}))
        ]
        questions = active_questions
        total = len(questions)
        answered = [q for q in questions if q.get("answered")]
        answered_count = len(answered)
        correct_count = sum(1 for q in answered if self._question_correct(q))
        wrong_count = answered_count - correct_count
        flagged_count = sum(1 for q in questions if q.get("flagged"))
        issues_count = sum(1 for q in questions if self.question_has_any_issue(q))
        unseen_count = total - answered_count
        accuracy = round((correct_count / answered_count) * 100, 1) if answered_count else 0.0
        recent = answered[-50:]
        recent_acc = (
            round(sum(1 for q in recent if self._question_correct(q)) / len(recent) * 100, 1) if recent else 0.0
        )
        history = [
            event
            for event in self._recent_history(28)
            if not is_suspended(records.get(str(event.get("question_number")), {}))
        ]
        decision_quality = self._decision_quality_score(history, self.progress_summary())

        domain_stats, topic_stats = {}, {}
        for q in questions:
            domain = q.get("domain") or "Unsorted"
            d = domain_stats.setdefault(
                domain, {"total": 0, "answered": 0, "correct": 0, "wrong": 0, "flagged": 0, "issues": 0}
            )
            d["total"] += 1
            d["flagged"] += 1 if q.get("flagged") else 0
            d["issues"] += 1 if self.question_has_any_issue(q) else 0
            if q.get("answered"):
                d["answered"] += 1
                if self._question_correct(q):
                    d["correct"] += 1
                else:
                    d["wrong"] += 1
            for topic in q.get("topics", []):
                topic = str(topic).strip()
                if not topic:
                    continue
                t = topic_stats.setdefault(topic, {"seen": 0, "correct": 0, "wrong": 0})
                if q.get("answered"):
                    t["seen"] += 1
                    if self._question_correct(q):
                        t["correct"] += 1
                    else:
                        t["wrong"] += 1

        progress_domain_stats, progress_topic_stats = {}, {}
        for q in self.master_questions:
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            domain = q.get("domain") or "Unsorted"
            d = progress_domain_stats.setdefault(
                domain,
                {
                    "progress_attempted": 0,
                    "progress_wrong": 0,
                    "progress_due": 0,
                    "progress_flagged": 0,
                    "progress_active_weak": 0,
                    "progress_recovered": 0,
                    "confidence_score": 0.0,
                    "confidence_seen": 0,
                },
            )
            attempts = int(rec.get("attempts", 0))
            d["progress_attempted"] += 1 if attempts else 0
            d["progress_wrong"] += int(rec.get("wrong_count", 0))
            d["progress_due"] += 1 if is_review_due(rec) else 0
            d["progress_flagged"] += 1 if rec.get("flagged") else 0
            d["progress_active_weak"] += 1 if is_active_weak(rec) else 0
            d["progress_recovered"] += 1 if is_ever_wrong(rec) and not is_active_weak(rec) else 0
            if rec.get("last_confidence"):
                d["confidence_score"] += self._confidence_weight(rec.get("last_confidence"))
                d["confidence_seen"] += 1
            for topic in q.get("topics", []):
                topic = str(topic).strip()
                if not topic:
                    continue
                t = progress_topic_stats.setdefault(
                    topic,
                    {
                        "progress_attempted": 0,
                        "progress_wrong": 0,
                        "progress_due": 0,
                        "progress_active_weak": 0,
                        "progress_recovered": 0,
                        "confidence_score": 0.0,
                        "confidence_seen": 0,
                    },
                )
                t["progress_attempted"] += 1 if attempts else 0
                t["progress_wrong"] += int(rec.get("wrong_count", 0))
                t["progress_due"] += 1 if is_review_due(rec) else 0
                t["progress_active_weak"] += 1 if is_active_weak(rec) else 0
                t["progress_recovered"] += 1 if is_ever_wrong(rec) and not is_active_weak(rec) else 0
                if rec.get("last_confidence"):
                    t["confidence_score"] += self._confidence_weight(rec.get("last_confidence"))
                    t["confidence_seen"] += 1

        domain_history_map = {}
        topic_history_map = {}
        question_history_map: dict[int, list[QuestionHistoryEvent]] = {}
        for event in history:
            domain = str(event.get("domain") or "Unsorted")
            domain_history_map.setdefault(domain, []).append(event)
            qnum = int(event.get("question_number") or 0)
            question_history_map.setdefault(qnum, []).append(event)
            for topic in event.get("topics") or []:
                topic = str(topic).strip()
                if topic:
                    topic_history_map.setdefault(topic, []).append(event)

        question_stability = {}
        for q in self.master_questions:
            rec = records.get(self._question_key(q), {})
            if not rec or is_suspended(rec):
                continue
            qnum = int(q.get("question_number") or 0)
            question_stability[qnum] = self._question_stability_score(q, rec, question_history_map.get(qnum, []))
        source_agreement_rows, source_agreement_map = self._build_source_agreement_rows(self.master_questions)
        source_trust_rows, source_trust_map = self._build_source_trust_rows(
            self.master_questions, source_agreement_rows
        )
        coverage_gaps = self._build_coverage_gap_rows(records, self.master_questions)
        coverage_gap_map = self._coverage_gap_priority_map(coverage_gaps)
        knowledge_trace_rows, knowledge_trace_map = self._build_knowledge_trace_rows(
            question_history_map, self.master_questions
        )
        concept_memory_state_rows, _concept_memory_state_map = self._build_concept_memory_state_rows(
            question_history_map, self.master_questions
        )
        wrong_answer_memory_rows, _wrong_answer_memory_map = self._build_wrong_answer_memory_rows(
            history, self.master_questions
        )
        confusion_pairs = self._build_confusion_pair_rows(history)
        interference_map_rows = self._build_interference_map_rows(history)
        confidence_compression_rows, confidence_compression_map = self._build_confidence_compression_rows(
            records, question_stability, question_history_map, self.master_questions
        )
        abstraction_ladder_rows, abstraction_ladder_map = self._build_abstraction_ladder_rows(
            records, question_stability, question_history_map, self.master_questions
        )
        recognition_retrieval_rows, recognition_retrieval_map = self._build_recognition_retrieval_rows(
            question_history_map, self.master_questions
        )
        compression_point_rows, compression_point_map = self._build_compression_point_rows(
            recognition_retrieval_map, abstraction_ladder_map
        )
        decision_latency_rows, decision_latency_map = self._build_decision_latency_rows(history, self.master_questions)
        answer_latency_rows = self._build_answer_latency_diagnosis_rows(history, self.master_questions)
        confidence_mismatch_rows = self._build_confidence_mismatch_rows(history, self.master_questions)
        error_boundary_rows, error_boundary_map = self._build_error_boundary_rows(history, self.master_questions)
        counterfactual_distractor_rows, counterfactual_pressure_map = self._build_counterfactual_distractor_rows(
            history, self.master_questions
        )
        contrast_rule_rows, contrast_pressure_map = self._build_contrast_rule_rows(
            counterfactual_distractor_rows, confusion_pairs, self.master_questions
        )
        objective_mastery_rows, objective_mastery_map = self._build_objective_mastery_rows(
            records, question_stability, question_history_map, source_agreement_map, self.master_questions
        )
        prerequisite_debt_rows, prerequisite_debt_map = self._build_prerequisite_debt_rows(
            records,
            question_stability,
            coverage_gaps,
            objective_mastery_map,
            error_boundary_map,
            counterfactual_pressure_map,
            self.master_questions,
        )
        concept_half_life_rows, concept_half_life_map = self._build_concept_half_life_rows(
            records, question_stability, question_history_map, self.master_questions
        )
        leverage_ranking_rows, leverage_map = self._build_leverage_ranking_rows(
            records, prerequisite_debt_map, self.master_questions
        )
        blind_spot_rows, blind_spot_map = self._build_blind_spot_inference_rows(
            coverage_gaps, prerequisite_debt_map, leverage_map, self.master_questions
        )
        difficulty_rows, difficulty_map = self._build_difficulty_calibration_rows(
            records, question_stability, question_history_map, source_agreement_map, self.master_questions
        )
        phrasing_rows, phrasing_map = self._build_phrasing_normalization_rows(self.master_questions)
        effort_efficiency_rows, effort_efficiency_map = self._build_effort_efficiency_rows(
            history, self.master_questions
        )
        misconception_fingerprints, misconception_pressure_map = self._build_misconception_fingerprint_rows(
            history, self.master_questions
        )

        domain_rows: list[AnalyticsDomainRow] = []
        for name, d in domain_stats.items():
            acc = round((d["correct"] / d["answered"]) * 100, 1) if d["answered"] else 0.0
            coverage = round((d["answered"] / d["total"]) * 100, 1) if d["total"] else 0.0
            progress_bits = progress_domain_stats.get(
                name,
                {
                    "progress_attempted": 0,
                    "progress_wrong": 0,
                    "progress_due": 0,
                    "progress_flagged": 0,
                    "progress_active_weak": 0,
                    "progress_recovered": 0,
                    "confidence_score": 0.0,
                    "confidence_seen": 0,
                },
            )
            heat = round(
                (100 - acc) * 0.65
                + max(0, 70 - coverage) * 0.35
                + d["wrong"] * 1.5
                + progress_bits["progress_wrong"] * 0.8
                + progress_bits["progress_active_weak"] * 2.4
                + progress_bits["progress_due"] * 1.8,
                1,
            )
            confidence_avg = (
                (progress_bits["confidence_score"] / progress_bits["confidence_seen"])
                if progress_bits["confidence_seen"]
                else 0.75
            )
            stability_values = [
                question_stability.get(int(q.get("question_number") or 0), 0.0)
                for q in self.master_questions
                if (q.get("domain") or "Unsorted") == name
                and records.get(self._question_key(q), {})
                and not is_suspended(records.get(self._question_key(q), {}))
            ]
            stability = round(sum(stability_values) / len(stability_values), 1) if stability_values else 0.0
            readiness = round(
                max(
                    0.0,
                    min(
                        100.0,
                        acc * 0.4
                        + coverage * 0.16
                        + confidence_avg * 16
                        + stability * 0.18
                        + max(0, progress_bits["progress_recovered"]) * 1.4
                        - progress_bits["progress_active_weak"] * 4.0
                        - progress_bits["progress_due"] * 2.0,
                    ),
                ),
                1,
            )
            trend = round(self._trend_delta_for_group(domain_history_map.get(name, [])), 1)
            domain_rows.append(
                {
                    "domain": name,
                    **d,
                    **progress_bits,
                    "accuracy": acc,
                    "coverage": coverage,
                    "heat": heat,
                    "readiness": readiness,
                    "stability": stability,
                    "trend": trend,
                }
            )
        domain_rows.sort(key=lambda x: (x["heat"], x["wrong"], -x["answered"]), reverse=True)

        topic_rows: list[AnalyticsTopicRow] = []
        for name in sorted(set(topic_stats) | set(progress_topic_stats)):
            t = topic_stats.get(name, {"seen": 0, "correct": 0, "wrong": 0})
            progress_bits = progress_topic_stats.get(
                name,
                {
                    "progress_attempted": 0,
                    "progress_wrong": 0,
                    "progress_due": 0,
                    "progress_active_weak": 0,
                    "progress_recovered": 0,
                    "confidence_score": 0.0,
                    "confidence_seen": 0,
                },
            )
            if not t["seen"] and not progress_bits["progress_attempted"]:
                continue
            acc = round((t["correct"] / t["seen"]) * 100, 1) if t["seen"] else 0.0
            confidence_avg = (
                (progress_bits["confidence_score"] / progress_bits["confidence_seen"])
                if progress_bits["confidence_seen"]
                else 0.75
            )
            stability_values = [
                question_stability.get(int(q.get("question_number") or 0), 0.0)
                for q in self.master_questions
                if name in [str(topic).strip() for topic in q.get("topics", [])]
                and records.get(self._question_key(q), {})
                and not is_suspended(records.get(self._question_key(q), {}))
            ]
            stability = round(sum(stability_values) / len(stability_values), 1) if stability_values else 0.0
            readiness = round(
                max(
                    0.0,
                    min(
                        100.0,
                        acc * 0.42
                        + confidence_avg * 20
                        + stability * 0.22
                        - progress_bits["progress_active_weak"] * 4.0
                        - progress_bits["progress_due"] * 2.2
                        + progress_bits["progress_recovered"] * 1.2,
                    ),
                ),
                1,
            )
            trend = round(self._trend_delta_for_group(topic_history_map.get(name, [])), 1)
            topic_rows.append(
                {
                    "topic": name,
                    **t,
                    **progress_bits,
                    "accuracy": acc,
                    "readiness": readiness,
                    "stability": stability,
                    "trend": trend,
                }
            )
        topic_rows.sort(
            key=lambda x: (x["progress_active_weak"], x["progress_due"], x["progress_wrong"], -x["accuracy"]),
            reverse=True,
        )

        streak = 0
        for q in reversed(answered):
            if self._question_correct(q):
                streak += 1
            else:
                break

        progress = self.progress_summary()
        weak_domains = [r for r in domain_rows if r["answered"] >= 3 or r["progress_attempted"]][:3]
        weak_topics = [r for r in topic_rows if r["seen"] >= 2 or r["progress_attempted"]][:5]
        roi_rows: list[AnalyticsRoiRow] = []
        volatile_rows: list[AnalyticsVolatilityRow] = []
        domain_heat_lookup = {row["domain"]: row["heat"] for row in domain_rows}
        burnout_risk = self._build_burnout_risk_row(self.session_answer_history or history)
        for q in self.master_questions:
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            qnum = int(q.get("question_number") or 0)
            volatility = self.question_volatility(q)
            if volatility.get("label"):
                volatile_rows.append(
                    {
                        "question_number": qnum,
                        "domain": q.get("domain") or "Unsorted",
                        "topic": ", ".join(
                            [str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()][:2]
                        ),
                        "score": volatility["score"],
                        "label": volatility["label"],
                        "attempts": volatility["attempts"],
                        "flips": volatility["flips"],
                        "last_outcome": volatility["last_outcome"],
                    }
                )
            confidence_counts = dict(rec.get("confidence_counts") or {})
            miss_counts = dict(rec.get("miss_reason_counts") or {})
            source_support = source_agreement_map.get(qnum, {"score": 0.8, "label": "Single-source only"})
            kind, unit = self._coverage_unit_for_question(q)
            unit_key = f"{kind}::{unit}"
            gap_score = coverage_gap_map.get(unit_key, 0.0)
            error_boundary_row = error_boundary_map.get(unit_key)
            counterfactual_pressure = float(counterfactual_pressure_map.get(unit_key, 0.0))
            difficulty_row = difficulty_map.get(qnum, {"score": 0.0, "label": "Stable"})
            phrasing_row = phrasing_map.get(qnum, {"score": 100.0, "label": "Clean"})
            roi = 0.0
            roi += 8.0 if is_active_weak(rec) else 0.0
            roi += 6.0 if is_review_due(rec) else 0.0
            roi += 5.0 if rec.get("flagged") else 0.0
            roi += confidence_counts.get("Guessed", 0) * 2.6
            roi += confidence_counts.get("Unsure", 0) * 1.4
            roi += miss_counts.get("Did not know", 0) * 2.7
            roi += miss_counts.get("Narrowed to two", 0) * 1.8
            roi += miss_counts.get("Misread", 0) * 1.1
            roi += miss_counts.get("Changed answer", 0) * 1.3
            roi += domain_heat_lookup.get(q.get("domain") or "Unsorted", 0) * 0.12
            roi += gap_score * 0.08
            roi += float((error_boundary_row or {}).get("gap", 0.0)) * 0.1
            roi += counterfactual_pressure * 0.08
            roi += float(difficulty_row.get("score", 0.0)) * 0.06
            roi -= max(0.0, 78.0 - float(phrasing_row.get("score", 100.0))) * 0.05
            roi += max(0.0, (float(source_support.get("score", 0.8)) - 0.75) * 6.0)
            if source_support.get("label") == "Source conflict":
                roi -= 3.0
            roi -= int(rec.get("correct_streak", 0)) * 0.8
            if roi <= 0:
                continue
            reasons = []
            if is_active_weak(rec):
                reasons.append("active weak")
            if is_review_due(rec):
                reasons.append("due")
            if confidence_counts.get("Guessed", 0):
                reasons.append(f"guessed {confidence_counts.get('Guessed', 0)}x")
            if miss_counts.get("Did not know", 0):
                reasons.append("knowledge gap")
            if gap_score >= 45:
                reasons.append("coverage gap")
            if error_boundary_row and self._stem_style_for_question(q) == error_boundary_row["weak_style"]:
                reasons.append("weak stem boundary")
            if counterfactual_pressure >= 22.0:
                reasons.append("distractor trap")
            if float(difficulty_row.get("score", 0.0)) >= 65.0:
                reasons.append("hard item")
            if phrasing_row.get("label") == "Noisy":
                reasons.append("wording friction")
            if source_support.get("label") == "Cross-source agreement":
                reasons.append("cross-source confirmed")
            roi_rows.append(
                {
                    "question_number": qnum,
                    "domain": q.get("domain") or "Unsorted",
                    "topic": ", ".join([str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()][:2]),
                    "roi": round(roi, 1),
                    "reasons": ", ".join(reasons) or "review opportunity",
                }
            )
        roi_rows.sort(key=lambda row: (row["roi"], row["question_number"]), reverse=True)
        roi_rows = roi_rows[:20]
        volatile_rows.sort(
            key=lambda row: (row["score"], row["flips"], row["attempts"], row["question_number"]), reverse=True
        )
        volatile_rows = volatile_rows[:20]
        confidence_calibration: list[ConfidenceCalibrationRow] = []
        for level in CONFIDENCE_OPTIONS:
            group = [event for event in history if str(event.get("confidence") or "").strip() == level]
            attempts = len(group)
            correct = sum(1 for event in group if event.get("correct"))
            accuracy_pct = round((correct / attempts) * 100, 1) if attempts else 0.0
            confidence_calibration.append(
                {
                    "confidence": level,
                    "attempts": attempts,
                    "correct": correct,
                    "accuracy": accuracy_pct,
                }
            )

        anti_patterns = []
        trap_word_counts = {}
        if history:
            total_wrong = sum(1 for event in history if not event.get("correct"))
            misread_count = sum(1 for event in history if str(event.get("miss_reason") or "").strip() == "Misread")
            narrowed_count = sum(
                1 for event in history if str(event.get("miss_reason") or "").strip() == "Narrowed to two"
            )
            changed_count = sum(
                1 for event in history if str(event.get("miss_reason") or "").strip() == "Changed answer"
            )
            guessed_correct = sum(
                1
                for event in history
                if event.get("correct") and str(event.get("confidence") or "").strip() == "Guessed"
            )
            unsure_correct = sum(
                1
                for event in history
                if event.get("correct") and str(event.get("confidence") or "").strip() == "Unsure"
            )
            sure_group = next((row for row in confidence_calibration if row["confidence"] == "Sure"), None)
            question_lookup = {int(q.get("question_number") or 0): q for q in self.master_questions}
            longest_choice_wrong = 0
            fast_wrong_count = 0
            for event in history:
                if event.get("correct"):
                    continue
                if self._effective_response_seconds(event) > 0 and self._effective_response_seconds(event) <= 7.0:
                    fast_wrong_count += 1
                for trap_word in event.get("trap_words") or []:
                    trap_word_counts[trap_word] = trap_word_counts.get(trap_word, 0) + 1
                question = question_lookup.get(int(event.get("question_number") or 0))
                if not question:
                    continue
                choice_lengths = [
                    len(str(text or "").strip())
                    for text in question.get("choices", {}).values()
                    if str(text or "").strip()
                ]
                if not choice_lengths:
                    continue
                longest = max(choice_lengths)
                selected_texts = [
                    str(text or "").strip() for text in event.get("selected_texts") or [] if str(text or "").strip()
                ]
                if any(len(text) >= longest for text in selected_texts):
                    longest_choice_wrong += 1
            if total_wrong and misread_count / total_wrong >= 0.3:
                anti_patterns.append(
                    f"Misread trap: {misread_count}/{total_wrong} recent misses were tagged as misreads."
                )
            if total_wrong and narrowed_count / total_wrong >= 0.25:
                anti_patterns.append(
                    f"Two-answer trap: {narrowed_count}/{total_wrong} recent misses were narrowed to two."
                )
            if total_wrong and changed_count / total_wrong >= 0.2:
                anti_patterns.append(
                    f"Second-guessing trap: {changed_count}/{total_wrong} recent misses came from changing your answer."
                )
            if total_wrong >= 3 and longest_choice_wrong / total_wrong >= 0.35:
                anti_patterns.append(
                    f"Choice-length bias: {longest_choice_wrong}/{total_wrong} recent misses came from picking the longest answer."
                )
            if total_wrong >= 3 and fast_wrong_count / total_wrong >= 0.35:
                anti_patterns.append(
                    f"Speed-risk pattern: {fast_wrong_count}/{total_wrong} recent misses were locked in under 7 seconds."
                )
            if guessed_correct >= 4:
                anti_patterns.append(
                    f"False mastery risk: {guessed_correct} recent correct answers were still tagged as guesses."
                )
            if unsure_correct >= 5:
                anti_patterns.append(f"Confidence gap: {unsure_correct} recent correct answers were marked unsure.")
            if sure_group and sure_group["attempts"] >= 6 and sure_group["accuracy"] < 70:
                anti_patterns.append(
                    f"Calibration drift: 'Sure' answers are only {sure_group['accuracy']}% accurate right now."
                )
            for trap_word, count in sorted(trap_word_counts.items(), key=lambda item: (item[1], item[0]), reverse=True)[
                :3
            ]:
                if count >= 2:
                    anti_patterns.append(f"Trap-word pattern: '{trap_word}' appeared in {count} recent misses.")

        mastery_rows: list[MasteryMapRow] = []
        ladder_counts = {}
        for q in self.master_questions:
            rec = records.get(self._question_key(q), {})
            if is_suspended(rec):
                continue
            ladder = recovery_ladder_stage(rec)
            ladder_counts[ladder] = ladder_counts.get(ladder, 0) + 1
        topic_names = sorted(
            {str(topic).strip() for q in self.master_questions for topic in q.get("topics", []) if str(topic).strip()}
        )
        for topic in topic_names:
            counts = {
                "New": 0,
                "Active weak": 0,
                "Recovered": 0,
                "Recovered - due": 0,
                "Due review": 0,
                "Mastered": 0,
                "In progress": 0,
                "Flagged": 0,
            }
            for q in self.master_questions:
                if topic not in [str(item).strip() for item in q.get("topics", [])]:
                    continue
                rec = records.get(self._question_key(q), {})
                if is_suspended(rec):
                    continue
                counts[study_status_name(rec)] = counts.get(study_status_name(rec), 0) + 1
            topic_row = next((row for row in topic_rows if row["topic"] == topic), None)
            mastery_rows.append(
                {
                    "topic": topic,
                    "new": counts.get("New", 0),
                    "active_weak": counts.get("Active weak", 0),
                    "recovered": counts.get("Recovered", 0) + counts.get("Recovered - due", 0),
                    "due": counts.get("Due review", 0) + counts.get("Recovered - due", 0),
                    "mastered": counts.get("Mastered", 0),
                    "in_progress": counts.get("In progress", 0),
                    "flagged": counts.get("Flagged", 0),
                    "readiness": topic_row.get("readiness", 0.0) if topic_row else 0.0,
                }
            )
        mastery_rows.sort(
            key=lambda row: (row["active_weak"], row["due"], -row["mastered"], row["topic"]), reverse=True
        )
        concept_anchor_notes = self._build_concept_anchor_notes(topic_rows, topic_history_map)
        concept_clusters = self._build_concept_clusters(history, records, question_stability)
        remediation_cards = self._build_remediation_cards(concept_clusters)
        wrong_answer_families = self._build_wrong_answer_family_review(history)
        latent_weakness_rows = self._build_latent_weakness_rows(
            records,
            question_stability,
            question_history_map,
            source_agreement_map,
            source_trust_map,
            self.master_questions,
        )
        transfer_strength_rows, transfer_strength_map = self._build_transfer_strength_rows(
            records, question_stability, self.master_questions
        )
        robustness_rows, robustness_map = self._build_robustness_score_rows(
            transfer_strength_rows, abstraction_ladder_map, concept_half_life_map
        )
        generalization_rows, generalization_map = self._build_generalization_score_rows(
            transfer_strength_rows, abstraction_ladder_map, robustness_map
        )
        reinforcement_distance_rows, reinforcement_distance_map = self._build_reinforcement_distance_rows(
            records, question_stability, concept_half_life_map, self.master_questions
        )
        synthesis_check_rows, synthesis_check_map = self._build_synthesis_check_rows(
            objective_mastery_map, self.master_questions
        )
        cue_dependence_rows, cue_dependence_map = self._build_cue_dependence_rows(
            question_history_map, recognition_retrieval_map, phrasing_map, self.master_questions
        )
        delayed_probe_rows, delayed_probe_map = self._build_delayed_probe_rows(
            records, concept_half_life_map, self.master_questions
        )
        counterexample_training_rows, counterexample_training_map = self._build_counterexample_training_rows(
            counterfactual_distractor_rows, contrast_pressure_map, self.master_questions
        )
        failure_mode_rows, failure_mode_map = self._build_failure_mode_rows(history, self.master_questions)
        expected_learning_gain_rows, expected_learning_gain_map = self._build_expected_learning_gain_rows(
            records, knowledge_trace_map, leverage_map, difficulty_map, self.master_questions
        )
        retention_stress_rows, retention_stress_map = self._build_retention_stress_rows(
            records, concept_half_life_map, robustness_map, self.master_questions
        )
        concept_state_rows, concept_state_map = self._build_concept_state_rows(
            knowledge_trace_map, generalization_map, robustness_map, concept_half_life_map
        )
        attempted_stability_values = [score for score in question_stability.values() if score > 0]
        stability_score = (
            round(sum(attempted_stability_values) / len(attempted_stability_values), 1)
            if attempted_stability_values
            else 0.0
        )
        recs = build_analytics_recommendations(
            AnalyticsRecommendationInputs(
                progress=progress,
                decision_quality=decision_quality,
                volatile_rows=volatile_rows,
                concept_clusters=concept_clusters,
                confusion_pairs=confusion_pairs,
                interference_map_rows=interference_map_rows,
                coverage_gaps=coverage_gaps,
                objective_mastery_rows=objective_mastery_rows,
                prerequisite_debt_rows=prerequisite_debt_rows,
                knowledge_trace_rows=knowledge_trace_rows,
                concept_memory_state_rows=concept_memory_state_rows,
                wrong_answer_memory_rows=wrong_answer_memory_rows,
                concept_half_life_rows=concept_half_life_rows,
                blind_spot_rows=blind_spot_rows,
                expected_learning_gain_rows=expected_learning_gain_rows,
                confidence_compression_rows=confidence_compression_rows,
                compression_point_rows=compression_point_rows,
                abstraction_ladder_rows=abstraction_ladder_rows,
                recognition_retrieval_rows=recognition_retrieval_rows,
                robustness_rows=robustness_rows,
                leverage_ranking_rows=leverage_ranking_rows,
                generalization_rows=generalization_rows,
                error_boundary_rows=error_boundary_rows,
                counterfactual_distractor_rows=counterfactual_distractor_rows,
                counterexample_training_rows=counterexample_training_rows,
                difficulty_rows=difficulty_rows,
                phrasing_rows=phrasing_rows,
                misconception_fingerprints=misconception_fingerprints,
                effort_efficiency_rows=effort_efficiency_rows,
                decision_latency_rows=decision_latency_rows,
                answer_latency_rows=answer_latency_rows,
                confidence_mismatch_rows=confidence_mismatch_rows,
                cue_dependence_rows=cue_dependence_rows,
                latent_weakness_rows=latent_weakness_rows,
                transfer_strength_rows=transfer_strength_rows,
                reinforcement_distance_rows=reinforcement_distance_rows,
                delayed_probe_rows=delayed_probe_rows,
                synthesis_check_rows=synthesis_check_rows,
                contrast_rule_rows=contrast_rule_rows,
                retention_stress_rows=retention_stress_rows,
                failure_mode_rows=failure_mode_rows,
                concept_state_rows=concept_state_rows,
                source_trust_rows=source_trust_rows,
                burnout_risk=burnout_risk,
                source_agreement_rows=source_agreement_rows,
                weak_domains=weak_domains,
                weak_topics=weak_topics,
            )
        )

        pass_prediction = self._build_pass_prediction(
            {
                "total": total,
                "answered": answered_count,
                "unanswered": unseen_count,
                "correct": correct_count,
                "wrong": wrong_count,
                "accuracy": accuracy,
                "flagged": flagged_count,
                "with_issues": issues_count,
                "elapsed_seconds": 0,
                "recent50_accuracy": recent_acc,
                "recent50_count": len(recent),
                "current_streak": streak,
                "mode": self.active_session_mode,
                "decision_quality": decision_quality,
                "stability_score": stability_score,
                "pass_prediction_score": 0.0,
                "pass_prediction_label": "",
            },
            progress,
            confidence_calibration,
            stability_score,
            volatile_rows,
            source_agreement_rows,
            coverage_gaps,
        )
        overall: AnalyticsOverall = {
            "total": total,
            "answered": answered_count,
            "unanswered": unseen_count,
            "correct": correct_count,
            "wrong": wrong_count,
            "accuracy": accuracy,
            "flagged": flagged_count,
            "with_issues": issues_count,
            "elapsed_seconds": 0,
            "recent50_accuracy": recent_acc,
            "recent50_count": len(recent),
            "current_streak": streak,
            "mode": self.active_session_mode,
            "decision_quality": decision_quality,
            "stability_score": stability_score,
            "pass_prediction_score": pass_prediction["score"],
            "pass_prediction_label": pass_prediction["label"],
        }
        trap_word_patterns: list[TrapWordPatternRow] = [
            {"trap_word": trap_word, "count": count}
            for trap_word, count in sorted(trap_word_counts.items(), key=lambda item: (item[1], item[0]), reverse=True)[
                :8
            ]
        ]
        recall_failures = self._build_recall_failure_rows(history)
        deciding_clues = self._build_deciding_clue_rows(history)
        payload: AnalyticsPayload = {
            "overall": {
                "total": overall["total"],
                "answered": overall["answered"],
                "unanswered": overall["unanswered"],
                "correct": overall["correct"],
                "wrong": overall["wrong"],
                "accuracy": overall["accuracy"],
                "flagged": overall["flagged"],
                "with_issues": overall["with_issues"],
                "elapsed_seconds": overall["elapsed_seconds"],
                "recent50_accuracy": overall["recent50_accuracy"],
                "recent50_count": overall["recent50_count"],
                "current_streak": overall["current_streak"],
                "mode": overall["mode"],
                "decision_quality": overall["decision_quality"],
                "stability_score": overall["stability_score"],
                "pass_prediction_score": overall["pass_prediction_score"],
                "pass_prediction_label": overall["pass_prediction_label"],
            },
            "progress": progress,
            "domains": domain_rows,
            "topics": topic_rows,
            "recommendations": recs,
            "roi_questions": roi_rows,
            "volatile_questions": volatile_rows,
            "confidence_calibration": confidence_calibration,
            "answer_latency_diagnosis": answer_latency_rows,
            "confidence_mismatch": confidence_mismatch_rows,
            "anti_patterns": anti_patterns,
            "topic_mastery_map": mastery_rows,
            "concept_anchor_notes": concept_anchor_notes,
            "wrong_answer_families": wrong_answer_families,
            "trap_word_patterns": trap_word_patterns,
            "recall_failures": recall_failures,
            "deciding_clues": deciding_clues,
            "concept_memory_states": concept_memory_state_rows,
            "wrong_answer_memory": wrong_answer_memory_rows,
            "recovery_ladder": ladder_counts,
            "pass_prediction": pass_prediction,
            "concept_clusters": concept_clusters,
            "remediation_cards": remediation_cards,
            "source_agreement": source_agreement_rows,
            "coverage_gaps": coverage_gaps,
            "confusion_pairs": confusion_pairs,
            "interference_map": interference_map_rows,
            "confidence_compression": confidence_compression_rows,
            "abstraction_ladder": abstraction_ladder_rows,
            "error_boundaries": error_boundary_rows,
            "counterfactual_distractors": counterfactual_distractor_rows,
            "difficulty_calibration": difficulty_rows,
            "phrasing_normalization": phrasing_rows,
            "burnout_risk": burnout_risk,
            "latent_weakness": latent_weakness_rows,
            "source_trust": source_trust_rows,
            "transfer_strength": transfer_strength_rows,
            "objective_mastery": objective_mastery_rows,
            "prerequisite_debt": prerequisite_debt_rows,
            "concept_half_life": concept_half_life_rows,
            "blind_spot_inference": blind_spot_rows,
            "robustness_scores": robustness_rows,
            "leverage_ranking": leverage_ranking_rows,
            "misconception_fingerprints": misconception_fingerprints,
            "effort_efficiency": effort_efficiency_rows,
            "reinforcement_distance": reinforcement_distance_rows,
            "synthesis_checks": synthesis_check_rows,
            "knowledge_trace": knowledge_trace_rows,
            "expected_learning_gain": expected_learning_gain_rows,
            "delayed_probes": delayed_probe_rows,
            "counterexample_training": counterexample_training_rows,
            "recognition_retrieval": recognition_retrieval_rows,
            "cue_dependence": cue_dependence_rows,
            "concept_states": concept_state_rows,
            "contrast_rules": contrast_rule_rows,
            "retention_stress": retention_stress_rows,
            "failure_modes": failure_mode_rows,
            "compression_points": compression_point_rows,
            "decision_latency": decision_latency_rows,
            "generalization_scores": generalization_rows,
        }
        return payload

    def compute_analytics(self, source=None) -> AnalyticsPayload:
        if source is not None:
            source_list = list(source)
            signature = (
                "source",
                tuple(q.get("question_number") for q in source_list),
                self._analytics_signature(),
            )
            if (
                signature != getattr(self, "analytics_source_cache_key", None)
                or getattr(self, "analytics_source_cache_payload", None) is None
            ):
                self.analytics_source_cache_key = signature
                self.analytics_source_cache_payload = self._build_analytics_payload(source=source_list)
            analytics = copy.deepcopy(self.analytics_source_cache_payload)
            analytics["overall"]["elapsed_seconds"] = self.current_elapsed_seconds()
            return analytics

        signature = self._analytics_signature()
        if signature != self.analytics_cache_key or self.analytics_cache_payload is None:
            self.analytics_cache_key = signature
            self.analytics_cache_payload = self._build_analytics_payload()
        analytics = copy.deepcopy(self.analytics_cache_payload)
        analytics["overall"]["elapsed_seconds"] = self.current_elapsed_seconds()
        return analytics

    def export_analytics_json(self):
        analytics = self.compute_analytics()
        default_name = (
            self.bank_path.with_name(f"{self.bank_path.stem}_analytics.json")
            if self.bank_path
            else Path("analytics.json")
        )
        path = filedialog.asksaveasfilename(
            title="Export analytics JSON",
            defaultextension=".json",
            initialfile=default_name.name,
            initialdir=str(default_name.parent),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        safe_write_json(Path(path), analytics)
        messagebox.showinfo("Analytics exported", f"Saved analytics to:\n{path}")

    def open_analytics_window(self):
        if not self.questions:
            return
        if self.analytics_window and self.analytics_window.winfo_exists():
            self.analytics_window.deiconify()
            self.analytics_window.lift()
            self.refresh_analytics_window()
            return
        win = tk.Toplevel(self.root)
        self.analytics_window = win
        win.title("Performance Analytics")
        win.geometry(str(self.config.get("analytics_geometry") or DEFAULT_CONFIG["analytics_geometry"]))
        win.minsize(1000, 680)
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.close_analytics_window)
        win.bind("<Configure>", self.on_analytics_configure)
        header = tk.Frame(win, bg=BLUE, height=42)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="Performance Analytics", bg=BLUE, fg="white", font=("Segoe UI", 11, "bold"), padx=14
        ).pack(side="left")
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x")
        dashboard = tk.Frame(top, bg=BG)
        dashboard.pack(side="left", fill="both", expand=True)
        card_keys = (
            "summary_readiness",
            "summary_next_move",
            "summary_retention",
            "summary_momentum",
            "summary_source_health",
        )
        for column, key in enumerate(card_keys):
            dashboard.grid_columnconfigure(column, weight=1, uniform="analytics-summary")
            label = tk.Label(
                dashboard,
                text="",
                bg=CARD,
                fg=TEXT,
                justify="left",
                anchor="nw",
                padx=11,
                pady=9,
                font=("Segoe UI", 9),
                relief="solid",
                bd=1,
                wraplength=210,
            )
            label.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0))
            self.analytics_widgets[key] = label
        side = tk.Frame(top, bg=BG)
        side.pack(side="left", fill="y", padx=(10, 0))
        tk.Button(
            side,
            text="Refresh",
            font=("Segoe UI", 9, "bold"),
            bd=0,
            bg=BLUE,
            fg="white",
            padx=14,
            pady=8,
            command=self.refresh_analytics_window,
        ).pack(fill="x")
        tk.Button(
            side,
            text="Export JSON",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=14,
            pady=8,
            command=self.export_analytics_json,
        ).pack(fill="x", pady=(8, 0))
        notebook = ttk.Notebook(body)
        notebook.pack(fill="both", expand=True, pady=(12, 0))
        self.analytics_widgets["domain_tree"] = self._make_tree(
            notebook,
            [
                ("domain", "Domain", 220),
                ("answered", "Answered", 75),
                ("correct", "Correct", 65),
                ("wrong", "Wrong", 65),
                ("accuracy", "Accuracy %", 85),
                ("coverage", "Coverage %", 85),
                ("readiness", "Readiness", 80),
                ("stability", "Stability", 80),
                ("trend", "Trend", 70),
                ("progress_wrong", "LT Wrong", 75),
                ("progress_due", "Due", 55),
                ("heat", "Heat", 65),
            ],
            "Domains",
        )
        self.analytics_widgets["topic_tree"] = self._make_tree(
            notebook,
            [
                ("topic", "Topic", 260),
                ("seen", "Seen", 65),
                ("correct", "Correct", 70),
                ("wrong", "Wrong", 70),
                ("accuracy", "Accuracy %", 90),
                ("readiness", "Readiness", 80),
                ("stability", "Stability", 80),
                ("trend", "Trend", 70),
                ("progress_wrong", "LT Wrong", 75),
                ("progress_due", "Due", 55),
            ],
            "Topics",
        )
        self.analytics_widgets["mastery_tree"] = self._make_tree(
            notebook,
            [
                ("topic", "Topic", 240),
                ("new", "New", 55),
                ("active_weak", "Weak", 55),
                ("recovered", "Recovered", 75),
                ("due", "Due", 55),
                ("mastered", "Mastered", 75),
                ("flagged", "Flagged", 65),
                ("readiness", "Readiness", 80),
            ],
            "Mastery Map",
        )
        recent_frame = tk.Frame(notebook, bg=CARD)
        notebook.add(recent_frame, text="Hot signals")
        txt = tk.Text(
            recent_frame, wrap="word", font=("Segoe UI", 10), bg=CARD, fg=TEXT, relief="flat", padx=10, pady=10
        )
        txt.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(recent_frame, command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set, state="disabled")
        self.analytics_widgets["hot_text"] = txt
        patterns_frame = tk.Frame(notebook, bg=CARD)
        notebook.add(patterns_frame, text="Patterns")
        patterns_text = tk.Text(
            patterns_frame, wrap="word", font=("Segoe UI", 10), bg=CARD, fg=TEXT, relief="flat", padx=10, pady=10
        )
        patterns_text.pack(side="left", fill="both", expand=True)
        patterns_sb = tk.Scrollbar(patterns_frame, command=patterns_text.yview)
        patterns_sb.pack(side="right", fill="y")
        patterns_text.configure(yscrollcommand=patterns_sb.set, state="disabled")
        self.analytics_widgets["patterns_text"] = patterns_text
        self.refresh_analytics_window()

    def _make_tree(self, notebook, columns, title) -> ttk.Treeview:
        frame = tk.Frame(notebook, bg=CARD)
        notebook.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings")
        saved_widths = dict(self.config.get(f"analytics_{title.lower()}_widths") or {})
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=int(saved_widths.get(key, width)), anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(frame, command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<ButtonRelease-1>", lambda e: self.schedule_analytics_layout_save())
        return tree

    def capture_tree_widths(self, key):
        tree = self.analytics_widgets.get(key)
        if tree and tree.winfo_exists():
            return {column: int(tree.column(column, "width")) for column in tree["columns"]}
        prefix = key.split("_")[0]
        return dict(self.config.get(f"analytics_{prefix}_widths") or {})

    def on_analytics_configure(self, event=None):
        if event is not None and event.widget != self.analytics_window:
            return
        self.schedule_analytics_layout_save()

    def schedule_analytics_layout_save(self):
        self._schedule_config_save()

    def flush_analytics_layout_save(self):
        self._flush_scheduled_config_save()

    def close_analytics_window(self):
        self.flush_analytics_layout_save()
        self.save_app_config()
        if self.analytics_window and self.analytics_window.winfo_exists():
            self.analytics_window.destroy()
        self.analytics_window = None
        self.analytics_widgets = cast(AnalyticsWidgetRegistry, {})

    def refresh_analytics_window(self):
        if not (self.analytics_window and self.analytics_window.winfo_exists()):
            return
        analytics = self.compute_analytics()
        summary = build_analytics_summary(analytics)
        tones = {
            "good": ("#edf7f0", "#21683d"),
            "watch": ("#fff6df", "#81590f"),
            "risk": ("#fae8e8", "#913535"),
            "focus": ("#eaf2fb", BLUE),
            "neutral": (CARD, TEXT),
        }
        card_map: tuple[tuple[str, AnalyticsSummaryCard], ...] = (
            ("summary_readiness", summary["readiness"]),
            ("summary_next_move", summary["next_move"]),
            ("summary_retention", summary["retention"]),
            ("summary_momentum", summary["momentum"]),
            ("summary_source_health", summary["source_health"]),
        )
        for widget_key, card in card_map:
            bg, fg = tones.get(card["tone"], tones["neutral"])
            self.analytics_widgets[widget_key].configure(
                text=f"{card['title']}\n{card['headline']}\n{card['detail']}",
                bg=bg,
                fg=fg,
            )
        for key in ("domain_tree", "topic_tree", "mastery_tree"):
            tree = self.analytics_widgets[key]
            for item in tree.get_children():
                tree.delete(item)
        for row in analytics["domains"]:
            self.analytics_widgets["domain_tree"].insert(
                "",
                "end",
                values=(
                    row["domain"],
                    row["answered"],
                    row["correct"],
                    row["wrong"],
                    row["accuracy"],
                    row["coverage"],
                    row["readiness"],
                    row["stability"],
                    row["trend"],
                    row["progress_wrong"],
                    row["progress_due"],
                    row["heat"],
                ),
            )
        for row in analytics["topics"][:150]:
            self.analytics_widgets["topic_tree"].insert(
                "",
                "end",
                values=(
                    row["topic"],
                    row["seen"],
                    row["correct"],
                    row["wrong"],
                    row["accuracy"],
                    row["readiness"],
                    row["stability"],
                    row["trend"],
                    row["progress_wrong"],
                    row["progress_due"],
                ),
            )
        for row in analytics.get("topic_mastery_map", [])[:150]:
            self.analytics_widgets["mastery_tree"].insert(
                "",
                "end",
                values=(
                    row["topic"],
                    row["new"],
                    row["active_weak"],
                    row["recovered"],
                    row["due"],
                    row["mastered"],
                    row["flagged"],
                    row["readiness"],
                ),
            )
        txt = self.analytics_widgets["hot_text"]
        txt.configure(state="normal")
        txt.delete("1.0", tk.END)
        prediction = analytics.get("pass_prediction") or {}
        txt.insert(tk.END, "Pass predictor\n\n")
        txt.insert(tk.END, f"{prediction.get('label', 'Not ready')}  {prediction.get('score', 0.0)}%\n")
        txt.insert(
            tk.END,
            f"Confidence honesty: {prediction.get('confidence_honesty', 0.0)}%    Readiness floor: {prediction.get('readiness_floor', 0.0)}%\n",
        )
        for reason in prediction.get("reasons", []):
            txt.insert(tk.END, f"- {reason}\n")
        txt.insert(tk.END, "\n")
        txt.insert(tk.END, "Priority targets\n\n")
        for i, rec in enumerate(analytics["recommendations"], start=1):
            txt.insert(tk.END, f"{i}. {rec}\n")
        txt.insert(tk.END, "\nHighest ROI next 20\n\n")
        for row in analytics.get("roi_questions", []):
            txt.insert(tk.END, f"Q{row['question_number']}  {row['domain']}  ROI {row['roi']}  {row['reasons']}\n")
        txt.insert(tk.END, "\nVolatility watchlist\n\n")
        for row in analytics.get("volatile_questions", []):
            txt.insert(
                tk.END,
                f"Q{row['question_number']}  {row['domain']}  {row['label']} volatility {row['score']}  {row['flips']} flips across {row['attempts']} tries\n",
            )
        txt.insert(tk.END, "\nConcept mistake clusters\n\n")
        for row in analytics.get("concept_clusters", []):
            txt.insert(
                tk.END,
                f"{row['concept']}  severity {row['severity']}  misses {row['misses']}  weak {row['active_weak']}  due {row['due']}  top miss {row['top_miss_reason'] or 'n/a'}\n",
            )
        txt.insert(tk.END, "\nCoverage gap detector\n\n")
        for row in analytics.get("coverage_gaps", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}  severity {row['severity']}  covered {row['attempted']}/{row['available']}  accuracy {row['accuracy']}%\n",
            )
        txt.insert(tk.END, "\nObjective-code mastery autopilot\n\n")
        for row in analytics.get("objective_mastery", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['objective_code']}: mastery {row['mastery_score']}%  attempted {row['attempted']}/{row['available']}  stems {row['stem_style_count']}  sources {row['source_count']}  due {row['due']}\n",
            )
        txt.insert(tk.END, "\nConfidence compression\n\n")
        for row in analytics.get("confidence_compression", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: compression {row['compression']}  fragile {row['fragile_correct']}/{row['correct_total']}  stability {row['stability']}\n",
            )
        txt.insert(tk.END, "\nAbstraction ladder\n\n")
        for row in analytics.get("abstraction_ladder", [])[:8]:
            missing = ", ".join(row["missing_styles"][:3]) or "none"
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: {row['label']}  {row['score']}%  rungs {row['rung_count']}/{row['available_style_count']}  missing {missing}\n",
            )
        txt.insert(tk.END, "\nError-boundary tracing\n\n")
        for row in analytics.get("error_boundaries", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: weak {row['weak_style']} {row['weak_accuracy']}% vs strong {row['strong_style']} {row['strong_accuracy']}%  gap {row['gap']} across {row['attempts']} tries\n",
            )
        txt.insert(tk.END, "\nCounterfactual distractor memory\n\n")
        for row in analytics.get("counterfactual_distractors", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: '{row['distractor']}' keeps beating '{row['correct']}'  pressure {row['pressure']}  count {row['count']}\n",
            )
        txt.insert(tk.END, "\nConcept memory state\n\n")
        for row in analytics.get("concept_memory_states", [])[:10]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: {row['state']}  evidence {row['evidence_count']}  confidence {row['confidence_quality']}%  transfer {row['transfer_evidence']}  next {row['next_ramp']}\n",
            )
        txt.insert(tk.END, "\nWrong-answer memory\n\n")
        for row in analytics.get("wrong_answer_memory", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: '{row['tempting_distractor']}' vs '{row['correct_concept']}'  pressure {row['pressure']}  count {row['count']}  examples {row['example_question_numbers'][:4]}\n",
            )
        txt.insert(tk.END, "\nDifficulty calibration\n\n")
        for row in analytics.get("difficulty_calibration", [])[:8]:
            txt.insert(
                tk.END,
                f"Q{row['question_number']}  {row['label']}  score {row['score']}  wrong {row['wrong_rate']}%  fragile {row['fragile_rate']}%  volatility {row['volatility']}\n",
            )
        txt.insert(tk.END, "\nSource phrasing normalization\n\n")
        for row in analytics.get("phrasing_normalization", [])[:8]:
            txt.insert(tk.END, f"Q{row['question_number']}  {row['label']}  {row['score']}%  {row['source_name']}\n")
        burnout = analytics.get("burnout_risk") or {}
        txt.insert(tk.END, "\nMicro-burnout detector\n\n")
        txt.insert(
            tk.END,
            f"{burnout.get('label', 'Low')}  {burnout.get('score', 0.0)}%  accuracy drop {burnout.get('accuracy_drop', 0.0)}  response drag {burnout.get('response_drag', 0.0)}s  fragile {burnout.get('fragile_rate', 0.0)}%\n",
        )
        txt.insert(tk.END, "\nSource agreement layer\n\n")
        for row in analytics.get("source_agreement", [])[:8]:
            txt.insert(
                tk.END,
                f"Q{row['question_number']}  {row['label']}  trust {round(row['score'] * 100)}%  source {row['source_name']}\n",
            )
        txt.insert(tk.END, "\nDynamic source trust decay\n\n")
        for row in analytics.get("source_trust", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['source_name']}: {row['label']}  trust {row['trust_score']}%  decay {row['decay']}  conflicts {row['conflict_count']}  issues {row['issue_count']}\n",
            )
        txt.insert(tk.END, "\nLatent weakness detector\n\n")
        for row in analytics.get("latent_weakness", [])[:8]:
            txt.insert(
                tk.END,
                f"Q{row['question_number']}  {row['score']}  {row['confidence_signal']}  stability {row['stability']}  {', '.join(row['reasons'])}\n",
            )
        txt.insert(tk.END, "\nTransfer-strength scoring\n\n")
        for row in analytics.get("transfer_strength", [])[:8]:
            txt.insert(
                tk.END,
                f"{row['kind']} {row['unit']}: {row['label']}  {row['score']}%  exposure {row['exposure']}  sources {row['source_count']}  stems {row['stem_style_count']}  due {row['due']}\n",
            )
        txt.insert(tk.END, "\nAuto-remediation cards\n\n")
        for row in analytics.get("remediation_cards", []):
            focus = ", ".join(f"Q{qnum}" for qnum in row.get("focus_questions", []))
            txt.insert(tk.END, f"{row['concept']}\n")
            txt.insert(tk.END, f"Diagnosis: {row['diagnosis']}\n")
            txt.insert(tk.END, f"Action: {row['action']}\n")
            txt.insert(tk.END, f"Anchor: {row['anchor']}\n")
            if focus:
                txt.insert(tk.END, f"Focus: {focus}\n")
            txt.insert(tk.END, "\n")
        txt.insert(tk.END, "\nConcept anchor notes\n\n")
        for row in analytics.get("concept_anchor_notes", []):
            txt.insert(tk.END, f"{row['topic']}: {row['note']}\n")
        txt.insert(tk.END, "\nRecovery ladder\n\n")
        for ladder, count in sorted((analytics.get("recovery_ladder") or {}).items(), key=lambda item: item[0]):
            txt.insert(tk.END, f"{ladder}: {count}\n")
        txt.insert(tk.END, "\nHow to read this\n\n")
        txt.insert(tk.END, "- Heat combines low accuracy, low coverage, and wrong-count drag. Higher means weaker.\n")
        txt.insert(
            tk.END,
            "- Readiness rewards accuracy, coverage, confidence, and recovery while penalizing active weak and due drag.\n",
        )
        txt.insert(
            tk.END,
            "- Decision quality rewards correct answers with honest confidence and penalizes overconfident misses.\n",
        )
        txt.insert(tk.END, "- Trend compares recent 7-day weighted accuracy against the previous 7 days.\n")
        txt.insert(tk.END, "- Recent 50 shows whether you are improving now, not just overall.\n")
        txt.insert(tk.END, "- Due review follows the saved spaced-repetition schedule.\n")
        txt.insert(tk.END, "- Weak retest uses active weak questions, due reviews, flags, and weak domains.\n")
        if self.active_session_mode == MODE_EXAM and not self.exam_reveal:
            txt.insert(tk.END, "- Exam mode is still locked. Finish Exam to reveal correctness and explanations.\n")
        txt.configure(state="disabled")
        patterns_text = self.analytics_widgets["patterns_text"]
        patterns_text.configure(state="normal")
        patterns_text.delete("1.0", tk.END)
        patterns_text.insert(tk.END, "Confidence calibration\n\n")
        for row in analytics.get("confidence_calibration", []):
            patterns_text.insert(tk.END, f"{row['confidence']}: {row['accuracy']}% across {row['attempts']} attempts\n")
        patterns_text.insert(tk.END, "\nAnti-patterns\n\n")
        patterns = analytics.get("anti_patterns") or []
        if patterns:
            for idx, pattern in enumerate(patterns, start=1):
                patterns_text.insert(tk.END, f"{idx}. {pattern}\n")
        else:
            patterns_text.insert(tk.END, "No major anti-patterns detected yet.\n")
        patterns_text.insert(tk.END, "\nTrap-word review\n\n")
        trap_rows = analytics.get("trap_word_patterns") or []
        if trap_rows:
            for row in trap_rows:
                patterns_text.insert(tk.END, f"{row['trap_word']}: {row['count']} recent misses\n")
        else:
            patterns_text.insert(tk.END, "No repeated trap-word misses yet.\n")
        patterns_text.insert(tk.END, "\nAnswer latency diagnosis\n\n")
        latency_rows = analytics.get("answer_latency_diagnosis") or []
        if latency_rows:
            for row in latency_rows[:8]:
                patterns_text.insert(
                    tk.END,
                    f"{row['kind']} {row['unit']}: {row['label']} pressure {row['pressure']} | fast wrong {row['fast_wrong']} | slow wrong {row['slow_wrong']} | avg {row['avg_seconds']}s. {row['note']}\n",
                )
        else:
            patterns_text.insert(tk.END, "No timing-based answer pattern detected yet.\n")
        patterns_text.insert(tk.END, "\nConcept confidence mismatch\n\n")
        mismatch_rows = analytics.get("confidence_mismatch") or []
        if mismatch_rows:
            for row in mismatch_rows[:8]:
                examples = ", ".join(f"Q{qnum}" for qnum in row.get("example_question_numbers", [])[:4])
                patterns_text.insert(
                    tk.END,
                    f"{row['kind']} {row['unit']}: {row['sure_wrong_rate']}% sure-wrong rate across {row['sure_attempts']} sure attempts. {row['note']} {examples}\n",
                )
        else:
            patterns_text.insert(tk.END, "No repeated sure-but-wrong concept mismatch detected yet.\n")
        patterns_text.insert(tk.END, "\nWrong-answer family review\n\n")
        family_rows = analytics.get("wrong_answer_families") or []
        if family_rows:
            for row in family_rows:
                patterns_text.insert(tk.END, f"{row['family']}: {row['count']} misses. {row['coaching']}")
                if row.get("topics"):
                    patterns_text.insert(tk.END, f" Topics: {row['topics']}.")
                if row.get("examples"):
                    patterns_text.insert(tk.END, f" Example distractors: {row['examples']}.")
                patterns_text.insert(tk.END, "\n")
        else:
            patterns_text.insert(tk.END, "No repeated wrong-answer family patterns yet.\n")
        patterns_text.insert(tk.END, "\nConfusion-pair drills\n\n")
        confusion_rows = analytics.get("confusion_pairs") or []
        if confusion_rows:
            for row in confusion_rows:
                patterns_text.insert(tk.END, f"{row['pair']}: {row['count']} times. {row['action']}\n")
        else:
            patterns_text.insert(tk.END, "No repeated confusion pairs detected yet.\n")
        patterns_text.insert(tk.END, "\nInterference map\n\n")
        interference_rows = analytics.get("interference_map") or []
        if interference_rows:
            for row in interference_rows:
                patterns_text.insert(
                    tk.END, f"{row['pair']}: pressure {row['pressure']} across {row['count']} misses. {row['action']}\n"
                )
        else:
            patterns_text.insert(tk.END, "No strong concept interference pairs detected yet.\n")
        patterns_text.insert(tk.END, "\nError-boundary tracing\n\n")
        error_boundary_rows = analytics.get("error_boundaries") or []
        if error_boundary_rows:
            for row in error_boundary_rows:
                patterns_text.insert(
                    tk.END,
                    f"{row['kind']} {row['unit']}: {row['weak_style']} is trailing {row['strong_style']} by {row['gap']} points. {row['note']}\n",
                )
        else:
            patterns_text.insert(tk.END, "No strong stem-style transfer boundaries detected yet.\n")
        patterns_text.insert(tk.END, "\nCounterfactual distractor memory\n\n")
        counterfactual_rows = analytics.get("counterfactual_distractors") or []
        if counterfactual_rows:
            for row in counterfactual_rows:
                patterns_text.insert(
                    tk.END,
                    f"{row['kind']} {row['unit']}: '{row['distractor']}' beats '{row['correct']}' {row['count']} times. {row['note']}\n",
                )
        else:
            patterns_text.insert(tk.END, "No repeated distractor trap pairs detected yet.\n")
        patterns_text.insert(tk.END, "\nWrong-answer memory\n\n")
        memory_rows = analytics.get("wrong_answer_memory") or []
        if memory_rows:
            for row in memory_rows:
                patterns_text.insert(
                    tk.END,
                    f"{row['kind']} {row['unit']}: '{row['tempting_distractor']}' keeps competing with '{row['correct_concept']}' at pressure {row['pressure']}. {row['note']}\n",
                )
        else:
            patterns_text.insert(tk.END, "No concept-level tempting distractor pressure detected yet.\n")
        patterns_text.insert(tk.END, "\nHow to use this\n\n")
        patterns_text.insert(
            tk.END,
            "- If guessed answers are often correct, treat them as unstable knowledge and review them before trusting readiness.\n",
        )
        patterns_text.insert(
            tk.END, "- Repeated miss reasons usually point to a habit problem, not just a content gap.\n"
        )
        patterns_text.insert(
            tk.END, "- Trap-word counts help you slow down before qualifier, exception, and timing questions.\n"
        )
        patterns_text.insert(
            tk.END,
            "- Volatile questions are the ones flipping between right and wrong; review the rule behind them, not just the key.\n",
        )
        patterns_text.insert(
            tk.END, "- Stability scores reward concepts that stay correct over time, not just one-off wins.\n"
        )
        patterns_text.insert(
            tk.END,
            "- Concept clusters and remediation cards show where repeated misses belong to the same idea, not separate questions.\n",
        )
        patterns_text.configure(state="disabled")
