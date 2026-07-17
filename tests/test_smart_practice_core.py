import copy
import unittest

from app_question_flow_mixin import QuestionFlowMixin
from progress_store import set_progress_super_confident, update_progress_record
from session_models import reset_runtime_question_state
from smart_practice_core import (
    SmartPracticeCandidate,
    build_smart_practice_score,
    build_smart_practice_selection,
)
from smart_practice_profile import SMART_PRACTICE_SCORING, UTILITY_COMPONENT_BOUNDS


class _HeadlessFollowupHarness(QuestionFlowMixin):
    def __init__(self, questions, *, progress_questions=None):
        self.master_questions = copy.deepcopy(questions)
        self.questions = [copy.deepcopy(self.master_questions[0])]
        self.index = 0
        self.session_question_limit = None
        self.progress_data = {"questions": copy.deepcopy(progress_questions or {}), "history": [], "meta": {}}
        self.last_question_list_signature = None
        for question in self.master_questions:
            reset_runtime_question_state(question)
        for question in self.questions:
            reset_runtime_question_state(question)

    def _clone_questions(self, questions):
        return copy.deepcopy(questions)

    def _reset_runtime_question_state(self, questions):
        for question in questions:
            reset_runtime_question_state(question)

    def refresh_session_runtime_identity(self):
        return None

    def _question_key(self, question):
        return str(question.get("question_number"))

    def _progress_questions(self):
        return self.progress_data.setdefault("questions", {})


class SmartPracticeCoreTests(unittest.TestCase):
    def _question(self, qnum, *, topic="Topic 1"):
        return {
            "question_number": qnum,
            "prompt": f"Question {qnum}",
            "choices": {"A": "Correct", "B": "Wrong"},
            "correct": ["A"],
            "domain": "Domain A",
            "topics": [topic],
        }

    def test_build_smart_practice_score_returns_payload_without_mutating_question(self):
        question = {
            "question_number": 101,
            "domain": "Security Operations",
            "topic": "Monitoring",
            "source_name": "Guide",
        }
        original = copy.deepcopy(question)
        meta = {
            "record": {"attempts": 0, "correct_streak": 0, "wrong_count": 0, "correct_count": 0},
            "unit_key": "topic::monitoring",
            "stem_style": "single_answer",
            "objective_code": "OBJ-1",
            "source_name": "Guide",
            "base_concept_key": "concept.monitoring",
        }
        context = {
            "profile": SMART_PRACTICE_SCORING,
            "active_smart_policy": {"policy_id": "policy-a"},
            "graph_enabled": False,
            "quality_enabled": False,
            "information_enabled": False,
            "source_map": {},
            "utility_scales": {},
            "utility_bounds": UTILITY_COMPONENT_BOUNDS,
            "role_shares": {},
            "active_policy_values": {},
        }

        result = build_smart_practice_score(question, qnum=101, meta=meta, context=context)

        self.assertEqual(question, original)
        self.assertEqual("blueprint_coverage", result.primary_role)
        self.assertEqual("policy-a", result.question_updates["smart_policy_id"])
        self.assertEqual("insufficient_evidence", result.question_updates["smart_root_cause"])
        self.assertIn("smart_runtime_policy_controls", result.question_updates)
        self.assertEqual("101:policy-a", result.information_history_entry["record_id"])

    def test_build_smart_practice_selection_keeps_role_mix_for_small_targets(self):
        candidates = [
            SmartPracticeCandidate(
                question={"question_number": 1, "smart_primary_role": "weak_repair"},
                qnum=1,
                priority=90.0,
                selection_bonus=0.0,
                primary_role="weak_repair",
                objective_code="OBJ-1",
                source_label="Bank A",
                primary_topic="T1",
                normalized_domain="d1",
                raw_domain="D1",
                attempts=1,
                is_unseen=False,
                is_active_weak=True,
                is_due=False,
                is_mastered=False,
                is_super_confident=False,
                last_seen="2026-07-01",
                recent_selection_pressure=0.0,
                eligibility_tier=1,
                duplicate_group_key="qnum::1",
            ),
            SmartPracticeCandidate(
                question={"question_number": 2, "smart_primary_role": "due_retention"},
                qnum=2,
                priority=88.0,
                selection_bonus=0.0,
                primary_role="due_retention",
                objective_code="OBJ-2",
                source_label="Bank A",
                primary_topic="T2",
                normalized_domain="d1",
                raw_domain="D1",
                attempts=1,
                is_unseen=False,
                is_active_weak=False,
                is_due=True,
                is_mastered=False,
                is_super_confident=False,
                last_seen="2026-07-01",
                recent_selection_pressure=0.0,
                eligibility_tier=1,
                duplicate_group_key="qnum::2",
            ),
            SmartPracticeCandidate(
                question={"question_number": 3, "smart_primary_role": "blueprint_coverage"},
                qnum=3,
                priority=86.0,
                selection_bonus=0.0,
                primary_role="blueprint_coverage",
                objective_code="OBJ-3",
                source_label="Bank B",
                primary_topic="T3",
                normalized_domain="d2",
                raw_domain="D2",
                attempts=0,
                is_unseen=True,
                is_active_weak=False,
                is_due=False,
                is_mastered=False,
                is_super_confident=False,
                last_seen="",
                recent_selection_pressure=0.0,
                eligibility_tier=1,
                duplicate_group_key="qnum::3",
            ),
            SmartPracticeCandidate(
                question={"question_number": 4, "smart_primary_role": "transfer"},
                qnum=4,
                priority=84.0,
                selection_bonus=0.0,
                primary_role="transfer",
                objective_code="OBJ-4",
                source_label="Bank B",
                primary_topic="T4",
                normalized_domain="d2",
                raw_domain="D2",
                attempts=1,
                is_unseen=False,
                is_active_weak=False,
                is_due=False,
                is_mastered=False,
                is_super_confident=False,
                last_seen="2026-06-20",
                recent_selection_pressure=0.0,
                eligibility_tier=2,
                duplicate_group_key="qnum::4",
            ),
            SmartPracticeCandidate(
                question={"question_number": 5, "smart_primary_role": "controlled_stretch"},
                qnum=5,
                priority=82.0,
                selection_bonus=0.0,
                primary_role="controlled_stretch",
                objective_code="OBJ-5",
                source_label="Bank C",
                primary_topic="T5",
                normalized_domain="d3",
                raw_domain="D3",
                attempts=3,
                is_unseen=False,
                is_active_weak=False,
                is_due=False,
                is_mastered=True,
                is_super_confident=False,
                last_seen="2026-06-10",
                recent_selection_pressure=0.0,
                eligibility_tier=3,
                duplicate_group_key="qnum::5",
            ),
        ]

        result = build_smart_practice_selection(
            candidates,
            candidates,
            target=5,
            role_shares={},
            objective_cap=2,
            profile=SMART_PRACTICE_SCORING,
            high_signal_qnums={1, 2},
            freshness_map={1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0},
            explicit_history_filter="All",
            session_intent={"label": "Build coverage"},
        )

        ordered_qnums = [question["question_number"] for question in result.ordered_questions]
        seed_qnums = [question["question_number"] for question in result.role_seed_questions]

        self.assertEqual([1, 2, 3, 4, 5], seed_qnums)
        self.assertEqual(seed_qnums, ordered_qnums)
        self.assertFalse(result.retry_used)
        self.assertGreater(result.quality_score, 0.0)
        self.assertEqual(1, result.audit["selected_unseen"])

    def test_super_confident_candidate_is_blocked_from_immediate_followup_insertion(self):
        questions = [self._question(1), self._question(2)]
        record = update_progress_record({}, ["A"], True, seen_on="2026-05-17", confidence="Sure")
        record = set_progress_super_confident(record, seen_on="2026-05-17", cooldown_days=120)
        harness = _HeadlessFollowupHarness(questions, progress_questions={"2": record})

        inserted = harness._insert_followup_questions(
            harness.questions[0], [harness.master_questions[1]], "Question twin"
        )

        self.assertEqual([], inserted)
        self.assertEqual([1], [question["question_number"] for question in harness.questions])

    def test_super_confident_candidate_is_blocked_from_delayed_followup_insertion(self):
        questions = [self._question(1), self._question(2)]
        record = update_progress_record({}, ["A"], True, seen_on="2026-05-17", confidence="Sure")
        record = set_progress_super_confident(record, seen_on="2026-05-17", cooldown_days=120)
        harness = _HeadlessFollowupHarness(questions, progress_questions={"2": record})

        inserted = harness._insert_delayed_followup_questions(
            harness.questions[0], [harness.master_questions[1]], "Delayed recall", delay_slots=2
        )

        self.assertEqual([], inserted)
        self.assertEqual([1], [question["question_number"] for question in harness.questions])

    def test_eligible_candidate_still_inserts_as_followup(self):
        questions = [self._question(1), self._question(2)]
        harness = _HeadlessFollowupHarness(questions)

        inserted = harness._insert_followup_questions(
            harness.questions[0], [harness.master_questions[1]], "Question twin"
        )

        self.assertEqual([2], [question["question_number"] for question in inserted])
        self.assertEqual([1, 2], [question["question_number"] for question in harness.questions])


if __name__ == "__main__":
    unittest.main()
