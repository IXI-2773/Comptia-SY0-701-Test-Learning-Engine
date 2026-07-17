import copy
import unittest

from progress_store import (
    is_active_weak,
    is_effective_super_confident_active,
    is_review_due,
    is_super_confident_active,
    normalize_progress_record,
    set_progress_super_confident,
    update_progress_record,
)
from session_models import answer_state_from_question, reset_runtime_question_state
from session_store import build_session_snapshot, migrate_session_snapshot


class SmartPracticeAuditTests(unittest.TestCase):
    def test_progress_transition_matrix_core_invariants(self):
        scenarios = [
            (
                "new_to_correct",
                {},
                lambda record: update_progress_record(record, ["A"], True, seen_on="2026-07-01", confidence="Sure"),
                {
                    "attempts": 1,
                    "correct_count": 1,
                    "wrong_count": 0,
                    "correct_streak": 1,
                    "is_active_weak": False,
                    "is_due": False,
                    "is_super_confident": False,
                },
            ),
            (
                "new_to_wrong",
                {},
                lambda record: update_progress_record(record, ["B"], False, seen_on="2026-07-01", confidence="Sure"),
                {
                    "attempts": 1,
                    "correct_count": 0,
                    "wrong_count": 1,
                    "correct_streak": 0,
                    "is_active_weak": True,
                    "is_due": True,
                    "is_super_confident": False,
                },
            ),
            (
                "correct_to_super_confident",
                update_progress_record({}, ["A"], True, seen_on="2026-07-01", confidence="Sure"),
                lambda record: set_progress_super_confident(record, seen_on="2026-07-01", cooldown_days=5),
                {
                    "attempts": 1,
                    "correct_count": 1,
                    "wrong_count": 0,
                    "correct_streak": 6,
                    "is_active_weak": False,
                    "is_due": False,
                    "is_super_confident": True,
                },
            ),
            (
                "super_confident_to_wrong",
                set_progress_super_confident(
                    update_progress_record({}, ["A"], True, seen_on="2026-07-01", confidence="Sure"),
                    seen_on="2026-07-01",
                    cooldown_days=5,
                ),
                lambda record: update_progress_record(record, ["B"], False, seen_on="2026-07-03", confidence="Sure"),
                {
                    "attempts": 2,
                    "correct_count": 1,
                    "wrong_count": 1,
                    "correct_streak": 0,
                    "is_active_weak": True,
                    "is_due": True,
                    "is_super_confident": False,
                },
            ),
        ]

        for name, initial, operation, expected in scenarios:
            with self.subTest(name=name):
                before = copy.deepcopy(initial)
                after = operation(initial)
                normalized = normalize_progress_record(after)

                self.assertEqual(before, initial)
                self.assertEqual(expected["attempts"], normalized["attempts"])
                self.assertEqual(expected["correct_count"], normalized["correct_count"])
                self.assertEqual(expected["wrong_count"], normalized["wrong_count"])
                self.assertEqual(expected["correct_streak"], normalized["correct_streak"])
                self.assertEqual(expected["is_active_weak"], is_active_weak(normalized))
                self.assertEqual(expected["is_due"], is_review_due(normalized, on_date="2026-07-03"))
                self.assertEqual(
                    expected["is_super_confident"], is_super_confident_active(normalized, on_date="2026-07-03")
                )
                self.assertGreaterEqual(normalized["attempts"], normalized["correct_count"] + normalized["wrong_count"])

    def test_super_confident_cooldown_boundary_and_expiry(self):
        record = set_progress_super_confident(
            update_progress_record({}, ["A"], True, seen_on="2026-07-01", confidence="Sure"),
            seen_on="2026-07-01",
            cooldown_days=5,
        )

        self.assertTrue(is_super_confident_active(record, on_date="2026-07-05"))
        self.assertFalse(is_super_confident_active(record, on_date="2026-07-06"))
        self.assertTrue(is_review_due(record, on_date="2026-07-06"))

    def test_contradictory_stale_super_confident_state_is_not_effectively_active(self):
        record = {
            "attempts": 1,
            "correct_count": 0,
            "wrong_count": 1,
            "correct_streak": 0,
            "last_correct": False,
            "next_review": "2026-07-01",
            "super_confident_until": "2026-12-31",
        }

        normalized = normalize_progress_record(record)

        self.assertTrue(is_super_confident_active(normalized, on_date="2026-07-16"))
        self.assertTrue(is_active_weak(normalized))
        self.assertTrue(is_review_due(normalized, on_date="2026-07-16"))
        self.assertFalse(is_effective_super_confident_active(normalized, on_date="2026-07-16"))

    def test_normalize_progress_record_repairs_legacy_impossible_counts_idempotently(self):
        legacy = {"attempts": -1, "correct_count": 5, "wrong_count": 4, "correct_streak": 9}

        first = normalize_progress_record(legacy)
        second = normalize_progress_record(first)

        self.assertEqual(first, second)
        self.assertEqual(9, first["attempts"])
        self.assertEqual(5, first["correct_count"])
        self.assertEqual(4, first["wrong_count"])
        self.assertEqual(9, first["correct_streak"])

    def test_session_snapshot_round_trip_preserves_followup_and_repair_metadata(self):
        question = {
            "question_number": 7,
            "prompt": "Question 7",
            "choices": {"A": "Correct", "B": "Wrong"},
            "correct": ["A"],
            "selected": ["A"],
            "pending": ["A"],
            "answered": True,
            "session_tag": "Question twin",
            "repair_stage": "contrast",
            "repair_concept_key": "concept.7",
            "prediction_id": "pred-7",
        }
        reset_runtime_question_state(question)
        question["selected"] = ["A"]
        question["pending"] = ["A"]
        question["answered"] = True
        question["session_tag"] = "Question twin"
        question["repair_stage"] = "contrast"
        question["repair_concept_key"] = "concept.7"
        question["prediction_id"] = "pred-7"
        snapshot = build_session_snapshot(
            app_version="8.0.0",
            bank_file="bank.json",
            mode="Smart Practice",
            builder_context={
                "mode": "Smart Practice",
                "count": "25",
                "source_label": "Full bank",
                "session_source": "All",
                "randomize": False,
                "domain_filter": "All domains",
                "topic_filter": "All topics",
                "status_filter": "All questions",
            },
            source_label="Full bank",
            question_numbers=[7],
            restore_question_numbers=[7],
            session_base_question_count=1,
            session_question_limit=1,
            current_index=0,
            elapsed_seconds=15,
            exam_reveal=True,
            checkpoints_saved=[],
            session_rewards=[],
            unlocked_rewards=[],
            session_answer_history=[
                {
                    "question_number": 7,
                    "domain": "Domain",
                    "correct": True,
                    "confidence": "Sure",
                    "miss_reason": "",
                    "recall_failure": "",
                    "deciding_clue": "",
                    "was_active_weak": False,
                    "was_due": False,
                    "response_seconds": 3.0,
                    "raw_response_seconds": 3.0,
                    "effective_response_seconds": 3.0,
                    "response_time_contaminated": False,
                    "session_tag": "Question twin",
                    "smart_primary_role": "",
                    "smart_selection_reasons": [],
                    "smart_utility": 0.0,
                    "repair_stage": "contrast",
                    "repair_concept_key": "concept.7",
                    "prediction_id": "pred-7",
                }
            ],
            current_quests=[],
            quest_completion_keys=[],
            session_boss_markers=[],
            session_stealth_markers=[],
            session_xp_gained=0,
            answers=[answer_state_from_question(question)],
        )

        restored = migrate_session_snapshot(snapshot, "Smart Practice", [7])

        self.assertEqual("Question twin", restored["answers"][0]["session_tag"])
        self.assertEqual("contrast", restored["answers"][0]["repair_stage"])
        self.assertEqual("concept.7", restored["answers"][0]["repair_concept_key"])
        self.assertEqual("pred-7", restored["answers"][0]["prediction_id"])
        self.assertEqual("Question twin", restored["session_answer_history"][0]["session_tag"])
        self.assertEqual("pred-7", restored["session_answer_history"][0]["prediction_id"])

    def test_session_snapshot_rejects_invalid_builder_context_and_negative_elapsed(self):
        with self.assertRaisesRegex(ValueError, "builder_context"):
            migrate_session_snapshot(
                {
                    "mode": "Smart Practice",
                    "question_numbers": [1],
                    "restore_question_numbers": [1],
                    "answers": [],
                    "builder_context": "bad",
                },
                "Smart Practice",
                [1],
            )
        with self.assertRaisesRegex(ValueError, "elapsed_seconds"):
            migrate_session_snapshot(
                {
                    "mode": "Smart Practice",
                    "question_numbers": [1],
                    "restore_question_numbers": [1],
                    "answers": [],
                    "elapsed_seconds": -1,
                },
                "Smart Practice",
                [1],
            )


if __name__ == "__main__":
    unittest.main()
