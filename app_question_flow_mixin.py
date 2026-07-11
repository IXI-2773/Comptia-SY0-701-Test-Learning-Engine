import re
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any

from app_constants import (
    MODE_EXAM,
    QUESTION_TAG_CONFUSION_PAIR,
    QUESTION_TAG_DELAYED_RECALL_PROBE,
    QUESTION_TAG_RETRIEVAL_RAMP,
    QUESTION_TAG_STREAK_RESCUE_PREFIX,
    QUESTION_TAG_TRANSFER_CHECK,
    QUESTION_TAG_TWIN,
    QUESTION_TAG_WRONG_ANSWER_MEMORY,
)
from progress_store import (
    is_active_weak,
    is_review_due,
    is_suspended,
    sanitize_response_time,
    set_progress_super_confident,
)
from session_models import QuestionRuntimeState, SessionAnswerEvent, clear_runtime_answer_state
from smart_practice_concept_graph import concept_key_for_question


class QuestionFlowMixin:
    def _question_correct(self, q: QuestionRuntimeState) -> bool:
        return set(q.get("selected", [])) == set(q.get("correct", []))

    def _infer_miss_reason_from_confidence(self, confidence, is_correct):
        if is_correct:
            return ""
        confidence = str(confidence or "").strip()
        if confidence == "Guessed":
            return "Did not know"
        if confidence == "Unsure":
            return "Narrowed to two"
        return "Misread"

    def classify_recall_failure(
        self, q: QuestionRuntimeState, is_correct: bool, feedback: dict[str, Any] | None = None
    ) -> str:
        feedback = feedback or {}
        confidence = str(feedback.get("confidence") or q.get("last_confidence") or "").strip()
        miss_reason = str(feedback.get("miss_reason") or q.get("last_miss_reason") or "").strip()
        if is_correct:
            if confidence == "Guessed":
                return "Recognition without recall"
            if confidence == "Unsure":
                return "Fragile retrieval"
            return ""
        if miss_reason == "Did not know" or confidence == "Guessed":
            return "Blank recall"
        if miss_reason in ("Narrowed to two", "Changed answer") or confidence == "Unsure":
            return "Concept interference"
        if miss_reason == "Misread" or confidence == "Sure":
            return "Cue / wording miss"
        return "Unclassified miss"

    def deciding_clue_for_question(self, q: QuestionRuntimeState) -> str:
        correct_texts = [
            str(q.get("choices", {}).get(letter, "")).strip()
            for letter in q.get("correct", [])
            if str(q.get("choices", {}).get(letter, "")).strip()
        ]
        labels = [self._choice_concept_label(text) for text in correct_texts]
        labels = [label for label in labels if label]
        if labels:
            return labels[0]
        topics = [str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()]
        if topics:
            return topics[0]
        objective = str(q.get("objective_code") or "").strip()
        if objective:
            return f"Objective {objective}"
        prompt = re.sub(r"[^A-Za-z0-9\s-]", " ", str(q.get("prompt") or ""))
        words = [
            word
            for word in prompt.split()
            if len(word) >= 5 and word.lower() not in {"which", "would", "should", "could", "about", "following"}
        ]
        return " ".join(words[:3]) if words else "General clue"

    def _focus_feedback_button(self, buttons, step):
        if not buttons:
            return
        current = None
        widget = self.root.focus_get()
        for idx, button in enumerate(buttons):
            if button == widget:
                current = idx
                break
        if current is None:
            current = 0
        buttons[(current + step) % len(buttons)].focus_set()

    def _position_feedback_popover(self, popover, anchor):
        popover.update_idletasks()
        host = self.content_frame
        pop_w = popover.winfo_width()
        pop_h = popover.winfo_height()
        host_w = max(host.winfo_width(), self.content_canvas.winfo_width())
        host_h = max(host.winfo_height(), self.content_canvas.winfo_height())
        if anchor is None or not getattr(anchor, "winfo_exists", lambda: False)():
            return max(20, int((host_w - pop_w) / 2)), max(20, int((host_h - pop_h) / 5))

        ax = anchor.winfo_rootx() - host.winfo_rootx()
        ay = anchor.winfo_rooty() - host.winfo_rooty()
        aw = anchor.winfo_width()
        ah = anchor.winfo_height()
        candidates = [
            (ax + aw + 10, ay + max(0, int((ah - pop_h) / 2))),
            (ax, ay + ah + 10),
            (ax - pop_w - 10, ay + max(0, int((ah - pop_h) / 2))),
            (ax, ay - pop_h - 10),
        ]
        for x, y in candidates:
            if 12 <= x <= host_w - pop_w - 12 and 12 <= y <= host_h - pop_h - 12:
                return x, y
        x = min(max(12, candidates[0][0]), max(12, host_w - pop_w - 12))
        y = min(max(12, candidates[0][1]), max(12, host_h - pop_h - 12))
        return x, y

    def _feedback_popover_active(self):
        popover = getattr(self, "answer_feedback_popover", None)
        return popover is not None and popover.winfo_exists()

    def _destroy_feedback_popover(self):
        if self._feedback_popover_active():
            self.answer_feedback_popover.place_forget()
            self.answer_feedback_popover.destroy()
        self.answer_feedback_popover = None
        self.answer_feedback_buttons = []

    def _complete_feedback_choice(self, confidence):
        request = dict(getattr(self, "pending_feedback_request", None) or {})
        self.pending_feedback_request = None
        self._destroy_feedback_popover()
        if not request:
            return
        qnum = request.get("question_number")
        q = next((item for item in self.questions if item.get("question_number") == qnum), None)
        if q is None:
            return
        feedback = {
            "confidence": confidence,
            "miss_reason": self._infer_miss_reason_from_confidence(confidence, request.get("is_correct")),
        }
        self._record_answer(q, request.get("selected", []), anchor_widget=None, feedback_override=feedback)

    def handle_return_key(self):
        if self._feedback_popover_active():
            self._destroy_feedback_popover()
            self.pending_feedback_request = None
            return "break"
        self.submit_answer()
        return "break"

    def _question_matches_filters(self, q: QuestionRuntimeState, domain=None, topic=None, status=None, rec=None):
        d = self.domain_filter_var.get() if domain is None else domain
        if d and d != "All domains" and q.get("domain") != d:
            return False
        topic = self.topic_filter_var.get() if topic is None else topic
        if topic and topic != "All topics" and topic not in [str(t).strip() for t in q.get("topics", [])]:
            return False
        s = self.normalize_status_filter(self.status_filter_var.get()) if status is None else status
        rec = self._progress_record(q, create=False) if rec is None else rec
        if s == "Unanswered" and q.get("answered"):
            return False
        if s == "Answered in session" and not q.get("answered"):
            return False
        if s == "Correct in session" and (not q.get("answered") or not self._question_correct(q)):
            return False
        if s == "Wrong in session" and (not q.get("answered") or self._question_correct(q)):
            return False
        if s == "Previously wrong" and not is_active_weak(rec):
            return False
        if s == "Flagged" and not q.get("flagged"):
            return False
        if s == "Due review" and not is_review_due(rec):
            return False
        if s == "Suspended" and not is_suspended(rec):
            return False
        if s not in ("Suspended", "With issues") and is_suspended(rec):
            return False
        if s == "With issues" and not self.question_has_any_issue(q):
            return False
        return True

    def _question_list_signature(self):
        rows = []
        for q in self.questions:
            rec = self._progress_record(q, create=False) or {}
            rows.append(
                (
                    q.get("question_number"),
                    bool(q.get("answered")),
                    tuple(sorted(q.get("selected", []))),
                    bool(q.get("flagged")),
                    bool(q.get("suspended")),
                    bool(self.question_has_any_issue(q)),
                    rec.get("next_review", ""),
                    int(rec.get("wrong_count", 0)),
                    int(rec.get("correct_count", 0)),
                    rec.get("last_correct"),
                    rec.get("last_confidence", ""),
                    rec.get("last_miss_reason", ""),
                )
            )
        return (
            self.active_session_mode,
            bool(self.exam_reveal),
            self.domain_filter_var.get(),
            self.topic_filter_var.get(),
            self.normalize_status_filter(self.status_filter_var.get()),
            tuple(rows),
        )

    def _sync_question_list_selection(self):
        if not self.questions:
            return
        current_qnum = self.questions[self.index]["question_number"]
        pos = None
        for i, idx in enumerate(self.visible_indices):
            if self.questions[idx]["question_number"] == current_qnum:
                pos = i
                break
        self.question_list.selection_clear(0, tk.END)
        if pos is not None:
            self.question_list.selection_set(pos)
            self.question_list.see(pos)

    def refresh_question_list(self):
        if not self.questions:
            self.visible_indices = []
            self.question_list.delete(0, tk.END)
            progress = self.progress_summary()
            self.sidebar_stats.configure(
                text=f"Session: Ready\nQuestions: 0\nVisible: 0\nAnswered: 0\nFlagged: 0    Issues: 0\nDue review: {progress['due']}    Active weak: {progress['wrong']}"
            )
            self.last_question_list_signature = None
            self.question_list_dirty = False
            return
        signature = self._question_list_signature()
        if signature == self.last_question_list_signature:
            self._sync_question_list_selection()
            self.question_list_dirty = False
            return
        current_qnum = self.questions[self.index]["question_number"]
        domain = self.domain_filter_var.get()
        topic = self.topic_filter_var.get()
        status = self.normalize_status_filter(self.status_filter_var.get())
        visible_rows = []
        for i, q in enumerate(self.questions):
            rec = self._progress_record(q, create=False) or {}
            if self._question_matches_filters(q, domain=domain, topic=topic, status=status, rec=rec):
                visible_rows.append((i, q, rec))
        self.visible_indices = [i for i, _q, _rec in visible_rows]
        self.question_list.delete(0, tk.END)
        for _idx, q, rec in visible_rows:
            status = "."
            if q.get("answered"):
                status = "OK" if self._question_correct(q) else "X"
                if self.active_session_mode == MODE_EXAM and not self.exam_reveal:
                    status = "R"
            if q.get("flagged"):
                status += "F"
            if q.get("suspended"):
                status += "S"
            elif self.question_has_any_issue(q):
                status += "!"
            if rec and is_review_due(rec):
                status += "D"
            text = (
                f"{status:<3} Q{q['question_number']:>3}  p.{str(q.get('source_page','')):<4} {q.get('domain','')[:22]}"
            )
            self.question_list.insert(tk.END, text)
        pos = 0
        for i, idx in enumerate(self.visible_indices):
            if self.questions[idx]["question_number"] == current_qnum:
                pos = i
                break
        self.question_list.selection_clear(0, tk.END)
        if self.visible_indices:
            self.question_list.selection_set(pos)
            self.question_list.see(pos)
        flagged_count = sum(1 for q in self.questions if q.get("flagged"))
        issues_count = sum(1 for q in self.questions if self.question_has_any_issue(q))
        answered_count = sum(1 for q in self.questions if q.get("answered"))
        progress = self.progress_summary()
        self.sidebar_stats.configure(
            text=f"Session: {self.active_session_mode}\nQuestions: {len(self.questions)}\nVisible: {len(self.visible_indices)}\nAnswered: {answered_count}\nFlagged: {flagged_count}    Issues: {issues_count}\nDue review: {progress['due']}    Active weak: {progress['wrong']}"
        )
        self.last_question_list_signature = signature
        self.question_list_dirty = False

    def _render_current_view(self, save_session=True):
        if save_session:
            self.schedule_session_save(delay_ms=450)
        self.scroll_to_top_on_render = True
        self.render_question()

    def mark_question_list_dirty(self):
        self.last_question_list_signature = None
        self.question_list_dirty = True

    def _set_current_index(self, idx):
        self.index = idx
        self.schedule_session_save(delay_ms=1200)
        self._render_current_view(save_session=False)

    def _collect_answer_feedback(self, q, is_correct):
        return {"confidence": "Sure", "miss_reason": self._infer_miss_reason_from_confidence("Sure", is_correct)}

    def complete_explanation_recall(self):
        if not self.questions:
            return
        q = self.current_question()
        q["recall_ready"] = True
        self.render_question()

    def _insert_followup_questions(
        self, current_q: QuestionRuntimeState, candidates: list[QuestionRuntimeState], tag: str
    ) -> list[QuestionRuntimeState]:
        if not candidates:
            return []
        existing_qnums = {q.get("question_number") for q in self.questions}
        unique_candidates = [q for q in candidates if q.get("question_number") not in existing_qnums]
        if not unique_candidates:
            return []
        clones = self._clone_questions(unique_candidates)
        self._reset_runtime_question_state(clones)
        for clone in clones:
            clone["session_tag"] = tag
            clone["recall_ready"] = False
        insert_at = min(len(self.questions), self.index + 1)
        inserted = self._insert_or_replace_followup_clones(clones, insert_at)
        if not inserted:
            return []
        self.refresh_session_runtime_identity()
        self.last_question_list_signature = None
        return inserted

    def _insert_delayed_followup_questions(
        self, current_q: QuestionRuntimeState, candidates: list[QuestionRuntimeState], tag: str, delay_slots: int = 3
    ) -> list[QuestionRuntimeState]:
        if not candidates:
            return []
        existing_qnums = {q.get("question_number") for q in self.questions}
        unique_candidates = [q for q in candidates if q.get("question_number") not in existing_qnums]
        if not unique_candidates:
            return []
        clones = self._clone_questions(unique_candidates)
        self._reset_runtime_question_state(clones)
        for clone in clones:
            clone["session_tag"] = tag
            clone["recall_ready"] = False
        insert_at = min(len(self.questions), self.index + max(2, int(delay_slots)))
        inserted = self._insert_or_replace_followup_clones(clones, insert_at)
        if not inserted:
            return []
        self.refresh_session_runtime_identity()
        self.last_question_list_signature = None
        return inserted

    def _is_replaceable_followup_slot(self, q: QuestionRuntimeState) -> bool:
        return not (
            q.get("answered") or q.get("flagged") or q.get("suspended") or str(q.get("session_tag") or "").strip()
        )

    def _next_followup_replacement_index(self, start_at: int) -> int | None:
        latest_start = max(0, len(self.questions) - 1)
        start = max(self.index + 1, min(int(start_at), latest_start))
        for idx in range(start, len(self.questions)):
            if self._is_replaceable_followup_slot(self.questions[idx]):
                return idx
        return None

    def _insert_or_replace_followup_clones(
        self, clones: list[QuestionRuntimeState], insert_at: int
    ) -> list[QuestionRuntimeState]:
        limit = getattr(self, "session_question_limit", None)
        if limit is None:
            for offset, clone in enumerate(clones):
                self.questions.insert(insert_at + offset, clone)
            return clones
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return []
        inserted = []
        for clone in clones:
            if len(self.questions) < limit:
                position = min(len(self.questions), insert_at + len(inserted))
                self.questions.insert(position, clone)
                inserted.append(clone)
                continue
            replace_idx = self._next_followup_replacement_index(insert_at + len(inserted))
            if replace_idx is None:
                break
            self.questions.pop(replace_idx)
            position = min(replace_idx, insert_at + len(inserted), len(self.questions))
            self.questions.insert(position, clone)
            inserted.append(clone)
        return inserted

    def find_question_twins(self, q: QuestionRuntimeState, limit: int = 2) -> list[QuestionRuntimeState]:
        topics = {str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()}
        domain = q.get("domain")
        records = self._progress_questions()
        current_qnums = {item.get("question_number") for item in self.questions}
        ranked = []
        for candidate in self.master_questions:
            qnum = candidate.get("question_number")
            if qnum == q.get("question_number") or qnum in current_qnums:
                continue
            rec = records.get(self._question_key(candidate), {})
            if is_suspended(rec):
                continue
            candidate_topics = {str(topic).strip() for topic in candidate.get("topics", []) if str(topic).strip()}
            shared_topics = len(topics & candidate_topics)
            same_domain = 1 if domain and candidate.get("domain") == domain else 0
            if not shared_topics and not same_domain:
                continue
            score = (
                shared_topics * 4
                + same_domain * 3
                + (2 if is_active_weak(rec) else 0)
                + (1 if is_review_due(rec) else 0)
                - int(rec.get("attempts", 0)) * 0.05
            )
            ranked.append((score, qnum, candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        return [candidate for _score, _qnum, candidate in ranked[:limit]]

    def _rebuild_followup_candidate_index(self) -> None:
        by_unit = {}
        by_topic = {}
        by_objective = {}
        by_number = {}
        search_text = {}
        metadata = {}
        for question in self.master_questions:
            qnum = int(question.get("question_number") or 0)
            if not qnum:
                continue
            kind, unit = self._coverage_unit_for_question(question)
            unit_key = f"{kind}::{unit}"
            topics = tuple(str(topic).strip() for topic in question.get("topics", []) if str(topic).strip())
            objective = str(question.get("objective_code") or "").strip()
            by_number[qnum] = question
            by_unit.setdefault(unit_key, set()).add(qnum)
            for topic in topics:
                by_topic.setdefault(topic, set()).add(qnum)
            if objective:
                by_objective.setdefault(objective, set()).add(qnum)
            search_text[qnum] = " ".join(
                [
                    str(question.get("prompt") or ""),
                    *(str(text or "") for text in question.get("choices", {}).values()),
                ]
            ).casefold()
            metadata[qnum] = {
                "unit_key": unit_key,
                "topics": frozenset(topics),
                "objective": objective,
                "source_name": str(question.get("source_name") or ""),
                "stem_style": self._stem_style_for_question(question),
            }
        self.followup_candidate_index = {
            "by_unit": by_unit,
            "by_topic": by_topic,
            "by_objective": by_objective,
            "by_number": by_number,
            "search_text": search_text,
            "metadata": metadata,
        }
        self.followup_candidate_index_signature = self._followup_index_signature()

    def _followup_index_signature(self):
        return (
            id(self.master_questions),
            len(self.master_questions),
            int(self.master_questions[0].get("question_number") or 0) if self.master_questions else 0,
            int(self.master_questions[-1].get("question_number") or 0) if self.master_questions else 0,
        )

    def _followup_index(self):
        if (
            self.followup_candidate_index is None
            or self.followup_candidate_index_signature != self._followup_index_signature()
        ):
            self._rebuild_followup_candidate_index()
        return self.followup_candidate_index

    def _related_followup_candidates(self, q: QuestionRuntimeState, clue: str = "") -> list[QuestionRuntimeState]:
        index = self._followup_index()
        kind, unit = self._coverage_unit_for_question(q)
        qnums = set(index["by_unit"].get(f"{kind}::{unit}", set()))
        for topic in q.get("topics", []):
            topic_text = str(topic).strip()
            if topic_text:
                qnums.update(index["by_topic"].get(topic_text, set()))
        objective = str(q.get("objective_code") or "").strip()
        if objective:
            qnums.update(index["by_objective"].get(objective, set()))
        clue_text = str(clue or "").strip().casefold()
        if clue_text:
            qnums.update(qnum for qnum, text in index["search_text"].items() if clue_text in text)
        current_qnum = int(q.get("question_number") or 0)
        qnums.discard(current_qnum)
        return [index["by_number"][qnum] for qnum in qnums if qnum in index["by_number"]]

    def maybe_queue_question_twins(self, q: QuestionRuntimeState) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        twins = self.find_question_twins(q, limit=2)
        return self._insert_followup_questions(q, twins, QUESTION_TAG_TWIN)

    def maybe_queue_delayed_recall_probe(self, q: QuestionRuntimeState) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        if str(q.get("session_tag") or "").startswith(QUESTION_TAG_DELAYED_RECALL_PROBE):
            return []
        rec = self._progress_record(q, create=False) or {}
        confidence = str(q.get("last_confidence") or rec.get("last_confidence") or "").strip()
        if confidence == "Guessed":
            return []
        clue = self.deciding_clue_for_question(q)
        records = self._progress_questions()
        current_qnums = {item.get("question_number") for item in self.questions}
        topics = {str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()}
        ranked = []
        for candidate in self._related_followup_candidates(q, clue=clue):
            qnum = candidate.get("question_number")
            if qnum == q.get("question_number") or qnum in current_qnums:
                continue
            candidate_rec = records.get(self._question_key(candidate), {})
            if is_suspended(candidate_rec):
                continue
            candidate_topics = {str(topic).strip() for topic in candidate.get("topics", []) if str(topic).strip()}
            shared_topics = len(topics & candidate_topics)
            mentions_clue = 1 if clue and self._question_mentions_label(candidate, clue) else 0
            same_objective = (
                1 if q.get("objective_code") and candidate.get("objective_code") == q.get("objective_code") else 0
            )
            if not shared_topics and not mentions_clue and not same_objective:
                continue
            score = (
                shared_topics * 5
                + mentions_clue * 4
                + same_objective * 3
                + (2 if int(candidate_rec.get("attempts", 0)) <= 0 else 0)
                + (2 if is_review_due(candidate_rec) else 0)
                - int(candidate_rec.get("correct_streak", 0)) * 0.3
            )
            ranked.append((score, int(qnum or 0), candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        return self._insert_delayed_followup_questions(
            q, [candidate for _score, _qnum, candidate in ranked[:1]], QUESTION_TAG_DELAYED_RECALL_PROBE
        )

    def _concept_memory_row_for_question(self, q: QuestionRuntimeState) -> dict[str, Any]:
        kind, unit = self._coverage_unit_for_question(q)
        index = self._followup_index()
        concept_questions = [
            index["by_number"][qnum]
            for qnum in index["by_unit"].get(f"{kind}::{unit}", set())
            if qnum in index["by_number"]
        ]
        concept_qnums = {int(candidate.get("question_number") or 0) for candidate in concept_questions}
        history_map: dict[int, list[dict[str, Any]]] = {}
        for event in self._progress_history():
            qnum = int(event.get("question_number") or 0)
            if qnum not in concept_qnums:
                continue
            history_map.setdefault(qnum, []).append(event)
        _rows, memory_map = self._build_concept_memory_state_rows(history_map, concept_questions)
        return memory_map.get(f"{kind}::{unit}", {"state": "new", "evidence_count": 0, "next_ramp": "recognition"})

    def find_memory_ramp_candidates(
        self, q: QuestionRuntimeState, limit: int = 1
    ) -> tuple[str, list[QuestionRuntimeState]]:
        memory_row = self._concept_memory_row_for_question(q)
        if int(memory_row.get("evidence_count", 0)) < 2:
            return "", []
        state = str(memory_row.get("state") or "new")
        if state == "recognizable":
            tag = QUESTION_TAG_RETRIEVAL_RAMP
        elif state in ("retrievable", "transferable"):
            tag = QUESTION_TAG_TRANSFER_CHECK
        else:
            return "", []
        kind, unit = self._coverage_unit_for_question(q)
        unit_key = f"{kind}::{unit}"
        current_qnums = {item.get("question_number") for item in self.questions}
        records = self._progress_questions()
        topics = {str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()}
        q_source = str(q.get("source_name") or "")
        q_style = self._stem_style_for_question(q)
        ranked = []
        index = self._followup_index()
        for candidate in self._related_followup_candidates(q):
            qnum = candidate.get("question_number")
            if qnum == q.get("question_number") or qnum in current_qnums:
                continue
            rec = records.get(self._question_key(candidate), {})
            if is_suspended(rec):
                continue
            candidate_meta = index["metadata"].get(int(qnum or 0), {})
            candidate_topics = set(candidate_meta.get("topics") or ())
            same_unit = str(candidate_meta.get("unit_key") or "") == unit_key
            shared_topics = len(topics & candidate_topics)
            same_objective = bool(
                q.get("objective_code") and candidate.get("objective_code") == q.get("objective_code")
            )
            if not same_unit and not shared_topics and not same_objective:
                continue
            different_source = str(candidate_meta.get("source_name") or "") != q_source
            different_style = str(candidate_meta.get("stem_style") or "") != q_style
            score = (
                (8 if same_unit else 0)
                + shared_topics * 3
                + (3 if same_objective else 0)
                + (4 if tag == QUESTION_TAG_TRANSFER_CHECK and different_source else 0)
                + (4 if tag == QUESTION_TAG_TRANSFER_CHECK and different_style else 0)
                + (2 if int(rec.get("attempts", 0)) <= 0 else 0)
                + (2 if is_review_due(rec) else 0)
                - int(rec.get("correct_streak", 0)) * 0.4
            )
            ranked.append((score, int(qnum or 0), candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        return tag, [candidate for _score, _qnum, candidate in ranked[:limit]]

    def maybe_queue_memory_ramp(self, q: QuestionRuntimeState) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        if str(q.get("session_tag") or "") in {QUESTION_TAG_RETRIEVAL_RAMP, QUESTION_TAG_TRANSFER_CHECK}:
            return []
        tag, candidates = self.find_memory_ramp_candidates(q, limit=1)
        if not tag:
            return []
        delay = 2 if tag == QUESTION_TAG_RETRIEVAL_RAMP else 3
        return self._insert_delayed_followup_questions(q, candidates, tag, delay_slots=delay)

    def find_wrong_answer_memory_candidates(
        self, q: QuestionRuntimeState, limit: int = 1
    ) -> list[QuestionRuntimeState]:
        wrong_labels = [
            self._choice_concept_label(str(q.get("choices", {}).get(letter, "")))
            for letter in q.get("selected", [])
            if letter not in q.get("correct", [])
        ]
        correct_labels = [
            self._choice_concept_label(str(q.get("choices", {}).get(letter, ""))) for letter in q.get("correct", [])
        ]
        wrong_labels = [label for label in wrong_labels if label]
        correct_labels = [label for label in correct_labels if label]
        if not wrong_labels or not correct_labels:
            return []
        kind, unit = self._coverage_unit_for_question(q)
        unit_key = f"{kind}::{unit}"
        current_qnums = {item.get("question_number") for item in self.questions}
        records = self._progress_questions()
        topics = {str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()}
        ranked = []
        for candidate in self.master_questions:
            qnum = candidate.get("question_number")
            if qnum == q.get("question_number") or qnum in current_qnums:
                continue
            rec = records.get(self._question_key(candidate), {})
            if is_suspended(rec):
                continue
            cand_kind, cand_unit = self._coverage_unit_for_question(candidate)
            candidate_topics = {str(topic).strip() for topic in candidate.get("topics", []) if str(topic).strip()}
            same_unit = f"{cand_kind}::{cand_unit}" == unit_key
            shared_topics = len(topics & candidate_topics)
            wrong_match = sum(1 for label in wrong_labels if self._question_mentions_label(candidate, label))
            correct_match = sum(1 for label in correct_labels if self._question_mentions_label(candidate, label))
            if not same_unit and not shared_topics and not wrong_match and not correct_match:
                continue
            score = (
                wrong_match * 7
                + correct_match * 6
                + (5 if same_unit else 0)
                + shared_topics * 3
                + (3 if int(rec.get("attempts", 0)) <= 0 else 0)
                + int(rec.get("wrong_count", 0))
                - int(rec.get("correct_streak", 0)) * 0.3
            )
            ranked.append((score, int(qnum or 0), candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        return [candidate for _score, _qnum, candidate in ranked[:limit]]

    def maybe_queue_wrong_answer_memory(self, q: QuestionRuntimeState) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        if str(q.get("session_tag") or "") == QUESTION_TAG_WRONG_ANSWER_MEMORY:
            return []
        candidates = self.find_wrong_answer_memory_candidates(q, limit=1)
        return self._insert_followup_questions(q, candidates, QUESTION_TAG_WRONG_ANSWER_MEMORY)

    def find_confusion_pair_candidates(self, q: QuestionRuntimeState, limit: int = 1) -> list[QuestionRuntimeState]:
        wrong_labels = [
            self._choice_concept_label(str(q.get("choices", {}).get(letter, "")))
            for letter in q.get("selected", [])
            if letter not in q.get("correct", [])
        ]
        correct_labels = [
            self._choice_concept_label(str(q.get("choices", {}).get(letter, ""))) for letter in q.get("correct", [])
        ]
        wrong_labels = [label for label in wrong_labels if label]
        correct_labels = [label for label in correct_labels if label]
        if not wrong_labels or not correct_labels:
            return []
        records = self._progress_questions()
        current_qnums = {item.get("question_number") for item in self.questions}
        topics = {str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()}
        domain = q.get("domain")
        ranked = []
        for candidate in self.master_questions:
            qnum = candidate.get("question_number")
            if qnum == q.get("question_number") or qnum in current_qnums:
                continue
            rec = records.get(self._question_key(candidate), {})
            if is_suspended(rec):
                continue
            match_score = 0
            for label in wrong_labels:
                if self._question_mentions_label(candidate, label):
                    match_score += 3
            for label in correct_labels:
                if self._question_mentions_label(candidate, label):
                    match_score += 4
            candidate_topics = {str(topic).strip() for topic in candidate.get("topics", []) if str(topic).strip()}
            shared_topics = len(topics & candidate_topics)
            same_domain = 1 if domain and candidate.get("domain") == domain else 0
            if match_score <= 0 and not shared_topics and not same_domain:
                continue
            score = (
                match_score * 4
                + shared_topics * 5
                + same_domain * 3
                + (2 if is_active_weak(rec) else 0)
                + (1 if is_review_due(rec) else 0)
                - int(rec.get("attempts", 0)) * 0.06
            )
            ranked.append((score, int(qnum or 0), candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        return [candidate for _score, _qnum, candidate in ranked[:limit]]

    def maybe_queue_confusion_pair_drill(self, q: QuestionRuntimeState) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        candidates = self.find_confusion_pair_candidates(q, limit=1)
        return self._insert_followup_questions(q, candidates, QUESTION_TAG_CONFUSION_PAIR)

    def _domain_wrong_streak(self, domain: str) -> int:
        streak = 0
        for entry in reversed(self.session_answer_history):
            if entry.get("domain") != domain or entry.get("correct"):
                break
            streak += 1
        return streak

    def maybe_trigger_streak_rescue(self, q: QuestionRuntimeState) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        domain = q.get("domain") or ""
        if not domain or domain in self.rescue_domains_triggered:
            return []
        if self._domain_wrong_streak(domain) < 2:
            return []
        records = self._progress_questions()
        current_qnums = {item.get("question_number") for item in self.questions}
        ranked = []
        for candidate in self.master_questions:
            qnum = candidate.get("question_number")
            if qnum == q.get("question_number") or qnum in current_qnums:
                continue
            if candidate.get("domain") != domain:
                continue
            rec = records.get(self._question_key(candidate), {})
            if is_suspended(rec):
                continue
            score = (
                (4 if is_active_weak(rec) else 0)
                + (3 if is_review_due(rec) else 0)
                + int(rec.get("wrong_count", 0))
                - int(rec.get("correct_streak", 0))
            )
            ranked.append((score, qnum, candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        inserted = self._insert_followup_questions(
            q, [candidate for _score, _qnum, candidate in ranked[:3]], f"{QUESTION_TAG_STREAK_RESCUE_PREFIX}{domain}"
        )
        if inserted:
            self.rescue_domains_triggered.add(domain)
        return inserted

    def repair_concept_key_for_question(self, q: QuestionRuntimeState) -> str:
        kind, unit = self._coverage_unit_for_question(q)
        return f"{kind}::{unit}"

    def progress_repair_state(self) -> dict[str, Any]:
        meta = self.progress_data.setdefault("meta", {})
        state = meta.setdefault("repair_state", {})
        return state if isinstance(state, dict) else {}

    def normalize_progress_repair_state(self) -> bool:
        meta = self.progress_data.setdefault("meta", {})
        state = meta.get("repair_state")
        if not isinstance(state, dict):
            meta["repair_state"] = {}
            return False
        source_questions = []
        master_questions = list(getattr(self, "master_questions", []) or [])
        data = getattr(self, "data", None)
        if master_questions:
            source_questions = master_questions
        elif isinstance(data, dict):
            source_questions = list(data.get("questions") or [])
        by_qnum = {
            int(question.get("question_number") or 0): question
            for question in source_questions
            if int(question.get("question_number") or 0)
        }
        normalized: dict[str, dict[str, Any]] = {}
        changed = False
        for raw_key, raw_row in state.items():
            row = dict(raw_row or {})
            qnum = int(row.get("last_question_number") or 0)
            question = by_qnum.get(qnum)
            if question:
                canonical_key = self.repair_concept_key_for_question(question)
                row_key = str(row.get("concept_key") or raw_key or "")
                if row_key != canonical_key or str(raw_key) != canonical_key:
                    row["legacy_repair_concept_key"] = row_key
                    row["concept_key"] = canonical_key
                    changed = True
                normalized[canonical_key] = row
                continue
            normalized[str(raw_key)] = row
        if changed or normalized != state:
            meta["repair_state"] = normalized
            return True
        return False

    def plan_misconception_repair(self, q: QuestionRuntimeState, is_correct: bool) -> list[QuestionRuntimeState]:
        if self.active_session_mode == MODE_EXAM:
            return []
        concept_key = self.repair_concept_key_for_question(q)
        state = self.progress_repair_state()
        row = dict(state.get(concept_key) or {})
        active_repair = bool(row) or bool(q.get("repair_stage")) or bool(q.get("repair_concept_key"))
        row["concept_key"] = concept_key
        row["last_question_number"] = int(q.get("question_number") or 0)
        row["last_seen"] = time.strftime("%Y-%m-%d")
        root_cause = str(q.get("smart_root_cause") or "")
        supporting = [str(value) for value in q.get("smart_supporting_concepts", [])]
        if not is_correct and root_cause == "missing_prerequisite" and supporting:
            candidates = [
                candidate
                for candidate in self.master_questions
                if concept_key_for_question(candidate)[0] in set(supporting)
                and int(candidate.get("question_number") or 0) != int(q.get("question_number") or 0)
            ]
            inserted = self._insert_delayed_followup_questions(q, candidates, "Prerequisite repair", delay_slots=1)
            if inserted:
                for item in inserted:
                    item["repair_stage"] = "contrast"
                    item["repair_concept_key"] = supporting[0]
                row["stage"] = "contrast"
                row["status"] = "unresolved"
                row["scheduled_tag"] = "Prerequisite repair"
                state[concept_key] = row
                return inserted
        if not is_correct and root_cause == "transfer_failure":
            candidates = [
                candidate
                for candidate in self.find_question_twins(q, limit=3)
                if int(candidate.get("question_number") or 0) != int(q.get("question_number") or 0)
            ]
            inserted = self._insert_delayed_followup_questions(q, candidates, "Transfer repair", delay_slots=2)
            if inserted:
                for item in inserted:
                    item["repair_stage"] = "transfer"
                    item["repair_concept_key"] = concept_key
                row["stage"] = "transfer"
                row["status"] = "provisional"
                row["scheduled_tag"] = "Transfer repair"
                state[concept_key] = row
                return inserted
        if is_correct:
            if not active_repair:
                return []
            current_stage = str(q.get("repair_stage") or row.get("stage") or "")
            if current_stage == "spaced_retrieval":
                row["status"] = "resolved"
                row["stage"] = "spaced_retrieval"
                row["resolved_at_question"] = int(q.get("question_number") or 0)
            elif str(row.get("status") or "") in {"unresolved", "blocked", ""}:
                row["status"] = "provisional"
                row["stage"] = "transfer"
                tag, candidates = self.find_memory_ramp_candidates(q, limit=1)
                if not candidates:
                    candidates = self.find_question_twins(q, limit=1)
                    tag = QUESTION_TAG_TRANSFER_CHECK
                inserted = self._insert_delayed_followup_questions(q, candidates, tag or QUESTION_TAG_TRANSFER_CHECK, delay_slots=3)
                if inserted:
                    for item in inserted:
                        item["repair_stage"] = "transfer"
                        item["repair_concept_key"] = concept_key
                    row["scheduled_transfer_qnums"] = [int(item.get("question_number") or 0) for item in inserted]
                else:
                    row["blocked_reason"] = "no_distinct_transfer_candidate"
                    row["stage"] = "spaced_retrieval"
                state[concept_key] = row
                q["repair_stage"] = str(row.get("stage") or "")
                q["repair_concept_key"] = concept_key
                return inserted
            elif current_stage == "transfer":
                row["status"] = "provisional"
                row["stage"] = "spaced_retrieval"
                row["spaced_retrieval_due"] = True
            state[concept_key] = row
            q["repair_stage"] = str(row.get("stage") or "")
            q["repair_concept_key"] = concept_key
            return []

        row["stage"] = "contrast"
        row["status"] = "unresolved"
        row["attempts"] = int(row.get("attempts") or 0) + 1
        q["repair_stage"] = "contrast"
        q["repair_concept_key"] = concept_key
        repair_options = (
            (QUESTION_TAG_CONFUSION_PAIR, self.maybe_queue_confusion_pair_drill),
            (QUESTION_TAG_WRONG_ANSWER_MEMORY, self.maybe_queue_wrong_answer_memory),
            (QUESTION_TAG_TWIN, self.maybe_queue_question_twins),
        )
        for tag, queue_followup in repair_options:
            inserted = queue_followup(q)
            if inserted:
                for item in inserted:
                    item["repair_stage"] = "contrast"
                    item["repair_concept_key"] = concept_key
                row["stage"] = "contrast"
                row["scheduled_tag"] = tag
                row["scheduled_question_numbers"] = [int(item.get("question_number") or 0) for item in inserted]
                state[concept_key] = row
                return inserted
        row["status"] = "blocked"
        row["stage"] = "spaced_retrieval"
        row["spaced_retrieval_due"] = True
        row["blocked_reason"] = "no_distinct_followup_candidate"
        state[concept_key] = row
        return []

    def _record_answer(
        self,
        q: QuestionRuntimeState,
        selected: list[str],
        anchor_widget=None,
        feedback_override: dict[str, Any] | None = None,
    ):
        rec_before = self._progress_record(q, create=False)
        was_active_weak = is_active_weak(rec_before)
        was_due = is_review_due(rec_before)
        response_seconds = 0.0
        if getattr(self, "active_question_started_qnum", None) == q.get("question_number") and getattr(
            self, "active_question_started_at", None
        ):
            response_seconds = round(max(0.2, time.time() - self.active_question_started_at), 1)
        recent_times = [
            float(event.get("effective_response_seconds", event.get("response_seconds", 0.0)) or 0.0)
            for event in self.session_answer_history[-12:]
        ]
        timing = sanitize_response_time(response_seconds, recent_effective_seconds=recent_times)
        q["selected"] = list(selected)
        q["pending"] = list(selected)
        q["answered"] = True
        q["recall_ready"] = False
        self.mark_question_list_dirty()
        if feedback_override is not None:
            feedback = dict(feedback_override)
        else:
            feedback = self._collect_answer_feedback(q, self._question_correct(q))
        feedback.update(timing)
        feedback["response_seconds"] = timing["effective_response_seconds"]
        feedback["was_due"] = was_due
        feedback["was_active_weak"] = was_active_weak
        q["last_confidence"] = feedback.get("confidence", "")
        q["last_miss_reason"] = feedback.get("miss_reason", "")
        is_correct = self._question_correct(q)
        recall_failure = self.classify_recall_failure(q, is_correct, feedback)
        deciding_clue = self.deciding_clue_for_question(q)
        feedback["recall_failure"] = recall_failure
        feedback["deciding_clue"] = deciding_clue
        self.update_progress_for_answer(q, feedback=feedback)
        event: SessionAnswerEvent = {
            "question_number": int(q.get("question_number") or 0),
            "domain": q.get("domain") or "",
            "correct": bool(is_correct),
            "confidence": q.get("last_confidence", ""),
            "miss_reason": q.get("last_miss_reason", ""),
            "recall_failure": recall_failure,
            "deciding_clue": deciding_clue,
            "was_active_weak": bool(was_active_weak),
            "was_due": bool(was_due),
            "response_seconds": float(timing["effective_response_seconds"]),
            "raw_response_seconds": float(timing["raw_response_seconds"]),
            "effective_response_seconds": float(timing["effective_response_seconds"]),
            "response_time_contaminated": bool(timing["response_time_contaminated"]),
            "session_tag": q.get("session_tag", ""),
            "smart_primary_role": str(q.get("smart_primary_role") or ""),
            "smart_selection_reasons": list(q.get("smart_selection_reasons") or []),
            "smart_utility": float(q.get("smart_utility", 0.0) or 0.0),
            "repair_stage": str(q.get("repair_stage") or ""),
            "repair_concept_key": str(q.get("repair_concept_key") or ""),
            "prediction_id": str(q.get("prediction_id") or ""),
            "smart_policy_id": str(q.get("smart_policy_id") or ""),
            "smart_policy_version": str(q.get("smart_policy_version") or ""),
            "smart_concept_key": str(q.get("smart_concept_key") or ""),
            "smart_root_cause": str(q.get("smart_root_cause") or ""),
            "smart_root_cause_confidence": float(q.get("smart_root_cause_confidence", 0.0) or 0.0),
            "smart_supporting_concepts": [str(value) for value in q.get("smart_supporting_concepts", [])],
            "smart_graph_version": str(q.get("smart_graph_version") or ""),
            "smart_information_value": float(q.get("smart_information_value", 0.0) or 0.0),
            "smart_information_breakdown": dict(q.get("smart_information_breakdown") or {}),
            "smart_question_quality_status": str(q.get("smart_question_quality_status") or ""),
            "smart_question_quality_confidence": float(q.get("smart_question_quality_confidence", 0.0) or 0.0),
            "smart_graph_bottleneck": float(q.get("smart_graph_bottleneck", 0.0) or 0.0),
        }
        self.session_answer_history.append(event)
        self.active_question_started_qnum = None
        self.active_question_started_at = None
        xp_gained = self._apply_xp_for_answer(q, is_correct, feedback, was_active_weak=was_active_weak, was_due=was_due)
        q["last_xp_gained"] = int(xp_gained)
        if not is_correct:
            self.plan_misconception_repair(q, is_correct=False)
        else:
            repair_inserted = self.plan_misconception_repair(q, is_correct=True)
            self.maybe_trigger_stealth_checkpoint(q)
            if not repair_inserted:
                inserted = self.maybe_queue_memory_ramp(q)
                if not inserted:
                    self.maybe_queue_delayed_recall_probe(q)
        self.schedule_progress_save()
        self.maybe_trigger_boss_round(q)
        self.refresh_session_quests()
        self._unlock_quest_rewards()
        self.schedule_session_save(delay_ms=125)
        self.maybe_save_checkpoint()
        self.unlock_session_rewards()
        self.render_question()
        self.show_answer_feedback_chip(q, is_correct, xp_gained, was_active_weak=was_active_weak, was_due=was_due)
        self.maybe_finish_session()
        self.maybe_auto_next_after_answer(q)
        self.schedule_smart_practice_prewarm(delay_ms=2800)

    def on_listbox_select(self, event=None):
        if not self.visible_indices:
            return
        sel = self.question_list.curselection()
        if not sel:
            return
        pos = sel[0]
        if pos >= len(self.visible_indices):
            return
        self.index = self.visible_indices[pos]
        self._render_current_view()

    def jump_to_question(self):
        raw = self.jump_var.get().strip()
        if not raw:
            return
        try:
            qnum = int(raw)
        except ValueError:
            messagebox.showerror("Invalid input", "Enter a numeric question number.")
            return
        for idx, q in enumerate(self.questions):
            if q.get("question_number") == qnum:
                self._set_current_index(idx)
                return
        messagebox.showinfo("Not found", f"Question {qnum} was not found in this session.")

    def apply_status_filter(self, status):
        self.status_filter_var.set(self.normalize_status_filter(status))
        self.refresh_question_list()
        if self.visible_indices:
            self.index = self.visible_indices[0]
            self._render_current_view()

    def current_question(self) -> QuestionRuntimeState:
        return self.questions[self.index]

    def toggle_choice(self, letter, anchor_widget=None):
        if not self.questions:
            return
        q = self.current_question()
        if letter not in q.get("choices", {}) or not q["choices"].get(letter) or q.get("answered"):
            return
        pending = list(q.get("pending", []))
        if q.get("question_type") == "multi":
            if letter in pending:
                pending.remove(letter)
            else:
                pending.append(letter)
                pending.sort()
            q["pending"] = pending
            self._render_current_view()
        else:
            q["pending"] = [letter]
            anchor_widget = anchor_widget or self.choice_rows.get(letter).outer
            self._record_answer(q, [letter], anchor_widget=anchor_widget)

    def submit_answer(self):
        if not self.questions:
            return
        q = self.current_question()
        if q.get("answered"):
            return
        pending = list(q.get("pending", []))
        if not pending:
            messagebox.showinfo("No selection", "Pick at least one answer before submitting.")
            return
        self._record_answer(q, pending, anchor_widget=self.submit_btn)

    def retag_current_answer_confidence(self, confidence):
        if not self.questions:
            return
        q = self.current_question()
        if not q.get("answered"):
            return
        self.cancel_auto_next_after_answer()
        rec = self._progress_record(q, create=True)
        old_conf = str(rec.get("last_confidence") or q.get("last_confidence") or "Sure")
        new_conf = str(confidence or "Sure")
        if old_conf != new_conf:
            conf_counts = dict(rec.get("confidence_counts") or {})
            if old_conf:
                conf_counts[old_conf] = max(0, int(conf_counts.get(old_conf, 0)) - 1)
            conf_counts[new_conf] = int(conf_counts.get(new_conf, 0)) + 1
            rec["confidence_counts"] = conf_counts
            old_reason = str(rec.get("last_miss_reason") or "")
            new_reason = self._infer_miss_reason_from_confidence(new_conf, self._question_correct(q))
            miss_counts = dict(rec.get("miss_reason_counts") or {})
            if old_reason:
                miss_counts[old_reason] = max(0, int(miss_counts.get(old_reason, 0)) - 1)
            if new_reason:
                miss_counts[new_reason] = int(miss_counts.get(new_reason, 0)) + 1
            rec["miss_reason_counts"] = miss_counts
            rec["last_confidence"] = new_conf
            rec["last_miss_reason"] = new_reason
            q["last_confidence"] = new_conf
            q["last_miss_reason"] = new_reason
            for event in reversed(self._progress_history()):
                if int(event.get("question_number") or 0) == int(q.get("question_number") or 0):
                    event["confidence"] = new_conf
                    event["miss_reason"] = new_reason
                    break
            self._progress_questions()[self._question_key(q)] = rec
            self.mark_question_list_dirty()
            self.schedule_progress_save()
            self.schedule_session_save(delay_ms=125)
        if self._go_to_next_unanswered_silent():
            return
        self.render_question()

    def mark_current_question_super_confident(self):
        if not self.questions:
            return
        q = self.current_question()
        if not q.get("answered") or not self._question_correct(q):
            return
        self.cancel_auto_next_after_answer()
        rec = set_progress_super_confident(self._progress_record(q, create=True))
        q["last_confidence"] = str(rec.get("last_confidence") or "Sure")
        q["last_miss_reason"] = ""
        for event in reversed(self._progress_history()):
            if int(event.get("question_number") or 0) == int(q.get("question_number") or 0):
                event["confidence"] = "Sure"
                event["miss_reason"] = ""
                break
        self._progress_questions()[self._question_key(q)] = rec
        self.mark_question_list_dirty()
        self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=350)
        self.schedule_progress_save()
        self.schedule_session_save(delay_ms=125)
        if self._go_to_next_unanswered_silent():
            return
        self.render_question()

    def _go_to_next_unanswered_silent(self):
        if not self.questions:
            return False
        total = len(self.questions)
        for step in range(1, total + 1):
            idx = (self.index + step) % total
            if not self._question_resolved_for_finish(self.questions[idx]):
                self._set_current_index(idx)
                return True
        return False

    def _question_resolved_for_finish(self, q):
        return bool(q.get("answered") or q.get("flagged") or q.get("suspended"))

    def _all_session_questions_resolved_for_finish(self):
        return bool(self.questions) and all(self._question_resolved_for_finish(q) for q in self.questions)

    def finish_exam(self):
        if self.active_session_mode != MODE_EXAM:
            if not self._all_session_questions_resolved_for_finish():
                messagebox.showinfo(
                    "Finish set",
                    "Answer, flag, or suspend every question in this set before finishing.",
                )
                return
            self.maybe_finish_session(force=True)
            self.open_analytics_window()
            return
        self.exam_reveal = True
        self._render_current_view()
        self.maybe_finish_session(force=True)
        self.open_analytics_window()

    def toggle_flag(self):
        q = self.current_question()
        q["flagged"] = not q.get("flagged", False)
        self.update_progress_for_flag(q)
        self.mark_question_list_dirty()
        self.schedule_session_save()
        self._render_current_view(save_session=False)

    def toggle_suspend(self):
        q = self.current_question()
        q["suspended"] = not q.get("suspended", False)
        self.update_progress_for_suspended(q)
        self.mark_question_list_dirty()
        if q.get("suspended"):
            for idx, candidate in enumerate(self.questions):
                rec = self._progress_record(candidate, create=False)
                if idx != self.index and not is_suspended(rec):
                    self.index = idx
                    break
        self.schedule_session_save()
        self._render_current_view(save_session=False)

    def redo_question(self):
        if not self.questions:
            return
        q = self.current_question()
        if not q.get("answered"):
            return
        if self.active_session_mode == MODE_EXAM and not self.exam_reveal:
            messagebox.showinfo("Exam mode", "Finish the exam before redoing recorded answers.")
            return
        clear_runtime_answer_state(q)
        self.mark_question_list_dirty()
        self.schedule_session_save()
        self._render_current_view(save_session=False)

    def prev_question(self):
        if self.index > 0:
            self._set_current_index(self.index - 1)

    def next_question(self):
        if self.index < len(self.questions) - 1:
            self._set_current_index(self.index + 1)

    def next_unanswered(self):
        if self._go_to_next_unanswered_silent():
            return
        messagebox.showinfo("Next unanswered", "All questions in this session are answered, flagged, or suspended.")

    def maybe_auto_next_after_answer(self, q):
        if not self.auto_next_correct_var.get():
            return
        if self.active_session_mode == MODE_EXAM:
            return
        if not self._question_correct(q):
            return
        if self.index >= len(self.questions) - 1:
            return
        self.cancel_auto_next_after_answer()
        self.auto_next_after_id = self.root.after(650, self._auto_next_after_answer)

    def _auto_next_after_answer(self):
        self.auto_next_after_id = None
        self.next_question()

    def cancel_auto_next_after_answer(self):
        after_id = getattr(self, "auto_next_after_id", None)
        if after_id:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
            self.auto_next_after_id = None

    def format_choice_explanations(self, q):
        selected = sorted(q.get("selected", []))
        correct = sorted(q.get("correct", []))
        explanations = q.get("choice_explanations", {}) or {}
        lines = [
            f"Selected: {', '.join(selected) if selected else 'none'}",
            f"Keyed answer: {', '.join(correct) if correct else 'none'}",
            "",
        ]
        for letter in ["A", "B", "C", "D", "E", "F"]:
            if not q.get("choices", {}).get(letter):
                continue
            tags = []
            if letter in selected:
                tags.append("selected")
            if letter in correct:
                tags.append("correct")
            suffix = f" ({', '.join(tags)})" if tags else ""
            detail = str(explanations.get(letter, "")).strip() or "No choice-specific explanation."
            lines.append(f"{letter}{suffix}: {detail}")
        return "\n".join(lines)

    def clean_inline_choice_explanation(self, detail):
        detail = str(detail or "").strip()
        noise_patterns = [
            r"^(correct|incorrect)\s+(option|answer)\.\s*",
            r"^the\s+source\s+key\s+marks\s+[a-f]\s+as\s+(correct|incorrect)\.\s*",
        ]
        changed = True
        while changed:
            changed = False
            for pattern in noise_patterns:
                detail, count = re.subn(pattern, "", detail, count=1, flags=re.IGNORECASE)
                if count:
                    detail = detail.strip()
                    changed = True
        return detail or "No choice-specific explanation."
