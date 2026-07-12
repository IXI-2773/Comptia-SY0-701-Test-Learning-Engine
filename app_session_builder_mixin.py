import copy
import random
import threading
from tkinter import messagebox

from app_constants import MODE_PRACTICE, MODE_SMART_PRACTICE
from progress_store import (
    is_active_weak,
    is_ever_wrong,
    is_review_due,
    is_super_confident_active,
    is_suspended,
    select_due_review_questions,
    select_questions_by_history,
)
from session_models import QuestionRuntimeState, reset_runtime_question_state
from smart_practice_concept_graph import (
    audit_graph,
    concept_key_for_question,
    normalize_graph,
    store_diagnosis,
)
from smart_practice_core import (
    SmartPracticeCandidate,
    build_smart_practice_score,
    build_smart_practice_selection,
)
from smart_practice_measurement import attach_prediction_to_question, normalize_measurement_store
from smart_practice_policy import active_policy, normalize_governance
from smart_practice_profile import (
    SMART_PRACTICE_POLICY_VERSION,
    SMART_PRACTICE_SCORING,
    smart_practice_objective_cap,
)
from smart_practice_question_value import (
    normalize_calibration_store,
)
from smart_practice_worker import (
    SmartPracticeWorkerSnapshot,
    build_detached_signal_payload,
    create_detached_context,
)
from study_question_utils import (
    coverage_unit_for_question,
    normalized_study_label,
    primary_topic_label,
    question_mentions_label,
    stem_style_for_question,
)


class SessionBuilderMixin:
    def _smart_practice_worker_revision(self):
        return self._freeze_signal_value(
            {
                "signal_key": self._smart_practice_signal_key(),
                "progress_history": list(self._progress_history())[-28:],
                "session_answer_history": list(self.session_answer_history or [])[-12:],
            }
        )

    def _smart_practice_worker_snapshot(self, *, base_pool=None):
        meta = self.progress_data.setdefault("meta", {})
        return SmartPracticeWorkerSnapshot(
            master_questions=copy.deepcopy(self.master_questions),
            questions=copy.deepcopy(self.questions),
            progress_data=copy.deepcopy(self.progress_data),
            session_answer_history=copy.deepcopy(list(self.session_answer_history or [])),
            active_session_mode=str(self.active_session_mode or ""),
            smart_practice_signal_cache_key=copy.deepcopy(getattr(self, "smart_practice_signal_cache_key", None)),
            smart_practice_signal_cache_payload=copy.deepcopy(
                getattr(self, "smart_practice_signal_cache_payload", None)
            ),
            smart_practice_pool_cache=copy.deepcopy(getattr(self, "smart_practice_pool_cache", {})),
            progress_meta_cache_raw=copy.deepcopy(meta if isinstance(meta, dict) else {}),
            progress_meta_cache_value=None,
            base_pool=copy.deepcopy(list(base_pool) if base_pool is not None else None),
        )

    def _normalized_study_label(self, value: str) -> str:
        return normalized_study_label(value)

    def _freeze_signal_value(self, value):
        if isinstance(value, dict):
            return tuple(
                (str(key), self._freeze_signal_value(nested_value))
                for key, nested_value in sorted(value.items(), key=lambda item: str(item[0]))
            )
        if isinstance(value, (list, tuple)):
            return tuple(self._freeze_signal_value(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted(self._freeze_signal_value(item) for item in value))
        return value

    def _smart_practice_signal_key(self):
        records_key = tuple(
            (
                key,
                str((rec or {}).get("next_review", "")),
                str(((rec or {}).get("learner_memory") or {}).get("next_review_at", "")),
                float(((rec or {}).get("learner_memory") or {}).get("retrievability", 0.0) or 0.0),
                int((rec or {}).get("attempts", 0) or 0),
                int((rec or {}).get("wrong_count", 0) or 0),
                int((rec or {}).get("correct_streak", 0) or 0),
            )
            for key, rec in sorted(self._progress_questions().items())
        )
        repair_key = tuple(
            sorted(
                (
                    str(key),
                    self._freeze_signal_value(value),
                )
                for key, value in (self.progress_data.get("meta", {}).get("repair_state", {}) or {}).items()
            )
        )
        measurement_policy = self._freeze_signal_value(
            self.progress_data.get("meta", {}).get("smart_practice_measurement", {}).get("active_policy", {}) or {}
        )
        governance = normalize_governance(self.progress_data.get("meta", {}).get("smart_practice_policy_governance"))
        active_smart_policy = active_policy(governance)
        governance_policy = (
            str(active_smart_policy.get("policy_id") or ""),
            str(active_smart_policy.get("checksum") or ""),
            int(active_smart_policy.get("policy_schema_version") or 0),
        )
        graph_key = str(
            (self.progress_data.get("meta", {}).get("smart_practice_concept_graph") or {}).get("graph_signature") or ""
        )
        calibration_key = str(
            (self.progress_data.get("meta", {}).get("smart_practice_question_calibration") or {}).get("last_updated_at")
            or ""
        )
        session_answer_key = tuple(
            (
                int(event.get("question_number") or 0),
                bool(event.get("correct")),
                str(event.get("confidence") or ""),
                str(event.get("miss_reason") or ""),
            )
            for event in (self.session_answer_history or [])
        )
        return (
            SMART_PRACTICE_POLICY_VERSION,
            measurement_policy,
            governance_policy,
            graph_key,
            calibration_key,
            self._analytics_signature(),
            records_key,
            repair_key,
            session_answer_key,
        )

    def _build_near_miss_pressure_maps(self, history, questions):
        question_lookup = {int(q.get("question_number") or 0): q for q in questions}
        unit_pressure: dict[str, float] = {}
        label_pressure: dict[str, float] = {}
        near_miss_families = {"Near-synonym / look-alike distractor", "Plausible distractor"}
        for event in history:
            if event.get("correct"):
                continue
            family = str(event.get("wrong_answer_family") or "")
            recall_failure = str(event.get("recall_failure") or "")
            confidence = str(event.get("confidence") or "")
            is_near_miss = (
                family in near_miss_families
                or recall_failure == "Concept interference"
                or confidence in {"Sure", "Unsure"}
            )
            if not is_near_miss:
                continue
            question = question_lookup.get(int(event.get("question_number") or 0))
            if not question:
                continue
            kind, unit = self._coverage_unit_for_question(question)
            unit_key = f"{kind}::{unit}"
            unit_pressure[unit_key] = min(100.0, unit_pressure.get(unit_key, 0.0) + 18.0)
            labels = [
                self._choice_concept_label(str(text)) or str(text).strip()[:48]
                for text in list(event.get("selected_texts") or []) + list(event.get("correct_texts") or [])
                if str(text).strip()
            ]
            for label in labels:
                if label:
                    label_pressure[label] = min(100.0, label_pressure.get(label, 0.0) + 14.0)
        question_pressure = {}
        for question in questions:
            qnum = int(question.get("question_number") or 0)
            kind, unit = self._coverage_unit_for_question(question)
            pressure = unit_pressure.get(f"{kind}::{unit}", 0.0)
            for label, label_score in label_pressure.items():
                if self._question_mentions_label(question, label):
                    pressure = max(pressure, label_score)
            if pressure:
                question_pressure[qnum] = pressure
        return unit_pressure, question_pressure

    def _build_wrong_answer_recycling_map(self, memory_rows, questions):
        question_pressure = {}
        for question in questions:
            qnum = int(question.get("question_number") or 0)
            pressure = 0.0
            for row in memory_rows[:12]:
                tempting = str(row.get("tempting_distractor") or "")
                correct = str(row.get("correct_concept") or "")
                row_pressure = float(row.get("pressure", 0.0))
                if qnum in set(row.get("example_question_numbers") or []):
                    continue
                mentions_tempting = tempting and self._question_mentions_label(question, tempting)
                mentions_correct = correct and self._question_mentions_label(question, correct)
                if mentions_tempting and mentions_correct:
                    pressure = max(pressure, row_pressure + 14.0)
                elif mentions_tempting:
                    pressure = max(pressure, row_pressure + 6.0)
                elif mentions_correct:
                    pressure = max(pressure, row_pressure * 0.55)
            if pressure:
                question_pressure[qnum] = min(100.0, pressure)
        return question_pressure

    def _infer_smart_practice_intent(
        self,
        *,
        records,
        signal_questions,
        gap_map,
        wrong_answer_memory_pressure_map,
        near_miss_unit_map,
        retention_stress_map,
        momentum_profile,
    ):
        attempted = 0
        unseen = 0
        active_weak = 0
        due = 0
        for question in signal_questions:
            rec = records.get(self._question_key(question), {})
            if int(rec.get("attempts", 0)) > 0:
                attempted += 1
            else:
                unseen += 1
            if is_active_weak(rec):
                active_weak += 1
            if is_review_due(rec):
                due += 1
        total = max(1, len(signal_questions))
        coverage_signal = (unseen / total) * 100.0 + (max(gap_map.values()) if gap_map else 0.0) * 0.35
        repair_signal = (
            active_weak * 8.0
            + (max(wrong_answer_memory_pressure_map.values()) if wrong_answer_memory_pressure_map else 0.0)
            + (max(near_miss_unit_map.values()) if near_miss_unit_map else 0.0) * 0.6
        )
        retention_signal = due * 10.0 + (
            max(float(row.get("pressure", 0.0)) for row in retention_stress_map.values())
            if retention_stress_map
            else 0.0
        )
        readiness_signal = attempted / total * 70.0
        if momentum_profile.get("label") == "Press":
            readiness_signal += 18.0
        if repair_signal >= 45.0 or repair_signal >= max(coverage_signal, retention_signal, readiness_signal):
            label = "Repair weak spots"
        elif retention_signal >= max(coverage_signal, readiness_signal):
            label = "Retain old material"
        elif readiness_signal >= coverage_signal and attempted / total >= 0.55:
            label = "Exam readiness"
        else:
            label = "Build coverage"
        return {
            "label": label,
            "coverage_signal": round(coverage_signal, 1),
            "repair_signal": round(repair_signal, 1),
            "retention_signal": round(retention_signal, 1),
            "readiness_signal": round(readiness_signal, 1),
        }

    def _build_smart_practice_signal_payload(self):
        records = self._progress_questions()
        signal_questions = [
            question
            for question in self.master_questions
            if not question.get("suspended") and not is_suspended(records.get(self._question_key(question), {}))
        ]
        recent_history = self._recent_history(28)
        profile = SMART_PRACTICE_SCORING
        source_rows, source_map = self._build_source_agreement_rows(signal_questions)
        _source_trust_rows, source_trust_map = self._build_source_trust_rows(signal_questions, source_rows)
        coverage_gaps = self._build_coverage_gap_rows(records, signal_questions)
        gap_map = self._coverage_gap_priority_map(coverage_gaps)
        interference_rows = self._build_interference_map_rows(recent_history)
        question_history_map = {}
        for event in recent_history:
            qnum = int(event.get("question_number") or 0)
            question_history_map.setdefault(qnum, []).append(event)
        question_stability = {}
        for question in signal_questions:
            rec = records.get(self._question_key(question), {})
            if not rec or is_suspended(rec):
                continue
            qnum = int(question.get("question_number") or 0)
            question_stability[qnum] = self._question_stability_score(
                question,
                rec,
                question_history_map.get(qnum, []),
            )
        _objective_rows, objective_map = self._build_objective_mastery_rows(
            records, question_stability, question_history_map, source_map, signal_questions
        )
        _knowledge_trace_rows, knowledge_trace_map = self._build_knowledge_trace_rows(
            question_history_map, signal_questions
        )
        _concept_memory_rows, concept_memory_map = self._build_concept_memory_state_rows(
            question_history_map, signal_questions
        )
        wrong_answer_memory_rows, wrong_answer_memory_pressure_map = self._build_wrong_answer_memory_rows(
            recent_history, signal_questions
        )
        near_miss_unit_map, near_miss_question_map = self._build_near_miss_pressure_maps(
            recent_history, signal_questions
        )
        wrong_answer_recycling_map = self._build_wrong_answer_recycling_map(wrong_answer_memory_rows, signal_questions)
        wrong_answer_memory_example_qnums = {
            int(qnum)
            for row in wrong_answer_memory_rows
            for qnum in row.get("example_question_numbers", [])
            if int(qnum or 0)
        }
        _recognition_retrieval_rows, recognition_retrieval_map = self._build_recognition_retrieval_rows(
            question_history_map, signal_questions
        )
        _confidence_compression_rows, confidence_compression_map = self._build_confidence_compression_rows(
            records, question_stability, question_history_map, signal_questions
        )
        _abstraction_ladder_rows, abstraction_ladder_map = self._build_abstraction_ladder_rows(
            records, question_stability, question_history_map, signal_questions
        )
        _compression_point_rows, compression_point_map = self._build_compression_point_rows(
            recognition_retrieval_map, abstraction_ladder_map
        )
        _decision_latency_rows, decision_latency_map = self._build_decision_latency_rows(
            recent_history, self.master_questions
        )
        _error_boundary_rows, error_boundary_map = self._build_error_boundary_rows(
            recent_history, self.master_questions
        )
        counterfactual_distractor_rows, counterfactual_pressure_map = self._build_counterfactual_distractor_rows(
            recent_history, self.master_questions
        )
        _contrast_rule_rows, contrast_pressure_map = self._build_contrast_rule_rows(
            counterfactual_distractor_rows,
            self._build_confusion_pair_rows(recent_history),
            signal_questions,
        )
        _prerequisite_debt_rows, prerequisite_debt_map = self._build_prerequisite_debt_rows(
            records,
            question_stability,
            coverage_gaps,
            objective_map,
            error_boundary_map,
            counterfactual_pressure_map,
            signal_questions,
        )
        _concept_half_life_rows, concept_half_life_map = self._build_concept_half_life_rows(
            records, question_stability, question_history_map, signal_questions
        )
        _leverage_rows, leverage_map = self._build_leverage_ranking_rows(
            records, prerequisite_debt_map, signal_questions
        )
        _blind_spot_rows, blind_spot_map = self._build_blind_spot_inference_rows(
            coverage_gaps, prerequisite_debt_map, leverage_map, signal_questions
        )
        _misconception_rows, misconception_pressure_map = self._build_misconception_fingerprint_rows(
            recent_history, signal_questions
        )
        latent_rows = self._build_latent_weakness_rows(
            records, question_stability, question_history_map, source_map, source_trust_map, signal_questions
        )
        latent_map = {int(row["question_number"]): row for row in latent_rows}
        transfer_rows, transfer_map = self._build_transfer_strength_rows(records, question_stability, signal_questions)
        _robustness_rows, robustness_map = self._build_robustness_score_rows(
            transfer_rows, abstraction_ladder_map, concept_half_life_map
        )
        _generalization_rows, generalization_map = self._build_generalization_score_rows(
            transfer_rows, abstraction_ladder_map, robustness_map
        )
        _difficulty_rows, difficulty_map = self._build_difficulty_calibration_rows(
            records, question_stability, question_history_map, source_map, signal_questions
        )
        _phrasing_rows, phrasing_map = self._build_phrasing_normalization_rows(signal_questions)
        _effort_efficiency_rows, effort_efficiency_map = self._build_effort_efficiency_rows(
            recent_history, signal_questions
        )
        _reinforcement_rows, reinforcement_map = self._build_reinforcement_distance_rows(
            records, question_stability, concept_half_life_map, signal_questions
        )
        _synthesis_rows, synthesis_map = self._build_synthesis_check_rows(objective_map, signal_questions)
        _cue_dependence_rows, cue_dependence_map = self._build_cue_dependence_rows(
            question_history_map, recognition_retrieval_map, phrasing_map, signal_questions
        )
        _delayed_probe_rows, delayed_probe_map = self._build_delayed_probe_rows(
            records, concept_half_life_map, signal_questions
        )
        _counterexample_training_rows, counterexample_training_map = self._build_counterexample_training_rows(
            counterfactual_distractor_rows, contrast_pressure_map, signal_questions
        )
        _failure_mode_rows, failure_mode_map = self._build_failure_mode_rows(recent_history, signal_questions)
        _expected_learning_gain_rows, expected_learning_gain_map = self._build_expected_learning_gain_rows(
            records, knowledge_trace_map, leverage_map, difficulty_map, signal_questions
        )
        _retention_stress_rows, retention_stress_map = self._build_retention_stress_rows(
            records, concept_half_life_map, robustness_map, signal_questions
        )
        _concept_state_rows, concept_state_map = self._build_concept_state_rows(
            knowledge_trace_map, generalization_map, robustness_map, concept_half_life_map
        )
        freshness_map = self._build_question_freshness_map(recent_history, records, signal_questions)
        qnum_unit_map = {}
        for question in signal_questions:
            kind, unit = self._coverage_unit_for_question(question)
            qnum_unit_map[int(question.get("question_number") or 0)] = f"{kind}::{unit}"

        def event_unit_key(event) -> str:
            objective_code = str(event.get("objective_code") or "").strip()
            if objective_code:
                return f"Objective::{objective_code}"
            qnum = int(event.get("question_number") or 0)
            if qnum in qnum_unit_map:
                return qnum_unit_map[qnum]
            topics = [str(topic).strip() for topic in event.get("topics", []) if str(topic).strip()]
            if topics:
                return f"Topic::{topics[0]}"
            return f"Domain::{str(event.get('domain') or 'Unsorted')}"

        recent_concept_cooldown_map = {}
        cooldown_events = list(self.session_answer_history or [])[-profile.recent_concept_cooldown_window :]
        if not cooldown_events:
            cooldown_events = list(recent_history)[-profile.recent_concept_cooldown_window :]
        for event in cooldown_events:
            unit_key = event_unit_key(event)
            recent_concept_cooldown_map[unit_key] = recent_concept_cooldown_map.get(unit_key, 0) + 1
        burnout_risk = self._build_burnout_risk_row(self.session_answer_history or recent_history)
        momentum_profile = self._build_momentum_profile(self.session_answer_history or recent_history, burnout_risk)
        session_intent = self._infer_smart_practice_intent(
            records=records,
            signal_questions=signal_questions,
            gap_map=gap_map,
            wrong_answer_memory_pressure_map=wrong_answer_memory_pressure_map,
            near_miss_unit_map=near_miss_unit_map,
            retention_stress_map=retention_stress_map,
            momentum_profile=momentum_profile,
        )
        return {
            "source_map": source_map,
            "source_trust_map": source_trust_map,
            "gap_map": gap_map,
            "interference_rows": interference_rows,
            "objective_map": objective_map,
            "knowledge_trace_map": knowledge_trace_map,
            "concept_memory_map": concept_memory_map,
            "wrong_answer_memory_pressure_map": wrong_answer_memory_pressure_map,
            "wrong_answer_recycling_map": wrong_answer_recycling_map,
            "wrong_answer_memory_example_qnums": wrong_answer_memory_example_qnums,
            "near_miss_unit_map": near_miss_unit_map,
            "near_miss_question_map": near_miss_question_map,
            "recognition_retrieval_map": recognition_retrieval_map,
            "confidence_compression_map": confidence_compression_map,
            "abstraction_ladder_map": abstraction_ladder_map,
            "compression_point_map": compression_point_map,
            "decision_latency_map": decision_latency_map,
            "error_boundary_map": error_boundary_map,
            "counterfactual_pressure_map": counterfactual_pressure_map,
            "contrast_pressure_map": contrast_pressure_map,
            "prerequisite_debt_map": prerequisite_debt_map,
            "concept_half_life_map": concept_half_life_map,
            "leverage_map": leverage_map,
            "blind_spot_map": blind_spot_map,
            "misconception_pressure_map": misconception_pressure_map,
            "latent_map": latent_map,
            "transfer_map": transfer_map,
            "robustness_map": robustness_map,
            "generalization_map": generalization_map,
            "difficulty_map": difficulty_map,
            "phrasing_map": phrasing_map,
            "effort_efficiency_map": effort_efficiency_map,
            "reinforcement_map": reinforcement_map,
            "synthesis_map": synthesis_map,
            "cue_dependence_map": cue_dependence_map,
            "delayed_probe_map": delayed_probe_map,
            "counterexample_training_map": counterexample_training_map,
            "failure_mode_map": failure_mode_map,
            "expected_learning_gain_map": expected_learning_gain_map,
            "retention_stress_map": retention_stress_map,
            "concept_state_map": concept_state_map,
            "freshness_map": freshness_map,
            "recent_concept_cooldown_map": recent_concept_cooldown_map,
            "burnout_risk": burnout_risk,
            "momentum_profile": momentum_profile,
            "session_intent": session_intent,
        }

    def _publish_smart_practice_signal_snapshot(self, snapshot) -> None:
        if getattr(self, "_app_closing", False):
            return
        if snapshot.get("revision") != self._smart_practice_worker_revision():
            return
        if snapshot["key"] != self._smart_practice_signal_key():
            return
        self.smart_practice_signal_cache_key = snapshot["key"]
        self.smart_practice_signal_cache_payload = snapshot["payload"]

    def schedule_smart_practice_prewarm(self, delay_ms=None) -> None:
        if not self.master_questions or not getattr(self, "smart_practice_prewarm", None):
            return
        key = self._smart_practice_signal_key()
        revision = self._smart_practice_worker_revision()
        snapshot = self._smart_practice_worker_snapshot()

        def build_payload():
            return build_detached_signal_payload(type(self), snapshot)

        self.smart_practice_prewarm.schedule(
            key,
            build_payload,
            revision=revision,
            delay_ms=delay_ms,
        )

    def _set_session_start_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for name in ("start_set_btn", "full_bank_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                try:
                    btn.configure(state=state)
                except Exception:
                    pass

    def _run_session_start_action(self, action) -> None:
        if getattr(self, "_session_start_busy", False):
            return
        self._session_start_busy = True
        self._set_session_start_controls_enabled(False)
        try:
            try:
                self.root.configure(cursor="watch")
            except Exception:
                pass
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            action()
        finally:
            try:
                self.root.configure(cursor="")
            except Exception:
                pass
            self._set_session_start_controls_enabled(True)
            self._session_start_busy = False

    def _set_session_start_busy_state(self, busy: bool, message: str = "") -> None:
        self._session_start_busy = bool(busy)
        self._set_session_start_controls_enabled(not busy)
        try:
            self.root.configure(cursor="watch" if busy else "")
        except Exception:
            pass
        if message:
            try:
                self.question_meta_label.configure(text="Building Smart Practice")
                self.question_label.configure(text=message)
                self.session_label.configure(text="Preparing adaptive question set...")
                self.root.update_idletasks()
            except Exception:
                pass

    def _build_smart_practice_pool_compat(self, count, randomize, base_pool):
        try:
            return self.build_smart_practice_pool(count, randomize=randomize, base_pool=base_pool)
        except TypeError as exc:
            if "base_pool" not in str(exc):
                raise
            return self.build_smart_practice_pool(count, randomize=randomize)

    def _resume_existing_session_choice(self, builder_context):
        try:
            if self.root.state() == "withdrawn":
                return None
        except Exception:
            return None
        resume_path = self.find_resumable_session_for_builder(builder_context)
        if resume_path is None:
            return None
        answer = messagebox.askyesnocancel(
            "Resume saved set?",
            "An unfinished matching set was found.\n\n"
            "Yes: resume where you left off.\n"
            "No: start a fresh set with these options.\n"
            "Cancel: stay on the builder.",
        )
        if answer is None:
            return "cancel"
        return bool(answer)

    def _start_smart_practice_async(
        self, count, randomize, base_pool, *, preserve_if_saved=True, builder_context=None
    ) -> None:
        if getattr(self, "_session_start_busy", False):
            return
        builder_context = builder_context or self.current_builder_context(
            mode=MODE_SMART_PRACTICE,
            count=count,
            randomize=False,
            source_label=self.current_builder_source_label(MODE_SMART_PRACTICE),
        )
        try:
            root_withdrawn = self.root.state() == "withdrawn"
        except Exception:
            root_withdrawn = False
        if root_withdrawn:
            pool = self._build_smart_practice_pool_compat(count, randomize=randomize, base_pool=base_pool)
            if not pool:
                messagebox.showinfo(
                    "Smart Practice", "No questions are available for smart practice with the current filters."
                )
                return
            self.save_app_config()
            self.start_session_from_pool(
                pool,
                mode=MODE_SMART_PRACTICE,
                count="All visible",
                randomize=False,
                reset_clock=True,
                preserve_if_saved=preserve_if_saved,
                source_label=self.current_builder_source_label(MODE_SMART_PRACTICE),
                builder_context=builder_context,
            )
            return
        self._set_session_start_busy_state(
            True, "Building your adaptive set. The app should stay responsive while the tutor scores the bank."
        )
        self._smart_practice_async_generation = int(getattr(self, "_smart_practice_async_generation", 0) or 0) + 1
        generation = self._smart_practice_async_generation
        signal_key = self._smart_practice_signal_key()
        revision = self._smart_practice_worker_revision()
        snapshot = self._smart_practice_worker_snapshot(base_pool=base_pool)

        def worker():
            error = None
            pool = []
            worker_meta = {}
            try:
                context = create_detached_context(type(self), snapshot)
                pool = context._build_smart_practice_pool_compat(
                    count,
                    randomize=randomize,
                    base_pool=snapshot.base_pool,
                )
                detached_signal_payload = context._build_smart_practice_signal_payload()
                worker_meta = {
                    "progress_meta": copy.deepcopy(snapshot.progress_data.get("meta", {})),
                    "signal_cache_key": copy.deepcopy(signal_key),
                    "signal_cache_payload": copy.deepcopy(detached_signal_payload),
                    "pool_cache": copy.deepcopy(snapshot.smart_practice_pool_cache),
                }
            except Exception as exc:
                error = exc

            def finish():
                if getattr(self, "_app_closing", False):
                    return
                if generation != getattr(self, "_smart_practice_async_generation", 0):
                    return
                if revision != self._smart_practice_worker_revision():
                    self._set_session_start_busy_state(False)
                    self.session_label.configure(text="Smart Practice build discarded because learner state changed.")
                    return
                self._set_session_start_busy_state(False)
                if error is not None:
                    messagebox.showerror("Smart Practice", f"Could not build Smart Practice set.\n\n{error}")
                    self.render_question()
                    return
                if not pool:
                    messagebox.showinfo(
                        "Smart Practice", "No questions are available for smart practice with the current filters."
                    )
                    self.render_question()
                    return
                if isinstance(worker_meta.get("progress_meta"), dict):
                    self.progress_data["meta"] = worker_meta["progress_meta"]
                    self._progress_meta_cache_raw = self.progress_data["meta"]
                    self._progress_meta_cache_value = self.progress_data["meta"]
                self.smart_practice_signal_cache_key = worker_meta.get("signal_cache_key")
                self.smart_practice_signal_cache_payload = worker_meta.get("signal_cache_payload")
                self.smart_practice_pool_cache = worker_meta.get("pool_cache", {})
                self.save_app_config()
                self.start_session_from_pool(
                    pool,
                    mode=MODE_SMART_PRACTICE,
                    count="All visible",
                    randomize=False,
                    reset_clock=True,
                    preserve_if_saved=preserve_if_saved,
                    source_label=self.current_builder_source_label(MODE_SMART_PRACTICE),
                    builder_context=builder_context,
                )

            try:
                self.root.after(0, finish)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def on_session_mode_change(self, event=None):
        mode = self.session_mode_var.get()
        if mode in ("Weak retest", "Due review", MODE_SMART_PRACTICE):
            self.session_source_var.set("All")
        self.save_app_config()

    def current_source_badge_text(self):
        return f"Source: {self.active_source_label}"

    def current_builder_source_label(self, mode=None):
        mode = mode or self.session_mode_var.get()
        source = self.normalize_session_source(self.session_source_var.get())
        if mode == "Weak retest":
            return "Weak retest" if source == "All" else f"Weak retest + {source}"
        if mode == "Due review":
            return "Due review" if source == "All" else f"Due review + {source}"
        if mode == MODE_SMART_PRACTICE:
            return "Smart practice"
        return source

    def current_builder_context(self, mode=None, count=None, randomize=None, source_label=None):
        mode = mode or self.session_mode_var.get()
        source_label = str(source_label or self.current_builder_source_label(mode))
        count_value = count if count is not None else self.session_count_var.get()
        if count_value == "All visible":
            count_value = str(len(self.get_session_builder_pool()) or len(self.master_questions) or "")
        return {
            "mode": str(mode),
            "count": str(count_value or ""),
            "source_label": source_label,
            "session_source": self.normalize_session_source(self.session_source_var.get()),
            "randomize": bool(self.session_random_var.get() if randomize is None else randomize),
            "domain_filter": self.domain_filter_var.get(),
            "topic_filter": self.topic_filter_var.get(),
            "status_filter": self.normalize_status_filter(self.status_filter_var.get()),
        }

    def _interleave_questions(self, questions: list[QuestionRuntimeState]) -> list[QuestionRuntimeState]:
        if len(questions) <= 2:
            return list(questions)
        remaining = list(questions)
        ordered = [remaining.pop(0)]
        profile = SMART_PRACTICE_SCORING

        def source_label(question: QuestionRuntimeState) -> str:
            return str(question.get("source_label") or question.get("source_name") or "")

        while remaining:
            prev = ordered[-1]
            prev_domain = str(prev.get("domain") or "")
            prev_topic = primary_topic_label(prev)
            prev_objective = str(prev.get("objective_code") or "").strip()
            prev_source = str(prev.get("source_name") or "")
            prev_source_label = source_label(prev)
            prev_stem = stem_style_for_question(prev)
            recent = ordered[-3:]
            recent_topics = {primary_topic_label(item) for item in recent}
            recent_source_labels = {source_label(item) for item in recent}
            best_idx = 0
            best_score = None
            for idx, candidate in enumerate(remaining):
                score = 0.0
                if str(candidate.get("domain") or "") != prev_domain:
                    score += 4.0
                if primary_topic_label(candidate) != prev_topic:
                    score += 5.0
                if (
                    str(candidate.get("objective_code") or "").strip()
                    and str(candidate.get("objective_code") or "").strip() != prev_objective
                ):
                    score += 3.0
                if str(candidate.get("source_name") or "") != prev_source:
                    score += 2.0
                candidate_source_label = source_label(candidate)
                if candidate_source_label != prev_source_label:
                    score += profile.interleave_source_label_bonus
                elif candidate_source_label in recent_source_labels:
                    score -= profile.interleave_recent_source_penalty
                if stem_style_for_question(candidate) != prev_stem:
                    score += 2.5
                if primary_topic_label(candidate) in recent_topics:
                    score -= profile.interleave_recent_topic_penalty
                score -= idx * 0.01
                if best_score is None or score > best_score:
                    best_score = score
                    best_idx = idx
            ordered.append(remaining.pop(best_idx))
        return ordered

    def _reset_runtime_question_state(self, questions: list[QuestionRuntimeState]) -> None:
        for q in questions:
            reset_runtime_question_state(q)

    def start_custom_session(self):
        mode = self.session_mode_var.get()
        if mode == MODE_SMART_PRACTICE:
            builder_context = self.current_builder_context(
                mode=MODE_SMART_PRACTICE,
                count=self.session_count_var.get(),
                randomize=False,
                source_label=self.current_builder_source_label(MODE_SMART_PRACTICE),
            )
            resume_choice = self._resume_existing_session_choice(builder_context)
            if resume_choice == "cancel":
                return
            if resume_choice is True:
                self.save_app_config()
                self.start_session_from_pool(
                    self.master_questions,
                    mode=MODE_SMART_PRACTICE,
                    count="All visible",
                    randomize=False,
                    reset_clock=True,
                    preserve_if_saved=True,
                    source_label=self.current_builder_source_label(MODE_SMART_PRACTICE),
                    builder_context=builder_context,
                )
                return
            self._start_smart_practice_async(
                self.session_count_var.get(),
                self.session_random_var.get(),
                self.get_filtered_master_pool(),
                preserve_if_saved=(resume_choice is None),
                builder_context=builder_context,
            )
            return

        def _start():
            pool = self.get_session_builder_pool()
            mode = self.session_mode_var.get()
            count = self.session_count_var.get()
            if mode == "Weak retest":
                pool = self.build_weak_retest_pool()
                pool = self.filter_pool_by_session_source(pool)
                if not pool:
                    messagebox.showinfo(
                        "Weak retest",
                        "No weak-area pool is available yet. Answer some questions wrong, flag some, or build more coverage first.",
                    )
                    return
            elif mode == "Due review":
                pool = self.build_due_review_pool()
                pool = self.filter_pool_by_session_source(pool)
                if not pool:
                    messagebox.showinfo(
                        "Due review",
                        "No questions are due for review yet. Missed answers become due immediately; correct answers are scheduled for later.",
                    )
                    return
            if not pool:
                messagebox.showinfo("No questions", "No questions match the current filters and source selection.")
                return
            builder_context = self.current_builder_context(
                mode=mode,
                count=count,
                randomize=(False if mode == MODE_SMART_PRACTICE else self.session_random_var.get()),
                source_label=self.current_builder_source_label(mode),
            )
            resume_choice = self._resume_existing_session_choice(builder_context)
            if resume_choice == "cancel":
                return
            self.save_app_config()
            self.start_session_from_pool(
                pool,
                mode=mode,
                count="All visible" if mode == MODE_SMART_PRACTICE else count,
                randomize=(False if mode == MODE_SMART_PRACTICE else self.session_random_var.get()),
                reset_clock=True,
                preserve_if_saved=(resume_choice is not False),
                source_label=self.current_builder_source_label(mode),
                builder_context=builder_context,
            )

        self._run_session_start_action(_start)

    def restore_full_bank(self):
        def _restore():
            if not self.master_questions:
                return
            self.start_session_from_pool(
                self.master_questions,
                mode=MODE_PRACTICE,
                count="All visible",
                randomize=False,
                reset_clock=False,
                preserve_if_saved=True,
                source_label="Full bank",
                builder_context={
                    "mode": MODE_PRACTICE,
                    "count": str(len(self.master_questions)),
                    "source_label": "Full bank",
                    "session_source": "All",
                    "randomize": False,
                    "domain_filter": "All domains",
                    "topic_filter": "All topics",
                    "status_filter": "All questions",
                },
            )

        self._run_session_start_action(_restore)

    def get_filtered_master_pool(self):
        domain = self.domain_filter_var.get()
        topic = self.topic_filter_var.get()
        records = self._progress_questions()
        pool = [
            q
            for q in self.master_questions
            if not q.get("suspended") and not is_suspended(records.get(self._question_key(q), {}))
        ]
        if domain and domain != "All domains":
            normalized_domain = self._normalized_study_label(domain)
            pool = [q for q in pool if self._normalized_study_label(str(q.get("domain") or "")) == normalized_domain]
        if topic and topic != "All topics":
            normalized_topic = self._normalized_study_label(topic)
            pool = [
                q
                for q in pool
                if normalized_topic in [self._normalized_study_label(str(t)) for t in q.get("topics", [])]
            ]
        return pool

    def filter_pool_by_session_source(self, pool):
        return select_questions_by_history(pool, self._progress_questions(), self.session_source_var.get())

    def get_session_builder_pool(self):
        return self.filter_pool_by_session_source(self.get_filtered_master_pool())

    def build_weak_retest_pool(self) -> list[QuestionRuntimeState]:
        if not self.master_questions:
            return []
        domain_pool = self.get_filtered_master_pool()
        records = self._progress_questions()

        def weak_score(q):
            rec = records.get(self._question_key(q), {})
            wrong = int(rec.get("wrong_count", 0))
            recovered = int(rec.get("correct_count", 0))
            attempts = int(rec.get("attempts", 0))
            return (
                3 if rec.get("flagged") or q.get("flagged") else 0,
                2 if is_review_due(rec) else 0,
                2 if is_active_weak(rec) else 0,
                max(0, wrong - recovered),
                wrong,
                attempts,
            )

        progress_weak = [
            q
            for q in domain_pool
            if records.get(self._question_key(q), {}).get("flagged")
            or q.get("flagged")
            or is_review_due(records.get(self._question_key(q), {}))
            or is_active_weak(records.get(self._question_key(q), {}))
        ]
        if progress_weak:
            base = sorted(progress_weak, key=weak_score, reverse=True)
        else:
            analytics = self.compute_analytics(source=self.master_questions)
            weak_domains = [r["domain"] for r in analytics["domains"][:2]]
            base = [q for q in domain_pool if q.get("domain") in weak_domains]
        seen = set()
        out = []
        for q in base:
            qn = q.get("question_number")
            if qn not in seen:
                seen.add(qn)
                out.append(q)
        return out

    def build_due_review_pool(self) -> list[QuestionRuntimeState]:
        if not self.master_questions:
            return []
        records = self._progress_questions()
        domain_pool = self.get_filtered_master_pool()
        return select_due_review_questions(domain_pool, records)

    def build_smart_practice_pool(self, count, randomize=True, base_pool=None) -> list[QuestionRuntimeState]:
        profile = SMART_PRACTICE_SCORING
        governance = normalize_governance(
            self.progress_data.setdefault("meta", {}).get("smart_practice_policy_governance")
        )
        self.progress_data.setdefault("meta", {})["smart_practice_policy_governance"] = governance
        active_smart_policy = active_policy(governance)
        active_policy_values = active_smart_policy.get("policy_values") or {}
        utility_scales = dict(active_policy_values.get("utility_component_scales") or {})
        utility_bounds = dict(active_policy_values.get("utility_component_bounds") or {})
        source_risk_settings = dict(active_policy_values.get("source_risk_settings") or {})
        fatigue_settings = dict(active_policy_values.get("fatigue_settings") or {})
        review_interval_multiplier = float(active_policy_values.get("review_interval_multiplier", 1.0) or 1.0)
        repair_trigger_settings = dict(active_policy_values.get("repair_trigger_settings") or {})
        repair_spacing_settings = dict(active_policy_values.get("repair_spacing_settings") or {})
        weakness_thresholds = dict(active_policy_values.get("weakness_thresholds") or {})
        prediction_calibration = dict(active_policy_values.get("prediction_calibration") or {})
        exploration_settings = dict(active_policy_values.get("exploration_settings") or {})
        repetition_settings = dict(active_policy_values.get("repetition_settings") or {})
        graph_enabled = bool(active_policy_values.get("graph_enabled", True))
        graph_max_utility = float(active_policy_values.get("maximum_graph_utility_contribution", 4.0) or 4.0)
        information_enabled = bool(active_policy_values.get("information_value_enabled", True))
        quality_enabled = bool(active_policy_values.get("question_quality_enabled", True))
        info_max = float(active_policy_values.get("maximum_information_value_contribution", 6.0) or 6.0)
        quality_min_samples = int(active_policy_values.get("minimum_question_quality_samples", 10) or 10)
        bad_key_min_samples = int(active_policy_values.get("possible_bad_key_minimum_samples", 20) or 20)
        quality_risk_max = float(active_policy_values.get("quality_risk_maximum", 4.0) or 4.0)
        role_shares = dict(active_policy_values.get("role_shares") or {})
        pool = list(base_pool) if base_pool is not None else self.get_filtered_master_pool()
        if not pool:
            return []
        existing_signal_key = getattr(self, "smart_practice_signal_cache_key", None)
        existing_signal_payload = getattr(self, "smart_practice_signal_cache_payload", None)
        existing_pool_cache = getattr(self, "smart_practice_pool_cache", {})
        pool_qnums = tuple(int(question.get("question_number") or 0) for question in pool)
        if existing_signal_key is not None and existing_signal_payload is not None:
            quick_cache_key = (existing_signal_key, str(count), pool_qnums, bool(randomize))
            cached_qnums = existing_pool_cache.get(quick_cache_key)
            if cached_qnums is not None:
                question_map = {int(question.get("question_number") or 0): question for question in pool}
                cached_order = [qnum for qnum in cached_qnums if qnum in question_map]
                if randomize:
                    random.shuffle(cached_order)
                return [question_map[qnum] for qnum in cached_order]
        records = self._progress_questions()
        progress_history = self._progress_history()
        meta = self.progress_data.setdefault("meta", {})
        concept_graph = normalize_graph(meta.get("smart_practice_concept_graph"), pool)
        meta["smart_practice_concept_graph"] = concept_graph
        calibration_store = normalize_calibration_store(meta.get("smart_practice_question_calibration"))
        meta["smart_practice_question_calibration"] = calibration_store
        signal_cache_key = self._smart_practice_signal_key()
        pool_cache_key = (
            signal_cache_key,
            str(count),
            pool_qnums,
            bool(randomize),
        )
        cached_qnums = getattr(self, "smart_practice_pool_cache", {}).get(pool_cache_key)
        if cached_qnums is not None:
            question_map = {int(question.get("question_number") or 0): question for question in pool}
            cached_order = [qnum for qnum in cached_qnums if qnum in question_map]
            if randomize:
                random.shuffle(cached_order)
            return [question_map[qnum] for qnum in cached_order]
        signal_payload = getattr(self, "smart_practice_signal_cache_payload", None)
        if signal_cache_key != getattr(self, "smart_practice_signal_cache_key", None) or signal_payload is None:
            prewarm = getattr(self, "smart_practice_prewarm", None)
            if prewarm is not None:
                prewarm.invalidate()
            signal_payload = self._build_smart_practice_signal_payload()
            self.smart_practice_signal_cache_key = signal_cache_key
            self.smart_practice_signal_cache_payload = signal_payload

        source_map = signal_payload["source_map"]
        source_trust_map = signal_payload["source_trust_map"]
        gap_map = signal_payload["gap_map"]
        interference_rows = signal_payload["interference_rows"]
        objective_map = signal_payload["objective_map"]
        knowledge_trace_map = signal_payload["knowledge_trace_map"]
        concept_memory_map = signal_payload["concept_memory_map"]
        wrong_answer_memory_pressure_map = signal_payload["wrong_answer_memory_pressure_map"]
        wrong_answer_recycling_map = signal_payload["wrong_answer_recycling_map"]
        near_miss_unit_map = signal_payload["near_miss_unit_map"]
        near_miss_question_map = signal_payload["near_miss_question_map"]
        recognition_retrieval_map = signal_payload["recognition_retrieval_map"]
        confidence_compression_map = signal_payload["confidence_compression_map"]
        abstraction_ladder_map = signal_payload["abstraction_ladder_map"]
        decision_latency_map = signal_payload["decision_latency_map"]
        error_boundary_map = signal_payload["error_boundary_map"]
        counterfactual_pressure_map = signal_payload["counterfactual_pressure_map"]
        contrast_pressure_map = signal_payload["contrast_pressure_map"]
        prerequisite_debt_map = signal_payload["prerequisite_debt_map"]
        blind_spot_map = signal_payload["blind_spot_map"]
        misconception_pressure_map = signal_payload["misconception_pressure_map"]
        latent_map = signal_payload["latent_map"]
        transfer_map = signal_payload["transfer_map"]
        robustness_map = signal_payload["robustness_map"]
        generalization_map = signal_payload["generalization_map"]
        difficulty_map = signal_payload["difficulty_map"]
        phrasing_map = signal_payload["phrasing_map"]
        reinforcement_map = signal_payload["reinforcement_map"]
        synthesis_map = signal_payload["synthesis_map"]
        cue_dependence_map = signal_payload["cue_dependence_map"]
        delayed_probe_map = signal_payload["delayed_probe_map"]
        failure_mode_map = signal_payload["failure_mode_map"]
        expected_learning_gain_map = signal_payload["expected_learning_gain_map"]
        retention_stress_map = signal_payload["retention_stress_map"]
        concept_state_map = signal_payload["concept_state_map"]
        freshness_map = signal_payload["freshness_map"]
        recent_concept_cooldown_map = signal_payload["recent_concept_cooldown_map"]
        burnout_risk = signal_payload["burnout_risk"]
        momentum_profile = signal_payload["momentum_profile"]

        def interference_priority(question: QuestionRuntimeState) -> float:
            score = 0.0
            for row in interference_rows[:8]:
                if question_mentions_label(question, row["left"]) or question_mentions_label(question, row["right"]):
                    score = max(score, float(row["pressure"]))
            return score

        question_meta = {}
        objective_exposure_map = {}
        attempted_by_unit = {}
        attempted_by_objective = {}
        unseen_by_unit = {}
        unseen_by_objective = {}
        outcomes_by_qnum = {}
        for question in pool:
            qnum = int(question.get("question_number") or 0)
            kind, unit = coverage_unit_for_question(question)
            objective_code = str(question.get("objective_code") or "").strip()
            stem_style = stem_style_for_question(question)
            source_name = str(question.get("source_name") or "Unknown source")
            source_label = str(question.get("source_label") or "")
            normalized_domain = normalized_study_label(str(question.get("domain") or ""))
            normalized_topics = tuple(
                normalized_study_label(str(topic)) for topic in question.get("topics", []) if str(topic).strip()
            )
            record = records.get(self._question_key(question), {})
            attempts = int(record.get("attempts", 0) or 0)
            unit_key = f"{kind}::{unit}"
            base_concept_key = concept_key_for_question(question)[0]
            question_meta[qnum] = {
                "record": record,
                "unit_key": unit_key,
                "stem_style": stem_style,
                "objective_code": objective_code,
                "source_name": source_name,
                "source_label": source_label,
                "normalized_domain": normalized_domain,
                "normalized_topics": normalized_topics,
                "base_concept_key": base_concept_key,
            }
            if attempts > 0:
                attempted_by_unit[unit_key] = int(attempted_by_unit.get(unit_key, 0)) + 1
                if objective_code:
                    attempted_by_objective[objective_code] = int(attempted_by_objective.get(objective_code, 0)) + 1
            else:
                unseen_by_unit[unit_key] = int(unseen_by_unit.get(unit_key, 0)) + 1
                if objective_code:
                    unseen_by_objective[objective_code] = int(unseen_by_objective.get(objective_code, 0)) + 1
            if objective_code and attempts > 0:
                exposure = objective_exposure_map.setdefault(objective_code, {"sources": set(), "styles": set()})
                exposure["sources"].add(source_name)
                exposure["styles"].add(stem_style)
        for event in progress_history:
            qnum = int(event.get("question_number") or 0)
            outcomes_by_qnum.setdefault(qnum, []).append(event)
        interference_priority_map = {
            int(question.get("question_number") or 0): interference_priority(question) for question in pool
        }
        concept_keys = sorted(
            {
                str(meta.get("base_concept_key") or "")
                for meta in question_meta.values()
                if str(meta.get("base_concept_key") or "")
            }
        )
        concept_groups = {}
        for question in pool:
            qnum = int(question.get("question_number") or 0)
            concept_key = str(question_meta.get(qnum, {}).get("base_concept_key") or "")
            if concept_key:
                concept_groups.setdefault(concept_key, []).append(question)
        high_conf_wrong_by_concept = {}
        for event in progress_history:
            if event.get("correct") is False and str(event.get("confidence") or "") == "Sure":
                concept_key = str(event.get("smart_concept_key") or "")
                if concept_key:
                    high_conf_wrong_by_concept[concept_key] = int(high_conf_wrong_by_concept.get(concept_key, 0)) + 1
        concept_states = {}
        for concept_key in concept_keys:
            concept_questions = concept_groups.get(concept_key, [])
            per_question = []
            sources = set()
            styles = set()
            for question in concept_questions:
                qnum = int(question.get("question_number") or 0)
                rec = dict(question_meta.get(qnum, {}).get("record") or {})
                memory = dict(rec.get("learner_memory") or {})
                attempts = int(rec.get("attempts", 0) or 0)
                correct = int(rec.get("correct_count", 0) or 0)
                wrong = int(rec.get("wrong_count", 0) or 0)
                if attempts or correct or wrong:
                    per_question.append(
                        {
                            "retrievability": float(memory.get("retrievability", 0.35) or 0.35),
                            "stability": float(memory.get("stability", 0.0) or 0.0),
                            "uncertainty": float(memory.get("uncertainty", 0.65) or 0.65),
                            "attempts": attempts,
                            "correct": correct,
                            "wrong": wrong,
                            "last": str(memory.get("last_reviewed_at") or rec.get("last_seen") or ""),
                            "next": str(memory.get("next_review_at") or rec.get("next_review") or ""),
                        }
                    )
                if question.get("source_name") or question.get("source_label"):
                    sources.add(str(question.get("source_name") or question.get("source_label")))
                if question.get("stem_style"):
                    styles.add(str(question.get("stem_style")))
            if not per_question:
                concept_states[concept_key] = {
                    "concept_key": concept_key,
                    "stability": 0.0,
                    "lowest_retrievability": 0.0,
                    "mean_retrievability": 0.0,
                    "uncertainty": 1.0,
                    "attempt_count": 0,
                    "correct_count": 0,
                    "wrong_count": 0,
                    "high_confidence_wrong_count": int(high_conf_wrong_by_concept.get(concept_key, 0)),
                    "distinct_question_count": len(concept_questions),
                    "distinct_source_count": len(sources),
                    "distinct_stem_style_count": len(styles),
                    "last_reviewed_at": "",
                    "next_review_at": "",
                    "evidence_strength": "insufficient_evidence",
                }
                continue
            concept_states[concept_key] = {
                "concept_key": concept_key,
                "stability": round(sum(row["stability"] for row in per_question) / len(per_question), 4),
                "lowest_retrievability": round(min(row["retrievability"] for row in per_question), 4),
                "mean_retrievability": round(sum(row["retrievability"] for row in per_question) / len(per_question), 4),
                "uncertainty": round(sum(row["uncertainty"] for row in per_question) / len(per_question), 4),
                "attempt_count": sum(min(1, row["attempts"]) for row in per_question),
                "correct_count": sum(1 for row in per_question if row["correct"] > 0),
                "wrong_count": sum(1 for row in per_question if row["wrong"] > 0),
                "high_confidence_wrong_count": int(high_conf_wrong_by_concept.get(concept_key, 0)),
                "distinct_question_count": len(per_question),
                "distinct_source_count": len(sources),
                "distinct_stem_style_count": len(styles),
                "last_reviewed_at": max((row["last"] for row in per_question), default=""),
                "next_review_at": min((row["next"] for row in per_question if row["next"]), default=""),
                "evidence_strength": (
                    "strong" if len(per_question) >= 3 else "moderate" if len(per_question) >= 2 else "weak"
                ),
            }
        graph_audit = audit_graph(concept_graph, pool)
        normalized_source_trust_map = {
            str(key).strip().casefold(): value for key, value in (source_trust_map or {}).items()
        }
        dependent_concepts_by_source = {}
        for edge in (concept_graph.get("edges") or {}).values():
            if edge.get("status") != "active" or edge.get("edge_type") != "prerequisite_of":
                continue
            source_key = str(edge.get("source_concept_key") or "")
            target_key = str(edge.get("target_concept_key") or "")
            if source_key and target_key:
                dependent_concepts_by_source.setdefault(source_key, []).append(target_key)
        current_session_questions = list(getattr(self, "questions", []))
        session_context = {
            "seen_question_numbers": [int(q.get("question_number") or 0) for q in current_session_questions],
            "seen_concepts": [str(q.get("smart_concept_key") or "") for q in current_session_questions],
            "seen_stem_styles": [str(q.get("stem_style") or "") for q in current_session_questions],
            "seen_objectives": [str(q.get("objective_code") or "") for q in current_session_questions],
        }

        priority_cache: dict[int, float] = {}

        def is_screenshot_import(question: QuestionRuntimeState) -> bool:
            source_label = str(question.get("source_label") or "").lower()
            return "screenshot" in source_label or bool(question.get("source_image"))

        screenshot_total = 0
        screenshot_unseen = 0
        for question in pool:
            if not is_screenshot_import(question):
                continue
            rec = records.get(self._question_key(question), {})
            screenshot_total += 1
            if int(rec.get("attempts", 0)) <= 0:
                screenshot_unseen += 1
        imported_chapter_burst_active = (
            screenshot_total > 0
            and screenshot_unseen / max(1, screenshot_total) >= profile.imported_chapter_burst_unseen_min_ratio
        )

        score_context = {
            "profile": profile,
            "source_map": source_map,
            "source_trust_map": source_trust_map,
            "normalized_source_trust_map": normalized_source_trust_map,
            "graph_enabled": graph_enabled,
            "concept_graph": concept_graph,
            "concept_states": concept_states,
            "progress_history": progress_history,
            "active_smart_policy": active_smart_policy,
            "graph_max_utility": graph_max_utility,
            "outcomes_by_qnum": outcomes_by_qnum,
            "quality_min_samples": quality_min_samples,
            "bad_key_min_samples": bad_key_min_samples,
            "quality_enabled": quality_enabled,
            "dependent_concepts_by_source": dependent_concepts_by_source,
            "graph_audit": graph_audit,
            "session_context": session_context,
            "information_enabled": information_enabled,
            "info_max": info_max,
            "gap_map": gap_map,
            "transfer_map": transfer_map,
            "misconception_pressure_map": misconception_pressure_map,
            "knowledge_trace_map": knowledge_trace_map,
            "concept_memory_map": concept_memory_map,
            "wrong_answer_memory_pressure_map": wrong_answer_memory_pressure_map,
            "wrong_answer_recycling_map": wrong_answer_recycling_map,
            "near_miss_unit_map": near_miss_unit_map,
            "near_miss_question_map": near_miss_question_map,
            "confidence_compression_map": confidence_compression_map,
            "error_boundary_map": error_boundary_map,
            "counterfactual_pressure_map": counterfactual_pressure_map,
            "objective_map": objective_map,
            "latent_map": latent_map,
            "difficulty_map": difficulty_map,
            "phrasing_map": phrasing_map,
            "generalization_map": generalization_map,
            "expected_learning_gain_map": expected_learning_gain_map,
            "retention_stress_map": retention_stress_map,
            "freshness_map": freshness_map,
            "momentum_profile": momentum_profile,
            "source_risk_settings": source_risk_settings,
            "fatigue_settings": fatigue_settings,
            "review_interval_multiplier": review_interval_multiplier,
            "utility_scales": utility_scales,
            "utility_bounds": utility_bounds,
            "quality_risk_max": quality_risk_max,
            "burnout_risk": burnout_risk,
            "repetition_settings": repetition_settings,
            "recent_concept_cooldown_map": recent_concept_cooldown_map,
            "weakness_thresholds": weakness_thresholds,
            "unseen_by_unit": unseen_by_unit,
            "unseen_by_objective": unseen_by_objective,
            "repair_spacing_settings": repair_spacing_settings,
            "repair_trigger_settings": repair_trigger_settings,
            "role_shares": role_shares,
            "prediction_calibration": prediction_calibration,
            "exploration_settings": exploration_settings,
            "active_policy_values": active_policy_values,
            "attempted_by_unit": attempted_by_unit,
            "attempted_by_objective": attempted_by_objective,
            "objective_exposure_map": objective_exposure_map,
            "imported_chapter_burst_active": imported_chapter_burst_active,
        }

        def smart_priority(question: QuestionRuntimeState) -> float:
            qnum = int(question.get("question_number") or 0)
            if qnum in priority_cache:
                return priority_cache[qnum]
            meta = question_meta.get(qnum, {})
            score_result = build_smart_practice_score(question, qnum=qnum, meta=meta, context=score_context)
            question.update(score_result.question_updates)
            calibration_store.setdefault("question_quality", {})[str(qnum)] = score_result.question_quality
            info_entry = score_result.information_history_entry
            calibration_store.setdefault("information_value_history", {})[info_entry["record_id"]] = info_entry
            self.progress_data.setdefault("meta", {})["smart_practice_question_calibration"] = calibration_store
            if graph_enabled and question["smart_root_cause"] != "insufficient_evidence":
                stored_graph = store_diagnosis(
                    self.progress_data.setdefault("meta", {}).get("smart_practice_concept_graph"),
                    score_result.diagnosis,
                )
                self.progress_data.setdefault("meta", {})["smart_practice_concept_graph"] = stored_graph
            priority_cache[qnum] = score_result.priority
            return priority_cache[qnum]

        unseen = [
            q
            for q in pool
            if int((question_meta.get(int(q.get("question_number") or 0), {}).get("record") or {}).get("attempts", 0))
            <= 0
        ]
        active_weak = [
            q
            for q in pool
            if is_active_weak(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
        ]
        due = select_due_review_questions(pool, records)
        recovered = [
            q
            for q in pool
            if is_ever_wrong(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
            and not is_active_weak(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
        ]
        screenshot_focus = [
            q
            for q in pool
            if is_screenshot_import(q) and str(q.get("import_status") or "") != "screenshot_review_needed"
        ]
        coverage_focus = [
            q
            for q in pool
            if gap_map.get(str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or ""), 0.0)
            >= profile.coverage_focus_gap_min
        ]
        objective_focus = [
            q
            for q in pool
            if str(question_meta.get(int(q.get("question_number") or 0), {}).get("objective_code") or "")
            and (
                float(
                    (
                        objective_map.get(
                            str(question_meta.get(int(q.get("question_number") or 0), {}).get("objective_code") or "")
                        )
                        or {}
                    ).get("mastery_score", 100.0)
                )
                < profile.objective_focus_mastery_max
                or int(
                    (
                        objective_map.get(
                            str(question_meta.get(int(q.get("question_number") or 0), {}).get("objective_code") or "")
                        )
                        or {}
                    ).get("stem_style_count", 2)
                )
                <= profile.objective_focus_stem_count_max
            )
        ]
        interference_focus = [
            q
            for q in pool
            if float(interference_priority_map.get(int(q.get("question_number") or 0), 0.0))
            >= profile.interference_focus_min
        ]
        compression_focus = [
            q
            for q in pool
            if float(
                (
                    confidence_compression_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("compression", 0.0)
            )
            >= profile.compression_focus_min
        ]
        ladder_focus = [
            q
            for q in pool
            if float(
                (
                    abstraction_ladder_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("score", 100.0)
            )
            < profile.ladder_focus_score_max
        ]
        boundary_focus = [
            q
            for q in pool
            if (
                float(
                    (
                        error_boundary_map.get(
                            str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                        )
                        or {}
                    ).get("gap", 0.0)
                )
                >= profile.boundary_focus_gap_min
                and str(
                    (
                        error_boundary_map.get(
                            str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                        )
                        or {}
                    ).get("weak_style", "")
                )
                == str(question_meta.get(int(q.get("question_number") or 0), {}).get("stem_style") or "")
            )
        ]
        counterfactual_focus = [
            q
            for q in pool
            if float(
                counterfactual_pressure_map.get(
                    str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or ""), 0.0
                )
            )
            >= profile.counterfactual_focus_min
        ]
        prerequisite_focus = [
            q
            for q in pool
            if float(
                (
                    prerequisite_debt_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("severity", 0.0)
            )
            >= profile.prerequisite_focus_min
        ]
        blind_spot_focus = [
            q
            for q in pool
            if float(
                (
                    blind_spot_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("severity", 0.0)
            )
            >= profile.blind_spot_focus_min
        ]
        robustness_focus = [
            q
            for q in pool
            if float(
                (
                    robustness_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("score", 100.0)
            )
            <= profile.robustness_focus_max
        ]
        reinforcement_focus = [
            q
            for q in pool
            if float((reinforcement_map.get(int(q.get("question_number") or 0)) or {}).get("priority", 0.0))
            >= profile.reinforcement_focus_min
        ]
        synthesis_focus = [
            q
            for q in pool
            if float((synthesis_map.get(int(q.get("question_number") or 0)) or {}).get("score", 0.0))
            >= profile.synthesis_focus_min
        ]
        knowledge_trace_focus = [
            q
            for q in pool
            if (
                float(
                    (
                        knowledge_trace_map.get(
                            str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                        )
                        or {}
                    ).get("mastery_prob", 100.0)
                )
                <= profile.knowledge_trace_focus_max
                or float(
                    (
                        knowledge_trace_map.get(
                            str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                        )
                        or {}
                    ).get("uncertainty", 0.0)
                )
                >= profile.uncertainty_focus_min
            )
        ]
        learning_gain_focus = [
            q
            for q in pool
            if float(
                (expected_learning_gain_map.get(int(q.get("question_number") or 0)) or {}).get("expected_gain", 0.0)
            )
            >= profile.learning_gain_focus_min
        ]
        delayed_probe_focus = [
            q
            for q in pool
            if float((delayed_probe_map.get(int(q.get("question_number") or 0)) or {}).get("pressure", 0.0))
            >= profile.delayed_probe_focus_min
        ]
        cue_dependence_focus = [
            q
            for q in pool
            if float((cue_dependence_map.get(int(q.get("question_number") or 0)) or {}).get("score", 0.0))
            >= profile.cue_dependence_focus_min
        ]
        recognition_focus = [
            q
            for q in pool
            if float(
                (
                    recognition_retrieval_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("gap", 0.0)
            )
            >= profile.recognition_gap_focus_min
        ]
        retention_stress_focus = [
            q
            for q in pool
            if float((retention_stress_map.get(int(q.get("question_number") or 0)) or {}).get("pressure", 0.0))
            >= profile.retention_stress_focus_min
        ]
        failure_mode_focus = [
            q
            for q in pool
            if float(
                (
                    failure_mode_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("pressure", 0.0)
            )
            >= profile.failure_mode_focus_min
        ]
        generalization_focus = [
            q
            for q in pool
            if float(
                (
                    generalization_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("score", 100.0)
            )
            <= profile.generalization_focus_max
        ]
        decision_latency_focus = [
            q
            for q in pool
            if float(
                (
                    decision_latency_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("drag", 0.0)
            )
            >= profile.decision_latency_focus_min
        ]
        contrast_rule_focus = [
            q
            for q in pool
            if float(
                contrast_pressure_map.get(
                    str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or ""), 0.0
                )
            )
            >= profile.contrast_rule_focus_min
        ]
        concept_state_focus = [
            q
            for q in pool
            if str(
                (
                    concept_state_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or "")
                    )
                    or {}
                ).get("state", "stable")
            )
            in profile.concept_state_focus_states
        ]
        wrong_recycle_focus = [
            q
            for q in pool
            if float(wrong_answer_recycling_map.get(int(q.get("question_number") or 0), 0.0))
            >= profile.wrong_answer_recycle_focus_min
        ]
        near_miss_focus = [
            q
            for q in pool
            if max(
                float(
                    near_miss_unit_map.get(
                        str(question_meta.get(int(q.get("question_number") or 0), {}).get("unit_key") or ""), 0.0
                    )
                ),
                float(near_miss_question_map.get(int(q.get("question_number") or 0), 0.0)),
            )
            >= profile.near_miss_focus_min
        ]
        target = len(pool)
        if count != "All visible":
            try:
                target = min(int(count), len(pool))
            except Exception:
                target = len(pool)
        if target <= 0:
            return []

        super_confident_qnums = {
            q.get("question_number")
            for q in pool
            if is_super_confident_active(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
            and not is_active_weak(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
            and not is_review_due(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
        }
        freshness_suppressed_qnums = {
            q.get("question_number")
            for q in pool
            if float(freshness_map.get(int(q.get("question_number") or 0), 0.0)) >= profile.freshness_suppression_min
            and not is_active_weak(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
            and not is_review_due(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
        }
        suppressed_qnums = super_confident_qnums | freshness_suppressed_qnums
        non_super_count = len(pool) - len(super_confident_qnums)
        available_count = len(pool) - len(suppressed_qnums)
        if super_confident_qnums and non_super_count >= max(1, target):
            working_pool = [q for q in pool if q.get("question_number") not in super_confident_qnums]
        elif available_count >= max(1, target):
            working_pool = [q for q in pool if q.get("question_number") not in suppressed_qnums]
        else:
            working_pool = list(pool)

        working_qnums = {int(question.get("question_number") or 0) for question in working_pool}

        def in_working_set(question: QuestionRuntimeState) -> bool:
            return int(question.get("question_number") or 0) in working_qnums

        groups = [
            [q for q in group if in_working_set(q)]
            for group in [
                unseen,
                active_weak,
                due,
                recovered,
                screenshot_focus,
                coverage_focus,
                objective_focus,
                interference_focus,
                compression_focus,
                ladder_focus,
                boundary_focus,
                counterfactual_focus,
                prerequisite_focus,
                blind_spot_focus,
                robustness_focus,
                reinforcement_focus,
                synthesis_focus,
                knowledge_trace_focus,
                learning_gain_focus,
                delayed_probe_focus,
                cue_dependence_focus,
                recognition_focus,
                retention_stress_focus,
                failure_mode_focus,
                generalization_focus,
                decision_latency_focus,
                contrast_rule_focus,
                concept_state_focus,
                wrong_recycle_focus,
                near_miss_focus,
            ]
        ]
        (
            unseen,
            active_weak,
            due,
            recovered,
            screenshot_focus,
            coverage_focus,
            objective_focus,
            interference_focus,
            compression_focus,
            ladder_focus,
            boundary_focus,
            counterfactual_focus,
            prerequisite_focus,
            blind_spot_focus,
            robustness_focus,
            reinforcement_focus,
            synthesis_focus,
            knowledge_trace_focus,
            learning_gain_focus,
            delayed_probe_focus,
            cue_dependence_focus,
            recognition_focus,
            retention_stress_focus,
            failure_mode_focus,
            generalization_focus,
            decision_latency_focus,
            contrast_rule_focus,
            concept_state_focus,
            wrong_recycle_focus,
            near_miss_focus,
        ) = groups
        for group in groups:
            if randomize:
                random.shuffle(group)
            initial_order = {int(item.get("question_number") or 0): idx for idx, item in enumerate(group)}
            group.sort(
                key=lambda item: (
                    smart_priority(item),
                    -initial_order.get(int(item.get("question_number") or 0), 0),
                ),
                reverse=True,
            )

        objective_cap = smart_practice_objective_cap(target, profile)

        fallback = []
        for group in (
            screenshot_focus,
            active_weak,
            due,
            prerequisite_focus,
            blind_spot_focus,
            knowledge_trace_focus,
            learning_gain_focus,
            delayed_probe_focus,
            cue_dependence_focus,
            recognition_focus,
            failure_mode_focus,
            retention_stress_focus,
            generalization_focus,
            decision_latency_focus,
            contrast_rule_focus,
            concept_state_focus,
            reinforcement_focus,
            coverage_focus,
            objective_focus,
            robustness_focus,
            synthesis_focus,
            interference_focus,
            compression_focus,
            ladder_focus,
            boundary_focus,
            counterfactual_focus,
            unseen,
            recovered,
            working_pool,
        ):
            fallback.extend(group)

        def selection_priority_bonus(question: QuestionRuntimeState) -> float:
            qnum = int(question.get("question_number") or 0)
            attempts = int((question_meta.get(qnum, {}).get("record") or {}).get("attempts", 0) or 0)
            if attempts > 0:
                return 0.0
            bonus = 0.0
            if question in screenshot_focus:
                bonus += 10.0
            if question in coverage_focus:
                bonus += 8.0
            if question in objective_focus:
                bonus += 8.0
            if question in wrong_recycle_focus:
                bonus += 18.0
            return bonus

        candidate_cache: dict[int, SmartPracticeCandidate] = {}

        def build_candidate(question: QuestionRuntimeState) -> SmartPracticeCandidate:
            qnum = int(question.get("question_number") or 0)
            cached = candidate_cache.get(qnum)
            if cached is not None:
                return cached
            smart_priority(question)
            meta = question_meta.get(qnum, {})
            candidate = SmartPracticeCandidate(
                question=question,
                qnum=qnum,
                priority=float(priority_cache.get(qnum, 0.0)),
                selection_bonus=selection_priority_bonus(question),
                primary_role=str(question.get("smart_primary_role") or "blueprint_coverage"),
                objective_code=str(meta.get("objective_code") or ""),
                source_label=str(
                    question.get("source_label") or question.get("source_name") or "Unknown source"
                ).strip(),
                primary_topic=primary_topic_label(question),
                normalized_domain=normalized_study_label(str(question.get("domain") or "")),
                raw_domain=str(question.get("domain") or "").strip(),
            )
            candidate_cache[qnum] = candidate
            return candidate

        high_signal_qnums = {
            int(question.get("question_number") or 0)
            for question in (active_weak + due)
            if int(question.get("question_number") or 0)
        }
        selection_result = build_smart_practice_selection(
            [build_candidate(question) for question in working_pool],
            [build_candidate(question) for question in fallback],
            target=target,
            role_shares=role_shares,
            objective_cap=objective_cap,
            profile=profile,
            high_signal_qnums=high_signal_qnums,
            freshness_map=freshness_map,
        )
        ordered = list(selection_result.ordered_questions)
        role_seed = list(selection_result.role_seed_questions)
        self.last_smart_practice_set_quality = {
            "score": selection_result.quality_score,
            "retry_used": selection_result.retry_used,
        }

        def protected_role_counts(selection: list[QuestionRuntimeState]) -> dict[str, int]:
            counts = {"weak_repair": 0, "due_retention": 0, "blueprint_coverage": 0}
            for question in selection:
                role = str(question.get("smart_primary_role") or "")
                if role in counts:
                    counts[role] += 1
            return counts

        def preserves_protected_roles(
            candidate: list[QuestionRuntimeState], baseline: list[QuestionRuntimeState]
        ) -> bool:
            candidate_counts = protected_role_counts(candidate)
            baseline_counts = protected_role_counts(baseline)
            return all(candidate_counts[role] >= baseline_counts[role] for role in baseline_counts)

        def final_selection(selection: list[QuestionRuntimeState]) -> list[QuestionRuntimeState]:
            result = self._interleave_questions(selection[:target])
            if not preserves_protected_roles(result, role_seed):
                result = self._interleave_questions(role_seed[:target])
            measurement = normalize_measurement_store(
                self.progress_data.setdefault("meta", {}).get("smart_practice_measurement")
            )
            for question in result:
                if not question.get("smart_primary_role"):
                    smart_priority(question)
                record = records.get(self._question_key(question), {})
                attach_prediction_to_question(question, measurement, record)
            self.progress_data.setdefault("meta", {})["smart_practice_measurement"] = measurement
            final_signal_key = self._smart_practice_signal_key()
            self.smart_practice_signal_cache_key = final_signal_key
            self.smart_practice_pool_cache[(final_signal_key, str(count), pool_qnums, bool(randomize))] = tuple(
                int(question.get("question_number") or 0) for question in result
            )
            return result[:target]

        if not randomize:
            result = final_selection(ordered)
            return result

        mixed = list(ordered[:target])
        random.shuffle(mixed)
        return final_selection(mixed)
