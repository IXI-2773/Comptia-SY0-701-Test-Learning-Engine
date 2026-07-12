import copy
import unittest

from smart_practice_core import (
    SmartPracticeCandidate,
    build_smart_practice_score,
    build_smart_practice_selection,
)
from smart_practice_profile import SMART_PRACTICE_SCORING, UTILITY_COMPONENT_BOUNDS


class SmartPracticeCoreTests(unittest.TestCase):
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
        )

        ordered_qnums = [question["question_number"] for question in result.ordered_questions]
        seed_qnums = [question["question_number"] for question in result.role_seed_questions]

        self.assertEqual([1, 2, 3, 4, 5], seed_qnums)
        self.assertEqual(seed_qnums, ordered_qnums)
        self.assertFalse(result.retry_used)
        self.assertGreater(result.quality_score, 0.0)


if __name__ == "__main__":
    unittest.main()
