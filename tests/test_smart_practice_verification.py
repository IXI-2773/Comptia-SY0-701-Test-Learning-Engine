import copy
import json
import tempfile
import unittest
from datetime import date as real_date
from pathlib import Path
from unittest import mock

import app as app_module
import app_session_builder_mixin as builder_module
import progress_store
from smart_practice_measurement import attach_prediction_to_question
from tests.test_security_testing_engine import SecurityTestingEngineGuiTests


def _fake_date_type(iso_day: str):
    class FakeDate:
        @classmethod
        def today(cls):
            return real_date.fromisoformat(iso_day)

        @staticmethod
        def fromisoformat(value):
            return real_date.fromisoformat(value)

    return FakeDate


class SmartPracticeVerificationTests(SecurityTestingEngineGuiTests):
    def make_shared_app(self, root_dir: Path, *, questions=None, start_session=False):
        tmpdir = Path(root_dir)
        user_data = tmpdir / "user_data"
        checkpoints = user_data / "checkpoints"
        backups = user_data / "backups"
        logs = user_data / "logs"
        for folder in (user_data, checkpoints, backups, logs):
            folder.mkdir(parents=True, exist_ok=True)

        bank_path = tmpdir / "mini_bank.json"
        bank_questions = questions or [
            {
                "question_number": 1,
                "prompt": "Question 1",
                "choices": {"A": "Correct 1", "B": "Wrong 1"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
            },
            {
                "question_number": 2,
                "prompt": "Question 2",
                "choices": {"A": "Correct 2", "B": "Wrong 2"},
                "correct": ["A"],
                "domain": "Domain B",
                "topics": ["Topic 2"],
            },
            {
                "question_number": 3,
                "prompt": "Question 3",
                "choices": {"A": "Correct 3", "B": "Wrong 3"},
                "correct": ["A"],
                "domain": "Domain C",
                "topics": ["Topic 3"],
            },
        ]
        bank_path.write_text(json.dumps({"title": "Mini Bank", "questions": bank_questions}), encoding="utf-8")

        patches = [
            mock.patch.object(app_module, "APP_DIR", tmpdir),
            mock.patch.object(app_module, "USER_DATA_DIR", user_data),
            mock.patch.object(app_module, "CHECKPOINT_DIR", checkpoints),
            mock.patch.object(app_module, "BACKUP_DIR", backups),
            mock.patch.object(app_module, "CONFIG_PATH", user_data / "config.json"),
            mock.patch.object(app_module, "DEFAULT_BANK", bank_path),
            mock.patch.object(app_module.TestingEngineApp, "_tick", lambda self: None),
            mock.patch.object(
                app_module.TestingEngineApp,
                "_collect_answer_feedback",
                lambda self, q, is_correct: {"confidence": "Sure", "miss_reason": ""},
            ),
            mock.patch.object(app_module.messagebox, "showwarning", return_value=None),
            mock.patch.object(app_module.messagebox, "showerror", return_value=None),
            mock.patch.object(app_module.messagebox, "showinfo", return_value=None),
            mock.patch.object(app_module.messagebox, "askyesno", return_value=True),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        try:
            root = app_module.tk.Tk()
        except app_module.tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")

        def _cleanup_root():
            try:
                if root.winfo_exists():
                    root.destroy()
            except app_module.tk.TclError:
                pass

        self.addCleanup(_cleanup_root)
        root.withdraw()
        app = app_module.TestingEngineApp(root)
        app._show_feedback_popover = lambda q, selected, anchor_widget=None: app._record_answer(
            q, selected, feedback_override={"confidence": "Sure", "miss_reason": ""}
        )
        app.load_from_path(bank_path)
        if start_session:
            app.restore_full_bank()
        return app

    def test_prediction_fresh_cached_build_creates_new_prediction_id(self):
        app = self._sp9_app_with_role_pool()

        first = app.build_smart_practice_pool("1", randomize=False)
        first_id = first[0]["prediction_id"]
        first_snapshot = dict(app.progress_data["meta"]["smart_practice_measurement"]["predictions"][first_id])

        second = app.build_smart_practice_pool("1", randomize=False)
        second_id = second[0]["prediction_id"]

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(
            first_snapshot, app.progress_data["meta"]["smart_practice_measurement"]["predictions"][first_id]
        )
        self.assertEqual(2, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))
        self.assertFalse(any("prediction_id" in question for question in app.master_questions))

    def test_prediction_same_timestamp_collision_does_not_overwrite_original_prediction(self):
        store = {"predictions": {}}
        question = self._sp9_question(1)
        question["smart_primary_role"] = "weak_repair"
        question["smart_policy_version"] = "smart-practice-9"
        question["smart_utility"] = 8.0
        question["smart_utility_breakdown"] = {"retention_risk": 6.0, "expected_learning_gain": 10.0}

        first_question = copy.deepcopy(question)
        second_question = copy.deepcopy(question)
        first = attach_prediction_to_question(
            first_question,
            store,
            {"attempts": 1, "learner_memory": {"retrievability": 0.7, "stability": 0.6}},
            created_at="2026-01-01T00:00:00",
        )
        second = attach_prediction_to_question(
            second_question,
            store,
            {"attempts": 9, "learner_memory": {"retrievability": 0.1, "stability": 0.1}},
            created_at="2026-01-01T00:00:00",
        )

        self.assertNotEqual(first["prediction_id"], second["prediction_id"])
        self.assertEqual(2, len(store["predictions"]))
        self.assertEqual(0.7, store["predictions"][first["prediction_id"]]["learner_retrievability_at_selection"])
        self.assertEqual(0.1, store["predictions"][second["prediction_id"]]["learner_retrievability_at_selection"])

    def test_smart_practice_build_does_not_mutate_master_questions(self):
        app = self._sp9_app_with_role_pool()
        original = copy.deepcopy(app.master_questions)

        app.build_smart_practice_pool("5", randomize=False)

        self.assertEqual(original, app.master_questions)

    def test_selected_question_nested_metadata_is_detached_from_master_bank(self):
        app = self.make_app(start_session=False)
        question = self._sp9_question(1, topic="Isolation", source="Trusted")
        question["metadata"] = {"tags": ["alpha"], "source": {"page": 7}}
        app.master_questions = [question]
        app.questions = list(app.master_questions)
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("1", randomize=False)
        pool[0]["metadata"]["tags"].append("beta")
        pool[0]["metadata"]["source"]["page"] = 99
        pool[0]["choices"]["A"] = "Changed"

        self.assertEqual(["alpha"], app.master_questions[0]["metadata"]["tags"])
        self.assertEqual(7, app.master_questions[0]["metadata"]["source"]["page"])
        self.assertNotEqual("Changed", app.master_questions[0]["choices"]["A"])

    def test_smart_practice_cache_changes_with_effective_review_date(self):
        app = self.make_app(start_session=False)
        app.master_questions = [self._sp9_question(1, topic="Due"), self._sp9_question(2, topic="Fallback")]
        app.questions = list(app.master_questions)
        app._reset_runtime_question_state(app.master_questions)
        rec = progress_store.update_progress_record({}, ["A"], True, seen_on="2026-05-17", confidence="Sure")
        rec = progress_store.set_progress_super_confident(rec, seen_on="2026-05-17", cooldown_days=5)
        app._progress_questions()["1"] = rec

        fake_day_one = _fake_date_type("2026-05-21")
        with (
            mock.patch.object(builder_module, "date", fake_day_one),
            mock.patch.object(progress_store, "date", fake_day_one),
        ):
            first = app.build_smart_practice_pool("2", randomize=False)
            second = app.build_smart_practice_pool("2", randomize=False)
        fake_day_two = _fake_date_type("2026-05-22")
        with (
            mock.patch.object(builder_module, "date", fake_day_two),
            mock.patch.object(progress_store, "date", fake_day_two),
        ):
            third = app.build_smart_practice_pool("2", randomize=False)

        self.assertEqual([2], [q["question_number"] for q in first])
        self.assertTrue(app.smart_practice_pool_cache)
        self.assertEqual([2], [q["question_number"] for q in second])
        self.assertIn(1, [q["question_number"] for q in third])
        self.assertFalse(app.last_smart_practice_selection_audit["cache_hit"])

    def test_invalid_cached_membership_is_rejected_and_rebuilt(self):
        app = self.make_app(start_session=False)
        app.master_questions = [self._sp9_question(1, topic="One"), self._sp9_question(2, topic="Two")]
        app.questions = list(app.master_questions)
        app._reset_runtime_question_state(app.master_questions)

        app.build_smart_practice_pool("2", randomize=False)
        cache_key = next(iter(app.smart_practice_pool_cache))
        app.smart_practice_pool_cache[cache_key] = {
            "qnums": (1, 1),
            "audit": {"unseen_target": 2, "cache_hit": False},
        }

        rebuilt = app.build_smart_practice_pool("2", randomize=False)

        self.assertEqual([1, 2], [q["question_number"] for q in rebuilt])
        self.assertFalse(app.last_smart_practice_selection_audit["cache_hit"])
        self.assertTrue(app.last_smart_practice_selection_audit["post_selection_validation_passed"])

    def test_duplicate_variants_are_suppressed_without_backfill(self):
        app = self.make_app(start_session=False)
        q1 = self._sp9_question(1, topic="Dup", source="Trusted")
        q2 = self._sp9_question(2, topic="Dup", source="Trusted")
        q2["prompt"] = f"  {q1['prompt']}!! "
        q2["choices"] = {key: f" {value} " for key, value in q1["choices"].items()}
        q3 = self._sp9_question(3, topic="Other", source="Trusted")
        app.master_questions = [q1, q2, q3]
        app.questions = list(app.master_questions)
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = progress_store.update_progress_record({}, ["B"], False, seen_on="2026-07-01")
        mastered = progress_store.update_progress_record({}, ["A"], True, seen_on="2026-06-01", confidence="Sure")
        mastered["correct_streak"] = 5
        app._progress_questions()["2"] = mastered

        pool = app.build_smart_practice_pool("3", randomize=False)

        self.assertEqual([1, 3], [q["question_number"] for q in pool])
        self.assertEqual(2, len(pool))
        self.assertGreaterEqual(app.last_smart_practice_selection_audit["duplicate_groups_excluded"], 1)

    def test_similar_opening_distinct_questions_remain_separate(self):
        app = self.make_app(start_session=False)
        q1 = self._sp9_question(1, topic="A", source="Trusted")
        q1["prompt"] = "Which control best reduces phishing risk for remote employees?"
        q1["choices"] = {"A": "Awareness training", "B": "Extra printers"}
        q2 = self._sp9_question(2, topic="B", source="Trusted")
        q2["prompt"] = "Which control best detects phishing activity against remote employees?"
        q2["choices"] = {"A": "SIEM correlation", "B": "Extra printers"}
        app.master_questions = [q1, q2]
        app.questions = list(app.master_questions)
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("2", randomize=False)

        self.assertEqual([1, 2], [q["question_number"] for q in pool])
        self.assertEqual(0, app.last_smart_practice_selection_audit["duplicate_groups_excluded"])

    def test_rotation_state_survives_restart_and_remains_deterministic(self):
        questions = [self._sp9_question(qnum, topic=f"Topic {qnum}", source="Trusted") for qnum in range(1, 6)]
        with tempfile.TemporaryDirectory() as tmp:
            app1 = self.make_shared_app(Path(tmp), questions=questions, start_session=False)
            first = [q["question_number"] for q in app1.build_smart_practice_pool("3", randomize=False)]
            app1._advance_smart_practice_rotation_epoch()
            app1.close_app()

            app2 = self.make_shared_app(Path(tmp), questions=questions, start_session=False)
            second = [q["question_number"] for q in app2.build_smart_practice_pool("3", randomize=False)]
            self.assertEqual(1, app2.progress_data["meta"]["smart_practice_rotation"]["epoch"])
            self.assertNotEqual(first, second)
            app2.close_app()

            app3 = self.make_shared_app(Path(tmp), questions=questions, start_session=False)
            third = [q["question_number"] for q in app3.build_smart_practice_pool("3", randomize=False)]
            app4 = self.make_shared_app(Path(tmp), questions=questions, start_session=False)
            fourth = [q["question_number"] for q in app4.build_smart_practice_pool("3", randomize=False)]

        self.assertEqual(third, fourth)

    def test_malformed_rotation_state_normalizes_on_load(self):
        questions = [self._sp9_question(qnum, topic=f"Topic {qnum}", source="Trusted") for qnum in range(1, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            app1 = self.make_shared_app(Path(tmp), questions=questions, start_session=False)
            app1.progress_data.setdefault("meta", {})["smart_practice_rotation"] = "broken"
            app1.save_progress()
            app1.close_app()

            app2 = self.make_shared_app(Path(tmp), questions=questions, start_session=False)
            rotation = app2.progress_data["meta"]["smart_practice_rotation"]
            pool = app2.build_smart_practice_pool("1", randomize=False)

        self.assertEqual({"epoch": 0, "last_membership_qnums": [], "pending_reference_qnums": []}, rotation)
        self.assertEqual(1, len(pool))


if __name__ == "__main__":
    unittest.main()
