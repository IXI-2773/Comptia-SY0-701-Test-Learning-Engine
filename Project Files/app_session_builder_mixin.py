from tkinter import messagebox

import random
import threading

from app_constants import MODE_EXAM, MODE_PRACTICE, MODE_SMART_PRACTICE
from progress_store import (
    is_active_weak,
    is_ever_wrong,
    is_review_due,
    is_suspended,
    select_due_review_questions,
    select_questions_by_history,
)
from session_models import QuestionRuntimeState, reset_runtime_question_state
from smart_practice_profile import (
    SMART_PRACTICE_SCORING,
    smart_practice_objective_cap,
    smart_practice_quota_profile,
)


class SessionBuilderMixin:
    def _smart_practice_signal_key(self):
        session_answer_key = tuple(
            (
                int(event.get("question_number") or 0),
                bool(event.get("correct")),
                str(event.get("confidence") or ""),
                str(event.get("miss_reason") or ""),
            )
            for event in (self.session_answer_history or [])
        )
        return self._analytics_signature(), session_answer_key

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
        _wrong_answer_memory_rows, wrong_answer_memory_pressure_map = self._build_wrong_answer_memory_rows(
            recent_history, signal_questions
        )
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
        return {
            "source_map": source_map,
            "source_trust_map": source_trust_map,
            "gap_map": gap_map,
            "interference_rows": interference_rows,
            "objective_map": objective_map,
            "knowledge_trace_map": knowledge_trace_map,
            "concept_memory_map": concept_memory_map,
            "wrong_answer_memory_pressure_map": wrong_answer_memory_pressure_map,
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
        }

    def _publish_smart_practice_signal_snapshot(self, snapshot) -> None:
        if snapshot["key"] != self._smart_practice_signal_key():
            return
        self.smart_practice_signal_cache_key = snapshot["key"]
        self.smart_practice_signal_cache_payload = snapshot["payload"]

    def schedule_smart_practice_prewarm(self, delay_ms=None) -> None:
        if not self.master_questions or not getattr(self, "smart_practice_prewarm", None):
            return
        key = self._smart_practice_signal_key()
        self.smart_practice_prewarm.schedule(
            key,
            self._build_smart_practice_signal_payload,
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

    def _start_smart_practice_async(self, count, randomize, base_pool, *, preserve_if_saved=True, builder_context=None) -> None:
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

        def worker():
            error = None
            pool = []
            try:
                pool = self._build_smart_practice_pool_compat(count, randomize=randomize, base_pool=base_pool)
            except Exception as exc:
                error = exc

            def finish():
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
            prev_topic = self._primary_topic_label(prev)
            prev_objective = str(prev.get("objective_code") or "").strip()
            prev_source = str(prev.get("source_name") or "")
            prev_source_label = source_label(prev)
            prev_stem = self._stem_style_for_question(prev)
            recent = ordered[-3:]
            recent_topics = {self._primary_topic_label(item) for item in recent}
            recent_source_labels = {source_label(item) for item in recent}
            best_idx = 0
            best_score = None
            for idx, candidate in enumerate(remaining):
                score = 0.0
                if str(candidate.get("domain") or "") != prev_domain:
                    score += 4.0
                if self._primary_topic_label(candidate) != prev_topic:
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
                if self._stem_style_for_question(candidate) != prev_stem:
                    score += 2.5
                if self._primary_topic_label(candidate) in recent_topics:
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
            pool = [q for q in pool if q.get("domain") == domain]
        if topic and topic != "All topics":
            pool = [q for q in pool if topic in [str(t).strip() for t in q.get("topics", [])]]
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
        pool = list(base_pool) if base_pool is not None else self.get_filtered_master_pool()
        if not pool:
            return []
        records = self._progress_questions()
        signal_cache_key = self._smart_practice_signal_key()
        signal_payload = getattr(self, "smart_practice_signal_cache_payload", None)
        if signal_cache_key != getattr(self, "smart_practice_signal_cache_key", None) or signal_payload is None:
            prewarm = getattr(self, "smart_practice_prewarm", None)
            if prewarm is not None:
                prewarm.invalidate()
            signal_payload = self._build_smart_practice_signal_payload()
            self.smart_practice_signal_cache_key = signal_cache_key
            self.smart_practice_signal_cache_payload = signal_payload
        pool_cache_key = None
        if not randomize:
            pool_cache_key = (
                signal_cache_key,
                str(count),
                tuple(int(question.get("question_number") or 0) for question in pool),
            )
            cached_qnums = getattr(self, "smart_practice_pool_cache", {}).get(pool_cache_key)
            if cached_qnums is not None:
                question_map = {int(question.get("question_number") or 0): question for question in pool}
                return [question_map[qnum] for qnum in cached_qnums if qnum in question_map]

        source_map = signal_payload["source_map"]
        source_trust_map = signal_payload["source_trust_map"]
        gap_map = signal_payload["gap_map"]
        interference_rows = signal_payload["interference_rows"]
        objective_map = signal_payload["objective_map"]
        knowledge_trace_map = signal_payload["knowledge_trace_map"]
        concept_memory_map = signal_payload["concept_memory_map"]
        wrong_answer_memory_pressure_map = signal_payload["wrong_answer_memory_pressure_map"]
        recognition_retrieval_map = signal_payload["recognition_retrieval_map"]
        confidence_compression_map = signal_payload["confidence_compression_map"]
        abstraction_ladder_map = signal_payload["abstraction_ladder_map"]
        compression_point_map = signal_payload["compression_point_map"]
        decision_latency_map = signal_payload["decision_latency_map"]
        error_boundary_map = signal_payload["error_boundary_map"]
        counterfactual_pressure_map = signal_payload["counterfactual_pressure_map"]
        contrast_pressure_map = signal_payload["contrast_pressure_map"]
        prerequisite_debt_map = signal_payload["prerequisite_debt_map"]
        concept_half_life_map = signal_payload["concept_half_life_map"]
        leverage_map = signal_payload["leverage_map"]
        blind_spot_map = signal_payload["blind_spot_map"]
        misconception_pressure_map = signal_payload["misconception_pressure_map"]
        latent_map = signal_payload["latent_map"]
        transfer_map = signal_payload["transfer_map"]
        robustness_map = signal_payload["robustness_map"]
        generalization_map = signal_payload["generalization_map"]
        difficulty_map = signal_payload["difficulty_map"]
        phrasing_map = signal_payload["phrasing_map"]
        effort_efficiency_map = signal_payload["effort_efficiency_map"]
        reinforcement_map = signal_payload["reinforcement_map"]
        synthesis_map = signal_payload["synthesis_map"]
        cue_dependence_map = signal_payload["cue_dependence_map"]
        delayed_probe_map = signal_payload["delayed_probe_map"]
        counterexample_training_map = signal_payload["counterexample_training_map"]
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
                if self._question_mentions_label(question, row["left"]) or self._question_mentions_label(
                    question, row["right"]
                ):
                    score = max(score, float(row["pressure"]))
            return score

        question_meta = {}
        objective_exposure_map = {}
        for question in pool:
            qnum = int(question.get("question_number") or 0)
            kind, unit = self._coverage_unit_for_question(question)
            objective_code = str(question.get("objective_code") or "").strip()
            stem_style = self._stem_style_for_question(question)
            source_name = str(question.get("source_name") or "Unknown source")
            source_label = str(question.get("source_label") or "")
            record = records.get(self._question_key(question), {})
            question_meta[qnum] = {
                "record": record,
                "unit_key": f"{kind}::{unit}",
                "stem_style": stem_style,
                "objective_code": objective_code,
                "source_name": source_name,
                "source_label": source_label,
            }
            if objective_code and int(record.get("attempts", 0)) > 0:
                exposure = objective_exposure_map.setdefault(objective_code, {"sources": set(), "styles": set()})
                exposure["sources"].add(source_name)
                exposure["styles"].add(stem_style)
        interference_priority_map = {
            int(question.get("question_number") or 0): interference_priority(question) for question in pool
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

        def smart_priority(question: QuestionRuntimeState) -> float:
            qnum = int(question.get("question_number") or 0)
            if qnum in priority_cache:
                return priority_cache[qnum]
            meta = question_meta.get(qnum, {})
            rec = meta.get("record", {})
            source_row = source_map.get(qnum, {"score": 0.8, "label": "Single-source only"})
            source_trust = source_trust_map.get(
                str(meta.get("source_name") or "Unknown source"), {"trust_score": 82.0, "label": "Watch"}
            )
            unit_key = str(meta.get("unit_key") or "")
            gap_score = float(gap_map.get(unit_key, 0.0))
            transfer_row = transfer_map.get(unit_key, {"score": 72.0})
            prerequisite_row = prerequisite_debt_map.get(unit_key, {"severity": 0.0})
            half_life_row = concept_half_life_map.get(unit_key, {"half_life_days": profile.half_life_target_days})
            blind_spot_row = blind_spot_map.get(unit_key, {"severity": 0.0})
            robustness_row = robustness_map.get(unit_key, {"score": profile.robustness_baseline})
            leverage_row = leverage_map.get(unit_key, {"leverage": 0.0})
            misconception_pressure = float(misconception_pressure_map.get(unit_key, 0.0))
            knowledge_row = knowledge_trace_map.get(
                unit_key, {"mastery_prob": profile.knowledge_trace_baseline, "uncertainty": 50.0}
            )
            concept_memory_row = concept_memory_map.get(
                unit_key, {"state": "new", "next_ramp": "recognition", "durability_signal": 0.0}
            )
            wrong_memory_pressure = float(wrong_answer_memory_pressure_map.get(unit_key, 0.0))
            recognition_row = recognition_retrieval_map.get(unit_key, {"gap": 0.0})
            compression_row = confidence_compression_map.get(unit_key, {"compression": 0.0})
            compression_point_row = compression_point_map.get(unit_key, {"gap": 0.0})
            ladder_row = abstraction_ladder_map.get(
                unit_key, {"score": 72.0, "rung_count": 1, "available_style_count": 1}
            )
            boundary_row = error_boundary_map.get(unit_key, {"gap": 0.0, "weak_style": ""})
            counterfactual_pressure = float(counterfactual_pressure_map.get(unit_key, 0.0))
            contrast_pressure = float(contrast_pressure_map.get(unit_key, 0.0))
            objective_row = objective_map.get(
                str(meta.get("objective_code") or ""), {"mastery_score": 72.0, "stem_style_count": 1}
            )
            latent_row = latent_map.get(qnum, {"score": 0.0})
            difficulty_row = difficulty_map.get(qnum, {"score": 0.0, "label": "Stable"})
            phrasing_row = phrasing_map.get(qnum, {"score": 100.0, "label": "Clean"})
            effort_row = effort_efficiency_map.get(unit_key, {"score": profile.effort_efficiency_baseline})
            reinforcement_row = reinforcement_map.get(qnum, {"priority": 0.0})
            synthesis_row = synthesis_map.get(qnum, {"score": 0.0})
            generalization_row = generalization_map.get(unit_key, {"score": profile.generalization_baseline})
            cue_row = cue_dependence_map.get(qnum, {"score": 0.0})
            delayed_probe_row = delayed_probe_map.get(qnum, {"pressure": 0.0})
            counterexample_row = counterexample_training_map.get(qnum, {"pressure": 0.0})
            failure_mode_row = failure_mode_map.get(unit_key, {"pressure": 0.0})
            expected_gain_row = expected_learning_gain_map.get(qnum, {"expected_gain": 0.0})
            retention_stress_row = retention_stress_map.get(qnum, {"pressure": 0.0})
            concept_state_row = concept_state_map.get(unit_key, {"state": "stable"})
            latency_row = decision_latency_map.get(unit_key, {"drag": 0.0})
            freshness_penalty = float(freshness_map.get(qnum, 0.0))
            interference_score = float(interference_priority_map.get(qnum, 0.0))
            difficulty_score = float(difficulty_row.get("score", 0.0))
            phrasing_penalty = max(0.0, 82.0 - float(phrasing_row.get("score", 100.0)))
            momentum_bias = float(momentum_profile.get("difficulty_bias", 0.0))
            score = gap_score * profile.gap_weight
            score += float(source_row.get("score", 0.8)) * profile.source_score_weight
            score += (
                max(0.0, profile.source_trust_baseline - float(source_trust.get("trust_score", 82.0)))
                * profile.source_trust_penalty_weight
            )
            score += (
                max(0.0, profile.transfer_baseline - float(transfer_row.get("score", 72.0))) * profile.transfer_weight
            )
            score += float(prerequisite_row.get("severity", 0.0)) * profile.prerequisite_debt_weight
            score += float(blind_spot_row.get("severity", 0.0)) * profile.blind_spot_weight
            score += (
                max(0.0, profile.robustness_baseline - float(robustness_row.get("score", profile.robustness_baseline)))
                * profile.robustness_weight
            )
            score += float(leverage_row.get("leverage", 0.0)) * profile.leverage_weight
            score += float(misconception_pressure) * profile.misconception_weight
            score += (
                max(
                    0.0,
                    profile.half_life_target_days
                    - float(half_life_row.get("half_life_days", profile.half_life_target_days)),
                )
                * profile.half_life_weight
            )
            score += (
                max(
                    0.0,
                    profile.effort_efficiency_baseline
                    - float(effort_row.get("score", profile.effort_efficiency_baseline)),
                )
                * profile.effort_efficiency_weight
            )
            score += float(reinforcement_row.get("priority", 0.0)) * profile.reinforcement_priority_weight
            score += float(synthesis_row.get("score", 0.0)) * profile.synthesis_weight
            score += (
                max(
                    0.0,
                    profile.knowledge_trace_baseline
                    - float(knowledge_row.get("mastery_prob", profile.knowledge_trace_baseline)),
                )
                * profile.knowledge_trace_weight
            )
            score += float(knowledge_row.get("uncertainty", 0.0)) * profile.knowledge_uncertainty_weight
            memory_state = str(concept_memory_row.get("state") or "new")
            if memory_state == "recognizable":
                score += profile.concept_memory_weight * 32.0
            elif memory_state == "retrievable":
                score += profile.concept_memory_weight * 24.0
            elif memory_state == "transferable":
                score += profile.concept_memory_weight * 12.0
            elif (
                memory_state == "durable"
                and not is_review_due(rec)
                and float(retention_stress_row.get("pressure", 0.0)) <= 0
            ):
                score -= profile.durable_memory_penalty
            score += wrong_memory_pressure * profile.wrong_answer_memory_weight
            score += float(expected_gain_row.get("expected_gain", 0.0)) * profile.learning_gain_weight
            score += float(compression_row.get("compression", 0.0)) * profile.compression_weight
            score += float(compression_point_row.get("gap", 0.0)) * (profile.compression_weight * 0.5)
            score += max(0.0, profile.ladder_baseline - float(ladder_row.get("score", 72.0))) * profile.ladder_weight
            if int(ladder_row.get("rung_count", 1)) < int(ladder_row.get("available_style_count", 1)):
                score += profile.ladder_missing_rung_bonus
            score += float(boundary_row.get("gap", 0.0)) * profile.boundary_weight
            if str(boundary_row.get("weak_style") or "") == str(meta.get("stem_style") or ""):
                score += profile.boundary_style_bonus
            score += counterfactual_pressure * profile.counterfactual_weight
            score += float(counterexample_row.get("pressure", 0.0)) * profile.counterexample_weight
            score += float(contrast_pressure) * profile.contrast_rule_weight
            score += float(recognition_row.get("gap", 0.0)) * profile.recognition_gap_weight
            score += float(cue_row.get("score", 0.0)) * profile.cue_dependence_weight
            score += float(delayed_probe_row.get("pressure", 0.0)) * profile.delayed_probe_weight
            score += float(retention_stress_row.get("pressure", 0.0)) * profile.retention_stress_weight
            score += float(failure_mode_row.get("pressure", 0.0)) * profile.failure_mode_weight
            score += float(latency_row.get("drag", 0.0)) * profile.decision_latency_weight
            score += (
                max(
                    0.0,
                    profile.generalization_baseline
                    - float(generalization_row.get("score", profile.generalization_baseline)),
                )
                * profile.generalization_weight
            )
            if str(concept_state_row.get("state") or "stable") in profile.concept_state_focus_states:
                score += profile.concept_state_weight * 24.0
            score += (
                max(0.0, profile.objective_mastery_baseline - float(objective_row.get("mastery_score", 72.0)))
                * profile.objective_mastery_weight
            )
            if int(objective_row.get("stem_style_count", 1)) <= 1:
                score += profile.objective_stem_bonus
            objective_exposure = objective_exposure_map.get(
                str(meta.get("objective_code") or ""), {"sources": set(), "styles": set()}
            )
            if (
                int(rec.get("attempts", 0)) <= 0
                and float(objective_row.get("mastery_score", 100.0)) < profile.objective_mastery_baseline
            ):
                if str(meta.get("source_name") or "") not in objective_exposure.get("sources", set()):
                    score += profile.objective_new_source_bonus
                if str(meta.get("stem_style") or "") not in objective_exposure.get("styles", set()):
                    score += profile.objective_new_style_bonus
            score += float(latent_row.get("score", 0.0)) * profile.latent_weight
            score += interference_score * profile.interference_weight
            score += difficulty_score * (
                profile.difficulty_weight_positive if momentum_bias >= 0 else profile.difficulty_weight_negative
            )
            if source_row.get("label") == "Cross-source agreement":
                score += profile.source_agreement_bonus
            elif source_row.get("label") == "Cross-source supported":
                score += profile.source_supported_bonus
            elif source_row.get("label") == "Source conflict":
                score -= profile.source_conflict_penalty
            if source_trust.get("label") == "Decayed":
                score -= profile.source_decayed_penalty
            if str(phrasing_row.get("label") or "") == "Noisy":
                score -= profile.noisy_phrasing_penalty
            score -= phrasing_penalty * profile.phrasing_penalty_weight
            score -= freshness_penalty * profile.freshness_penalty_weight
            if momentum_bias < 0:
                score -= (
                    max(0.0, difficulty_score - profile.negative_momentum_difficulty_floor)
                    * profile.negative_momentum_difficulty_weight
                )
            elif momentum_bias > 0:
                score += (
                    max(0.0, difficulty_score - profile.positive_momentum_difficulty_floor)
                    * profile.positive_momentum_difficulty_weight
                )
            if burnout_risk.get("label") == "High":
                score -= (
                    max(0.0, difficulty_score - profile.burnout_difficulty_floor) * profile.burnout_difficulty_weight
                )
            if is_active_weak(rec):
                score += profile.active_weak_bonus
            if is_review_due(rec):
                score += profile.due_bonus
            if int(rec.get("attempts", 0)) <= 0:
                score += profile.unseen_bonus
            if is_screenshot_import(question):
                score += profile.screenshot_source_priority_bonus
                if int(rec.get("attempts", 0)) <= 0:
                    score += profile.screenshot_unseen_priority_bonus
                    if imported_chapter_burst_active:
                        score += profile.imported_chapter_burst_bonus
            concept_recent_count = int(recent_concept_cooldown_map.get(unit_key, 0) or 0)
            if (
                concept_recent_count >= profile.recent_concept_cooldown_min_count
                and not is_active_weak(rec)
                and not is_review_due(rec)
            ):
                score -= (
                    concept_recent_count
                    - profile.recent_concept_cooldown_min_count
                    + 1
                ) * profile.recent_concept_cooldown_penalty
            score -= int(rec.get("correct_streak", 0)) * profile.correct_streak_penalty
            priority_cache[qnum] = round(score, 3)
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
            q for q in pool if is_screenshot_import(q) and str(q.get("import_status") or "") != "screenshot_review_needed"
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
        target = len(pool)
        if count != "All visible":
            try:
                target = min(int(count), len(pool))
            except Exception:
                target = len(pool)
        if target <= 0:
            return []

        suppressed_qnums = {
            q.get("question_number")
            for q in pool
            if float(freshness_map.get(int(q.get("question_number") or 0), 0.0)) >= profile.freshness_suppression_min
            and not is_active_weak(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
            and not is_review_due(question_meta.get(int(q.get("question_number") or 0), {}).get("record", {}))
        }
        available_count = len(pool) - len(suppressed_qnums)
        if available_count >= max(1, target):
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

        quota_profile = smart_practice_quota_profile(
            str(momentum_profile.get("label") or "Balanced"), str(burnout_risk.get("label") or "Low")
        )

        screenshot_ratio = (
            profile.imported_chapter_burst_quota_ratio
            if imported_chapter_burst_active
            else profile.screenshot_focus_ratio
        )

        quota = {
            "unseen": max(1, round(target * quota_profile.unseen_ratio)) if unseen else 0,
            "active_weak": max(1, round(target * quota_profile.active_weak_ratio)) if active_weak else 0,
            "due": max(1, round(target * quota_profile.due_ratio)) if due else 0,
            "recovered": max(1, round(target * quota_profile.recovered_ratio)) if recovered else 0,
            "screenshot": max(1, round(target * screenshot_ratio)) if screenshot_focus else 0,
            "coverage": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if coverage_focus
                else 0
            ),
            "objective": (
                max(1, round(target * profile.objective_focus_ratio * quota_profile.advanced_scale))
                if objective_focus
                else 0
            ),
            "interference": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if interference_focus
                else 0
            ),
            "compression": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if compression_focus
                else 0
            ),
            "ladder": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if ladder_focus
                else 0
            ),
            "boundary": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if boundary_focus
                else 0
            ),
            "counterfactual": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if counterfactual_focus
                else 0
            ),
            "prerequisite": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if prerequisite_focus
                else 0
            ),
            "blind_spot": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if blind_spot_focus
                else 0
            ),
            "robustness": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if robustness_focus
                else 0
            ),
            "reinforcement": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if reinforcement_focus
                else 0
            ),
            "synthesis": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if synthesis_focus
                else 0
            ),
            "knowledge_trace": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if knowledge_trace_focus
                else 0
            ),
            "learning_gain": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if learning_gain_focus
                else 0
            ),
            "delayed_probe": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if delayed_probe_focus
                else 0
            ),
            "cue_dependence": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if cue_dependence_focus
                else 0
            ),
            "recognition_gap": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if recognition_focus
                else 0
            ),
            "retention_stress": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if retention_stress_focus
                else 0
            ),
            "failure_mode": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if failure_mode_focus
                else 0
            ),
            "generalization": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if generalization_focus
                else 0
            ),
            "decision_latency": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if decision_latency_focus
                else 0
            ),
            "contrast_rule": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if contrast_rule_focus
                else 0
            ),
            "concept_state": (
                max(1, round(target * profile.advanced_focus_ratio * quota_profile.advanced_scale))
                if concept_state_focus
                else 0
            ),
        }

        ordered = []
        seen_qnums = set()
        objective_counts = {}
        objective_cap = smart_practice_objective_cap(target, profile)

        def take_from(group, limit):
            skipped = []
            for q in group:
                if len(ordered) >= target or limit <= 0:
                    break
                qnum = q.get("question_number")
                if qnum in seen_qnums:
                    continue
                objective_code = str(question_meta.get(int(qnum or 0), {}).get("objective_code") or "")
                if objective_code and objective_counts.get(objective_code, 0) >= objective_cap:
                    skipped.append(q)
                    continue
                seen_qnums.add(qnum)
                ordered.append(q)
                if objective_code:
                    objective_counts[objective_code] = objective_counts.get(objective_code, 0) + 1
                limit -= 1
            for q in skipped:
                if len(ordered) >= target or limit <= 0:
                    break
                qnum = q.get("question_number")
                if qnum in seen_qnums:
                    continue
                seen_qnums.add(qnum)
                ordered.append(q)
                objective_code = str(question_meta.get(int(qnum or 0), {}).get("objective_code") or "")
                if objective_code:
                    objective_counts[objective_code] = objective_counts.get(objective_code, 0) + 1
                limit -= 1

        if target <= 3:
            take_from(screenshot_focus, quota["screenshot"])
            take_from(active_weak, quota["active_weak"])
            take_from(boundary_focus, quota["boundary"])
            take_from(counterfactual_focus, quota["counterfactual"])
            take_from(coverage_focus, quota["coverage"])
            take_from(reinforcement_focus, quota["reinforcement"])
            take_from(objective_focus, quota["objective"])
            take_from(unseen, quota["unseen"])
            take_from(due, quota["due"])
            take_from(prerequisite_focus, quota["prerequisite"])
            take_from(blind_spot_focus, quota["blind_spot"])
            take_from(knowledge_trace_focus, quota["knowledge_trace"])
            take_from(learning_gain_focus, quota["learning_gain"])
            take_from(delayed_probe_focus, quota["delayed_probe"])
            take_from(retention_stress_focus, quota["retention_stress"])
            take_from(failure_mode_focus, quota["failure_mode"])
            take_from(contrast_rule_focus, quota["contrast_rule"])
            take_from(interference_focus, quota["interference"])
            take_from(compression_focus, quota["compression"])
            take_from(ladder_focus, quota["ladder"])
            take_from(cue_dependence_focus, quota["cue_dependence"])
            take_from(recognition_focus, quota["recognition_gap"])
            take_from(generalization_focus, quota["generalization"])
            take_from(decision_latency_focus, quota["decision_latency"])
            take_from(robustness_focus, quota["robustness"])
            take_from(synthesis_focus, quota["synthesis"])
            take_from(concept_state_focus, quota["concept_state"])
            take_from(recovered, quota["recovered"])
        else:
            take_from(screenshot_focus, quota["screenshot"])
            take_from(unseen, quota["unseen"])
            take_from(active_weak, quota["active_weak"])
            take_from(due, quota["due"])
            take_from(coverage_focus, quota["coverage"])
            take_from(objective_focus, quota["objective"])
            take_from(interference_focus, quota["interference"])
            take_from(compression_focus, quota["compression"])
            take_from(ladder_focus, quota["ladder"])
            take_from(boundary_focus, quota["boundary"])
            take_from(counterfactual_focus, quota["counterfactual"])
            take_from(prerequisite_focus, quota["prerequisite"])
            take_from(blind_spot_focus, quota["blind_spot"])
            take_from(robustness_focus, quota["robustness"])
            take_from(reinforcement_focus, quota["reinforcement"])
            take_from(synthesis_focus, quota["synthesis"])
            take_from(knowledge_trace_focus, quota["knowledge_trace"])
            take_from(learning_gain_focus, quota["learning_gain"])
            take_from(delayed_probe_focus, quota["delayed_probe"])
            take_from(cue_dependence_focus, quota["cue_dependence"])
            take_from(recognition_focus, quota["recognition_gap"])
            take_from(retention_stress_focus, quota["retention_stress"])
            take_from(failure_mode_focus, quota["failure_mode"])
            take_from(generalization_focus, quota["generalization"])
            take_from(decision_latency_focus, quota["decision_latency"])
            take_from(contrast_rule_focus, quota["contrast_rule"])
            take_from(concept_state_focus, quota["concept_state"])
            take_from(recovered, quota["recovered"])

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
        for q in fallback:
            if len(ordered) >= target:
                break
            qnum = q.get("question_number")
            if qnum in seen_qnums:
                continue
            objective_code = str(question_meta.get(int(qnum or 0), {}).get("objective_code") or "")
            if objective_code and objective_counts.get(objective_code, 0) >= objective_cap:
                continue
            seen_qnums.add(qnum)
            ordered.append(q)
            if objective_code:
                objective_counts[objective_code] = objective_counts.get(objective_code, 0) + 1

        def source_label_for_question(question: QuestionRuntimeState) -> str:
            return str(question.get("source_label") or question.get("source_name") or "Unknown source").strip()

        def source_label_cap() -> int:
            return max(1, int(target * profile.variety_source_label_cap_ratio + 0.999))

        def unique_candidates() -> list[QuestionRuntimeState]:
            candidates: list[QuestionRuntimeState] = []
            used_qnums = set()
            for group in (ordered, fallback, working_pool):
                for item in group:
                    qnum = item.get("question_number")
                    if qnum in used_qnums:
                        continue
                    used_qnums.add(qnum)
                    candidates.append(item)
            candidates.sort(key=smart_priority, reverse=True)
            return candidates

        def shape_for_variety(selected: list[QuestionRuntimeState]) -> list[QuestionRuntimeState]:
            if target < profile.variety_min_target_size:
                return selected[:target]
            candidates = unique_candidates()
            available_topics = {
                self._primary_topic_label(question)
                for question in candidates
                if self._primary_topic_label(question)
            }
            available_domains = {str(question.get("domain") or "").strip() for question in candidates if question.get("domain")}
            desired_topics = min(profile.variety_min_topics, target, len(available_topics))
            desired_domains = min(profile.variety_min_domains, target, len(available_domains))
            max_source = source_label_cap()
            shaped: list[QuestionRuntimeState] = []
            shaped_qnums = set()
            shaped_objectives: dict[str, int] = {}
            shaped_source_labels: dict[str, int] = {}
            pinned_count = min(target, max(profile.variety_pinned_min, round(target * profile.variety_pinned_ratio)))

            def can_add(question: QuestionRuntimeState, strict_source: bool, strict_objective: bool = True) -> bool:
                qnum = question.get("question_number")
                if qnum in shaped_qnums or len(shaped) >= target:
                    return False
                objective_code = str(question_meta.get(int(qnum or 0), {}).get("objective_code") or "")
                if strict_objective and objective_code and shaped_objectives.get(objective_code, 0) >= objective_cap:
                    return False
                label = source_label_for_question(question)
                if strict_source and shaped_source_labels.get(label, 0) >= max_source:
                    return False
                return True

            def add(
                question: QuestionRuntimeState, strict_source: bool = True, strict_objective: bool = True
            ) -> bool:
                if not can_add(question, strict_source, strict_objective):
                    return False
                qnum = question.get("question_number")
                shaped_qnums.add(qnum)
                shaped.append(question)
                objective_code = str(question_meta.get(int(qnum or 0), {}).get("objective_code") or "")
                if objective_code:
                    shaped_objectives[objective_code] = shaped_objectives.get(objective_code, 0) + 1
                label = source_label_for_question(question)
                shaped_source_labels[label] = shaped_source_labels.get(label, 0) + 1
                return True

            def best_values(value_fn, desired_count: int) -> list[str]:
                best_by_value: dict[str, float] = {}
                for question in candidates:
                    value = value_fn(question)
                    if not value:
                        continue
                    best_by_value[value] = max(best_by_value.get(value, 0.0), smart_priority(question))
                ranked = [(score, value) for value, score in best_by_value.items()]
                ranked.sort(reverse=True)
                return [value for _score, value in ranked[:desired_count]]

            for question in selected[:pinned_count]:
                add(question, strict_source=True)
                if len(shaped) >= pinned_count:
                    break
            for topic in best_values(lambda question: self._primary_topic_label(question), desired_topics):
                for question in candidates:
                    if self._primary_topic_label(question) == topic and add(question, strict_source=True):
                        break
            for domain in best_values(lambda question: str(question.get("domain") or "").strip(), desired_domains):
                if domain in {str(question.get("domain") or "").strip() for question in shaped}:
                    continue
                for question in candidates:
                    if str(question.get("domain") or "").strip() == domain and add(question, strict_source=True):
                        break
            for question in selected + candidates:
                add(question, strict_source=True)
                if len(shaped) >= target:
                    break
            for question in selected + candidates:
                add(question, strict_source=False)
                if len(shaped) >= target:
                    break
            for question in selected + candidates:
                add(question, strict_source=False, strict_objective=False)
                if len(shaped) >= target:
                    break
            return shaped[:target]

        def smart_practice_set_quality(selection: list[QuestionRuntimeState]) -> float:
            if not selection:
                return 0.0
            selected_qnums = {int(question.get("question_number") or 0) for question in selection}
            topics = {self._primary_topic_label(question) for question in selection if self._primary_topic_label(question)}
            domains = {str(question.get("domain") or "").strip() for question in selection if question.get("domain")}
            source_counts: dict[str, int] = {}
            for question in selection:
                label = source_label_for_question(question)
                source_counts[label] = source_counts.get(label, 0) + 1
            max_source_count = max(source_counts.values()) if source_counts else 0
            max_source = source_label_cap()
            available_sources = {source_label_for_question(question) for question in unique_candidates()}
            high_signal_qnums = {
                int(question.get("question_number") or 0)
                for question in (active_weak + due)
                if int(question.get("question_number") or 0)
            }
            desired_high_signal = min(len(high_signal_qnums), max(1, round(target * 0.25))) if high_signal_qnums else 0
            high_signal_hits = len(selected_qnums & high_signal_qnums)
            freshness_average = sum(float(freshness_map.get(qnum, 0.0)) for qnum in selected_qnums) / max(
                1, len(selected_qnums)
            )
            fresh_question_target = round(target * profile.fresh_question_target_ratio)
            fresh_question_hits = sum(
                1
                for qnum in selected_qnums
                if float(freshness_map.get(qnum, 0.0)) < profile.freshness_suppression_min
                or qnum in high_signal_qnums
            )
            desired_topics = min(profile.variety_min_topics, target)
            desired_domains = min(profile.variety_min_domains, target)
            score = 100.0
            score -= max(0, target - len(selected_qnums)) * 8.0
            if desired_high_signal:
                score -= max(0, desired_high_signal - high_signal_hits) * 10.0
            score -= max(0, fresh_question_target - fresh_question_hits) * profile.fresh_question_quality_penalty
            score -= max(0, desired_topics - len(topics)) * 4.0
            score -= max(0, desired_domains - len(domains)) * 6.0
            if len(available_sources) > 1 and max_source_count > max_source:
                score -= (max_source_count - max_source) * 5.0
            score -= min(18.0, freshness_average * 0.15)
            return round(max(0.0, min(100.0, score)), 2)

        def source_balanced_seed() -> list[QuestionRuntimeState]:
            remaining = unique_candidates()
            seeded: list[QuestionRuntimeState] = []
            used_qnums = set()
            source_counts: dict[str, int] = {}
            while remaining and len(seeded) < target:
                remaining.sort(
                    key=lambda question: (
                        source_counts.get(source_label_for_question(question), 0),
                        -smart_priority(question),
                    )
                )
                question = remaining.pop(0)
                qnum = question.get("question_number")
                if qnum in used_qnums:
                    continue
                used_qnums.add(qnum)
                seeded.append(question)
                label = source_label_for_question(question)
                source_counts[label] = source_counts.get(label, 0) + 1
            return seeded

        ordered = shape_for_variety(ordered)
        primary_quality = smart_practice_set_quality(ordered)
        retry_used = False
        if primary_quality < profile.set_quality_retry_threshold:
            alternate = shape_for_variety(source_balanced_seed())
            alternate_quality = smart_practice_set_quality(alternate)
            if alternate_quality >= primary_quality + profile.set_quality_retry_margin:
                ordered = alternate
                primary_quality = alternate_quality
                retry_used = True
        self.last_smart_practice_set_quality = {"score": primary_quality, "retry_used": retry_used}

        if not randomize:
            result = self._interleave_questions(ordered)
            if pool_cache_key is not None:
                self.smart_practice_pool_cache[pool_cache_key] = tuple(
                    int(question.get("question_number") or 0) for question in result
                )
            return result

        mixed = list(ordered[:target])
        random.shuffle(mixed)
        return self._interleave_questions(mixed)
