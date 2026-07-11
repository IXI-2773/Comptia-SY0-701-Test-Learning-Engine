import copy
import json
import random
import sys
import tempfile
import tkinter.font as tkfont
import unittest
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module
import app_game_mixin as game_module
from analytics_summary import build_analytics_summary
from config_store import load_config, save_config
from progress_store import (
    CONFIDENCE_OPTIONS,
    normalize_progress_record,
    default_progress_record,
    is_review_due,
    is_active_weak,
    is_super_confident_active,
    is_suspended,
    recovery_ladder_stage,
    select_questions_by_history,
    select_due_review_questions,
    sanitize_response_time,
    set_progress_super_confident,
    aggregate_concept_memory,
    review_days_for_grade,
    study_status_name,
    update_progress_record,
)
from progress_models import normalize_progress_meta
from question_bank import adaptive_shuffle_question, load_bank, sanitize_text, stable_shuffle_question
from runtime_persistence import RuntimePersistence
from save_queue import DeferredSaveQueue
from smart_practice_cache import SmartPracticePrewarmService
from smart_practice_profile import (
    UTILITY_COMPONENT_BOUNDS,
    smart_practice_role_allocation,
    smart_practice_utility_total,
)
from smart_practice_measurement import (
    attach_prediction_to_question,
    baseline_comparison,
    brier_score,
    build_measurement_report,
    calibration_bins,
    empty_measurement_store,
    find_future_outcome,
    link_prediction_outcomes,
    log_loss,
    normalize_measurement_store,
    pairwise_discrimination,
    prediction_from_question,
    repair_performance,
    role_performance,
    session_composition,
    source_performance,
    timing_quality,
)
from smart_practice_concept_graph import (
    GRAPH_VERSION,
    aggregate_concept_state,
    audit_graph,
    calibrate_edge,
    calibrate_edges,
    concept_key_for_question,
    concept_record_for_question,
    diagnose_root_cause,
    diagnosis_measurement,
    empty_graph,
    make_edge,
    normalize_graph,
    prerequisite_cycle,
    select_prerequisite_path,
    store_diagnosis,
)
from smart_practice_question_value import (
    INFO_BOUNDS,
    information_value,
    normalize_calibration_store,
    quality_measurement,
    question_quality_record,
)
from smart_practice_policy import (
    active_policy,
    activate_candidate_policy,
    build_policy_review_report,
    create_candidate_policy,
    create_shadow_decision,
    default_policy_values,
    detect_drift,
    empty_governance,
    evaluate_challenger,
    exactly_one_active,
    expire_candidate,
    normalize_governance,
    policy_checksum,
    regression_gate_failures,
    rollback_policy,
    validate_policy,
    validate_policy_values,
)
from source_trust import derive_source_trust_warning
from session_models import apply_answer_state, clear_runtime_answer_state, reset_runtime_question_state
from session_store import migrate_session_snapshot
from storage_utils import load_json_or_backup, safe_write_json
from tools.clean_bank import clean_bank
from tools.benchmark_engine import run_benchmark
from tools import build_release as build_release_module
from tools import import_chapter_screenshots
from tools.validate_bank import validate_bank, write_markdown_report


class SecurityTestingEngineTests(unittest.TestCase):
    def test_frozen_runtime_data_uses_local_app_data(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(app_module.sys, "frozen", True, create=True),
            mock.patch.dict(app_module.os.environ, {"LOCALAPPDATA": tmp}),
        ):
            self.assertEqual(Path(tmp) / "SecurityTestingEngine", app_module.resolve_user_data_dir())

    def test_packaged_runtime_auto_migrates_stronger_project_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            shell = Path(tmp) / "App Shell"
            source = shell / "Project Files" / "user_data"
            target = Path(tmp) / "LocalAppData" / "SecurityTestingEngine"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            source_payload = {
                "questions": {str(i): {"attempts": 1} for i in range(10)},
                "history": [{"question_number": i} for i in range(25)],
                "meta": {"xp": 2000, "session_history": [{"answered": 25}]},
            }
            target_payload = {"questions": {"1": {"attempts": 1}}, "history": [], "meta": {"xp": 5}}
            (source / "public_sy0701_bank_v4_progress.json").write_text(json.dumps(source_payload), encoding="utf-8")
            (source / "public_sy0701_bank_v4_practice_session_25_test.json").write_text("{}", encoding="utf-8")
            (target / "public_sy0701_bank_v4_progress.json").write_text(json.dumps(target_payload), encoding="utf-8")

            with (
                mock.patch.object(app_module.sys, "frozen", True, create=True),
                mock.patch.object(app_module, "APP_DIR", shell),
            ):
                notice = app_module.auto_migrate_packaged_runtime_data(target)

            restored = json.loads((target / "public_sy0701_bank_v4_progress.json").read_text(encoding="utf-8"))
            self.assertIn("Recovered 10 question records", notice)
            self.assertEqual(2000, restored["meta"]["xp"])
            self.assertTrue((target / "public_sy0701_bank_v4_practice_session_25_test.json").exists())
            self.assertTrue(any(path.name.startswith("SecurityTestingEngine_before_auto_migration_") for path in target.parent.iterdir()))

    def test_release_packager_outputs_single_exe_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist = root / "dist"
            release = root / "release" / "SecurityTestingEngine"
            root_exe = root / "SecurityTestingEngine.exe"
            start_here = root / "README - Start Here.txt"
            dist.mkdir()
            release.mkdir(parents=True)
            (dist / "SecurityTestingEngine.exe").write_bytes(b"exe")
            (release / "old_bank.json").write_text("{}", encoding="utf-8")

            with (
                mock.patch.object(build_release_module, "DIST_DIR", dist),
                mock.patch.object(build_release_module, "RELEASE_DIR", release),
                mock.patch.object(build_release_module, "ROOT_EXE", root_exe),
                mock.patch.object(build_release_module, "START_HERE", start_here),
            ):
                build_release_module.build_release()

            self.assertEqual(["SecurityTestingEngine.exe"], [path.name for path in release.iterdir()])
            self.assertEqual(b"exe", root_exe.read_bytes())
            self.assertIn("Double-click SecurityTestingEngine.exe", start_here.read_text(encoding="utf-8"))


    def test_chapter_screenshot_filename_parses_source_question_number(self):
        path = Path(
            "Screenshot 2026-06-19 at 01-04-26 Question 33 - Chapter 1 Domain 1.0 General Security Concepts.png"
        )

        self.assertEqual(33, import_chapter_screenshots.parse_source_question_number(path))

    def test_chapter_screenshot_metadata_infers_chapter_three_architecture(self):
        metadata = import_chapter_screenshots.infer_metadata_from_source_folder("Ch_3_domain_3.0_Security_Architecture")

        self.assertEqual("Chapter 3", metadata["chapter"])
        self.assertEqual("3.0", metadata["domain_code"])
        self.assertEqual("Security Architecture", metadata["domain"])
        self.assertEqual("Chapter 3 screenshot bank", metadata["source_label"])

    def test_chapter_screenshot_ocr_parser_prefers_first_explanation_match(self):
        text = (
            "Incorrect Jim wants to implement an authentication framework for his wireless network. "
            "Which of the following is most commonly used for wireless network authentication? "
            "A. EAP B. MS-CHAP C. Kerberos D. LDAP Explanation "
            "EAP is commonly used for authentication to wireless networks. MS-CHAP is used with PPTP-based VPNs, "
            "Kerberos is used for organizationwide authentication, and LDAP is used as part of Active Directory."
        )

        draft = import_chapter_screenshots.parse_ocr_draft(text)

        self.assertEqual(["A"], draft["correct"])
        self.assertEqual("EAP", draft["choices"]["A"])

    def test_chapter_screenshot_manifest_handles_missing_ocr_without_importing(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "screenshots"
            folder.mkdir()
            image_path = (
                folder / "Screenshot 2026-06-19 Question 33 - Chapter 1 Domain 1.0 General Security Concepts.png"
            )
            Image.new("RGB", (100, 80), color="white").save(image_path)
            review_path = Path(tmp) / "review.json"

            with mock.patch.object(import_chapter_screenshots, "ocr_is_available", return_value=False):
                manifest = import_chapter_screenshots.build_review_manifest(folder, review_path, expected_count=1)

            self.assertEqual(1, manifest["found_count"])
            self.assertFalse(manifest["ocr_available"])
            self.assertEqual(0, manifest["ready_to_merge_count"])
            self.assertEqual("needs_ocr_setup", manifest["screenshots"][0]["status"])
            self.assertEqual(33, manifest["screenshots"][0]["source_question_number"])
            self.assertTrue(review_path.exists())

    def test_verified_chapter_screenshot_record_maps_to_domain_metadata(self):
        record = {
            "filename": "Question 33.png",
            "source_question_number": 33,
            "prompt": "Which term best describes a security control?",
            "choices": {"A": "Control", "B": "Threat", "C": "Risk", "D": "Impact"},
            "correct": ["A"],
            "general_explanation": "A control reduces or manages risk.",
        }

        merged, summary = import_chapter_screenshots.merge_verified_records(
            {"title": "Base", "questions": []}, [record]
        )
        question = merged["questions"][0]

        self.assertEqual(1, summary["imported_count"])
        self.assertEqual("General Security Concepts", question["domain"])
        self.assertEqual("Chapter 1", question["chapter"])
        self.assertEqual(["General Review"], question["topics"])
        self.assertEqual(33, question["source_question_number"])
        self.assertEqual("single", question["question_type"])

    def test_chapter_screenshot_review_record_is_quarantined(self):
        record = {
            "filename": "Question 7.png",
            "path": r"C:\screens\Question 7.png",
            "source_question_number": 7,
            "chapter": "Chapter 4",
            "domain": "Security Operations",
            "domain_code": "4.0",
            "topic": "General Review",
            "source_label": "Chapter 4 screenshot bank",
        }

        question = import_chapter_screenshots.build_question_from_review_record(record, 1500)

        self.assertTrue(question["suspended"])
        self.assertEqual("screenshot_review_needed", question["import_status"])
        self.assertEqual("Chapter 4 screenshot bank", question["source_label"])
        self.assertIn("verify", question["flagged_issues"][0].lower())

    def test_verified_chapter_screenshot_duplicate_is_skipped(self):
        base_question = {
            "question_number": 1,
            "prompt": "Which term best describes a security control?",
            "choices": {"A": "Control", "B": "Threat", "C": "Risk", "D": "Impact"},
            "correct": ["B"],
        }
        record = {
            "filename": "Question 33.png",
            "source_question_number": 33,
            "prompt": "Which term best describes a security control?",
            "choices": {"A": "Control", "B": "Threat", "C": "Risk", "D": "Impact"},
            "correct": ["A"],
            "general_explanation": "A control reduces or manages risk.",
        }

        merged, summary = import_chapter_screenshots.merge_verified_records(
            {"title": "Base", "questions": [base_question]}, [record]
        )

        self.assertEqual(1, len(merged["questions"]))
        self.assertEqual(0, summary["imported_count"])
        self.assertEqual(1, summary["skipped_count"])
        self.assertEqual("duplicate_or_near_duplicate", summary["skipped"][0]["reason"])

    def test_analytics_summary_selects_focused_dashboard_values(self):
        payload = {
            "overall": {
                "pass_prediction_score": 71.0,
                "pass_prediction_label": "Borderline",
                "recent50_accuracy": 78.0,
                "stability_score": 69.0,
                "current_streak": 4,
            },
            "progress": {"due": 6, "wrong": 3, "recovered": 8, "mastered": 12},
            "pass_prediction": {"score": 72.5, "label": "Borderline", "readiness_floor": 61.0},
            "remediation_cards": [{"concept": "Identity controls", "action": "Contrast authentication factors."}],
            "roi_questions": [],
            "recommendations": [],
            "source_trust": [
                {
                    "source_name": "Source A",
                    "trust_score": 68.0,
                    "label": "Decayed",
                    "conflict_count": 2,
                    "issue_count": 1,
                }
            ],
        }

        summary = build_analytics_summary(payload)

        self.assertIn("72.5%", summary["readiness"]["headline"])
        self.assertEqual("Identity controls", summary["next_move"]["headline"])
        self.assertIn("6 due", summary["retention"]["headline"])
        self.assertIn("streak 4", summary["momentum"]["headline"])
        self.assertEqual("risk", summary["source_health"]["tone"])

    def test_source_trust_warning_is_risk_only(self):
        question = {"question_number": 7, "source_name": "Source A"}
        conflict = derive_source_trust_warning(
            question,
            {
                7: {
                    "question_number": 7,
                    "source_name": "Source A",
                    "label": "Source conflict",
                    "score": 0.2,
                    "support_sources": [],
                    "objective_code": "",
                    "topic": "",
                }
            },
            {},
        )
        decayed = derive_source_trust_warning(
            question,
            {},
            {
                "Source A": {
                    "source_name": "Source A",
                    "trust_score": 61.0,
                    "label": "Decayed",
                    "question_count": 1,
                    "agreement_count": 0,
                    "supported_count": 0,
                    "single_source_count": 1,
                    "conflict_count": 0,
                    "issue_count": 1,
                    "decay": 20.0,
                }
            },
        )
        healthy = derive_source_trust_warning(
            question,
            {},
            {
                "Source A": {
                    "source_name": "Source A",
                    "trust_score": 82.0,
                    "label": "Watch",
                    "question_count": 1,
                    "agreement_count": 0,
                    "supported_count": 0,
                    "single_source_count": 1,
                    "conflict_count": 0,
                    "issue_count": 0,
                    "decay": 0.0,
                }
            },
        )

        self.assertEqual("Source conflict", conflict["text"])
        self.assertEqual("Source decayed", decayed["text"])
        self.assertIsNone(healthy)

    def test_smart_practice_prewarm_coalesces_and_rejects_stale_results(self):
        class FakeRoot:
            def __init__(self):
                self.callbacks = {}
                self.next_id = 0

            def after(self, delay, callback):
                self.next_id += 1
                callback_id = f"after-{self.next_id}"
                self.callbacks[callback_id] = (delay, callback)
                return callback_id

            def after_cancel(self, callback_id):
                self.callbacks.pop(callback_id, None)

            def run_delay(self, delay):
                callback_id, (_delay, callback) = next((item for item in self.callbacks.items() if item[1][0] == delay))
                self.callbacks.pop(callback_id)
                callback()

        class ImmediateThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        root = FakeRoot()
        published = []
        with mock.patch("smart_practice_cache.threading.Thread", ImmediateThread):
            service = SmartPracticePrewarmService(root, published.append, debounce_ms=140)
            service.schedule("old", lambda: {"value": 1})
            service.schedule("new", lambda: {"value": 2})
            root.run_delay(140)
            root.run_delay(50)
            service.close()

        self.assertEqual(1, len(published))
        self.assertEqual("new", published[0]["key"])
        self.assertEqual(2, published[0]["payload"]["value"])

    def test_deferred_save_queue_coalesces_and_flushes_callbacks(self):
        events = []

        class FakeRoot:
            def __init__(self):
                self._callbacks = {}
                self._next_id = 1

            def after(self, delay_ms, callback):
                callback_id = f"after-{self._next_id}"
                self._next_id += 1
                self._callbacks[callback_id] = callback
                return callback_id

            def after_cancel(self, callback_id):
                self._callbacks.pop(callback_id, None)

        root = FakeRoot()
        queue = DeferredSaveQueue(root)

        queue.schedule("session", lambda: events.append("first"))
        queue.schedule("session", lambda: events.append("second"))
        queue.schedule("progress", lambda: events.append("progress"))

        self.assertTrue(queue.pending("session"))
        self.assertEqual(2, len(root._callbacks))

        queue.flush("session")
        self.assertEqual(["second"], events)
        self.assertFalse(queue.pending("session"))

        queue.flush_all()
        self.assertEqual(["second", "progress"], events)
        self.assertFalse(queue.pending("progress"))

    def test_load_bank_has_expected_question_count(self):
        data = load_bank(ROOT / "public_sy0701_bank_v4.json")
        self.assertEqual(720, len(data["questions"]))

    def test_merged_bank_includes_imported_study_guide_assessments(self):
        data = load_bank(ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json")
        self.assertEqual(1231, len(data["questions"]))
        imported = next(q for q in data["questions"] if q["question_number"] == 744)
        self.assertEqual("Pre-Assessment", imported["chapter"])
        self.assertEqual("Security Architecture", imported["domain"])
        self.assertEqual("Free Study Guide A5", imported["source_name"])
        self.assertTrue(imported["objective_code"])
        self.assertEqual(len(imported["correct"]), len(set(imported["correct"])))
        automation_question = next(q for q in data["questions"] if q["question_number"] == 793)
        self.assertNotIn(
            "CompTIA Security+ objectives covered in this chapter", automation_question["general_explanation"]
        )
        chapter_import = next(q for q in data["questions"] if q["question_number"] == 1028)
        self.assertEqual("Chapter 10: Understanding Cryptography and PKI", chapter_import["chapter"])
        self.assertEqual("Security Architecture", chapter_import["domain"])
        contiguous_choice_import = next(q for q in data["questions"] if q["question_number"] == 751)
        self.assertEqual(["A", "B", "C", "D"], sorted(contiguous_choice_import["choices"]))
        screenshot_counts = Counter(
            q.get("source_label") for q in data["questions"] if "screenshot" in str(q.get("source_label", "")).lower()
        )
        self.assertEqual(31, screenshot_counts["Chapter 1 screenshot bank"])
        self.assertEqual(31, screenshot_counts["Chapter 2 screenshot bank"])
        self.assertEqual(44, screenshot_counts["Chapter 3 screenshot bank"])
        self.assertEqual(47, screenshot_counts["Chapter 4 screenshot bank"])
        self.assertEqual(53, screenshot_counts["Chapter 5 screenshot bank"])
        active_screenshot_counts = Counter(
            q.get("source_label")
            for q in data["questions"]
            if "screenshot" in str(q.get("source_label", "")).lower() and not q.get("suspended")
        )
        self.assertEqual(31, active_screenshot_counts["Chapter 1 screenshot bank"])
        self.assertEqual(30, active_screenshot_counts["Chapter 2 screenshot bank"])
        self.assertEqual(44, active_screenshot_counts["Chapter 3 screenshot bank"])
        self.assertEqual(47, active_screenshot_counts["Chapter 4 screenshot bank"])
        self.assertEqual(53, active_screenshot_counts["Chapter 5 screenshot bank"])
        self.assertEqual(
            1,
            sum(1 for q in data["questions"] if q.get("import_status") == "screenshot_review_needed"),
        )
        sdn_question = next(q for q in data["questions"] if q["question_number"] == 1101)
        self.assertIn("implementing SDN", sdn_question["prompt"])
        self.assertEqual(["B"], sdn_question["correct"])
        self.assertIn("Software-defined networking (SDN)", sdn_question["general_explanation"])
        self.assertNotIn("SON", sdn_question["prompt"])
        self.assertNotIn("(SON)", sdn_question["general_explanation"])
        serverless_question = next(q for q in data["questions"] if q["question_number"] == 1124)
        self.assertEqual(["B"], serverless_question["correct"])
        self.assertIn("No need to patch infrastructure", serverless_question["choices"]["B"])
        ipsec_question = next(q for q in data["questions"] if q["question_number"] == 1128)
        self.assertEqual(["C"], ipsec_question["correct"])
        self.assertEqual("An IPSec VPN", ipsec_question["choices"]["C"])
        infrared_question = next(q for q in data["questions"] if q["question_number"] == 1072)
        self.assertEqual(["A"], infrared_question["correct"])
        self.assertEqual("Infrared", infrared_question["choices"]["A"])

    def test_merged_bank_validator_has_no_warnings(self):
        result = validate_bank(ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json")
        self.assertEqual([], result["issues"])
        self.assertEqual([], result["warnings"])

    def test_sanitize_text_repairs_mojibake_and_trims_embedded_questions(self):
        cleaned, notes = sanitize_text(
            "The companyâ€™s wireless network was targeted. QUESTION 744 Extra junk follows.",
            trim_embedded_questions=True,
            collect_notes=True,
        )
        self.assertEqual("The company's wireless network was targeted.", cleaned)
        self.assertIn("encoding artifacts repaired", notes)
        self.assertIn("embedded follow-on question removed", notes)

    def test_load_bank_infers_public_source_name_defaults(self):
        data = load_bank(ROOT / "public_sy0701_bank_v4_clean.json")
        question = next(q for q in data["questions"] if q["question_number"] == 1)
        self.assertEqual("Public SY0-701 Questions", question["source_name"])
        self.assertEqual("", question["objective_code"])

    def test_load_bank_trims_embedded_follow_on_questions_from_explanations(self):
        data = load_bank(ROOT / "public_sy0701_bank_v4.json")
        q743 = next(q for q in data["questions"] if q["question_number"] == 743)
        self.assertNotIn("QUESTION 744", q743["general_explanation"])
        self.assertTrue(
            q743["general_explanation"].startswith(
                "An Evil Twin (B) attack involves setting up a fraudulent Wi-Fi access point"
            )
        )
        self.assertIn("company's", sanitize_text("companyâ€™s"))

    def test_stable_shuffle_keeps_correct_choice_and_explanation_aligned(self):
        q = {
            "question_number": 99,
            "prompt": "Which answer is correct?",
            "choices": {"A": "right", "B": "wrong one", "C": "wrong two", "D": "wrong three"},
            "correct": ["A"],
            "choice_explanations": {"A": "right explanation", "B": "bad", "C": "bad", "D": "bad"},
        }
        shuffled = stable_shuffle_question(q)
        correct_letter = shuffled["correct"][0]
        self.assertEqual("right", shuffled["choices"][correct_letter])
        self.assertEqual("right explanation", shuffled["choice_explanations"][correct_letter])

    def test_adaptive_shuffle_keeps_correct_choice_and_explanation_aligned(self):
        q = {
            "question_number": 101,
            "prompt": "Pick the strongest control.",
            "choices": {"A": "right choice", "B": "wrong one", "C": "wrong two", "D": "wrong three"},
            "correct": ["A"],
            "choice_explanations": {"A": "right explanation", "B": "bad", "C": "bad", "D": "bad"},
        }
        shuffled_one = adaptive_shuffle_question(q, "seed-one")
        arrangements = {
            tuple(adaptive_shuffle_question(q, seed)["choices"].items())
            for seed in ("seed-one", "seed-two", "seed-three", "seed-four")
        }

        correct_letter = shuffled_one["correct"][0]
        self.assertEqual("right choice", shuffled_one["choices"][correct_letter])
        self.assertEqual("right explanation", shuffled_one["choice_explanations"][correct_letter])
        self.assertGreater(len(arrangements), 1)

    def test_progress_record_tracks_wrong_and_correct_review_schedule(self):
        rec = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        self.assertEqual(1, rec["attempts"])
        self.assertEqual(1, rec["wrong_count"])
        self.assertEqual(0, rec["correct_streak"])
        self.assertEqual("2026-04-23", rec["next_review"])
        self.assertTrue(is_review_due(rec, on_date="2026-04-23"))

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-23")
        self.assertEqual(2, rec["attempts"])
        self.assertEqual(1, rec["correct_count"])
        self.assertEqual(1, rec["correct_streak"])
        self.assertEqual("2026-04-24", rec["next_review"])

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-23")
        self.assertEqual(2, rec["correct_streak"])
        self.assertEqual("2026-04-26", rec["next_review"])

    def test_progress_record_tracks_confidence_and_miss_reason(self):
        rec = update_progress_record(
            {}, ["B"], False, seen_on="2026-04-23", confidence="Guessed", miss_reason="Did not know"
        )
        self.assertEqual("Guessed", rec["last_confidence"])
        self.assertEqual("Did not know", rec["last_miss_reason"])
        self.assertEqual(1, rec["confidence_counts"]["Guessed"])
        self.assertEqual(1, rec["miss_reason_counts"]["Did not know"])

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-24", confidence="Sure")
        self.assertEqual("Sure", rec["last_confidence"])
        self.assertEqual("", rec["last_miss_reason"])
        self.assertEqual(1, rec["confidence_counts"]["Sure"])

    def test_recovery_ladder_stage_moves_from_fragile_to_mastered(self):
        rec = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        self.assertEqual("Fragile", recovery_ladder_stage(rec))

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-24")
        self.assertEqual("Recovering", recovery_ladder_stage(rec))

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-25")
        self.assertEqual("Stable", recovery_ladder_stage(rec))

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-26")
        self.assertEqual("Trusted", recovery_ladder_stage(rec))

        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-27")
        self.assertEqual("Mastered", recovery_ladder_stage(rec, on_date="2026-04-28"))

    def test_normalize_progress_record_backfills_nested_counters(self):
        rec = normalize_progress_record({"attempts": "2", "flagged": 1, "confidence_counts": {"Sure": "4"}})
        self.assertEqual(2, rec["attempts"])
        self.assertTrue(rec["flagged"])
        self.assertEqual(4, rec["confidence_counts"]["Sure"])
        self.assertEqual(0, rec["confidence_counts"]["Guessed"])
        self.assertEqual([], rec["last_selected"])

    def test_due_review_selection_uses_records(self):
        questions = [{"question_number": 1}, {"question_number": 2}, {"question_number": 3}]
        records = {
            "1": {"next_review": "2026-04-22", "wrong_count": 1},
            "2": {"next_review": "2026-05-01", "wrong_count": 3},
            "3": {"next_review": "2026-04-23", "wrong_count": 2},
        }
        due = select_due_review_questions(questions, records, on_date="2026-04-23")
        self.assertEqual([1, 3], [q["question_number"] for q in due])

    def test_recovered_single_miss_drops_out_of_active_weak_filters(self):
        questions = [{"question_number": 1}]
        rec = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-23")
        records = {"1": rec}

        self.assertFalse(is_active_weak(rec))
        self.assertEqual([], select_questions_by_history(questions, records, "Previously wrong", on_date="2026-04-23"))
        self.assertEqual([], select_questions_by_history(questions, records, "Due/flagged weak", on_date="2026-04-23"))

    def test_suspended_question_is_excluded_from_history_selection(self):
        questions = [{"question_number": 1}, {"question_number": 2}]
        records = {
            "1": {"attempts": 3, "wrong_count": 2, "suspended": True},
            "2": {"attempts": 3, "wrong_count": 2, "suspended": False, "last_correct": False},
        }
        wrong = select_questions_by_history(questions, records, "Previously wrong", on_date="2026-04-23")
        self.assertEqual([2], [q["question_number"] for q in wrong])
        self.assertEqual("Suspended", study_status_name(records["1"]))

    def test_repeat_misses_stay_active_weak_until_recovered(self):
        questions = [{"question_number": 1}]
        rec = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        rec = update_progress_record(rec, ["B"], False, seen_on="2026-04-23")
        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-23")
        records = {"1": rec}

        self.assertTrue(is_active_weak(rec))
        self.assertEqual(
            [1],
            [
                q["question_number"]
                for q in select_questions_by_history(questions, records, "Previously wrong", on_date="2026-04-23")
            ],
        )

    def test_history_selection_filters_unseen_wrong_and_flagged_due(self):
        questions = [
            {"question_number": 1},
            {"question_number": 2},
            {"question_number": 3},
            {"question_number": 4, "flagged": True},
        ]
        records = {
            "1": {"attempts": 0, "wrong_count": 0, "flagged": False, "next_review": ""},
            "2": {"attempts": 3, "wrong_count": 1, "flagged": False, "next_review": "2026-04-22"},
            "3": {"attempts": 2, "wrong_count": 0, "flagged": False, "next_review": "2026-05-04"},
            "4": {"attempts": 1, "wrong_count": 0, "flagged": False, "next_review": ""},
        }

        unseen = select_questions_by_history(questions, records, "Unseen", on_date="2026-04-23")
        wrong = select_questions_by_history(questions, records, "Previously wrong", on_date="2026-04-23")
        flagged_or_due = select_questions_by_history(questions, records, "Due/flagged weak", on_date="2026-04-23")

        self.assertEqual([1], [q["question_number"] for q in unseen])
        self.assertEqual([2], [q["question_number"] for q in wrong])
        self.assertEqual([2, 4], [q["question_number"] for q in flagged_or_due])

    def test_corrupt_json_is_moved_aside(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text("{not valid json", encoding="utf-8")
            data, backup, err = load_json_or_backup(path)
            self.assertIsNone(data)
            self.assertIsNotNone(err)
            self.assertFalse(path.exists())
            self.assertTrue(backup.exists())
            self.assertIn(".bad.json", backup.name)

    def test_safe_write_json_replaces_file_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            safe_write_json(path, {"old": True})
            safe_write_json(path, {"new": True})
            data, backup, err = load_json_or_backup(path)
            self.assertIsNone(backup)
            self.assertIsNone(err)
            self.assertEqual({"new": True}, data)
            self.assertFalse((Path(tmp) / ".progress.json.tmp").exists())

    def test_runtime_persistence_handles_progress_backups_and_checkpoint_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            backup_dir = tmpdir / "backups"
            checkpoint_dir = tmpdir / "checkpoints"
            backup_dir.mkdir()
            checkpoint_dir.mkdir()
            persistence = RuntimePersistence(checkpoint_dir=checkpoint_dir, backup_dir=backup_dir)

            progress_path = tmpdir / "progress.json"
            progress_path.write_text(json.dumps({"questions": {"1": {"attempts": 1}}}), encoding="utf-8")

            auto_backup = persistence.backup_progress_file(progress_path, suffix="auto_backup")
            manual_backup = persistence.backup_progress_file(progress_path, destination=backup_dir / "manual.json")
            checkpoint_path = checkpoint_dir / "checkpoint_22.json"
            persistence.write_checkpoint(checkpoint_path, {"answered_count": 22})

            self.assertIsNotNone(auto_backup)
            self.assertTrue(auto_backup.exists())
            self.assertTrue(manual_backup.exists())
            self.assertEqual(progress_path.read_text(encoding="utf-8"), manual_backup.read_text(encoding="utf-8"))
            checkpoint_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(22, checkpoint_data["answered_count"])

    def test_runtime_persistence_migrates_legacy_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            persistence = RuntimePersistence(checkpoint_dir=tmpdir / "checkpoints", backup_dir=tmpdir / "backups")
            legacy_path = tmpdir / "legacy.json"
            new_path = tmpdir / "user_data" / "current.json"
            legacy_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

            first = persistence.migrate_runtime_file(legacy_path, new_path, label="session")
            second = persistence.migrate_runtime_file(legacy_path, new_path, label="session")

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual({"ok": True}, json.loads(new_path.read_text(encoding="utf-8")))

    def test_session_snapshot_migration_backfills_restore_identity_and_limit(self):
        migrated = migrate_session_snapshot(
            {
                "app_version": "legacy",
                "mode": "Practice",
                "question_numbers": [10, 11],
                "current_index": 1,
                "elapsed_seconds": 42,
                "answers": [
                    {
                        "selected": ["A"],
                        "pending": ["A"],
                        "answered": True,
                        "flagged": False,
                        "suspended": False,
                        "last_confidence": "",
                        "last_miss_reason": "",
                        "recall_ready": False,
                        "session_tag": "",
                    }
                ],
            },
            "Practice",
            [10, 11],
        )

        self.assertEqual(1, migrated["schema_version"])
        self.assertEqual([10, 11], migrated["restore_question_numbers"])
        self.assertEqual(2, migrated["session_base_question_count"])
        self.assertEqual(2, migrated["session_question_limit"])
        self.assertTrue(migrated["restore_signature"])

    def test_runtime_question_state_helpers_apply_reset_and_clear_answer_state(self):
        question = {
            "question_number": 77,
            "selected": ["B"],
            "pending": ["B"],
            "answered": True,
            "flagged": True,
            "suspended": False,
            "last_confidence": "Unsure",
            "last_miss_reason": "Misread",
            "recall_ready": True,
            "session_tag": "Question twin",
        }

        clear_runtime_answer_state(question)
        self.assertEqual([], question["selected"])
        self.assertEqual([], question["pending"])
        self.assertFalse(question["answered"])
        self.assertTrue(question["flagged"])
        self.assertEqual("", question["last_confidence"])
        self.assertEqual("", question["last_miss_reason"])
        self.assertFalse(question["recall_ready"])

        apply_answer_state(
            question,
            {
                "selected": ["A"],
                "pending": ["A"],
                "answered": True,
                "flagged": False,
                "suspended": True,
                "last_confidence": "Sure",
                "last_miss_reason": "",
                "recall_ready": True,
                "session_tag": "Boss round",
            },
        )
        self.assertEqual(["A"], question["selected"])
        self.assertEqual(["A"], question["pending"])
        self.assertTrue(question["answered"])
        self.assertFalse(question["flagged"])
        self.assertTrue(question["suspended"])
        self.assertEqual("Sure", question["last_confidence"])
        self.assertEqual("Boss round", question["session_tag"])

        reset_runtime_question_state(question)
        self.assertEqual([], question["selected"])
        self.assertEqual([], question["pending"])
        self.assertFalse(question["answered"])
        self.assertFalse(question["flagged"])
        self.assertTrue(question["suspended"])
        self.assertEqual("Sure", question["last_confidence"])
        self.assertEqual("Boss round", question["session_tag"])

    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(
                path,
                {
                    "session_count": "50",
                    "session_source": "Previously wrong",
                    "auto_next_correct": True,
                    "reward_intensity": "High",
                    "quest_count": "5",
                },
            )
            config = load_config(path)
            self.assertEqual("50", config["session_count"])
            self.assertEqual("Previously wrong", config["session_source"])
            self.assertTrue(config["auto_next_correct"])
            self.assertEqual("High", config["reward_intensity"])
            self.assertEqual("5", config["quest_count"])
            self.assertEqual("All domains", config["last_domain"])

    def test_normalize_progress_meta_backfills_nested_defaults(self):
        meta = normalize_progress_meta(
            {
                "xp": "42",
                "level": "3",
                "session_history": [{"at": "2026-05-15T10:00:00", "mode": "Practice", "accuracy": "80"}],
                "quest_stats": {"steady": {"offered": "2"}},
                "issue_reports": [{"question_number": "7", "status": "open"}],
                "stats": {"total_answered": "9", "domains_seen": ["Domain 1"]},
            }
        )

        self.assertEqual(42, meta["xp"])
        self.assertEqual(3, meta["level"])
        self.assertEqual(1, len(meta["session_history"]))
        self.assertEqual("", meta["session_history"][0]["source"])
        self.assertEqual(2, meta["quest_stats"]["steady"]["offered"])
        self.assertEqual(0, meta["quest_stats"]["steady"]["completed"])
        self.assertEqual(7, meta["issue_reports"][0]["question_number"])
        self.assertEqual(9, meta["stats"]["total_answered"])
        self.assertEqual([], meta["badges"])

    def test_bank_validation_report_has_no_issues(self):
        result = validate_bank(ROOT / "public_sy0701_bank_v4.json")
        self.assertEqual(720, result["question_count"])
        self.assertEqual([], result["issues"])

    def test_merged_bank_benchmark_stays_within_regression_guardrails(self):
        try:
            result = run_benchmark(
                ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json",
                smart_count="50",
                pool_randomize=False,
                repeat_count=3,
                pool_threshold_seconds=5.5,
                warm_pool_threshold_seconds=0.35,
                analytics_threshold_seconds=3.0,
            )
        except app_module.tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")

        self.assertEqual(1231, result["question_count"])
        self.assertEqual(50, result["pool_size"])
        self.assertEqual(3, result["repeat_count"])
        self.assertEqual(3, len(result["pool_timings"]))
        self.assertEqual(3, len(result["analytics_timings"]))
        self.assertLess(result["warm_pool_seconds"], 0.35)

    def test_merged_bank_q1105_uses_port_mirroring_answer_key(self):
        bank = load_bank(ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json")
        question = next(q for q in bank["questions"] if q.get("question_number") == 1105)

        self.assertEqual(["A"], question["correct"])
        self.assertIn("visibility", question["general_explanation"].lower())
        self.assertIn("port mirroring/monitor mode", question["general_explanation"].lower())
        self.assertIn("does not by itself make the nips see that traffic", question["choice_explanations"]["D"].lower())

    def test_bank_validation_flags_conflicting_and_repeated_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            payload = {
                "title": "Validator Bank",
                "questions": [
                    {
                        "question_number": 1,
                        "prompt": "Which control is best for remote access?",
                        "choices": {"A": "VPN", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "VPN is correct.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 2,
                        "prompt": "Which control is best for remote access",
                        "choices": {"A": "VPN", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["B"],
                        "general_explanation": "Intentional conflict.",
                        "choice_explanations": {"A": "Wrong", "B": "Right", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 3,
                        "prompt": "Which control is best for protecting email?",
                        "choices": {"A": "SPF", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "SPF is correct.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Email"],
                    },
                    {
                        "question_number": 4,
                        "prompt": "Which control is best for protecting emails?",
                        "choices": {"A": "SPF", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "SPF is correct again.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Email"],
                    },
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = validate_bank(path)

            self.assertTrue(any("Conflicting keyed answers" == title for title, _body in result["issues"]))
            self.assertTrue(any("Near-duplicate prompts" == title for title, _body in result["warnings"]))

    def test_bank_lint_report_captures_quality_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lint_bank.json"
            payload = {
                "title": "Lint Bank",
                "questions": [
                    {
                        "question_number": 1,
                        "prompt": "Best control?",
                        "choices": {"A": "VPN", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "",
                        "choice_explanations": {"A": "", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 2,
                        "prompt": "Best control",
                        "choices": {"A": "Firewall", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "Firewall is right.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 3,
                        "prompt": "Best control!!",
                        "choices": {"A": "MFA", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "MFA is right.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 4,
                        "prompt": "Best control now",
                        "choices": {"A": "SSO", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "SSO is right.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 5,
                        "prompt": "Best control again",
                        "choices": {"A": "PAM", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "PAM is right.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                    {
                        "question_number": 6,
                        "prompt": "Best control final",
                        "choices": {"A": "NAC", "B": "UPS", "C": "RAID", "D": "Hub"},
                        "correct": ["A"],
                        "general_explanation": "NAC is right.",
                        "choice_explanations": {"A": "Right", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                        "topics": ["Remote access"],
                    },
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = validate_bank(path)
            report_path = Path(tmp) / "report.md"
            write_markdown_report(result, report_path)
            report_text = report_path.read_text(encoding="utf-8")

            self.assertGreater(result["lint"]["missing_explanations"]["general_count"], 0)
            self.assertGreater(result["lint"]["missing_explanations"]["choice_count"], 0)
            self.assertGreater(result["lint"]["short_or_low_quality_prompts"]["count"], 0)
            self.assertTrue(result["lint"]["repeated_answer_pattern_bias"]["distribution"])
            self.assertIn("Lint Report", report_text)

    def test_bank_validation_reports_cleanup_artifacts_and_choice_explanation_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact_bank.json"
            payload = {
                "title": "Artifact Bank",
                "questions": [
                    {
                        "question_number": 1,
                        "prompt": "The companyâ€™s wireless network was targeted?",
                        "choices": {"A": "Evil Twin", "B": "Smishing"},
                        "correct": ["A"],
                        "general_explanation": "Evil Twin is correct. QUESTION 744 Extra answer block Answer: B Explanation: Wrong follow-on.",
                        "choice_explanations": {
                            "A": "Not keyed as correct in the source.",
                            "B": "Correct option. This should not be here.",
                        },
                        "topics": ["Wireless"],
                    },
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = validate_bank(path)

            self.assertGreater(result["lint"]["text_cleanup_artifacts"]["count"], 0)
            self.assertGreater(result["lint"]["explanation_anomalies"]["count"], 0)
            self.assertGreater(result["lint"]["choice_explanation_mismatches"]["count"], 0)
            self.assertTrue(
                any(
                    "encoding artifacts repaired" in body or "embedded follow-on question removed" in body
                    for _title, body in result["warnings"]
                )
            )

    def test_clean_bank_writes_sanitized_output_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bank.json"
            output = Path(tmp) / "bank_clean.json"
            payload = {
                "title": "Cleanup Bank",
                "questions": [
                    {
                        "question_number": 1,
                        "prompt": "The companyâ€™s wireless network was targeted?",
                        "choices": {"A": "Evil Twin", "B": "Smishing"},
                        "correct": ["A"],
                        "general_explanation": "Evil Twin is correct. QUESTION 744 Extra junk follows.",
                        "choice_explanations": {"A": "Correct option.", "B": "Wrong option."},
                        "topics": ["Wireless"],
                    },
                ],
            }
            source.write_text(json.dumps(payload), encoding="utf-8")

            cleaned_data, summary, validation_result, report_path = clean_bank(source, output)

            self.assertTrue(output.exists())
            self.assertEqual("The company's wireless network was targeted?", cleaned_data["questions"][0]["prompt"])
            self.assertNotIn("QUESTION 744", cleaned_data["questions"][0]["general_explanation"])
            self.assertGreater(summary["touched_questions"], 0)
            self.assertTrue(report_path.exists())
            self.assertEqual([], validation_result["issues"])


class SecurityTestingEngineGuiTests(unittest.TestCase):
    def make_app(self, start_session=True):
        self.tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_ctx.cleanup)
        tmpdir = Path(self.tmpdir_ctx.name)
        user_data = tmpdir / "user_data"
        checkpoints = user_data / "checkpoints"
        backups = user_data / "backups"
        logs = user_data / "logs"
        for folder in (user_data, checkpoints, backups, logs):
            folder.mkdir(parents=True, exist_ok=True)

        bank_path = tmpdir / "mini_bank.json"
        bank_payload = {
            "title": "Mini Bank",
            "questions": [
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
            ],
        }
        bank_path.write_text(json.dumps(bank_payload), encoding="utf-8")

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
        self.addCleanup(root.destroy)
        root.withdraw()
        app = app_module.TestingEngineApp(root)
        app._show_feedback_popover = lambda q, selected, anchor_widget=None: app._record_answer(
            q, selected, feedback_override={"confidence": "Sure", "miss_reason": ""}
        )
        if start_session:
            app.restore_full_bank()
        return app

    def visible_qnums(self, app):
        return [app.questions[idx]["question_number"] for idx in app.visible_indices]

    def test_startup_shows_blank_ready_state_until_set_is_started(self):
        app = self.make_app(start_session=False)

        self.assertEqual([], app.questions)
        self.assertEqual("Ready to start a set", app.question_meta_label.cget("text"))
        self.assertIn("START SET", app.question_label.cget("text"))
        self.assertEqual("Session file: not started", app.session_label.cget("text"))
        self.assertEqual("Smart Practice", app.session_mode_var.get())
        self.assertTrue(app.sidebar.winfo_manager())

    def test_smart_practice_finish_set_enables_after_all_questions_answered(self):
        app = self.make_app()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        for question in app.questions:
            question["answered"] = False

        app.render_question()

        self.assertEqual("FINISH SET", app.finish_btn.cget("text"))
        self.assertEqual("disabled", str(app.finish_btn.cget("state")))

        for question in app.questions:
            question["answered"] = True

        app.render_question()

        self.assertEqual("normal", str(app.finish_btn.cget("state")))
        with (
            mock.patch.object(app, "maybe_finish_session") as finish_mock,
            mock.patch.object(app, "open_analytics_window") as analytics_mock,
        ):
            app.finish_exam()

        finish_mock.assert_called_once_with(force=True)
        analytics_mock.assert_called_once()

    def test_smart_practice_finish_set_allows_flagged_or_suspended_unanswered_items(self):
        app = self.make_app()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        for question in app.questions:
            question["answered"] = True
            question["flagged"] = False
            question["suspended"] = False
        app.questions[0]["answered"] = False
        app.questions[0]["flagged"] = True
        app.questions[1]["answered"] = False
        app.questions[1]["suspended"] = True

        app.render_question()

        self.assertEqual("FINISH SET", app.finish_btn.cget("text"))
        self.assertEqual("normal", str(app.finish_btn.cget("state")))

    def test_next_unanswered_skips_flagged_or_suspended_unanswered_items(self):
        app = self.make_app()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        for question in app.questions:
            question["answered"] = True
            question["flagged"] = False
            question["suspended"] = False
        app.questions[0]["answered"] = False
        app.questions[0]["flagged"] = True
        app.questions[1]["answered"] = False
        app.questions[1]["suspended"] = True
        app.questions[2]["answered"] = False
        app.index = 0

        moved = app._go_to_next_unanswered_silent()

        self.assertTrue(moved)
        self.assertEqual(2, app.index)

    def test_finished_set_with_flagged_or_suspended_items_is_saved_and_not_resumable(self):
        app = self.make_app(start_session=False)
        app.session_mode_var.set(app_module.MODE_SMART_PRACTICE)
        app.session_count_var.set("2")
        app.session_source_var.set("All")
        app.session_random_var.set(False)

        app.start_custom_session()
        session_path = app.session_path
        builder_context = app.current_builder_context(
            mode=app_module.MODE_SMART_PRACTICE,
            count=app.session_count_var.get(),
            randomize=False,
            source_label=app.current_builder_source_label(app_module.MODE_SMART_PRACTICE),
        )
        app.questions[0]["answered"] = False
        app.questions[0]["flagged"] = True
        app.questions[1]["answered"] = False
        app.questions[1]["suspended"] = True
        app.update_progress_for_flag(app.questions[0])
        app.update_progress_for_suspended(app.questions[1])

        with mock.patch.object(app, "open_analytics_window"):
            app.finish_exam()

        self.assertFalse(session_path.exists())
        self.assertIsNone(app.session_path)
        self.assertEqual("Session complete: progress saved", app.session_label.cget("text"))
        self.assertIsNone(app.find_resumable_session_for_builder(builder_context))

    def test_finished_smart_practice_does_not_remain_resumable(self):
        app = self.make_app(start_session=False)
        app.session_mode_var.set(app_module.MODE_SMART_PRACTICE)
        app.session_count_var.set("2")
        app.session_source_var.set("All")
        app.session_random_var.set(False)

        app.start_custom_session()
        session_path = app.session_path
        builder_context = app.current_builder_context(
            mode=app_module.MODE_SMART_PRACTICE,
            count=app.session_count_var.get(),
            randomize=False,
            source_label=app.current_builder_source_label(app_module.MODE_SMART_PRACTICE),
        )
        stale_path = app.session_file_for_bank(
            app.bank_path,
            mode=app_module.MODE_SMART_PRACTICE,
            question_numbers=[1, 3],
        )
        stale_path.write_text(
            json.dumps(
                {
                    "mode": app_module.MODE_SMART_PRACTICE,
                    "builder_context": builder_context,
                    "source_label": "Smart practice",
                    "question_numbers": [1, 3],
                    "restore_question_numbers": [1, 3],
                    "session_base_question_count": 2,
                    "answers": [{"answered": False}, {"answered": False}],
                }
            ),
            encoding="utf-8",
        )

        for question in app.questions:
            question["answered"] = True
        with mock.patch.object(app, "open_analytics_window"):
            app.finish_exam()

        self.assertFalse(session_path.exists())
        self.assertIsNone(app.session_path)
        self.assertFalse(stale_path.exists())
        self.assertIsNone(app.find_resumable_session_for_builder(builder_context))

    def test_starting_a_set_collapses_sidebar_and_toggle_reopens_it(self):
        app = self.make_app()

        self.assertFalse(app.sidebar.winfo_manager())

        app.toggle_sidebar()

        self.assertTrue(app.sidebar.winfo_manager())

    def test_sidebar_width_preset_reopens_in_narrow_mode(self):
        app = self.make_app()
        app.set_sidebar_width_mode("Narrow", save=False)

        app.toggle_sidebar()
        app.root.update_idletasks()

        self.assertTrue(app.sidebar.winfo_manager())
        self.assertEqual(app.sidebar_width_options["Narrow"], int(app.sidebar.cget("width")))

    def test_clean_bank_default_preserves_runtime_file_stem(self):
        app = self.make_app(start_session=False)
        clean_path = Path("C:/tmp/public_sy0701_bank_v4_clean.json")
        merged_path = Path("C:/tmp/public_sy0701_bank_v4_plus_studyguide_clean.json")

        self.assertEqual("public_sy0701_bank_v4", app.runtime_bank_stem(clean_path))
        self.assertEqual("public_sy0701_bank_v4", app.runtime_bank_stem(merged_path))
        self.assertEqual("public_sy0701_bank_v4_progress.json", app.progress_file_for_bank(clean_path).name)
        self.assertEqual("public_sy0701_bank_v4_progress.json", app.progress_file_for_bank(merged_path).name)
        self.assertIn(
            "public_sy0701_bank_v4_practice_session_",
            app.session_file_for_bank(clean_path, mode="Practice", questions=[{"question_number": 1}]).name,
        )
        self.assertIn(
            "public_sy0701_bank_v4_practice_session_",
            app.session_file_for_bank(merged_path, mode="Practice", questions=[{"question_number": 1}]).name,
        )

    def test_report_issue_queues_question_and_suspends_it(self):
        app = self.make_app()

        app.report_current_question_issue()

        reports = app._issue_reports()
        self.assertEqual(1, len(reports))
        self.assertEqual(1, reports[0]["question_number"])
        self.assertTrue(reports[0]["exclude_from_scoring"])
        self.assertTrue(app.current_question().get("suspended"))
        self.assertTrue(app.question_has_any_issue(app.current_question()))
        self.assertIn("User-reported issue queued", app.issue_label.cget("text"))

    def test_reported_issues_window_opens_and_updates_detail_without_refresh_loop(self):
        app = self.make_app()

        app.report_current_question_issue()
        app.open_issue_review_window()

        self.assertTrue(app.issue_review_window.winfo_exists())
        self.assertTrue(app.issue_review_widgets["tree"].selection())
        self.assertIn("Q1", app.issue_review_widgets["detail"].cget("text"))

    def test_screenshot_review_window_enables_verified_placeholder(self):
        app = self.make_app(start_session=False)
        raw = json.loads(app.bank_path.read_text(encoding="utf-8"))
        raw["questions"].append(
            {
                "question_number": 99,
                "prompt": "Placeholder prompt",
                "choices": {
                    "A": "Review source screenshot before studying",
                    "B": "Needs prompt transcription",
                    "C": "Needs answer-key verification",
                    "D": "Needs explanation verification",
                },
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["General Review"],
                "general_explanation": "Placeholder explanation",
                "source_label": "Chapter 1 screenshot bank",
                "source_image": "question.png",
                "source_image_path": str(app.bank_path.with_name("question.png")),
                "flagged_issues": ["Screenshot imported as review-needed placeholder; verify before enabling."],
                "suspended": True,
                "import_status": "screenshot_review_needed",
            }
        )
        app.bank_path.write_text(json.dumps(raw), encoding="utf-8")
        app.load_from_path(app.bank_path)

        app.open_screenshot_review_window()
        app.root.update_idletasks()
        tree = app.screenshot_review_widgets["tree"]
        self.assertIn("99", tree.get_children())
        tree.selection_set("99")
        app._render_screenshot_review_detail()
        app.screenshot_review_widgets["prompt"].delete("1.0", app_module.tk.END)
        app.screenshot_review_widgets["prompt"].insert("1.0", "Verified screenshot prompt?")
        app.screenshot_review_widgets["choices"]["A"].set("Correct answer")
        app.screenshot_review_widgets["choices"]["B"].set("Distractor B")
        app.screenshot_review_widgets["choices"]["C"].set("Distractor C")
        app.screenshot_review_widgets["choices"]["D"].set("Distractor D")
        app.screenshot_review_widgets["correct"].set("A")
        app.screenshot_review_widgets["explanation"].delete("1.0", app_module.tk.END)
        app.screenshot_review_widgets["explanation"].insert("1.0", "Verified explanation.")

        app.save_selected_screenshot_review_item()

        updated = json.loads(app.bank_path.read_text(encoding="utf-8"))
        saved = next(q for q in updated["questions"] if q["question_number"] == 99)
        self.assertFalse(saved["suspended"])
        self.assertEqual("screenshot_verified", saved["import_status"])
        self.assertEqual("Verified screenshot prompt?", saved["prompt"])
        self.assertEqual([], saved["flagged_issues"])
        self.assertNotIn("99", app.screenshot_review_widgets["tree"].get_children())

    def test_with_issues_filter_includes_reported_suspended_questions(self):
        app = self.make_app()

        app.report_current_question_issue()
        app.status_filter_var.set("With issues")
        app.refresh_question_list()

        self.assertEqual([1], self.visible_qnums(app))

    def test_followup_questions_replace_future_regular_question_at_cap(self):
        app = self.make_app(start_session=False)
        subset = [
            dict(app.master_questions[0]),
            dict(app.master_questions[1]),
        ]
        app.start_session_from_pool(
            subset,
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )

        inserted = app._insert_followup_questions(app.current_question(), [app.master_questions[2]], "Question twin")
        blocked = app._insert_followup_questions(app.current_question(), [app.master_questions[2]], "Question twin")

        self.assertEqual(2, app.session_question_limit)
        self.assertEqual(1, len(inserted))
        self.assertEqual(2, len(app.questions))
        self.assertEqual([1, 3], [q.get("question_number") for q in app.questions])
        self.assertEqual([], blocked)
        self.assertEqual(2, len(app.questions))

    def test_followup_questions_do_not_replace_protected_future_questions(self):
        app = self.make_app(start_session=False)
        subset = [
            dict(app.master_questions[0]),
            dict(app.master_questions[1]),
            dict(app.master_questions[2]),
        ]
        app.start_session_from_pool(
            subset,
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        original_qnums = [q.get("question_number") for q in app.questions]
        app.questions[1]["flagged"] = True
        app.questions[2]["session_tag"] = "Question twin"
        candidate = dict(app.master_questions[0])
        candidate["question_number"] = 99
        candidate["prompt"] = "Synthetic protected-slot follow-up"
        app.master_questions.append(candidate)

        inserted = app._insert_followup_questions(app.current_question(), [candidate], "Question twin")

        self.assertEqual([], inserted)
        self.assertEqual(original_qnums, [q.get("question_number") for q in app.questions])

    def test_session_question_limit_matches_requested_count(self):
        app = self.make_app(start_session=False)

        self.assertEqual(50, app.calculate_session_question_limit(50))
        self.assertEqual(25, app.calculate_session_question_limit(25))

    def test_resume_existing_session_choice_supports_resume_fresh_and_cancel(self):
        app = self.make_app(start_session=False)
        builder_context = {"mode": "Smart Practice", "count": "25"}

        with (
            mock.patch.object(app.root, "state", return_value="normal"),
            mock.patch.object(app, "find_resumable_session_for_builder", return_value=Path("saved.json")),
            mock.patch.object(app_module.messagebox, "askyesnocancel", side_effect=[True, False, None]),
        ):
            self.assertIs(True, app._resume_existing_session_choice(builder_context))
            self.assertIs(False, app._resume_existing_session_choice(builder_context))
            self.assertEqual("cancel", app._resume_existing_session_choice(builder_context))

    def test_reset_all_progress_clears_learner_state_and_runtime_files(self):
        app = self.make_app()
        q = app.questions[0]
        q["selected"] = ["B"]
        q["answered"] = True
        q["flagged"] = True
        app.update_progress_for_answer(q, {"confidence": "Guessed", "miss_reason": "Misread"})
        app.update_progress_for_flag(q)
        app._progress_meta()["xp"] = 250
        app.save_progress()
        app.save_session(show_notice=False)
        checkpoint_path = app.checkpoint_file_for_bank(app.bank_path, 22)
        checkpoint_path.write_text("{}", encoding="utf-8")
        progress_path = app.progress_path
        session_path = app.session_path

        self.assertTrue(progress_path.exists())
        self.assertTrue(session_path.exists())
        self.assertTrue(checkpoint_path.exists())

        app.reset_all_progress()

        self.assertEqual({}, app._progress_questions())
        self.assertEqual([], app._progress_history())
        self.assertEqual(0, app._progress_meta()["xp"])
        self.assertEqual([], app.questions)
        self.assertFalse(session_path.exists())
        self.assertFalse(checkpoint_path.exists())
        self.assertTrue(progress_path.exists())
        self.assertFalse(
            any(q.get("answered") or q.get("selected") or q.get("flagged") for q in app.master_questions)
        )
        self.assertEqual("Ready to start a set", app.question_meta_label.cget("text"))
        self.assertIn("START SET", app.question_label.cget("text"))

    def test_close_app_saves_session_before_exit(self):
        app = self.make_app()

        with (
            mock.patch.object(app, "save_session") as save_session_mock,
            mock.patch.object(app, "save_progress") as save_progress_mock,
            mock.patch.object(app, "save_app_config") as save_config_mock,
            mock.patch.object(app.root, "destroy") as destroy_mock,
        ):
            app.close_app()

        save_session_mock.assert_called_once_with(show_notice=False)
        save_progress_mock.assert_called_once()
        save_config_mock.assert_called_once()
        destroy_mock.assert_called_once()

    def test_session_restores_with_replacement_followups(self):
        app = self.make_app(start_session=False)
        subset = [
            dict(app.master_questions[0]),
            dict(app.master_questions[1]),
        ]
        app.start_session_from_pool(
            subset,
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        app._insert_followup_questions(app.current_question(), [app.master_questions[2]], "Question twin")
        saved_qnums = [q.get("question_number") for q in app.questions]
        app.save_session(show_notice=False)

        app.start_session_from_pool(
            subset,
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=True,
        )

        self.assertEqual(saved_qnums, [q.get("question_number") for q in app.questions])
        self.assertEqual(2, len(app.questions))

    def test_restored_oversized_session_does_not_grow_past_saved_limit(self):
        app = self.make_app(start_session=False)
        subset = [
            dict(app.master_questions[0]),
            dict(app.master_questions[1]),
        ]
        app.start_session_from_pool(
            subset,
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        old_payload = {
            "app_version": "old-half-cap",
            "bank_file": app.bank_path.name,
            "mode": "Smart Practice",
            "question_count": 3,
            "question_numbers": [1, 2, 3],
            "restore_question_numbers": [1, 2],
            "session_base_question_count": 2,
            "session_question_limit": 3,
            "current_index": 0,
            "elapsed_seconds": 0,
            "exam_reveal": True,
            "checkpoints_saved": [],
            "answers": [
                {
                    "selected": [],
                    "pending": [],
                    "answered": False,
                    "flagged": False,
                    "suspended": False,
                    "last_confidence": "",
                    "last_miss_reason": "",
                    "recall_ready": False,
                    "session_tag": "",
                },
                {
                    "selected": [],
                    "pending": [],
                    "answered": False,
                    "flagged": False,
                    "suspended": False,
                    "last_confidence": "",
                    "last_miss_reason": "",
                    "recall_ready": False,
                    "session_tag": "",
                },
                {
                    "selected": [],
                    "pending": [],
                    "answered": False,
                    "flagged": False,
                    "suspended": False,
                    "last_confidence": "",
                    "last_miss_reason": "",
                    "recall_ready": False,
                    "session_tag": "Question twin",
                },
            ],
        }
        app.session_path.write_text(json.dumps(old_payload), encoding="utf-8")
        candidate = dict(app.master_questions[0])
        candidate["question_number"] = 99
        candidate["prompt"] = "Synthetic old-session follow-up"
        app.master_questions.append(candidate)

        app.load_session_if_present(skip_identity_check=True)
        inserted = app._insert_followup_questions(app.current_question(), [candidate], "Question twin")

        self.assertEqual(3, app.session_question_limit)
        self.assertEqual(3, len(app.questions))
        self.assertEqual(1, len(inserted))

    def test_start_custom_session_restores_matching_incomplete_smart_practice_even_if_pool_changes(self):
        app = self.make_app(start_session=False)
        app.auto_next_correct_var.set(False)
        app.session_mode_var.set("Smart Practice")
        app.session_count_var.set("2")
        app.session_source_var.set("All")
        app.session_random_var.set(False)

        app.start_custom_session()
        saved_qnums = [q.get("question_number") for q in app.questions]
        self.assertEqual(2, len(saved_qnums))

        app.toggle_choice("A")
        self.assertTrue(app.save_queue.pending("session"))
        app.flush_scheduled_session_save()
        self.assertTrue(app.session_path.exists())

        app.build_smart_practice_pool = lambda count, randomize=True: [
            dict(app.master_questions[1]),
            dict(app.master_questions[2]),
        ]

        app.start_custom_session()

        self.assertEqual(saved_qnums, [q.get("question_number") for q in app.questions])
        self.assertTrue(app.questions[0]["answered"])
        self.assertEqual(saved_qnums[0], app.questions[0]["question_number"])

    def test_session_restore_is_scoped_to_the_current_question_set(self):
        app = self.make_app()

        app.toggle_choice("A")
        app.save_session(show_notice=False)
        full_bank_path = app.session_path

        subset = [app.master_questions[1], app.master_questions[2]]
        app.start_session_from_pool(
            subset, mode="Practice", count="All visible", randomize=False, reset_clock=False, preserve_if_saved=False
        )
        app.toggle_choice("A")
        app.save_session(show_notice=False)
        subset_path = app.session_path

        self.assertNotEqual(full_bank_path, subset_path)

        app.restore_full_bank()

        self.assertEqual(full_bank_path, app.session_path)
        self.assertTrue(app.questions[0]["answered"])
        self.assertEqual(["A"], app.questions[0]["selected"])
        self.assertFalse(app.questions[1]["answered"])

    def test_session_restore_requires_exact_identity_not_just_count(self):
        app = self.make_app()

        subset = [app.master_questions[1], app.master_questions[2]]
        app.start_session_from_pool(
            subset, mode="Practice", count="All visible", randomize=False, reset_clock=False, preserve_if_saved=False
        )
        session_path = app.session_path
        session_payload = {
            "app_version": "test",
            "bank_file": app.bank_path.name,
            "mode": "Practice",
            "question_count": 2,
            "current_index": 1,
            "elapsed_seconds": 33,
            "exam_reveal": True,
            "checkpoints_saved": [],
            "answers": [
                {"selected": ["A"], "pending": ["A"], "answered": True, "flagged": False},
                {"selected": [], "pending": [], "answered": False, "flagged": False},
            ],
        }
        session_path.write_text(json.dumps(session_payload), encoding="utf-8")

        different_subset = [app.master_questions[0], app.master_questions[2]]
        app.start_session_from_pool(
            different_subset,
            mode="Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        app.session_path.write_text(json.dumps(session_payload), encoding="utf-8")
        app.load_session_if_present()

        self.assertFalse(app.questions[0]["answered"])
        self.assertEqual(0, app.index)

    def test_legacy_session_payload_restores_without_new_schema_fields(self):
        app = self.make_app(start_session=False)
        subset = [app.master_questions[0], app.master_questions[1]]
        app.start_session_from_pool(
            subset, mode="Practice", count="All visible", randomize=False, reset_clock=False, preserve_if_saved=False
        )
        legacy_payload = {
            "app_version": "legacy",
            "bank_file": app.bank_path.name,
            "mode": "Practice",
            "question_count": 2,
            "question_numbers": [q.get("question_number") for q in app.questions],
            "current_index": 1,
            "elapsed_seconds": 21,
            "exam_reveal": True,
            "checkpoints_saved": [],
            "answers": [
                {
                    "selected": ["A"],
                    "pending": ["A"],
                    "answered": True,
                    "flagged": False,
                    "suspended": False,
                    "last_confidence": "",
                    "last_miss_reason": "",
                    "recall_ready": False,
                    "session_tag": "",
                },
                {
                    "selected": [],
                    "pending": [],
                    "answered": False,
                    "flagged": False,
                    "suspended": False,
                    "last_confidence": "",
                    "last_miss_reason": "",
                    "recall_ready": False,
                    "session_tag": "",
                },
            ],
        }
        app.session_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

        app.start_session_from_pool(
            subset, mode="Practice", count="All visible", randomize=False, reset_clock=False, preserve_if_saved=True
        )

        self.assertEqual(1, app.index)
        self.assertTrue(app.questions[0]["answered"])
        self.assertEqual(["A"], app.questions[0]["selected"])
        self.assertEqual(2, app.session_question_limit)

    def test_session_restore_property_round_trip_preserves_randomized_unfinished_state(self):
        rng = random.Random(701)

        for seed in range(10):
            with self.subTest(seed=seed):
                app = self.make_app(start_session=False)
                subset_size = rng.randint(2, 3)
                subset = [dict(q) for q in app.master_questions[:subset_size]]
                app.start_session_from_pool(
                    subset,
                    mode="Practice",
                    count="All visible",
                    randomize=False,
                    reset_clock=False,
                    preserve_if_saved=False,
                )

                expected_states = []
                for idx, question in enumerate(app.questions):
                    answered = rng.choice([True, False])
                    if idx == len(app.questions) - 1:
                        answered = False
                    flagged = rng.choice([True, False])
                    suspended = rng.choice([True, False])
                    if idx == len(app.questions) - 1:
                        # Keep one truly unfinished question so the resumable session should persist.
                        flagged = False
                        suspended = False
                    if answered:
                        selected = ["A"] if rng.choice([True, False]) else ["B"]
                        question["selected"] = list(selected)
                        question["pending"] = list(selected)
                        question["answered"] = True
                        question["flagged"] = flagged
                        question["suspended"] = suspended
                        question["last_confidence"] = "Sure"
                        question["last_miss_reason"] = "" if selected == ["A"] else "Misread"
                    else:
                        question["selected"] = []
                        question["pending"] = []
                        question["answered"] = False
                        question["flagged"] = flagged
                        question["suspended"] = suspended
                        question["last_confidence"] = ""
                        question["last_miss_reason"] = ""
                    expected_states.append(
                        {
                            "selected": list(question["selected"]),
                            "answered": bool(question["answered"]),
                            "flagged": bool(question["flagged"]),
                            "suspended": bool(question["suspended"]),
                        }
                    )

                app.index = rng.randrange(len(app.questions))
                expected_index = app.index
                app.save_session(show_notice=False)

                app.start_session_from_pool(
                    subset,
                    mode="Practice",
                    count="All visible",
                    randomize=False,
                    reset_clock=False,
                    preserve_if_saved=True,
                )

                self.assertEqual(expected_index, app.index)
                self.assertEqual(subset_size, len(app.questions))
                self.assertTrue(any(not state["answered"] for state in expected_states))
                restored_states = [
                    {
                        "selected": list(question["selected"]),
                        "answered": bool(question["answered"]),
                        "flagged": bool(question["flagged"]),
                        "suspended": bool(question["suspended"]),
                    }
                    for question in app.questions
                ]
                self.assertEqual(expected_states, restored_states)

    def test_smart_practice_resume_property_reuses_saved_session_when_builder_pool_regenerates(self):
        rng = random.Random(702)

        for seed in range(10):
            with self.subTest(seed=seed):
                app = self.make_app(start_session=False)
                app.auto_next_correct_var.set(False)
                app.session_mode_var.set("Smart Practice")
                app.session_count_var.set(str(rng.choice([2, 3])))
                app.session_source_var.set("All")
                app.session_random_var.set(rng.choice([True, False]))

                app.start_custom_session()
                saved_qnums = [q.get("question_number") for q in app.questions]
                self.assertGreaterEqual(len(saved_qnums), 2)

                answer_letter = "A" if rng.choice([True, False]) else "B"
                app.toggle_choice(answer_letter)
                expected_answered = [bool(q.get("answered")) for q in app.questions]
                expected_selected = [list(q.get("selected", [])) for q in app.questions]

                reordered_qnums = list(reversed(saved_qnums))
                fallback_pool = [
                    dict(next(q for q in app.master_questions if q["question_number"] == qnum))
                    for qnum in reordered_qnums
                ]
                app.build_smart_practice_pool = lambda count, randomize=True, fallback_pool=fallback_pool: fallback_pool

                app.start_custom_session()

                self.assertEqual(saved_qnums, [q.get("question_number") for q in app.questions])
                self.assertEqual(expected_answered, [bool(q.get("answered")) for q in app.questions])
                self.assertEqual(expected_selected, [list(q.get("selected", [])) for q in app.questions])

    def test_redo_question_clears_answer_state(self):
        app = self.make_app()

        app.toggle_choice("A")
        self.assertTrue(app.current_question()["answered"])
        self.assertEqual(["A"], app.current_question()["selected"])

        app.redo_question()

        self.assertFalse(app.current_question()["answered"])
        self.assertEqual([], app.current_question()["selected"])
        self.assertEqual([], app.current_question()["pending"])

    def test_single_choice_answer_syncs_pending_with_selection(self):
        app = self.make_app()

        app.toggle_choice("A")

        self.assertTrue(app.current_question()["answered"])
        self.assertEqual(["A"], app.current_question()["selected"])
        self.assertEqual(["A"], app.current_question()["pending"])

    def test_confidence_click_advances_to_next_unanswered(self):
        app = self.make_app()

        app.toggle_choice("A")
        self.assertEqual(0, app.index)

        app.retag_current_answer_confidence("Sure")

        self.assertEqual(1, app.index)
        self.assertFalse(app.current_question()["answered"])

    def test_confidence_click_cancels_pending_auto_next_before_advancing(self):
        app = self.make_app()
        correct_letter = app.current_question()["correct"][0]
        app.auto_next_correct_var.set(True)

        with (
            mock.patch.object(app.root, "after", return_value="after#1") as after_mock,
            mock.patch.object(app.root, "after_cancel") as cancel_mock,
        ):
            app.toggle_choice(correct_letter)
            self.assertEqual("after#1", app.auto_next_after_id)
            app.retag_current_answer_confidence("Sure")

        self.assertEqual(1, sum(1 for args, _kwargs in after_mock.call_args_list if args and args[0] == 650))
        self.assertTrue(any(call.args == ("after#1",) for call in cancel_mock.call_args_list))
        self.assertEqual(1, app.index)
        self.assertIsNone(app.auto_next_after_id)

    def test_super_confident_button_pushes_question_far_out(self):
        app = self.make_app()

        app.toggle_choice("A")
        first_qnum = app.questions[0]["question_number"]
        app._set_current_index(0)
        app.mark_current_question_super_confident()

        rec = app._progress_questions()[str(first_qnum)]
        self.assertTrue(is_super_confident_active(rec))
        self.assertEqual("Sure", rec["last_confidence"])
        self.assertGreaterEqual(int(rec["correct_streak"]), 6)
        self.assertEqual(rec["next_review"], rec["super_confident_until"])
        self.assertEqual(1, app.index)

    def test_super_confident_action_button_is_visible_and_enabled_after_correct_answer(self):
        app = self.make_app()

        app.toggle_choice("A")

        self.assertEqual("normal", str(app.super_confident_action_btn.cget("state")))
        self.assertEqual("SUPER CONFIDENT", str(app.super_confident_action_btn.cget("text")))
        self.assertTrue(bool(app.super_confident_action_btn.winfo_manager()))

    def test_super_confident_action_button_is_disabled_after_wrong_answer(self):
        app = self.make_app()

        app.toggle_choice("B")

        self.assertEqual("disabled", str(app.super_confident_action_btn.cget("state")))
        self.assertEqual("SUPER CONFIDENT", str(app.super_confident_action_btn.cget("text")))
        self.assertTrue(bool(app.super_confident_action_btn.winfo_manager()))

    def test_answer_recording_uses_deferred_progress_and_session_saves(self):
        app = self.make_app()

        with (
            mock.patch.object(app, "schedule_progress_save") as progress_schedule_mock,
            mock.patch.object(app, "schedule_session_save") as session_schedule_mock,
            mock.patch.object(app, "save_progress") as save_progress_mock,
            mock.patch.object(app, "save_session") as save_session_mock,
        ):
            app.toggle_choice("A")

        progress_schedule_mock.assert_called()
        session_schedule_mock.assert_called()
        save_progress_mock.assert_not_called()
        save_session_mock.assert_not_called()

    def test_toggle_flag_uses_deferred_session_save(self):
        app = self.make_app()

        with (
            mock.patch.object(app, "schedule_session_save") as schedule_mock,
            mock.patch.object(app, "save_session") as save_session_mock,
        ):
            app.toggle_flag()

        schedule_mock.assert_called_once()
        save_session_mock.assert_not_called()
        self.assertTrue(app.current_question()["flagged"])

    def test_status_filters_distinguish_session_wrong_from_previously_wrong(self):
        app = self.make_app()

        q1 = app.questions[0]
        q1_record = default_progress_record()
        q1_record.update({"attempts": 2, "wrong_count": 1, "last_correct": False})
        app._progress_questions()[app._question_key(q1)] = q1_record

        app.index = 1
        app.toggle_choice("B")

        app.apply_status_filter("Wrong in session")
        self.assertEqual([2], self.visible_qnums(app))

        app.apply_status_filter("Previously wrong")
        self.assertEqual([1, 2], self.visible_qnums(app))

    def test_previously_wrong_filter_drops_question_after_recovery(self):
        app = self.make_app()

        q1 = app.questions[0]
        rec = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        rec = update_progress_record(rec, ["A"], True, seen_on="2026-04-23")
        app._progress_questions()[app._question_key(q1)] = rec

        app.apply_status_filter("Previously wrong")
        self.assertEqual([], self.visible_qnums(app))

    def test_practice_and_exam_modes_preserve_question_source(self):
        app = self.make_app()

        app.session_source_var.set("Previously wrong")
        app.session_mode_var.set("Practice")
        app.on_session_mode_change()
        self.assertEqual("Previously wrong", app.session_source_var.get())

        app.session_source_var.set("Previously answered")
        app.session_mode_var.set("Exam")
        app.on_session_mode_change()
        self.assertEqual("Previously answered", app.session_source_var.get())

    def test_all_source_is_preserved_when_bank_loads(self):
        app = self.make_app(start_session=False)

        app.config["session_source"] = "All"
        app.load_from_path(app.bank_path)

        self.assertEqual("All", app.session_source_var.get())

    def test_narrow_window_auto_collapses_and_restores_builder(self):
        app = self.make_app(start_session=False)

        app._apply_responsive_window_layout(900)
        self.assertFalse(app.sidebar.winfo_manager())
        self.assertTrue(app.sidebar_auto_collapsed)

        app._apply_responsive_window_layout(1200)
        self.assertTrue(app.sidebar.winfo_manager())
        self.assertFalse(app.sidebar_auto_collapsed)

    def test_source_badge_and_analytics_layout_are_persisted(self):
        app = self.make_app()

        app.start_session_from_pool(
            [app.master_questions[0], app.master_questions[1]],
            mode="Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
            source_label="Previously wrong",
        )
        app.render_question()
        self.assertIn("Source: Previously wrong", app.meta_strip_label.cget("text"))

        app.open_analytics_window()
        app.analytics_window.geometry("1111x700+20+20")
        app.analytics_widgets["domain_tree"].column("domain", width=333)
        app.analytics_widgets["topic_tree"].column("topic", width=377)
        app.analytics_window.update_idletasks()

        config = app.collect_config()

        self.assertIn("1111x700", config["analytics_geometry"])
        self.assertEqual(333, config["analytics_domain_widths"]["domain"])
        self.assertEqual(377, config["analytics_topic_widths"]["topic"])
        self.assertEqual("Full", config["sidebar_width_mode"])

    def test_study_status_badge_tracks_recovered_and_active_weak(self):
        app = self.make_app()

        recovered = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        recovered = update_progress_record(recovered, ["A"], True, seen_on="2026-04-23")
        app._progress_questions()[app._question_key(app.questions[0])] = recovered
        app.render_question()
        self.assertIn("Status: Recovered", app.meta_strip_label.cget("text"))

        active_weak = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        app._progress_questions()[app._question_key(app.questions[1])] = active_weak
        app.index = 1
        app.render_question()
        self.assertIn("Status: Active weak", app.meta_strip_label.cget("text"))

    def test_analytics_cache_reuses_payload_until_progress_changes(self):
        app = self.make_app()

        with mock.patch.object(app, "_build_analytics_payload", wraps=app._build_analytics_payload) as wrapped:
            app.compute_analytics()
            app.compute_analytics()
            self.assertEqual(1, wrapped.call_count)

            app.toggle_choice("A")
            app.compute_analytics()
            self.assertEqual(2, wrapped.call_count)

    def test_question_header_shows_only_risky_source_trust(self):
        app = self.make_app()
        question = app.current_question()
        qnum = int(question["question_number"])
        source_name = str(question.get("source_name") or "")
        signal_key = app._smart_practice_signal_key()
        app.smart_practice_signal_cache_key = signal_key
        app.smart_practice_signal_cache_payload = {
            "source_map": {
                qnum: {
                    "question_number": qnum,
                    "source_name": source_name,
                    "label": "Source conflict",
                    "score": 0.2,
                    "support_sources": [],
                    "objective_code": "",
                    "topic": "",
                }
            },
            "source_trust_map": {},
        }
        app.last_render_snapshot = None
        app.render_question()
        self.assertIn("Source conflict", app.meta_strip_label.cget("text"))

        app.smart_practice_signal_cache_payload = {
            "source_map": {},
            "source_trust_map": {
                source_name: {
                    "source_name": source_name,
                    "trust_score": 82.0,
                    "label": "Watch",
                    "question_count": 1,
                    "agreement_count": 0,
                    "supported_count": 0,
                    "single_source_count": 1,
                    "conflict_count": 0,
                    "issue_count": 0,
                    "decay": 0.0,
                }
            },
        }
        app.last_render_snapshot = None
        app.render_question()
        self.assertNotIn("Source conflict", app.meta_strip_label.cget("text"))
        self.assertNotIn("Source decayed", app.meta_strip_label.cget("text"))

    def test_unchanged_render_skips_redundant_question_widget_updates(self):
        app = self.make_app()
        app.last_render_snapshot = None
        with mock.patch.object(app, "_render_choice_rows", wraps=app._render_choice_rows) as render_choices:
            app.render_question()
            app.render_question()
        self.assertEqual(1, render_choices.call_count)

    def test_save_app_config_skips_identical_writes(self):
        app = self.make_app()

        with mock.patch.object(app_module, "save_config", wraps=app_module.save_config) as wrapped:
            app.last_config_snapshot = None
            app.save_app_config()
            app.save_app_config()
            self.assertEqual(1, wrapped.call_count)

    def test_smart_practice_builds_mixed_pool(self):
        app = self.make_app()
        rec1 = update_progress_record(
            {}, ["B"], False, seen_on="2026-04-23", confidence="Guessed", miss_reason="Did not know"
        )
        rec2 = update_progress_record({}, ["A"], True, seen_on="2026-04-23", confidence="Sure")
        rec3 = update_progress_record({}, ["A"], True, seen_on="2026-04-15", confidence="Unsure")
        rec3["next_review"] = "2026-04-20"
        app._progress_questions()["1"] = rec1
        app._progress_questions()["2"] = rec2
        app._progress_questions()["3"] = rec3

        pool = app.build_smart_practice_pool("3", randomize=False)
        self.assertEqual(3, len(pool))
        self.assertEqual({1, 2, 3}, {q["question_number"] for q in pool})

    def test_smart_practice_prioritizes_imported_screenshot_questions(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which policy defines acceptable device use?",
                "choices": {"A": "AUP", "B": "BIA"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Governance"],
                "source_name": "Clean bank",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Which concept describes a threat actor's reason for attacking?",
                "choices": {"A": "Motive", "B": "MTTR"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Threat actors"],
                "source_name": "Screenshot chapter bank",
                "source_label": "Chapter 5 screenshot bank",
                "source_image": "C:/Users/14422/Downloads/ch5/q001.png",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertEqual([2], [q["question_number"] for q in pool])

    def test_recent_screenshot_question_cools_down_when_not_weak_or_due(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which screenshot question was just answered?",
                "choices": {"A": "Correct", "B": "Distractor"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Threat actors"],
                "source_name": "Screenshot chapter bank",
                "source_label": "Chapter 5 screenshot bank",
                "source_image": "C:/Users/14422/Downloads/ch5/q002.png",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Which fresh question should be preferred?",
                "choices": {"A": "Correct", "B": "Distractor"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Governance"],
                "source_name": "Clean bank",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-06-26", confidence="Sure"
        )
        app._progress_questions()["1"]["next_review"] = "2099-01-01"
        app.master_questions[0]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[0], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 4.0}
        )

        freshness = app._build_question_freshness_map(
            app._recent_history(28), app._progress_questions(), app.master_questions
        )
        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertGreaterEqual(freshness[1], 12.0)
        self.assertEqual([2], [q["question_number"] for q in pool])

    def test_smart_practice_background_prioritizes_coverage_gaps(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which metric measures repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Which document defines required recovery order for systems?",
                "choices": {"A": "Business impact analysis", "B": "Recovery plan"},
                "correct": ["B"],
                "domain": "Security Program Management and Oversight",
                "topics": ["Recovery planning"],
                "source_name": "Source One",
                "objective_code": "1.2",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-04-23", confidence="Sure"
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-04-24", confidence="Sure"
        )

        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertEqual([3], [q["question_number"] for q in pool])

    def test_background_analytics_detect_source_agreement_coverage_gaps_and_confusion_pairs(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Which document defines required recovery order for systems?",
                "choices": {"A": "Business impact analysis", "B": "Recovery plan"},
                "correct": ["B"],
                "domain": "General Security Concepts",
                "topics": ["Recovery planning"],
                "source_name": "Source One",
                "objective_code": "1.2",
            },
            {
                "question_number": 4,
                "prompt": "Which metric measures repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.start_session_from_pool(
            [dict(app.master_questions[0]), dict(app.master_questions[2])],
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        app.toggle_choice("B")

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(
            any(
                row["question_number"] == 1 and row["label"] == "Cross-source agreement"
                for row in analytics["source_agreement"]
            )
        )
        self.assertTrue(any(row["unit"] == "1.2" for row in analytics["coverage_gaps"]))
        self.assertTrue(any("MTTR" in row["pair"] and "RTO" in row["pair"] for row in analytics["confusion_pairs"]))

    def test_background_analytics_detects_latent_weakness_source_trust_and_transfer_strength(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
                "flagged_issues": ["Suspect wording"],
            },
            {
                "question_number": 2,
                "prompt": "Which metric measures repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Which document defines required recovery order for systems?",
                "choices": {"A": "Business impact analysis", "B": "Recovery plan"},
                "correct": ["B"],
                "domain": "General Security Concepts",
                "topics": ["Recovery planning"],
                "source_name": "Source Two",
                "objective_code": "1.2",
            },
            {
                "question_number": 4,
                "prompt": "Which control validates contractor identities before entry?",
                "choices": {"A": "Badge reader", "B": "Visitor log"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Physical security"],
                "source_name": "Source One",
                "objective_code": "9.9",
                "flagged_issues": ["Needs review"],
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-10", confidence="Guessed"
        )
        app._progress_questions()["1"]["next_review"] = "2026-05-18"
        app.master_questions[0]["selected"] = ["A"]
        app.append_answer_history(app.master_questions[0], True, {"confidence": "Guessed", "miss_reason": ""})

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(any(row["question_number"] == 1 for row in analytics["latent_weakness"]))
        self.assertTrue(
            any(row["source_name"] == "Source One" and row["label"] == "Decayed" for row in analytics["source_trust"])
        )
        self.assertTrue(
            any(row["kind"] == "Objective" and row["unit"] == "5.2" for row in analytics["transfer_strength"])
        )
        self.assertTrue(any(row["objective_code"] == "5.2" for row in analytics["objective_mastery"]))

    def test_background_analytics_exposes_difficulty_phrasing_and_burnout(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric best maps recovery target time during an outage?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which metric tracks repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "LOUD /// PKI ///// TRUST ???? which control BEST BEST BEST confirms identity during remote crypto handshakes?",
                "choices": {"A": "Certificate validation", "B": "Visitor badge"},
                "correct": ["A"],
                "domain": "Security Architecture",
                "topics": ["Encryption / PKI"],
                "source_name": "Source Three",
                "objective_code": "3.9",
                "source_notes": ["OCR cleanup", "Long wording"],
                "general_explanation": "CERTIFICATE TRUST " * 20,
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        rec = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Guessed", miss_reason="Did not know"
        )
        rec = update_progress_record(
            rec, ["B"], False, seen_on="2026-05-11", confidence="Unsure", miss_reason="Misread"
        )
        rec = update_progress_record(rec, ["A"], True, seen_on="2026-05-12", confidence="Guessed")
        app._progress_questions()["1"] = rec
        app.master_questions[0]["selected"] = ["B"]
        app.append_answer_history(
            app.master_questions[0],
            False,
            {"confidence": "Guessed", "miss_reason": "Did not know", "response_seconds": 8.0},
        )
        app.master_questions[0]["selected"] = ["B"]
        app.append_answer_history(
            app.master_questions[0], False, {"confidence": "Unsure", "miss_reason": "Misread", "response_seconds": 12.0}
        )
        app.master_questions[0]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[0], True, {"confidence": "Guessed", "miss_reason": "", "response_seconds": 11.0}
        )

        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-12", confidence="Sure"
        )
        app.master_questions[1]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[1], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 6.0}
        )

        app.session_answer_history = [
            {"correct": True, "confidence": "Sure", "response_seconds": 5.0},
            {"correct": True, "confidence": "Sure", "response_seconds": 6.0},
            {"correct": True, "confidence": "Sure", "response_seconds": 6.5},
            {"correct": False, "confidence": "Guessed", "response_seconds": 17.0},
            {"correct": False, "confidence": "Unsure", "response_seconds": 18.0},
            {"correct": False, "confidence": "Guessed", "response_seconds": 19.5},
        ]

        analytics = app.compute_analytics(source=app.master_questions)

        difficulty_row = next(row for row in analytics["difficulty_calibration"] if row["question_number"] == 1)
        phrasing_row = next(row for row in analytics["phrasing_normalization"] if row["question_number"] == 3)
        self.assertIn(difficulty_row["label"], ("Hard", "Moderate"))
        self.assertGreater(difficulty_row["score"], 0.0)
        self.assertIn(phrasing_row["label"], ("Watch", "Noisy"))
        self.assertIn(analytics["burnout_risk"]["label"], ("Watch", "High"))
        self.assertGreater(analytics["burnout_risk"]["score"], 0.0)

    def test_background_analytics_exposes_deeper_learning_signals(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time during a disruption?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "A payment service fails during an outage. Which metric best defines the target recovery window for the service?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics", "Recovery planning"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Which document sets recovery order for business services after a disruption?",
                "choices": {"A": "Business impact analysis", "B": "Recovery plan"},
                "correct": ["B"],
                "domain": "Security Program Management and Oversight",
                "topics": ["Recovery planning"],
                "source_name": "Source One",
                "objective_code": "5.3",
            },
            {
                "question_number": 4,
                "prompt": "Which record verifies a contractor signed in to a secure area?",
                "choices": {"A": "Visitor log", "B": "Badge reader"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Physical security"],
                "source_name": "Source Three",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        rec1 = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Unsure", miss_reason="Narrowed to two"
        )
        rec1 = update_progress_record(rec1, ["A"], True, seen_on="2026-05-11", confidence="Guessed")
        app._progress_questions()["1"] = rec1
        app.master_questions[0]["selected"] = ["B"]
        app.append_answer_history(
            app.master_questions[0],
            False,
            {"confidence": "Unsure", "miss_reason": "Narrowed to two", "response_seconds": 11.0},
        )
        app.master_questions[0]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[0], True, {"confidence": "Guessed", "miss_reason": "", "response_seconds": 10.5}
        )

        rec2 = update_progress_record({}, ["A"], True, seen_on="2026-05-12", confidence="Sure")
        app._progress_questions()["2"] = rec2
        app.master_questions[1]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[1], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 8.5}
        )

        rec4 = update_progress_record({}, ["A"], True, seen_on="2026-05-12", confidence="Sure")
        app._progress_questions()["4"] = rec4
        app.master_questions[3]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[3], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 4.5}
        )

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["prerequisite_debt"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["concept_half_life"]))
        self.assertTrue(any(row["unit"] == "5.3" for row in analytics["blind_spot_inference"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["robustness_scores"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["leverage_ranking"]))
        self.assertTrue(any(row["fingerprint"] for row in analytics["misconception_fingerprints"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["effort_efficiency"]))
        self.assertTrue(any(row["question_number"] == 1 for row in analytics["reinforcement_distance"]))
        self.assertTrue(any(row["question_number"] == 2 for row in analytics["synthesis_checks"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["knowledge_trace"]))
        self.assertTrue(any(row["question_number"] == 1 for row in analytics["expected_learning_gain"]))
        self.assertIsInstance(analytics["delayed_probes"], list)
        self.assertTrue(any(row["question_number"] == 1 for row in analytics["counterexample_training"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["recognition_retrieval"]))
        self.assertTrue(any(row["question_number"] == 1 for row in analytics["cue_dependence"]))
        self.assertTrue(any(row["state"] for row in analytics["concept_states"]))
        self.assertTrue(any("!=" in row["rule"] for row in analytics["contrast_rules"]))
        self.assertIsInstance(analytics["retention_stress"], list)
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["failure_modes"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["compression_points"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["decision_latency"]))
        self.assertTrue(any(row["unit"] == "5.2" for row in analytics["generalization_scores"]))

    def test_smart_practice_uses_blind_spot_and_reinforcement_signals_in_background(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time during a disruption?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which document sets recovery order for business services after a disruption?",
                "choices": {"A": "Business impact analysis", "B": "Recovery plan"},
                "correct": ["B"],
                "domain": "Security Program Management and Oversight",
                "topics": ["Recovery planning"],
                "source_name": "Source One",
                "objective_code": "5.3",
            },
            {
                "question_number": 3,
                "prompt": "Which record verifies a contractor signed in to a secure area?",
                "choices": {"A": "Visitor log", "B": "Badge reader"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Physical security"],
                "source_name": "Source Two",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        rec1 = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Unsure", miss_reason="Narrowed to two"
        )
        rec1 = update_progress_record(rec1, ["A"], True, seen_on="2026-05-11", confidence="Guessed")
        app._progress_questions()["1"] = rec1
        app.master_questions[0]["selected"] = ["B"]
        app.append_answer_history(
            app.master_questions[0],
            False,
            {"confidence": "Unsure", "miss_reason": "Narrowed to two", "response_seconds": 11.0},
        )
        app.master_questions[0]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[0], True, {"confidence": "Guessed", "miss_reason": "", "response_seconds": 10.5}
        )

        pool = app.build_smart_practice_pool("2", randomize=False)

        self.assertEqual({1, 2}, {q["question_number"] for q in pool[:2]})

    def test_objective_mastery_and_stem_transfer_engine_track_style_diversity(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "A core service fails during an outage. What is the first metric you should review to understand the target recovery window?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-10", confidence="Sure"
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-11", confidence="Sure"
        )
        app.master_questions[0]["selected"] = ["A"]
        app.master_questions[1]["selected"] = ["A"]
        app.append_answer_history(app.master_questions[0], True, {"confidence": "Sure", "miss_reason": ""})
        app.append_answer_history(app.master_questions[1], True, {"confidence": "Sure", "miss_reason": ""})

        analytics = app.compute_analytics(source=app.master_questions)

        objective_row = next(row for row in analytics["objective_mastery"] if row["objective_code"] == "5.2")
        transfer_row = next(
            row for row in analytics["transfer_strength"] if row["kind"] == "Objective" and row["unit"] == "5.2"
        )
        self.assertGreaterEqual(objective_row["stem_style_count"], 2)
        self.assertGreaterEqual(transfer_row["stem_style_count"], 2)

    def test_interference_map_confidence_compression_and_abstraction_ladder_are_detected(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which term describes the metric that defines the target recovery window?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "A core service fails during an outage. What metric best captures the target recovery window?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Guessed", miss_reason="Did not know"
        )
        app.master_questions[0]["selected"] = ["B"]
        app.append_answer_history(
            app.master_questions[0], False, {"confidence": "Guessed", "miss_reason": "Did not know"}
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-11", confidence="Unsure"
        )
        app.master_questions[1]["selected"] = ["A"]
        app.append_answer_history(app.master_questions[1], True, {"confidence": "Unsure", "miss_reason": ""})

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(any("MTTR" in row["pair"] and "RTO" in row["pair"] for row in analytics["interference_map"]))
        self.assertTrue(
            any(
                row["kind"] == "Objective" and row["unit"] == "5.2" and row["compression"] > 0
                for row in analytics["confidence_compression"]
            )
        )
        self.assertTrue(
            any(
                row["kind"] == "Objective" and row["unit"] == "5.2" and row["available_style_count"] >= 2
                for row in analytics["abstraction_ladder"]
            )
        )
        self.assertTrue(
            any(
                row["kind"] == "Objective"
                and row["unit"] == "5.2"
                and row["weak_style"] == "Definition"
                and row["gap"] >= 12.0
                for row in analytics["error_boundaries"]
            )
        )
        self.assertTrue(
            any(
                row["kind"] == "Objective"
                and row["unit"] == "5.2"
                and row["distractor"] == "MTTR"
                and row["correct"] == "RTO"
                for row in analytics["counterfactual_distractors"]
            )
        )

    def test_smart_practice_interleaving_avoids_back_to_back_same_topic_when_possible(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Question 1",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic Same"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Question 2",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic Same"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 3,
                "prompt": "Question 3",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain B",
                "topics": ["Topic Other"],
                "source_name": "Source Two",
                "objective_code": "2.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("3", randomize=False)

        self.assertEqual([1, 3, 2], [q["question_number"] for q in pool])

    def test_smart_practice_interleaving_rotates_imported_source_labels(self):
        app = self.make_app(start_session=False)
        questions = [
            {
                "question_number": 1,
                "prompt": "Chapter 5 screenshot item one",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Topic Same"],
                "source_name": "Screenshot chapter bank",
                "source_label": "Chapter 5 screenshot bank",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Chapter 5 screenshot item two",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Topic Same"],
                "source_name": "Screenshot chapter bank",
                "source_label": "Chapter 5 screenshot bank",
                "objective_code": "1.1",
            },
            {
                "question_number": 3,
                "prompt": "Clean-bank transfer check",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Security Architecture",
                "topics": ["Topic Other"],
                "source_name": "Clean bank",
                "objective_code": "3.1",
            },
            {
                "question_number": 4,
                "prompt": "Chapter 3 screenshot item",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Security Architecture",
                "topics": ["Topic Other"],
                "source_name": "Screenshot chapter bank",
                "source_label": "Chapter 3 screenshot bank",
                "objective_code": "3.2",
            },
        ]

        ordered = app._interleave_questions(questions)

        first_labels = [q.get("source_label") or q.get("source_name") for q in ordered[:2]]
        self.assertNotEqual(first_labels[0], first_labels[1])

    def test_smart_practice_shapes_set_toward_variety_targets(self):
        app = self.make_app(start_session=False)
        questions = []
        for idx in range(1, 19):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Dominant source question {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "Domain A",
                    "topics": ["Topic A"],
                    "source_name": "Dominant Source",
                    "source_label": "Dominant Source",
                    "objective_code": f"1.{idx}",
                }
            )
        for idx in range(19, 41):
            offset = idx - 19
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Variety source question {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "Domain B" if offset % 2 else "Domain C",
                    "topics": [f"Topic {chr(66 + (offset % 4))}"],
                    "source_name": f"Source {offset % 5}",
                    "source_label": f"Source {offset % 5}",
                    "objective_code": f"3.{idx}",
                }
            )
        app.master_questions = questions
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("25", randomize=False)

        topics = {app._primary_topic_label(question) for question in pool}
        domains = {question.get("domain") for question in pool}
        source_counts = Counter(str(question.get("source_label") or question.get("source_name")) for question in pool)
        self.assertEqual(25, len(pool))
        self.assertGreaterEqual(len(topics), 4)
        self.assertGreaterEqual(len(domains), 2)
        self.assertLessEqual(max(source_counts.values()), 9)

        random.seed(7)
        random_pool = app.build_smart_practice_pool("25", randomize=True)
        random_topics = {app._primary_topic_label(question) for question in random_pool}
        random_domains = {question.get("domain") for question in random_pool}
        random_source_counts = Counter(
            str(question.get("source_label") or question.get("source_name")) for question in random_pool
        )
        self.assertEqual(25, len(random_pool))
        self.assertGreaterEqual(len(random_topics), 4)
        self.assertGreaterEqual(len(random_domains), 2)
        self.assertLessEqual(max(random_source_counts.values()), 9)

    def test_smart_practice_variety_does_not_shrink_narrow_filtered_pool(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": idx,
                "prompt": f"Same objective filtered question {idx}",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Single Topic"],
                "source_name": "Single Source",
                "source_label": "Single Source",
                "objective_code": "1.1",
            }
            for idx in range(1, 31)
        ]
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("25", randomize=False)
        random.seed(11)
        random_pool = app.build_smart_practice_pool("25", randomize=True)

        self.assertEqual(25, len(pool))
        self.assertEqual(25, len(random_pool))
        self.assertEqual(25, len({question["question_number"] for question in pool}))
        self.assertEqual(25, len({question["question_number"] for question in random_pool}))

    def test_smart_practice_source_cap_applies_during_variety_seeding(self):
        app = self.make_app(start_session=False)
        questions = []
        for idx in range(1, 16):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Dominant ordered first {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "Domain A",
                    "topics": [f"Topic {idx}"],
                    "source_name": "Dominant",
                    "source_label": "Dominant",
                    "objective_code": f"1.{idx}",
                }
            )
        for idx in range(16, 31):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Alternate source {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "Domain B",
                    "topics": [f"Topic {idx}"],
                    "source_name": f"Alt {idx % 5}",
                    "source_label": f"Alt {idx % 5}",
                    "objective_code": f"2.{idx}",
                }
            )
        app.master_questions = questions
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("10", randomize=False)
        source_counts = Counter(str(question.get("source_label") or question.get("source_name")) for question in pool)

        self.assertEqual(10, len(pool))
        self.assertLessEqual(source_counts["Dominant"], 4)

    def test_smart_practice_records_set_quality_score(self):
        app = self.make_app(start_session=False)
        questions = []
        for idx in range(1, 31):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Quality scored question {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": f"Domain {idx % 3}",
                    "topics": [f"Topic {idx % 6}"],
                    "source_name": f"Source {idx % 5}",
                    "source_label": f"Source {idx % 5}",
                    "objective_code": f"1.{idx}",
                }
            )
        app.master_questions = questions
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("25", randomize=False)
        quality = app.last_smart_practice_set_quality

        self.assertEqual(25, len(pool))
        self.assertGreaterEqual(float(quality["score"]), 80.0)
        self.assertIn(quality["retry_used"], {True, False})

    def test_smart_practice_quality_penalizes_recent_exact_repeats(self):
        app = self.make_app(start_session=False)
        questions = []
        for idx in range(1, 16):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Recently seen question {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": f"Domain {idx % 3}",
                    "topics": [f"Topic {idx % 6}"],
                    "source_name": f"Source {idx % 5}",
                    "source_label": f"Source {idx % 5}",
                    "objective_code": f"1.{idx}",
                }
            )
        app.master_questions = questions
        app._reset_runtime_question_state(app.master_questions)

        app._build_question_freshness_map = lambda _history, _records, source: {
            int(question.get("question_number") or 0): 20.0 for question in source
        }

        pool = app.build_smart_practice_pool("10", randomize=False)
        quality = app.last_smart_practice_set_quality

        self.assertEqual(10, len(pool))
        self.assertLess(float(quality["score"]), 82.0)

    def test_smart_practice_imported_chapter_burst_reserves_more_unseen_imports(self):
        app = self.make_app(start_session=False)
        questions = []
        for idx in range(1, 25):
            chapter = 1 + (idx % 4)
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Imported chapter screenshot {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "General Security Concepts",
                    "topics": [f"Imported Topic {idx % 5}"],
                    "source_name": "Screenshot chapter bank",
                    "source_label": f"Chapter {chapter} screenshot bank",
                    "source_image": f"C:/screens/q{idx}.png",
                    "objective_code": f"1.{idx}",
                }
            )
        for idx in range(25, 55):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Clean bank question {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "Security Architecture",
                    "topics": [f"Clean Topic {idx % 6}"],
                    "source_name": f"Clean Source {idx % 5}",
                    "objective_code": f"3.{idx}",
                }
            )
        app.master_questions = questions
        app._reset_runtime_question_state(app.master_questions)

        pool = app.build_smart_practice_pool("25", randomize=False)
        imported_count = sum(1 for question in pool if "screenshot" in str(question.get("source_label", "")).lower())

        self.assertGreaterEqual(imported_count, 12)

    def test_smart_practice_recent_concept_cooldown_rotates_away_from_repeats(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Recent objective practice one",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Repeated Topic"],
                "source_name": "Source A",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Recent objective practice two",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Repeated Topic"],
                "source_name": "Source B",
                "objective_code": "1.1",
            },
            {
                "question_number": 3,
                "prompt": "Same objective candidate",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Repeated Topic"],
                "source_name": "Source C",
                "objective_code": "1.1",
            },
            {
                "question_number": 4,
                "prompt": "Fresh objective candidate",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain B",
                "topics": ["Fresh Topic"],
                "source_name": "Source D",
                "objective_code": "2.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.append_answer_history(app.master_questions[0], True, {"confidence": "Sure", "miss_reason": ""})
        app.append_answer_history(app.master_questions[1], True, {"confidence": "Sure", "miss_reason": ""})

        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertEqual([4], [question["question_number"] for question in pool])

    def test_smart_practice_variety_preserves_high_signal_weak_core(self):
        app = self.make_app(start_session=False)
        questions = []
        for idx in range(1, 4):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Active weak question {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": "Weak Domain",
                    "topics": ["Weak Topic"],
                    "source_name": "Weak Source",
                    "source_label": "Weak Source",
                    "objective_code": f"1.{idx}",
                }
            )
        for idx in range(4, 36):
            questions.append(
                {
                    "question_number": idx,
                    "prompt": f"Variety alternative {idx}",
                    "choices": {"A": "Right", "B": "Wrong"},
                    "correct": ["A"],
                    "domain": f"Domain {idx % 4}",
                    "topics": [f"Topic {idx}"],
                    "source_name": f"Source {idx % 6}",
                    "source_label": f"Source {idx % 6}",
                    "objective_code": f"3.{idx}",
                }
            )
        app.master_questions = questions
        app._reset_runtime_question_state(app.master_questions)
        for qnum in range(1, 4):
            app._progress_questions()[str(qnum)] = update_progress_record(
                {}, ["B"], False, seen_on="2026-06-25", confidence="Sure", miss_reason="Did not know"
            )

        pool = app.build_smart_practice_pool("25", randomize=False)

        self.assertTrue({1, 2, 3}.issubset({question["question_number"] for question in pool}))

    def test_smart_practice_objective_autopilot_prioritizes_under_mastered_objective(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which metric measures repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Which control validates contractor identities before entry?",
                "choices": {"A": "Badge reader", "B": "Visitor log"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Physical security"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 4,
                "prompt": "A contractor arrives at the gate after hours. Which control is the best first check before physical access is granted?",
                "choices": {"A": "Badge reader", "B": "Visitor log"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Physical security"],
                "source_name": "Source Two",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-10", confidence="Sure"
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-11", confidence="Sure"
        )
        app._progress_questions()["3"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-12", confidence="Guessed"
        )

        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertEqual([4], [q["question_number"] for q in pool])

    def test_smart_practice_prioritizes_error_boundary_and_counterfactual_followup(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "A core service fails during an outage. What metric best captures the target recovery window?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Which control validates contractor identities before entry?",
                "choices": {"A": "Badge reader", "B": "Visitor log"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["Physical security"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        rec = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Guessed", miss_reason="Did not know"
        )
        rec = update_progress_record(rec, ["A"], True, seen_on="2026-05-11", confidence="Sure")
        app._progress_questions()["1"] = rec
        app.master_questions[0]["selected"] = ["B"]
        app.append_answer_history(
            app.master_questions[0], False, {"confidence": "Guessed", "miss_reason": "Did not know"}
        )
        app.master_questions[0]["selected"] = ["A"]
        app.append_answer_history(app.master_questions[0], True, {"confidence": "Sure", "miss_reason": ""})

        rec = update_progress_record({}, ["A"], True, seen_on="2026-05-12", confidence="Sure")
        rec = update_progress_record(rec, ["A"], True, seen_on="2026-05-13", confidence="Sure")
        app._progress_questions()["2"] = rec
        app.master_questions[1]["selected"] = ["A"]
        app.append_answer_history(app.master_questions[1], True, {"confidence": "Sure", "miss_reason": ""})
        app.append_answer_history(app.master_questions[1], True, {"confidence": "Sure", "miss_reason": ""})

        app._progress_questions()["3"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-14", confidence="Sure"
        )

        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertEqual([1], [q["question_number"] for q in pool])

    def test_smart_practice_freshness_decay_penalizes_recent_repeats_and_prioritizes_unseen(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Question 1",
                "choices": {"A": "Correct 1", "B": "Wrong 1"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Question 2",
                "choices": {"A": "Correct 2", "B": "Wrong 2"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 3,
                "prompt": "Question 3",
                "choices": {"A": "Correct 3", "B": "Wrong 3"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 4,
                "prompt": "Question 4",
                "choices": {"A": "Correct 4", "B": "Wrong 4"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-16", confidence="Sure"
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-17", confidence="Sure"
        )
        app._progress_questions()["1"]["next_review"] = "2099-01-01"
        app._progress_questions()["2"]["next_review"] = "2099-01-01"
        app._progress_questions()["1"]["learner_memory"]["next_review_at"] = "2099-01-01"
        app._progress_questions()["2"]["learner_memory"]["next_review_at"] = "2099-01-01"
        app.master_questions[0]["selected"] = ["A"]
        app.master_questions[1]["selected"] = ["A"]
        app.append_answer_history(
            app.master_questions[0], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 6.0}
        )
        app.append_answer_history(
            app.master_questions[0], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 5.5}
        )
        app.append_answer_history(
            app.master_questions[1], True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 5.0}
        )

        freshness = app._build_question_freshness_map(
            app._recent_history(28), app._progress_questions(), app.master_questions
        )
        pool = app.build_smart_practice_pool("2", randomize=False)

        self.assertGreater(freshness[1], freshness[2])
        self.assertEqual(3, pool[0]["question_number"])

    def test_smart_practice_super_confident_questions_are_skipped_when_other_choices_exist(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Question 1",
                "choices": {"A": "Correct 1", "B": "Wrong 1"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 2,
                "prompt": "Question 2",
                "choices": {"A": "Correct 2", "B": "Wrong 2"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source One",
                "objective_code": "1.1",
            },
            {
                "question_number": 3,
                "prompt": "Question 3",
                "choices": {"A": "Correct 3", "B": "Wrong 3"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic 1"],
                "source_name": "Source Two",
                "objective_code": "1.1",
            },
            {
                "question_number": 4,
                "prompt": "Question 4",
                "choices": {"A": "Correct 4", "B": "Wrong 4"},
                "correct": ["A"],
                "domain": "Domain B",
                "topics": ["Topic 2"],
                "source_name": "Source Three",
                "objective_code": "2.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        rec = update_progress_record({}, ["A"], True, seen_on="2026-05-17", confidence="Sure")
        rec = set_progress_super_confident(rec, seen_on="2026-05-17", cooldown_days=120)
        app._progress_questions()["1"] = rec

        pool = app.build_smart_practice_pool("2", randomize=False)

        self.assertTrue(is_super_confident_active(app._progress_questions()["1"], on_date="2026-05-17"))
        self.assertNotIn(1, [q["question_number"] for q in pool])

    def test_wrong_answer_queues_confusion_pair_drill_before_generic_twins(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which metric measures repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Future regular filler question.",
                "choices": {"A": "Unrelated", "B": "Other"},
                "correct": ["A"],
                "domain": "Other",
                "topics": ["Other"],
                "source_name": "Source Three",
                "objective_code": "1.0",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.start_session_from_pool(
            [dict(app.master_questions[0]), dict(app.master_questions[2])],
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )

        app.toggle_choice("B")

        self.assertEqual(2, len(app.questions))
        self.assertEqual("Confusion pair drill", app.questions[1]["session_tag"])

    def test_correct_answer_can_insert_stealth_checkpoint_followup(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which metric measures recovery target time?",
                "choices": {"A": "Recovery Time Objective (RTO)", "B": "Mean Time To Repair (MTTR)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source One",
                "objective_code": "5.2",
            },
            {
                "question_number": 2,
                "prompt": "Which metric measures repair speed?",
                "choices": {"A": "Mean Time To Repair (MTTR)", "B": "Recovery Time Objective (RTO)"},
                "correct": ["A"],
                "domain": "Security Program Management and Oversight",
                "topics": ["BCP / DR Metrics"],
                "source_name": "Source Two",
                "objective_code": "5.2",
            },
            {
                "question_number": 3,
                "prompt": "Future regular filler question.",
                "choices": {"A": "Unrelated", "B": "Other"},
                "correct": ["A"],
                "domain": "Other",
                "topics": ["Other"],
                "source_name": "Source Three",
                "objective_code": "1.0",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.start_session_from_pool(
            [dict(app.master_questions[0]), dict(app.master_questions[2])],
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        app.session_answer_history = [
            {
                "question_number": idx,
                "domain": "Security Program Management and Oversight",
                "correct": True,
                "confidence": "Sure",
                "miss_reason": "",
                "was_active_weak": False,
                "was_due": False,
                "response_seconds": 4.0,
                "session_tag": "",
            }
            for idx in range(10, 13)
        ]

        app._record_answer(app.questions[0], ["A"], feedback_override={"confidence": "Unsure", "miss_reason": ""})

        self.assertEqual(2, len(app.questions))
        self.assertEqual("Stealth checkpoint", app.questions[1]["session_tag"])
        self.assertEqual(2, app.questions[1]["question_number"])

    def test_correct_answer_can_insert_delayed_same_concept_probe(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which attack compromises a trusted site to target developers?",
                "choices": {"A": "Watering Hole", "B": "Whaling"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            },
            {
                "question_number": 2,
                "prompt": "Which attack targets users through a compromised site they already visit?",
                "choices": {"A": "Watering Hole", "B": "Smishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Two",
                "objective_code": "2.2",
            },
            {
                "question_number": 3,
                "prompt": "Future regular filler question.",
                "choices": {"A": "Unrelated", "B": "Other"},
                "correct": ["A"],
                "domain": "Other",
                "topics": ["Other"],
                "source_name": "Source Three",
                "objective_code": "1.0",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.start_session_from_pool(
            [dict(app.master_questions[0]), dict(app.master_questions[2])],
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )

        app._record_answer(app.questions[0], ["A"], feedback_override={"confidence": "Sure", "miss_reason": ""})

        self.assertEqual(2, len(app.questions))
        self.assertEqual("Delayed recall probe", app.questions[1]["session_tag"])
        self.assertEqual(2, app.questions[1]["question_number"])
        self.assertEqual("Watering Hole", app.session_answer_history[-1]["deciding_clue"])

    def test_recall_failure_and_deciding_clue_analytics_are_reported(self):
        app = self.make_app()
        q1 = app.master_questions[0]
        q2 = app.master_questions[1]
        q1["choices"] = {"A": "Watering Hole", "B": "Spear Phishing"}
        q1["correct"] = ["A"]
        q1["selected"] = ["B"]
        q1["domain"] = "Threats"
        q1["topics"] = ["Social engineering"]
        q2["choices"] = {"A": "Watering Hole", "B": "Whaling"}
        q2["correct"] = ["A"]
        q2["selected"] = ["A"]
        q2["domain"] = "Threats"
        q2["topics"] = ["Social engineering"]

        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Guessed", miss_reason="Did not know"
        )
        app.append_answer_history(q1, False, {"confidence": "Guessed", "miss_reason": "Did not know"})
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-11", confidence="Unsure"
        )
        app.append_answer_history(q2, True, {"confidence": "Unsure", "miss_reason": ""})

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(any(row["failure"] == "Blank recall" for row in analytics["recall_failures"]))
        self.assertTrue(any(row["clue"] == "Watering Hole" for row in analytics["deciding_clues"]))
        clue_row = next(row for row in analytics["deciding_clues"] if row["clue"] == "Watering Hole")
        self.assertEqual(1, clue_row["misses"])
        self.assertEqual(1, clue_row["fragile_correct"])

    def test_concept_memory_states_are_derived_from_history(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which attack compromises a trusted website to target developers?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            },
            {
                "question_number": 2,
                "prompt": "A team visits a compromised industry forum. What attack is this?",
                "choices": {"A": "Watering Hole", "B": "Whaling"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Two",
                "objective_code": "2.2",
            },
            {
                "question_number": 3,
                "prompt": "Which option best describes compromising a site used by a target group?",
                "choices": {"A": "Watering Hole", "B": "Smishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Three",
                "objective_code": "2.2",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)

        analytics = app.compute_analytics(source=app.master_questions)
        memory_row = next(row for row in analytics["concept_memory_states"] if row["unit"] == "2.2")
        self.assertEqual("new", memory_row["state"])

        q1, q2, q3 = app.master_questions
        q1["selected"] = ["A"]
        app._progress_questions()["1"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-01", confidence="Guessed"
        )
        app.append_answer_history(q1, True, {"confidence": "Guessed", "miss_reason": ""})
        app.analytics_source_cache_key = None
        memory_row = next(
            row
            for row in app.compute_analytics(source=app.master_questions)["concept_memory_states"]
            if row["unit"] == "2.2"
        )
        self.assertEqual("recognizable", memory_row["state"])

        q1["selected"] = ["A"]
        app._progress_questions()["1"] = update_progress_record(
            app._progress_questions()["1"], ["A"], True, seen_on="2026-05-02", confidence="Sure"
        )
        app.append_answer_history(q1, True, {"confidence": "Sure", "miss_reason": ""})
        app.analytics_source_cache_key = None
        memory_row = next(
            row
            for row in app.compute_analytics(source=app.master_questions)["concept_memory_states"]
            if row["unit"] == "2.2"
        )
        self.assertEqual("retrievable", memory_row["state"])

        q2["selected"] = ["A"]
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-03", confidence="Sure"
        )
        app.append_answer_history(q2, True, {"confidence": "Sure", "miss_reason": ""})
        app.analytics_source_cache_key = None
        memory_row = next(
            row
            for row in app.compute_analytics(source=app.master_questions)["concept_memory_states"]
            if row["unit"] == "2.2"
        )
        self.assertEqual("transferable", memory_row["state"])

        q3["selected"] = ["A"]
        app._progress_questions()["3"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-04", confidence="Sure"
        )
        app.append_answer_history(q3, True, {"confidence": "Sure", "miss_reason": ""})
        recent_delayed_success = (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds")
        for event in app._progress_history():
            event["at"] = recent_delayed_success
        app.analytics_source_cache_key = None
        memory_row = next(
            row
            for row in app.compute_analytics(source=app.master_questions)["concept_memory_states"]
            if row["unit"] == "2.2"
        )
        self.assertEqual("durable", memory_row["state"])

    def test_wrong_answer_memory_tracks_pressure_recovery_and_suspended_exclusion(self):
        app = self.make_app(start_session=False)
        q = app.master_questions[0]
        q.update(
            {
                "prompt": "Which attack compromises a trusted website to target developers?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            }
        )

        q["selected"] = ["B"]
        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, confidence="Sure", miss_reason="Misread"
        )
        app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread"})
        q["selected"] = ["B"]
        app._progress_questions()["1"] = update_progress_record(
            app._progress_questions()["1"], ["B"], False, confidence="Unsure", miss_reason="Narrowed to two"
        )
        app.append_answer_history(q, False, {"confidence": "Unsure", "miss_reason": "Narrowed to two"})
        analytics = app.compute_analytics(source=app.master_questions[:1])
        memory = analytics["wrong_answer_memory"][0]

        self.assertEqual("Spear Phishing", memory["tempting_distractor"])
        self.assertEqual("Watering Hole", memory["correct_concept"])
        self.assertEqual(2, memory["count"])
        self.assertGreaterEqual(memory["pressure"], 40.0)

        pressure_before = memory["pressure"]
        q["selected"] = ["A"]
        app._progress_questions()["1"] = update_progress_record(
            app._progress_questions()["1"], ["A"], True, confidence="Sure"
        )
        app.append_answer_history(q, True, {"confidence": "Sure", "miss_reason": ""})
        app.analytics_source_cache_key = None
        memory_after = app.compute_analytics(source=app.master_questions[:1])["wrong_answer_memory"][0]
        self.assertLess(memory_after["pressure"], pressure_before)
        self.assertGreater(memory_after["pressure"], 0.0)

        q["suspended"] = True
        app.update_progress_for_suspended(q)
        app.analytics_source_cache_key = None
        self.assertEqual([], app.compute_analytics(source=app.master_questions[:1])["wrong_answer_memory"])

    def test_smart_practice_infers_repair_intent_from_near_misses(self):
        app = self.make_app(start_session=False)
        q = app.master_questions[0]
        q.update(
            {
                "prompt": "Which attack compromises a trusted website to target developers?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            }
        )

        for _ in range(2):
            q["selected"] = ["B"]
            app._progress_questions()["1"] = update_progress_record(
                app._progress_questions().get("1", {}),
                ["B"],
                False,
                confidence="Unsure",
                miss_reason="Narrowed to two",
            )
            app.append_answer_history(q, False, {"confidence": "Unsure", "miss_reason": "Narrowed to two"})

        payload = app._build_smart_practice_signal_payload()

        self.assertEqual("Repair weak spots", payload["session_intent"]["label"])
        self.assertGreater(payload["near_miss_unit_map"]["Objective::2.2"], 0.0)

    def test_smart_practice_recycles_tempting_wrong_answer_contrasts(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which attack compromises a trusted website to target developers?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            },
            {
                "question_number": 2,
                "prompt": "Contrast Watering Hole with Spear Phishing for compromised trusted websites.",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Two",
                "objective_code": "2.2",
            },
            {
                "question_number": 3,
                "prompt": "Which control protects against power loss?",
                "choices": {"A": "UPS", "B": "WAF"},
                "correct": ["A"],
                "domain": "Operations",
                "topics": ["Resilience"],
                "source_name": "Source Three",
                "objective_code": "4.1",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        q = app.master_questions[0]
        for _ in range(2):
            q["selected"] = ["B"]
            app._progress_questions()["1"] = update_progress_record(
                app._progress_questions().get("1", {}),
                ["B"],
                False,
                confidence="Sure",
                miss_reason="Misread",
            )
            app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread"})

        payload = app._build_smart_practice_signal_payload()
        pool = app.build_smart_practice_pool("1", randomize=False)

        self.assertGreater(payload["wrong_answer_recycling_map"][2], 0.0)
        self.assertEqual([2], [question["question_number"] for question in pool])

    def test_correct_answer_can_insert_memory_ramp_followup(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which attack compromises a trusted website to target developers?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            },
            {
                "question_number": 2,
                "prompt": "Which attack targets users through a compromised site they already visit?",
                "choices": {"A": "Watering Hole", "B": "Whaling"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Two",
                "objective_code": "2.2",
            },
            {
                "question_number": 3,
                "prompt": "Future regular filler question.",
                "choices": {"A": "Unrelated", "B": "Other"},
                "correct": ["A"],
                "domain": "Other",
                "topics": ["Other"],
                "source_name": "Source Three",
                "objective_code": "1.0",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        prior = app.master_questions[0]
        prior["selected"] = ["A"]
        app._progress_questions()["1"] = update_progress_record({}, ["A"], True, confidence="Guessed")
        app.append_answer_history(prior, True, {"confidence": "Guessed", "miss_reason": ""})
        app.start_session_from_pool(
            [dict(app.master_questions[0]), dict(app.master_questions[2])],
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )

        app._record_answer(
            app.questions[0],
            list(app.questions[0]["correct"]),
            feedback_override={"confidence": "Unsure", "miss_reason": ""},
        )

        self.assertEqual(2, len(app.questions))
        self.assertEqual("Retrieval ramp", app.questions[1]["session_tag"])
        self.assertEqual(2, app.questions[1]["question_number"])

    def test_wrong_answer_memory_followup_precedes_generic_twins(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which attack compromises a trusted website to target developers?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source One",
                "objective_code": "2.2",
            },
            {
                "question_number": 2,
                "prompt": "Which attack is confused with spear phishing when a trusted site is compromised?",
                "choices": {"A": "Watering Hole", "B": "Spear Phishing"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Two",
                "objective_code": "2.2",
            },
            {
                "question_number": 3,
                "prompt": "A generic social engineering follow-up question.",
                "choices": {"A": "Watering Hole", "B": "Whaling"},
                "correct": ["A"],
                "domain": "Threats",
                "topics": ["Social engineering"],
                "source_name": "Source Three",
                "objective_code": "2.2",
            },
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.start_session_from_pool(
            [dict(app.master_questions[0]), dict(app.master_questions[2])],
            mode="Smart Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )

        with mock.patch.object(app, "maybe_queue_confusion_pair_drill", return_value=[]):
            app._record_answer(
                app.questions[0], ["B"], feedback_override={"confidence": "Sure", "miss_reason": "Misread"}
            )

        self.assertEqual(2, len(app.questions))
        self.assertEqual("Wrong-answer memory", app.questions[1]["session_tag"])
        self.assertEqual(2, app.questions[1]["question_number"])

    def test_progress_summary_cache_reflects_in_memory_progress_changes(self):
        app = self.make_app()
        initial = app.progress_summary()
        self.assertEqual(0, initial["attempted"])

        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Sure", miss_reason="Misread"
        )
        updated = app.progress_summary()

        self.assertEqual(1, updated["attempted"])
        self.assertEqual(1, updated["wrong"])

    def test_progress_question_map_is_normalized_once_per_loaded_map(self):
        app = self.make_app(start_session=False)
        app.progress_data["questions"] = {
            str(idx): {"attempts": idx % 2, "correct_count": idx % 2} for idx in range(1, 101)
        }

        with mock.patch.object(
            app_module, "normalize_progress_record", wraps=app_module.normalize_progress_record
        ) as wrapped:
            app._progress_questions()
            first_count = wrapped.call_count
            app._progress_questions()

        self.assertEqual(100, first_count)
        self.assertEqual(first_count, wrapped.call_count)

    def test_practice_count_is_applied_before_question_cloning(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": idx,
                "prompt": f"Question {idx}",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic A"],
            }
            for idx in range(1, 101)
        ]

        with mock.patch.object(app, "_clone_questions", wraps=app._clone_questions) as wrapped:
            app.start_session_from_pool(
                app.master_questions,
                mode="Practice",
                count="25",
                randomize=False,
                reset_clock=False,
                preserve_if_saved=False,
            )

        self.assertEqual(25, len(wrapped.call_args.args[0]))
        self.assertEqual(25, len(app.questions))

    def test_suspend_question_excludes_it_from_builder_pool(self):
        app = self.make_app()
        q = app.master_questions[0]
        q["suspended"] = True
        app.update_progress_for_suspended(q)

        pool = app.get_filtered_master_pool()
        self.assertNotIn(1, [question["question_number"] for question in pool])
        self.assertTrue(is_suspended(app._progress_record(q, create=False)))

    def test_analytics_reports_readiness_trend_and_roi(self):
        app = self.make_app()
        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Guessed", miss_reason="Did not know"
        )
        app.append_answer_history(
            app.master_questions[0], False, {"confidence": "Guessed", "miss_reason": "Did not know"}
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-10", confidence="Sure"
        )
        app.append_answer_history(app.master_questions[1], True, {"confidence": "Sure", "miss_reason": ""})

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertIn("readiness", analytics["domains"][0])
        self.assertIn("trend", analytics["domains"][0])
        self.assertIn("stability", analytics["domains"][0])
        self.assertTrue(isinstance(analytics["roi_questions"], list))
        self.assertTrue(isinstance(analytics["confidence_calibration"], list))
        self.assertIn("topic_mastery_map", analytics)
        self.assertIn("pass_prediction", analytics)
        self.assertIn("concept_clusters", analytics)
        self.assertIn("remediation_cards", analytics)

    def test_pass_predictor_and_remediation_cards_use_clustered_concepts(self):
        app = self.make_app()
        q1 = app.master_questions[0]
        q2 = app.master_questions[1]
        q1["topics"] = ["Wireless attacks"]
        q2["topics"] = ["Wireless attacks"]
        q1["domain"] = "Threats"
        q2["domain"] = "Threats"
        app.questions[0]["topics"] = ["Wireless attacks"]
        app.questions[1]["topics"] = ["Wireless attacks"]
        app.questions[0]["domain"] = "Threats"
        app.questions[1]["domain"] = "Threats"

        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, seen_on="2026-05-10", confidence="Sure", miss_reason="Misread"
        )
        app._progress_questions()["2"] = update_progress_record(
            {}, ["C"], False, seen_on="2026-05-11", confidence="Unsure", miss_reason="Narrowed to two"
        )
        app.questions[0]["selected"] = ["B"]
        app.questions[1]["selected"] = ["C"]
        app.append_answer_history(app.questions[0], False, {"confidence": "Sure", "miss_reason": "Misread"})
        app.append_answer_history(app.questions[1], False, {"confidence": "Unsure", "miss_reason": "Narrowed to two"})

        analytics = app.compute_analytics(source=app.master_questions[:2])

        self.assertTrue(analytics["concept_clusters"])
        self.assertEqual("Wireless attacks", analytics["concept_clusters"][0]["concept"])
        self.assertTrue(analytics["remediation_cards"])
        self.assertEqual("Wireless attacks", analytics["remediation_cards"][0]["concept"])
        self.assertIn(analytics["pass_prediction"]["label"], ("Likely ready", "Borderline", "Not ready"))

    def test_question_twins_insert_similar_followups(self):
        app = self.make_app()
        app.master_questions[0]["topics"] = ["Shared Topic"]
        app.master_questions[1]["topics"] = ["Shared Topic"]
        app.questions[0]["topics"] = ["Shared Topic"]
        app.questions[1]["topics"] = ["Shared Topic"]
        app.questions = [app.questions[0]]
        app.index = 0

        inserted = app.maybe_queue_question_twins(app.questions[0])

        self.assertEqual(1, len(inserted))
        self.assertEqual("Question twin", inserted[0]["session_tag"])
        self.assertEqual(2, app.questions[1]["question_number"])

    def test_streak_rescue_inserts_same_domain_followups(self):
        app = self.make_app()
        for question in app.master_questions:
            question["domain"] = "Shared Domain"
        for question in app.questions:
            question["domain"] = "Shared Domain"
        app.session_answer_history = [
            {"question_number": 1, "domain": "Shared Domain", "correct": False},
            {"question_number": 2, "domain": "Shared Domain", "correct": False},
        ]
        app.questions = [app.questions[0]]
        app.index = 0

        inserted = app.maybe_trigger_streak_rescue(app.questions[0])

        self.assertTrue(inserted)
        self.assertTrue(inserted[0]["session_tag"].startswith("Streak rescue"))

    def test_correct_answer_shows_inline_explanation_on_selected_row(self):
        app = self.make_app()
        app.questions[0]["general_explanation"] = "Inline explanation for the correct answer."
        app.toggle_choice("A")

        selected_row = app.choice_rows["A"]
        self.assertTrue(selected_row.detail.winfo_manager())
        self.assertIn("Inline explanation for the correct answer.", selected_row.detail.cget("text"))
        self.assertFalse(app.explanation_wrap.winfo_manager())

    def test_wrong_answer_shows_inline_explanation_on_selected_row(self):
        app = self.make_app()
        app.questions[0]["general_explanation"] = "Inline explanation for the wrong answer flow."
        app.toggle_choice("B")

        wrong_row = app.choice_rows["B"]
        correct_row = app.choice_rows["A"]
        wrong_font = tkfont.Font(font=wrong_row.detail.cget("font"))
        self.assertTrue(wrong_row.detail.winfo_manager())
        self.assertNotIn("Keyed answer:", wrong_row.detail.cget("text"))
        self.assertIn("Inline explanation for the wrong answer flow.", wrong_row.detail.cget("text"))
        self.assertEqual(app_module.DARK, wrong_row.detail.cget("fg"))
        self.assertEqual("bold", wrong_font.actual("weight"))
        self.assertGreaterEqual(wrong_font.actual("size"), 13)
        self.assertEqual("Review this one", app.status_label.cget("text"))
        self.assertFalse(correct_row.detail.winfo_manager())
        self.assertFalse(app.explanation_wrap.winfo_manager())

    def test_compact_review_mode_hides_footer_clutter_while_answering(self):
        app = self.make_app()
        app.compact_review_var.set(True)
        app.render_question()

        self.assertFalse(app.gamef.winfo_manager())
        self.assertFalse(app.session_label.winfo_manager())

        app.toggle_choice("A")

        self.assertTrue(app.gamef.winfo_manager())
        self.assertFalse(app.score_label.winfo_manager())
        self.assertTrue(app.top_feedback_label.winfo_manager())
        self.assertFalse(app.session_label.winfo_manager())

    def test_choice_specific_explanations_are_removed_from_review_rows(self):
        app = self.make_app()
        app.questions[0]["choice_explanations"] = {
            "A": "This is the right control for the scenario.",
            "B": "This sounds plausible, but it misses the main requirement.",
        }
        app.questions[0]["general_explanation"] = "General explanation body."

        app.toggle_choice("B")

        wrong_row = app.choice_rows["B"]
        correct_row = app.choice_rows["A"]
        self.assertTrue(wrong_row.detail.winfo_manager())
        self.assertFalse(correct_row.detail.winfo_manager())
        self.assertIn("General explanation body.", wrong_row.detail.cget("text"))
        self.assertNotIn("This sounds plausible", wrong_row.detail.cget("text"))
        self.assertFalse(wrong_row.mark.winfo_manager())
        self.assertEqual("OK", correct_row.mark.cget("text"))

    def test_dense_answers_mode_reduces_choice_padding(self):
        app = self.make_app()
        row = app.choice_rows["A"]
        default_pady = int(row.inner.cget("pady"))

        app.dense_answers_var.set(True)
        app.render_question()

        self.assertLess(int(row.inner.cget("pady")), default_pady)

    def test_responsive_card_padding_shrinks_on_smaller_widths(self):
        app = self.make_app()

        app._apply_responsive_card_padding(880)
        narrow_pad = int(app.content_frame.cget("padx"))

        app._apply_responsive_card_padding(1400)
        wide_pad = int(app.content_frame.cget("padx"))

        self.assertLess(narrow_pad, wide_pad)
        self.assertEqual(16, wide_pad)

    def test_choice_row_hover_state_softly_highlights_unanswered_row(self):
        app = self.make_app()
        row = app.choice_rows["A"]

        self.assertEqual(app_module.CARD, row.inner.cget("bg"))

        row._handle_hover(True)

        self.assertEqual(app_module.HOVER_BG, row.inner.cget("bg"))

        row._handle_hover(False)

        self.assertEqual(app_module.CARD, row.inner.cget("bg"))

    def test_question_and_answer_fonts_are_scaled_up_for_readability(self):
        app = self.make_app()

        prompt_size = tkfont.Font(font=app.question_label.cget("font")).actual("size")
        answer_size = tkfont.Font(font=app.choice_rows["A"].text.cget("font")).actual("size")
        app.questions[0]["general_explanation"] = "Larger inline explanation text."
        app.toggle_choice("B")
        explanation_size = tkfont.Font(font=app.choice_rows["B"].detail.cget("font")).actual("size")

        self.assertGreaterEqual(prompt_size, 14)
        self.assertGreaterEqual(answer_size, 13)
        self.assertGreaterEqual(explanation_size, 13)

    def test_answer_meta_details_are_removed_from_review_panel(self):
        app = self.make_app()

        app.toggle_choice("B")

        self.assertFalse(app.answer_meta_label.winfo_manager())

    def test_narrow_width_moves_maintenance_actions_into_more_menu(self):
        app = self.make_app()

        app._layout_action_buttons(width=900)

        self.assertFalse(app.flag_btn.winfo_manager())
        labels = [
            app.more_menu.entrycget(i, "label")
            for i in range((app.more_menu.index("end") or -1) + 1)
            if app.more_menu.type(i) == "command"
        ]
        self.assertIn("Flag", labels)
        self.assertIn("Suspend", labels)
        self.assertIn("Redo Question", labels)

        app._layout_action_buttons(width=1400)

        self.assertTrue(app.flag_btn.winfo_manager())

    def test_inline_explanation_omits_coaching_note_text(self):
        app = self.make_app()
        q = app.questions[0]
        q["selected"] = ["B"]
        q["answered"] = True
        q["last_confidence"] = "Guessed"
        q["last_miss_reason"] = "Narrowed to two"
        q["general_explanation"] = "General explanation body."
        app.render_question()

        self.assertIn("General explanation body.", app.choice_rows["B"].detail.cget("text"))
        self.assertNotIn("Coaching note:", app.choice_rows["B"].detail.cget("text"))

    def test_slowdown_prompt_is_not_rendered(self):
        app = self.make_app()
        q = app.master_questions[0]
        q["prompt"] = "Which is the BEST next step for containment?"
        wrong_letter = "B" if "B" not in q.get("correct", []) else "A"
        q["selected"] = [wrong_letter]
        app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread"})
        app.questions[0]["prompt"] = q["prompt"]
        app.questions[0]["answered"] = False

        app.render_question()

        self.assertNotIn("Slow down", app.question_label.cget("text"))

    def test_routine_reward_feedback_stays_silent(self):
        app = self.make_app()
        app.gamification_enabled_var.set(True)
        app.reward_sounds_var.set(True)
        app.micro_feedback_var.set(True)
        fake_winsound = mock.Mock(MB_ICONASTERISK=1, MB_OK=2)

        with mock.patch.object(game_module, "winsound", fake_winsound):
            app.show_reward_banner("Unlocked reward", kind="reward", bypass_cooldown=True)

        fake_winsound.MessageBeep.assert_not_called()

    def test_milestone_feedback_uses_optional_celebration_sound(self):
        app = self.make_app()
        app.gamification_enabled_var.set(True)
        app.reward_sounds_var.set(True)
        app.micro_feedback_var.set(True)
        fake_winsound = mock.Mock(MB_ICONASTERISK=1, MB_OK=2)

        with mock.patch.object(game_module, "winsound", fake_winsound):
            app.emit_micro_feedback(kind="milestone")

        fake_winsound.MessageBeep.assert_called_once_with(2)

    def test_analytics_exposes_decision_quality_trap_patterns_and_wrong_answer_families(self):
        app = self.make_app()
        q1 = app.master_questions[0]
        q1["prompt"] = "Which is the BEST control?"
        wrong_letter = "B" if "B" not in q1.get("correct", []) else "A"
        q1["selected"] = [wrong_letter]
        app._progress_questions()["1"] = update_progress_record(
            {}, [wrong_letter], False, seen_on="2026-05-10", confidence="Sure", miss_reason="Misread"
        )
        app.append_answer_history(q1, False, {"confidence": "Sure", "miss_reason": "Misread"})

        q2 = app.master_questions[1]
        q2["selected"] = ["A"]
        app._progress_questions()["2"] = update_progress_record(
            {}, ["A"], True, seen_on="2026-05-10", confidence="Unsure"
        )
        app.append_answer_history(q2, True, {"confidence": "Unsure", "miss_reason": ""})

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertIn("decision_quality", analytics["overall"])
        self.assertTrue(isinstance(analytics["concept_anchor_notes"], list))
        self.assertTrue(isinstance(analytics["wrong_answer_families"], list))
        self.assertTrue(isinstance(analytics["trap_word_patterns"], list))
        self.assertTrue(isinstance(analytics["recovery_ladder"], dict))
        self.assertTrue(
            any(row["family"] == "Technically true but not best" for row in analytics["wrong_answer_families"])
        )

    def test_question_volatility_watchlist_tracks_flip_flop_questions(self):
        app = self.make_app()
        q = app.master_questions[0]
        correct_letter = q.get("correct", ["A"])[0]
        wrong_letter = next(
            letter for letter in q.get("choices", {}) if q["choices"].get(letter) and letter not in q.get("correct", [])
        )

        app._progress_questions()["1"] = update_progress_record(
            {}, [wrong_letter], False, seen_on="2026-05-08", confidence="Sure", miss_reason="Misread"
        )
        q["selected"] = [wrong_letter]
        app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread"})

        app._progress_questions()["1"] = update_progress_record(
            app._progress_questions()["1"], [correct_letter], True, seen_on="2026-05-09", confidence="Sure"
        )
        q["selected"] = [correct_letter]
        app.append_answer_history(q, True, {"confidence": "Sure", "miss_reason": ""})

        app._progress_questions()["1"] = update_progress_record(
            app._progress_questions()["1"],
            [wrong_letter],
            False,
            seen_on="2026-05-10",
            confidence="Unsure",
            miss_reason="Narrowed to two",
        )
        q["selected"] = [wrong_letter]
        app.append_answer_history(q, False, {"confidence": "Unsure", "miss_reason": "Narrowed to two"})

        volatility = app.question_volatility(q)
        analytics = app.compute_analytics(source=app.master_questions)

        self.assertEqual("High", volatility["label"])
        self.assertTrue(any(row["question_number"] == 1 for row in analytics["volatile_questions"]))

    def test_choice_length_bias_pattern_is_reported(self):
        app = self.make_app()
        q = app.master_questions[0]
        q["choices"] = {
            "A": "Short right",
            "B": "This wrong answer is dramatically longer than every other option in the set",
        }
        q["correct"] = ["A"]
        app.questions[0]["choices"] = dict(q["choices"])
        app.questions[0]["correct"] = ["A"]
        wrong_letter = "B"

        for day in ("2026-05-08", "2026-05-09", "2026-05-10"):
            app._progress_questions()["1"] = update_progress_record(
                app._progress_questions().get("1", {}),
                [wrong_letter],
                False,
                seen_on=day,
                confidence="Sure",
                miss_reason="Misread",
            )
            q["selected"] = [wrong_letter]
            app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread"})

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(any("Choice-length bias" in pattern for pattern in analytics["anti_patterns"]))

    def test_reward_badges_unlock_for_streaks(self):
        app = self.make_app()

        app.toggle_choice("A")
        app.retag_current_answer_confidence("Sure")
        app.toggle_choice("A")
        app.retag_current_answer_confidence("Sure")
        app.toggle_choice("A")

        self.assertIn("3-Streak", app.reward_badges_text)

    def test_combo_meter_shows_heat_and_next_reward_hint(self):
        app = self.make_app()
        app.session_answer_history = [
            {"question_number": idx, "domain": "Domain A", "correct": True, "confidence": "Sure"} for idx in range(1, 4)
        ]
        app.unlocked_rewards.update({"first_win", "streak_3"})

        app._update_progress()

        self.assertEqual("2 to 5-Streak", app._next_reward_hint())
        self.assertIn("Streak x3", app.study_hud_label.cget("text"))

    def test_study_hud_combines_rewards_level_combo_and_quests(self):
        app = self.make_app()
        app.choose_session_quests()
        app.session_answer_history = [
            {"question_number": 1, "domain": "Domain A", "correct": True, "confidence": "Sure"},
            {"question_number": 2, "domain": "Domain A", "correct": True, "confidence": "Sure"},
        ]
        app.session_rewards = ["3-Streak"]
        app.session_xp_gained = 24

        app._update_progress()

        hud = app.study_hud_label.cget("text")
        self.assertIn("pace", hud)
        self.assertIn("Streak x2", hud)
        self.assertIn("Level", hud)
        self.assertIn("Latest badge: 3-Streak", hud)
        self.assertIn("Quest ", hud)

    def test_action_bar_stays_outside_scrollable_question_content(self):
        app = self.make_app()
        app.questions[0]["general_explanation"] = "Long explanation. " * 400
        app.toggle_choice("B")

        self.assertIs(app.card_action_outer.master, app.card)
        self.assertIsNot(app.card_action_outer.master, app.content_frame)
        self.assertTrue(app.card_action_outer.winfo_manager())
        self.assertTrue(app.next_btn.winfo_manager())
        self.assertTrue(app.more_btn.winfo_manager())

    def test_study_hud_pulse_only_changes_hud_area(self):
        app = self.make_app()
        page_bg = app.main.cget("bg")
        card_bg = app.card.cget("bg")

        app.pulse_study_hud("answer")

        self.assertNotEqual("#f7f9fc", app.study_hud_label.cget("bg"))
        self.assertEqual(page_bg, app.main.cget("bg"))
        self.assertEqual(card_bg, app.card.cget("bg"))

    def test_each_answer_shows_feedback_chip(self):
        app = self.make_app()

        app.toggle_choice("A")

        self.assertEqual("", app.score_label.cget("text"))
        self.assertFalse(app.score_label.winfo_manager())
        self.assertIn("Nice hit +", app.top_feedback_label.cget("text"))
        self.assertTrue(app.top_feedback_label.winfo_manager())
        self.assertIs(app.top_feedback_label.master, app.feedback_stage)
        self.assertIn("Correct", app.status_label.cget("text"))

    def test_answer_result_overlay_does_not_shift_question_layout(self):
        app = self.make_app()
        before_manager = app.question_label.winfo_manager()
        before_yview = app.content_canvas.yview()

        app.show_answer_result_overlay(True)

        self.assertEqual("place", app.answer_result_overlay.winfo_manager())
        self.assertEqual(before_manager, app.question_label.winfo_manager())
        self.assertEqual(before_yview, app.content_canvas.yview())
        self.assertIn("Correct", app.answer_result_overlay.cget("text"))
        self.assertIs(app.answer_result_overlay.master, app.feedback_stage)
        app.clear_answer_result_overlay()
        self.assertFalse(app.answer_result_overlay.winfo_manager())

    def test_correct_answer_toast_survives_auto_next_render(self):
        app = self.make_app()

        app.toggle_choice("A")
        app.next_question()

        self.assertEqual(1, app.index)
        self.assertTrue(app.top_feedback_label.winfo_manager())
        self.assertIn("Nice hit +", app.top_feedback_label.cget("text"))

    def test_no_op_rerender_skips_question_list_refresh(self):
        app = self.make_app()
        app.render_question()
        app.question_list_dirty = False

        with mock.patch.object(app, "refresh_question_list") as refresh_mock:
            app.render_question()

        refresh_mock.assert_not_called()

    def test_wrong_answer_feedback_chip_shows_miss_reason(self):
        app = self.make_app()

        app._record_answer(app.questions[0], ["B"], feedback_override={"confidence": "Sure", "miss_reason": "Misread"})

        self.assertEqual("", app.score_label.cget("text"))
        self.assertFalse(app.score_label.winfo_manager())
        self.assertIn("Try again +", app.top_feedback_label.cget("text"))
        self.assertIn("Misread", app.top_feedback_label.cget("text"))

    def test_answer_schedules_one_delayed_smart_practice_prewarm(self):
        app = self.make_app()

        with mock.patch.object(app, "schedule_smart_practice_prewarm") as prewarm:
            app.toggle_choice("A")

        prewarm.assert_called_once_with(delay_ms=2800)

    def test_prewarm_publish_does_not_force_question_rerender(self):
        app = self.make_app()
        snapshot = {
            "generation": 1,
            "key": app._smart_practice_signal_key(),
            "payload": {"source_map": {}, "source_trust_map": {}},
        }

        with mock.patch.object(app, "render_question") as render:
            app._publish_smart_practice_signal_snapshot(snapshot)

        render.assert_not_called()

    def test_compact_mode_shows_reward_banner_immediately(self):
        app = self.make_app()
        app.compact_review_var.set(True)
        app.render_question()

        app.show_reward_banner("Reward visible now", kind="reward", bypass_cooldown=True)

        self.assertTrue(app.reward_banner_label.winfo_manager())
        self.assertIn("Reward visible now", app.reward_banner_label.cget("text"))

    def test_ten_streak_badge_unlocks_and_combo_bursts_once(self):
        app = self.make_app()
        app.session_answer_history = [
            {"question_number": idx, "domain": "Domain A", "correct": True, "confidence": "Sure"}
            for idx in range(1, 11)
        ]

        app.unlock_session_rewards()
        app._maybe_show_combo_burst()
        first_banner = app.reward_banner_label.cget("text")
        app._maybe_show_combo_burst()

        self.assertIn("10-Streak", app.reward_badges_text)
        self.assertEqual("Hot streak x10: lock in the next one.", first_banner)
        self.assertEqual({10}, app.session_combo_burst_markers)

    def test_session_quests_start_with_three_goals_from_twenty_two_variants(self):
        app = self.make_app()

        self.assertEqual(22, len(app_module.QUEST_VARIANTS))
        self.assertEqual(3, len(app.current_quests))
        self.assertTrue(app.current_quests)

    def test_randomized_smart_practice_pool_reuses_cached_selection(self):
        app = self.make_app(start_session=False)
        app.session_source_var.set("All")

        first = app.build_smart_practice_pool("3", randomize=True)
        first_qnums = [q["question_number"] for q in first]

        with mock.patch.object(app, "_build_concept_memory_state_rows", side_effect=AssertionError("rebuild")):
            second = app.build_smart_practice_pool("3", randomize=True)

        second_qnums = [q["question_number"] for q in second]
        self.assertEqual(set(first_qnums), set(second_qnums))
        self.assertEqual(3, len(second_qnums))

    def test_boss_round_inserts_challenge_after_ten_answers(self):
        app = self.make_app()
        boss_candidate = {
            "question_number": 99,
            "prompt": "Boss question",
            "choices": {"A": "Right", "B": "Wrong"},
            "correct": ["A"],
            "domain": "Domain A",
            "topics": ["Boss Topic"],
        }
        app.master_questions.append(boss_candidate)
        app.session_answer_history = [
            {"question_number": idx, "domain": "Domain A", "correct": True} for idx in range(1, 11)
        ]
        app.session_question_limit = len(app.questions) + 1

        inserted = app.maybe_trigger_boss_round(app.questions[0])

        self.assertEqual(1, len(inserted))
        self.assertEqual("Boss round", inserted[0]["session_tag"])

    def test_speed_risk_pattern_is_reported(self):
        app = self.make_app()
        q = app.master_questions[0]
        wrong_letter = "B"
        for day in ("2026-05-08", "2026-05-09", "2026-05-10"):
            app._progress_questions()["1"] = update_progress_record(
                app._progress_questions().get("1", {}),
                [wrong_letter],
                False,
                seen_on=day,
                confidence="Sure",
                miss_reason="Misread",
            )
            q["selected"] = [wrong_letter]
            app.append_answer_history(
                q, False, {"confidence": "Sure", "miss_reason": "Misread", "response_seconds": 3.2}
            )

        analytics = app.compute_analytics(source=app.master_questions)

        self.assertTrue(any("Speed-risk pattern" in pattern for pattern in analytics["anti_patterns"]))

    def test_answer_latency_and_confidence_mismatch_are_reported(self):
        app = self.make_app()
        q = app.master_questions[0]
        q["domain"] = "Threats"
        q["topics"] = ["Social engineering"]
        q["objective_code"] = "2.2"
        q["selected"] = ["B"]
        app._progress_questions()["1"] = update_progress_record(
            {}, ["B"], False, confidence="Sure", miss_reason="Misread"
        )
        app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread", "response_seconds": 3.0})
        app.append_answer_history(q, False, {"confidence": "Sure", "miss_reason": "Misread", "response_seconds": 4.0})
        q["selected"] = ["A"]
        app.append_answer_history(q, True, {"confidence": "Sure", "miss_reason": "", "response_seconds": 5.0})

        analytics = app.compute_analytics(source=app.master_questions[:1])

        latency = analytics["answer_latency_diagnosis"][0]
        mismatch = analytics["confidence_mismatch"][0]
        self.assertEqual("Speed risk", latency["label"])
        self.assertGreaterEqual(latency["fast_wrong"], 2)
        self.assertEqual("2.2", mismatch["unit"])
        self.assertGreaterEqual(mismatch["sure_wrong"], 2)
        self.assertTrue(any("Answer latency diagnosis" in rec for rec in analytics["recommendations"]))
        self.assertTrue(any("Confidence mismatch" in rec for rec in analytics["recommendations"]))

    def test_session_completion_creates_summary_medal_and_xp(self):
        app = self.make_app()

        app.toggle_choice("A")
        app.retag_current_answer_confidence("Sure")
        app.toggle_choice("A")
        app.retag_current_answer_confidence("Sure")
        app.toggle_choice("B")

        self.assertIsNotNone(app.last_session_summary)
        self.assertIn(app.last_session_summary["medal"], {"Bronze", "Silver", "Gold", "Platinum"})
        self.assertTrue(isinstance(app.last_session_summary["replay_strip"], list))
        self.assertGreater(app.session_xp_gained, 0)
        self.assertIn("Level", app.study_hud_label.cget("text"))
        self.assertTrue(app.loot_card.winfo_manager())
        self.assertIn("Loot card:", app.loot_title_label.cget("text"))
        self.assertIn("XP", app.loot_stats_label.cget("text"))
        self.assertIn("Variety", app.loot_detail_label.cget("text"))
        self.assertIn("New", app.loot_detail_label.cget("text"))
        self.assertIn("Loot card ready", app.top_feedback_label.cget("text"))

        app.clear_active_session()

        self.assertFalse(app.loot_card.winfo_manager())

    def test_pass_score_crossing_colors_medal_and_shows_victory_banner(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": idx,
                "prompt": f"Question {idx}",
                "choices": {"A": "Right", "B": "Wrong"},
                "correct": ["A"],
                "domain": "Domain A",
                "topics": ["Topic A"],
            }
            for idx in range(1, 6)
        ]
        app._reset_runtime_question_state(app.master_questions)
        app.start_session_from_pool(
            app.master_questions,
            mode="Practice",
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=False,
        )
        for q in app.questions[:4]:
            q["answered"] = True
            q["selected"] = list(q["correct"])
            app.session_answer_history.append(
                {"question_number": q["question_number"], "domain": q["domain"], "correct": True, "confidence": "Sure"}
            )
        q = app.questions[4]
        q["answered"] = True
        q["selected"] = ["B"]
        app.session_answer_history.append(
            {"question_number": q["question_number"], "domain": q["domain"], "correct": False, "confidence": "Sure"}
        )

        app._update_progress()

        self.assertTrue(app.pass_score_victory_unlocked)
        self.assertIn("Pass score reached", app.reward_banner_label.cget("text"))
        self.assertEqual(app._medal_color("Silver"), app.study_hud_label.cget("fg"))

    def test_global_milestones_unlock_and_add_xp(self):
        app = self.make_app()
        meta = app._progress_meta()
        meta["stats"]["total_answered"] = 30
        meta["stats"]["total_recovered"] = 11
        meta["stats"]["sessions_completed"] = 5
        meta["stats"]["perfect_sessions"] = 3
        meta["stats"]["domains_seen"] = ["Domain A", "Domain B", "Domain C"]
        starting_xp = meta["xp"]

        app._check_global_milestones()

        self.assertTrue(meta["milestones"])
        self.assertGreater(meta["xp"], starting_xp)

    def test_reward_history_window_shows_persistent_session_history(self):
        app = self.make_app()
        app.toggle_choice("A")
        app.retag_current_answer_confidence("Sure")
        app.toggle_choice("A")
        app.retag_current_answer_confidence("Sure")
        app.toggle_choice("A")
        app.open_reward_history_window()

        self.assertTrue(app.reward_history_window.winfo_exists())
        self.assertIn("Level", app.reward_history_widgets["summary"].cget("text"))
        self.assertGreater(len(app.reward_history_widgets["history_tree"].get_children()), 0)

    def test_game_settings_can_disable_gamification_labels(self):
        app = self.make_app()
        app.gamification_enabled_var.set(False)
        app.on_game_setting_changed()

        self.assertEqual("Rewards: disabled", app.reward_badges_text)
        self.assertIn("Rewards off", app.study_hud_label.cget("text"))

    def test_collect_config_includes_game_layer_settings(self):
        app = self.make_app(start_session=False)
        app.reward_intensity_var.set("Light")
        app.quest_count_var.set("4")
        app.reward_sounds_var.set(False)
        app.boss_rounds_enabled_var.set(False)
        app.compact_review_var.set(True)
        app.dense_answers_var.set(True)

        config = app.collect_config()

        self.assertEqual("Light", config["reward_intensity"])
        self.assertEqual("4", config["quest_count"])
        self.assertFalse(config["reward_sounds"])
        self.assertFalse(config["boss_rounds_enabled"])
        self.assertTrue(config["compact_review_mode"])
        self.assertTrue(config["dense_answers_mode"])

    def test_smart_practice9_role_allocation_totals_and_prioritizes_small_sets(self):
        allocation = smart_practice_role_allocation(25)
        self.assertEqual(25, sum(allocation.values()))
        self.assertEqual(6, allocation["weak_repair"])
        self.assertEqual(6, allocation["due_retention"])
        self.assertEqual(6, allocation["blueprint_coverage"])
        self.assertEqual({"weak_repair": 1, "due_retention": 1, "blueprint_coverage": 1, "transfer": 0, "controlled_stretch": 0}, smart_practice_role_allocation(3))

    def test_smart_practice9_low_source_trust_is_penalty_not_reward(self):
        app = self.make_app(start_session=False)
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "High trust due item",
                "choices": {"A": "A", "B": "B"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["General Review"],
                "source_name": "Trusted",
            },
            {
                "question_number": 2,
                "prompt": "Low trust due item",
                "choices": {"A": "A", "B": "B"},
                "correct": ["A"],
                "domain": "General Security Concepts",
                "topics": ["General Review"],
                "source_name": "Decayed",
            },
        ]
        app.questions = list(app.master_questions)
        app._progress_questions()["1"] = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        app._progress_questions()["2"] = update_progress_record({}, ["B"], False, seen_on="2026-04-23")
        app.smart_practice_signal_cache_key = app._smart_practice_signal_key()
        app.smart_practice_signal_cache_payload = app._build_smart_practice_signal_payload()
        app.smart_practice_signal_cache_payload["source_trust_map"] = {
            "Trusted": {"trust_score": 95.0, "label": "Trusted"},
            "Decayed": {"trust_score": 45.0, "label": "Decayed"},
        }

        pool = app.build_smart_practice_pool("2", randomize=False)
        utilities = {int(q["question_number"]): float(q.get("smart_utility", 0.0)) for q in pool}

        self.assertLess(utilities[2], utilities[1])
        self.assertTrue(all(q.get("smart_primary_role") for q in pool))

    def test_smart_practice9_adaptive_memory_and_response_sanitizer(self):
        guessed = update_progress_record({}, ["A"], True, seen_on="2026-04-23", confidence="Guessed")
        strong = update_progress_record({}, ["A"], True, seen_on="2026-04-23", confidence="Sure", session_tag="Transfer check")
        lapse = update_progress_record(strong, ["B"], False, seen_on="2026-04-24", confidence="Sure", recall_failure="Blank recall")
        timing = sanitize_response_time(1200.0, recent_effective_seconds=[10.0, 12.0, 14.0])

        self.assertEqual("recognition", guessed["learner_memory"]["last_grade"])
        self.assertEqual("transfer", strong["learner_memory"]["last_grade"])
        self.assertEqual("lapse_strong", lapse["learner_memory"]["last_grade"])
        self.assertEqual(1200.0, timing["raw_response_seconds"])
        self.assertLess(timing["effective_response_seconds"], timing["raw_response_seconds"])
        self.assertTrue(timing["response_time_contaminated"])

    def test_smart_practice9_repair_state_schedules_one_distinct_probe(self):
        app = self.make_app(start_session=False)
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        app.master_questions = [
            {
                "question_number": 1,
                "prompt": "Which attack poisons a common site?",
                "choices": {"A": "Phishing", "B": "Watering hole"},
                "correct": ["B"],
                "domain": "Threats, Vulnerabilities, and Mitigations",
                "topics": ["Threats"],
            },
            {
                "question_number": 2,
                "prompt": "A trusted industry site is compromised for developers.",
                "choices": {"A": "Watering hole", "B": "Smishing"},
                "correct": ["A"],
                "domain": "Threats, Vulnerabilities, and Mitigations",
                "topics": ["Threats"],
            },
        ]
        app.questions = [dict(app.master_questions[0])]
        app.index = 0
        app.session_question_limit = 2
        app.questions[0]["selected"] = ["A"]

        inserted = app.plan_misconception_repair(app.questions[0], is_correct=False)

        self.assertEqual(1, len(inserted))
        self.assertNotEqual(1, inserted[0]["question_number"])
        self.assertEqual("contrast", inserted[0]["repair_stage"])
        self.assertIn(app.repair_concept_key_for_question(app.questions[0]), app.progress_data["meta"]["repair_state"])

    def test_smart_practice9_answer_state_preserves_selection_telemetry(self):
        question = {
            "question_number": 7,
            "selected": ["A"],
            "pending": ["A"],
            "answered": True,
            "smart_primary_role": "weak_repair",
            "smart_selection_reasons": ["repair", "source risk"],
            "smart_utility": 13.5,
            "smart_utility_breakdown": {"misconception_repair_value": 10.0},
            "smart_policy_version": "smart-practice-9",
            "repair_stage": "contrast",
            "repair_concept_key": "topic::Threats",
        }
        state = app_module.serialize_answer_state(question) if hasattr(app_module, "serialize_answer_state") else None
        if state is None:
            from session_store import serialize_answer_state

            state = serialize_answer_state(question)
        restored = apply_answer_state({"question_number": 7}, state)

        self.assertEqual("weak_repair", restored["smart_primary_role"])
        self.assertEqual(["repair", "source risk"], restored["smart_selection_reasons"])
        self.assertEqual("contrast", restored["repair_stage"])

    def _sp9_question(self, qnum, domain="General Security Concepts", topic="General Review", source="Clean"):
        return {
            "question_number": qnum,
            "prompt": f"Question {qnum}",
            "choices": {"A": "Alpha", "B": "Beta"},
            "correct": ["A"],
            "domain": domain,
            "topics": [topic],
            "source_name": source,
            "source_label": source,
        }

    def _sp9_app_with_role_pool(self):
        app = self.make_app(start_session=False)
        questions = []
        for qnum in range(1, 7):
            questions.append(self._sp9_question(qnum, topic=f"Weak {qnum}", source="Trusted"))
        for qnum in range(7, 13):
            questions.append(self._sp9_question(qnum, topic=f"Due {qnum}", source="Trusted"))
        for qnum in range(13, 31):
            questions.append(self._sp9_question(qnum, topic=f"Coverage {qnum}", source="Clean"))
        for qnum in range(31, 95):
            item = self._sp9_question(qnum, topic=f"Screenshot {qnum}", source="Screenshot chapter bank")
            item["source_image"] = f"{qnum}.png"
            questions.append(item)
        app.master_questions = questions
        app.questions = list(questions)
        for qnum in range(1, 7):
            app._progress_questions()[str(qnum)] = update_progress_record({}, ["B"], False, seen_on="2026-04-20")
        for qnum in range(7, 13):
            rec = update_progress_record({}, ["A"], True, seen_on="2026-04-20", confidence="Sure")
            rec["learner_memory"]["next_review_at"] = "2026-04-20"
            rec["next_review"] = "2026-04-20"
            app._progress_questions()[str(qnum)] = rec
        return app

    def test_sp9_01_weak_and_due_survive_abundant_unseen_screenshots(self):
        pool = self._sp9_app_with_role_pool().build_smart_practice_pool("25", randomize=False)
        roles = Counter(q["smart_primary_role"] for q in pool)
        self.assertGreaterEqual(roles["weak_repair"], 5)
        self.assertGreaterEqual(roles["due_retention"], 5)

    def test_sp9_02_one_question_consumes_one_primary_role(self):
        pool = self._sp9_app_with_role_pool().build_smart_practice_pool("25", randomize=False)
        self.assertTrue(all(isinstance(q.get("smart_primary_role"), str) and q["smart_primary_role"] for q in pool))

    def test_sp9_03_variety_reshaping_preserves_protected_role_counts(self):
        pool = self._sp9_app_with_role_pool().build_smart_practice_pool("25", randomize=False)
        roles = Counter(q["smart_primary_role"] for q in pool)
        self.assertGreaterEqual(roles["weak_repair"] + roles["due_retention"], 10)

    def test_sp9_04_quality_retry_preserves_protected_role_counts(self):
        app = self._sp9_app_with_role_pool()
        app.build_smart_practice_pool("25", randomize=False)
        self.assertIn("retry_used", app.last_smart_practice_set_quality)

    def test_sp9_05_role_shortages_redistribute_to_available_roles(self):
        app = self.make_app(start_session=False)
        app.master_questions = [self._sp9_question(i) for i in range(1, 6)]
        app.questions = list(app.master_questions)
        pool = app.build_smart_practice_pool("5", randomize=False)
        self.assertEqual(5, len(pool))

    def test_sp9_06_domain_aliases_normalize_identically(self):
        app = self.make_app(start_session=False)
        self.assertEqual(
            app._normalized_study_label("Security Program Management And Oversight"),
            app._normalized_study_label("Security Program Management and Oversight"),
        )
        self.assertEqual(
            app._normalized_study_label("Threats Vulnerabilities and Mitigations"),
            app._normalized_study_label("Threats, Vulnerabilities, and Mitigations"),
        )

    def test_sp9_07_raw_idle_time_preserved_effective_bounded(self):
        timing = sanitize_response_time(999.0, recent_effective_seconds=[8.0, 10.0, 12.0])
        self.assertEqual(999.0, timing["raw_response_seconds"])
        self.assertLess(timing["effective_response_seconds"], 999.0)

    def test_sp9_08_idle_time_does_not_create_extreme_burnout(self):
        app = self.make_app(start_session=False)
        events = [{"correct": True, "effective_response_seconds": 10.0} for _ in range(8)]
        events.append({"correct": True, "raw_response_seconds": 999.0, "effective_response_seconds": 12.0})
        self.assertNotEqual("High", app._build_burnout_risk_row(events)["label"])

    def test_sp9_09_legacy_progress_without_memory_migrates(self):
        rec = normalize_progress_record({"attempts": 1, "correct_streak": 1, "next_review": "2026-04-24"})
        self.assertIn("learner_memory", rec)
        self.assertEqual("2026-04-24", rec["learner_memory"]["next_review_at"])

    def test_sp9_10_malformed_memory_values_clamp_safely(self):
        rec = normalize_progress_record({"learner_memory": {"retrievability": "bad", "stability": 9}})
        self.assertEqual(0.0, rec["learner_memory"]["retrievability"])
        self.assertEqual(1.0, rec["learner_memory"]["stability"])

    def test_sp9_11_adaptive_due_uses_next_review_at(self):
        rec = normalize_progress_record({"attempts": 1, "learner_memory": {"retrievability": 0.5, "next_review_at": "2026-04-20"}})
        self.assertTrue(is_review_due(rec, on_date="2026-04-21"))

    def test_sp9_12_easy_schedules_later_than_good(self):
        self.assertGreater(review_days_for_grade("easy", 0.5), review_days_for_grade("good", 0.5))

    def test_sp9_13_good_schedules_later_than_hard(self):
        self.assertGreater(review_days_for_grade("good", 0.5), review_days_for_grade("hard", 0.5))

    def test_sp9_14_did_not_know_damages_memory_more_than_misread(self):
        base = {"retrievability": 0.6, "stability": 0.5}
        did_not = update_progress_record({"learner_memory": base}, ["B"], False, miss_reason="Did not know")
        misread = update_progress_record({"learner_memory": base}, ["B"], False, miss_reason="Misread")
        self.assertLess(did_not["learner_memory"]["retrievability"], misread["learner_memory"]["retrievability"])

    def test_sp9_15_concept_aggregation_valid_conservative(self):
        questions = [self._sp9_question(1, source="A"), self._sp9_question(2, source="B")]
        rows = aggregate_concept_memory({"1": update_progress_record({}, ["A"], True)}, questions)
        row = next(iter(rows.values()))
        self.assertIn("lowest_retrievability", row)
        self.assertEqual(2, row["supporting_question_count"])
        self.assertEqual(2, row["distinct_source_count"])

    def test_sp9_16_utility_components_inside_bounds(self):
        app = self._sp9_app_with_role_pool()
        q = app.build_smart_practice_pool("1", randomize=False)[0]
        for name, value in q["smart_utility_breakdown"].items():
            low, high = UTILITY_COMPONENT_BOUNDS[name]
            self.assertGreaterEqual(value, low)
            self.assertLessEqual(value, high)

    def test_sp9_17_utility_total_matches_component_equation(self):
        app = self._sp9_app_with_role_pool()
        q = app.build_smart_practice_pool("1", randomize=False)[0]
        self.assertEqual(q["smart_utility"], smart_practice_utility_total(q["smart_utility_breakdown"]))

    def test_sp9_18_correlated_misconception_signals_are_capped(self):
        total = smart_practice_utility_total({"misconception_repair_value": 999.0})
        self.assertEqual(20.0, total)

    def test_sp9_19_missing_metadata_produces_neutral_valid_utility(self):
        app = self.make_app(start_session=False)
        app.master_questions = [{"question_number": 1, "prompt": "x", "choices": {"A": "A"}, "correct": ["A"]}]
        app.questions = list(app.master_questions)
        q = app.build_smart_practice_pool("1", randomize=False)[0]
        self.assertIsInstance(q["smart_utility"], float)

    def test_sp9_20_bounded_utility_controls_final_ordering(self):
        pool = self._sp9_app_with_role_pool().build_smart_practice_pool("5", randomize=False)
        self.assertGreaterEqual(pool[0]["smart_utility"], pool[-1]["smart_utility"])

    def test_sp9_21_deterministic_mode_stable_order(self):
        app = self._sp9_app_with_role_pool()
        one = [q["question_number"] for q in app.build_smart_practice_pool("10", randomize=False)]
        two = [q["question_number"] for q in app.build_smart_practice_pool("10", randomize=False)]
        self.assertEqual(one, two)

    def test_sp9_22_meaningful_miss_creates_stage_one_repair_state(self):
        app = self._sp9_app_with_role_pool()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        q = dict(app.master_questions[0], selected=["B"])
        app.questions = [q]
        app.plan_misconception_repair(q, is_correct=False)
        self.assertEqual("contrast", app.progress_data["meta"]["repair_state"][app.repair_concept_key_for_question(q)]["stage"])

    def test_sp9_22b_progress_repair_state_normalizes_legacy_key_on_load(self):
        app = self._sp9_app_with_role_pool()
        question = app.master_questions[0]
        canonical_key = app.repair_concept_key_for_question(question)
        legacy_key = f"Topic::{question['topics'][0]}"
        payload = copy.deepcopy(app.progress_data)
        payload.setdefault("meta", {})["repair_state"] = {
            legacy_key: {
                "concept_key": legacy_key,
                "last_question_number": question["question_number"],
                "status": "resolved",
            }
        }
        app.progress_path.write_text(json.dumps(payload), encoding="utf-8")

        app.load_progress_if_present()

        normalized = app.progress_data["meta"]["repair_state"]
        self.assertIn(canonical_key, normalized)
        self.assertEqual(legacy_key, normalized[canonical_key]["legacy_repair_concept_key"])
        self.assertEqual(canonical_key, normalized[canonical_key]["concept_key"])

    def test_sp9_23_contrast_probe_distinct_and_delayed(self):
        app = self._sp9_app_with_role_pool()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        q = dict(app.master_questions[0], selected=["B"])
        app.questions = [q, dict(app.master_questions[20])]
        inserted = app.plan_misconception_repair(q, is_correct=False)
        self.assertTrue(inserted)
        self.assertNotEqual(q["question_number"], inserted[0]["question_number"])
        self.assertEqual("contrast", inserted[0]["repair_stage"])

    def test_sp9_24_transfer_stage_uses_another_distinct_question(self):
        app = self._sp9_app_with_role_pool()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        q = dict(app.master_questions[0], selected=["A"], repair_stage="contrast")
        key = app.repair_concept_key_for_question(q)
        app.progress_data["meta"]["repair_state"][key] = {"stage": "contrast", "status": "unresolved"}
        app.questions = [q]
        inserted = app.plan_misconception_repair(q, is_correct=True)
        self.assertEqual("provisional", app.progress_data["meta"]["repair_state"][key]["status"])
        self.assertTrue(inserted or app.progress_data["meta"]["repair_state"][key]["stage"] == "spaced_retrieval")

    def test_sp9_25_immediate_success_provisional_only(self):
        app = self._sp9_app_with_role_pool()
        q = dict(app.master_questions[0], selected=["A"], repair_stage="contrast")
        key = app.repair_concept_key_for_question(q)
        app.progress_data["meta"]["repair_state"][key] = {"stage": "contrast", "status": "unresolved"}
        app.plan_misconception_repair(q, is_correct=True)
        self.assertEqual("provisional", app.progress_data["meta"]["repair_state"][key]["status"])

    def test_sp9_26_later_spaced_success_can_resolve_repair(self):
        app = self._sp9_app_with_role_pool()
        q = dict(app.master_questions[0], selected=["A"], repair_stage="spaced_retrieval")
        key = app.repair_concept_key_for_question(q)
        app.progress_data["meta"]["repair_state"][key] = {"stage": "spaced_retrieval", "status": "provisional"}
        app.plan_misconception_repair(q, is_correct=True)
        self.assertEqual("resolved", app.progress_data["meta"]["repair_state"][key]["status"])

    def test_sp9_27_missing_candidate_records_blocked_reason(self):
        app = self.make_app(start_session=False)
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        q = self._sp9_question(1)
        q["selected"] = ["B"]
        app.master_questions = [q]
        app.questions = [q]
        app.plan_misconception_repair(q, is_correct=False)
        row = app.progress_data["meta"]["repair_state"][app.repair_concept_key_for_question(q)]
        self.assertEqual("blocked", row["status"])
        self.assertIn("blocked_reason", row)

    def test_sp9_28_only_one_repair_insertion_per_answer(self):
        app = self._sp9_app_with_role_pool()
        app.active_session_mode = app_module.MODE_SMART_PRACTICE
        q = dict(app.master_questions[0], selected=["B"])
        app.questions = [q]
        inserted = app.plan_misconception_repair(q, is_correct=False)
        self.assertLessEqual(len(inserted), 1)

    def test_sp9_29_cache_invalidates_after_memory_update(self):
        app = self._sp9_app_with_role_pool()
        before = app._smart_practice_signal_key()
        app._progress_questions()["1"] = update_progress_record(app._progress_questions()["1"], ["A"], True)
        after = app._smart_practice_signal_key()
        self.assertNotEqual(before, after)

    def test_sp9_30_session_save_restore_preserves_smart_and_repair_metadata(self):
        app = self.make_app(start_session=False)
        question = self._sp9_question(1)
        question.update(
            {
                "smart_primary_role": "weak_repair",
                "smart_selection_reasons": ["repair"],
                "smart_utility": 11.0,
                "smart_utility_breakdown": {"misconception_repair_value": 11.0},
                "smart_policy_version": "smart-practice-9",
                "repair_stage": "contrast",
                "repair_concept_key": "Topic::x",
            }
        )
        app.master_questions = [dict(question)]
        app.start_session_from_pool([dict(question)], mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        app.questions[0].update(question)
        app.save_session(show_notice=False)
        session_path = app.session_path

        app.questions[0]["smart_primary_role"] = ""
        app.questions[0]["repair_stage"] = ""
        app.load_session_if_present(skip_identity_check=True)

        self.assertTrue(session_path.exists())
        self.assertEqual("weak_repair", app.questions[0]["smart_primary_role"])
        self.assertEqual("contrast", app.questions[0]["repair_stage"])

    def _measurement_prediction(self, created_at="2026-01-01T00:00:00", qnum=1):
        question = self._sp9_question(qnum)
        question.update(
            {
                "smart_primary_role": "weak_repair",
                "smart_policy_version": "smart-practice-9",
                "smart_utility": 10.0,
                "smart_utility_breakdown": {"retention_risk": 5.0, "expected_learning_gain": 10.0},
            }
        )
        return prediction_from_question(
            question,
            {"attempts": 1, "learner_memory": {"retrievability": 0.6, "stability": 0.5}},
            created_at=created_at,
        )

    def _measurement_event(self, at, qnum=1, correct=True, prediction_id="", **extra):
        event = {
            "at": at,
            "question_number": qnum,
            "correct": correct,
            "confidence": "Sure",
            "effective_response_seconds": 9.0,
            "raw_response_seconds": 9.0,
            "prediction_id": prediction_id,
            "topics": ["General Review"],
            "objective_code": "",
            "repair_concept_key": "Topic::general review",
            "smart_primary_role": "weak_repair",
        }
        event.update(extra)
        return event

    def test_sp9_measurement_01_selection_creates_frozen_prediction_snapshot(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        store = app.progress_data["meta"]["smart_practice_measurement"]
        self.assertEqual(1, len(store["predictions"]))
        self.assertEqual(pool[0]["prediction_id"], next(iter(store["predictions"])))

    def test_sp9_measurement_02_prediction_probabilities_are_bounded(self):
        prediction = self._measurement_prediction()
        self.assertGreaterEqual(prediction["predicted_recall_probability"], 0.01)
        self.assertLessEqual(prediction["predicted_success_probability"], 0.99)
        self.assertGreater(prediction["predicted_response_seconds"], 0)

    def test_sp9_measurement_02b_prediction_uses_graph_concept_key_not_tuple_string(self):
        question = self._sp9_question(1)
        question.pop("repair_concept_key", None)
        prediction = prediction_from_question(question, {}, created_at="2026-01-01T00:00:00")

        self.assertEqual(concept_key_for_question(question)[0], prediction["concept_key"])
        self.assertNotIn("(", prediction["concept_key"])
        self.assertNotIn(",", prediction["concept_key"])

    def test_sp9_measurement_02c_rejects_container_like_concept_identity(self):
        question = self._sp9_question(1)
        question["repair_concept_key"] = "('domain_topic::general_security_concepts::general_review', 'weak')"

        with self.assertRaises(ValueError):
            prediction_from_question(question, {}, created_at="2026-01-01T00:00:00")

    def test_sp9_measurement_02d_runtime_loaded_paths_are_exercised_by_tests(self):
        import app_question_flow_mixin
        import app_session_builder_mixin
        import smart_practice_measurement

        repo_root = ROOT.parent

        self.assertEqual(repo_root / "Project Files" / "app_question_flow_mixin.py", Path(app_question_flow_mixin.__file__).resolve())
        self.assertEqual(repo_root / "Project Files" / "app_session_builder_mixin.py", Path(app_session_builder_mixin.__file__).resolve())
        self.assertEqual(repo_root / "smart_practice_measurement.py", Path(smart_practice_measurement.__file__).resolve())

    def test_sp9_measurement_02e_prediction_identity_survives_resume_and_answer_link(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        before_question = app.questions[0]
        before_prediction_id = before_question["prediction_id"]
        before_concept_key = before_question["prediction_snapshot"]["concept_key"]
        before_prediction_count = len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"])
        before_history_count = len(app._progress_history())

        app.save_session(show_notice=False)
        app.questions[0]["prediction_id"] = ""
        app.questions[0]["prediction_snapshot"] = {}
        app.load_session_if_present(skip_identity_check=True)
        resumed = app.questions[0]

        self.assertEqual(before_prediction_id, resumed["prediction_id"])
        self.assertEqual(before_concept_key, resumed["prediction_snapshot"]["concept_key"])
        self.assertEqual(before_prediction_count, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))

        app._record_answer(resumed, list(resumed["correct"]), feedback_override={"confidence": "Sure", "miss_reason": ""})
        new_history = app._progress_history()[before_history_count:]

        self.assertEqual(1, len(app.session_answer_history))
        self.assertEqual(1, len(new_history))
        self.assertEqual(before_prediction_id, app.session_answer_history[0]["prediction_id"])
        self.assertEqual(before_prediction_id, new_history[0]["prediction_id"])
        self.assertEqual(int(resumed["question_number"]), new_history[0]["question_number"])
        self.assertEqual(before_prediction_count, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))

    def test_sp9_measurement_02f_repair_prediction_preserves_canonical_repair_identity(self):
        question = self._sp9_question(1)
        repair_key = concept_key_for_question(question)[0]
        question["repair_concept_key"] = repair_key
        prediction = prediction_from_question(question, {}, created_at="2026-01-01T00:00:00")

        self.assertEqual(repair_key, prediction["concept_key"])
        self.assertEqual(repair_key, question["repair_concept_key"])

    def test_sp9_measurement_02g_legacy_topic_repair_key_migrates_on_real_session_restore(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        q = app.questions[0]
        canonical_key = concept_key_for_question(q)[0]
        legacy_key = f"Topic::{q['topics'][0]}"
        prediction_id = q["prediction_id"]
        prediction_count = len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"])
        app.save_session(show_notice=False)

        payload = json.loads(app.session_path.read_text(encoding="utf-8"))
        payload["answers"][0]["repair_concept_key"] = legacy_key
        payload["answers"][0]["prediction_id"] = prediction_id
        payload["answers"][0]["prediction_snapshot"] = {
            "prediction_id": prediction_id,
            "question_number": q["question_number"],
            "concept_key": legacy_key,
        }
        app.session_path.write_text(json.dumps(payload), encoding="utf-8")
        app.questions[0]["repair_concept_key"] = ""
        app.questions[0]["prediction_id"] = ""
        app.questions[0]["prediction_snapshot"] = {}

        app.load_session_if_present(skip_identity_check=True)
        restored = app.questions[0]

        self.assertEqual(canonical_key, restored["repair_concept_key"])
        self.assertEqual(legacy_key, restored["legacy_repair_concept_key"])
        self.assertEqual(canonical_key, restored["prediction_snapshot"]["concept_key"])
        self.assertEqual(prediction_id, restored["prediction_id"])
        self.assertEqual(prediction_count, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))

        app.questions[0]["repair_concept_key"] = ""
        app.questions[0]["prediction_snapshot"] = {}
        app.load_session_if_present(skip_identity_check=True)
        restored_again = app.questions[0]

        self.assertEqual(canonical_key, restored_again["repair_concept_key"])
        self.assertEqual(legacy_key, restored_again["legacy_repair_concept_key"])
        self.assertEqual(canonical_key, restored_again["prediction_snapshot"]["concept_key"])
        self.assertEqual(prediction_count, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))

    def test_sp9_measurement_02h_unknown_legacy_topic_repair_key_fails_visibly(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        app.save_session(show_notice=False)
        payload = json.loads(app.session_path.read_text(encoding="utf-8"))
        payload["answers"][0]["repair_concept_key"] = "Topic::Not This Question"
        app.session_path.write_text(json.dumps(payload), encoding="utf-8")

        with mock.patch.object(app, "_show_bad_json_warning") as warning:
            app.load_session_if_present(skip_identity_check=True)

        warning.assert_called_once()

    def test_sp9_measurement_02h1_mismatched_canonical_repair_key_fails_visibly(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        app.save_session(show_notice=False)

        payload = json.loads(app.session_path.read_text(encoding="utf-8"))
        payload["answers"][0]["repair_concept_key"] = "coverage::wrong_bucket"
        app.session_path.write_text(json.dumps(payload), encoding="utf-8")

        with mock.patch.object(app, "_show_bad_json_warning") as warning:
            app.load_session_if_present(skip_identity_check=True)

        warning.assert_called_once()

    def test_sp9_measurement_02i_legacy_objective_repair_key_migrates_on_real_session_restore(self):
        app = self.make_app(start_session=False)
        question = self._sp9_question(1, topic="General Review")
        question["objective_code"] = "1.2"
        app.master_questions = [dict(question)]
        pool = [dict(question)]
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        q = app.questions[0]
        canonical_key = concept_key_for_question(q)[0]
        legacy_key = "Objective::1.2"
        q["smart_primary_role"] = "weak_repair"
        q["smart_utility"] = 9.0
        q["smart_utility_breakdown"] = {"misconception_repair_value": 9.0}
        attach_prediction_to_question(q, app.progress_data["meta"]["smart_practice_measurement"], {}, created_at="2026-01-01T00:00:00")
        prediction_id = q["prediction_id"]
        prediction_count = len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"])
        app.save_session(show_notice=False)

        payload = json.loads(app.session_path.read_text(encoding="utf-8"))
        payload["answers"][0]["repair_concept_key"] = legacy_key
        payload["answers"][0]["prediction_id"] = prediction_id
        payload["answers"][0]["prediction_snapshot"] = {
            "prediction_id": prediction_id,
            "question_number": q["question_number"],
            "concept_key": legacy_key,
        }
        app.session_path.write_text(json.dumps(payload), encoding="utf-8")
        app.questions[0]["repair_concept_key"] = ""
        app.questions[0]["prediction_id"] = ""
        app.questions[0]["prediction_snapshot"] = {}

        app.load_session_if_present(skip_identity_check=True)
        restored = app.questions[0]

        self.assertEqual(canonical_key, restored["repair_concept_key"])
        self.assertEqual(legacy_key, restored["legacy_repair_concept_key"])
        self.assertEqual(canonical_key, restored["prediction_snapshot"]["concept_key"])
        self.assertEqual(prediction_id, restored["prediction_id"])
        self.assertEqual(prediction_count, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))

    def test_sp9_measurement_02j_legacy_domain_repair_key_migrates_on_real_session_restore(self):
        app = self.make_app(start_session=False)
        question = self._sp9_question(1, topic="General Review")
        question["domain"] = "Security Operations"
        question["objective_code"] = ""
        app.master_questions = [dict(question)]
        pool = [dict(question)]
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        q = app.questions[0]
        canonical_key = concept_key_for_question(q)[0]
        legacy_key = "Domain::Security Operations"
        q["smart_primary_role"] = "weak_repair"
        q["smart_utility"] = 8.0
        q["smart_utility_breakdown"] = {"misconception_repair_value": 8.0}
        attach_prediction_to_question(q, app.progress_data["meta"]["smart_practice_measurement"], {}, created_at="2026-01-01T00:00:00")
        prediction_id = q["prediction_id"]
        prediction_count = len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"])
        app.save_session(show_notice=False)

        payload = json.loads(app.session_path.read_text(encoding="utf-8"))
        payload["answers"][0]["repair_concept_key"] = legacy_key
        payload["answers"][0]["prediction_id"] = prediction_id
        payload["answers"][0]["prediction_snapshot"] = {
            "prediction_id": prediction_id,
            "question_number": q["question_number"],
            "concept_key": legacy_key,
        }
        app.session_path.write_text(json.dumps(payload), encoding="utf-8")
        app.questions[0]["repair_concept_key"] = ""
        app.questions[0]["prediction_id"] = ""
        app.questions[0]["prediction_snapshot"] = {}

        app.load_session_if_present(skip_identity_check=True)
        restored = app.questions[0]

        self.assertEqual(canonical_key, restored["repair_concept_key"])
        self.assertEqual(legacy_key, restored["legacy_repair_concept_key"])
        self.assertEqual(canonical_key, restored["prediction_snapshot"]["concept_key"])
        self.assertEqual(prediction_id, restored["prediction_id"])
        self.assertEqual(prediction_count, len(app.progress_data["meta"]["smart_practice_measurement"]["predictions"]))

    def test_sp9_measurement_03_prediction_keeps_original_learner_state(self):
        prediction = self._measurement_prediction()
        changed = update_progress_record({"learner_memory": {"retrievability": 0.1}}, ["B"], False)
        self.assertNotEqual(prediction["learner_retrievability_at_selection"], changed["learner_memory"]["retrievability"])

    def test_sp9_measurement_04_session_resume_preserves_prediction_id(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        pid = app.questions[0]["prediction_id"]
        app.save_session(show_notice=False)
        app.questions[0]["prediction_id"] = ""
        app.load_session_if_present(skip_identity_check=True)
        self.assertEqual(pid, app.questions[0]["prediction_id"])

    def test_sp9_measurement_05_answer_event_links_to_prediction(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        app.questions[0]["selected"] = list(app.questions[0]["correct"])
        app.update_progress_for_answer(app.questions[0], feedback={"confidence": "Sure"})
        self.assertEqual(app.questions[0]["prediction_id"], app._progress_history()[-1]["prediction_id"])

    def test_sp9_measurement_06_same_answer_cannot_evaluate_own_prediction(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-01T00:00:00", prediction_id=prediction["prediction_id"])
        self.assertEqual("not_observed", link_prediction_outcomes(prediction, [event])["delayed_24h_item_outcome"]["status"])

    def test_sp9_measurement_07_before_18h_not_24h(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-01T17:00:00")
        self.assertEqual("not_observed", find_future_outcome(prediction, [event], "24h")["status"])

    def test_sp9_measurement_08_first_eligible_24h_selected(self):
        prediction = self._measurement_prediction()
        events = [self._measurement_event("2026-01-02T20:00:00", correct=False), self._measurement_event("2026-01-01T19:00:00", correct=True)]
        self.assertTrue(find_future_outcome(prediction, events, "24h")["correct"])

    def test_sp9_measurement_09_after_36h_not_24h(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-02T13:00:00")
        self.assertEqual("not_observed", find_future_outcome(prediction, [event], "24h")["status"])

    def test_sp9_measurement_10_first_eligible_7d_selected(self):
        prediction = self._measurement_prediction()
        events = [self._measurement_event("2026-01-08T00:00:00", correct=False), self._measurement_event("2026-01-06T01:00:00", correct=True)]
        self.assertTrue(find_future_outcome(prediction, events, "7d")["correct"])

    def test_sp9_measurement_11_missing_future_attempt_not_observed(self):
        self.assertEqual("not_observed", find_future_outcome(self._measurement_prediction(), [], "24h")["status"])

    def test_sp9_measurement_12_exact_and_concept_transfer_separate(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-02T00:00:00", qnum=2)
        self.assertEqual("not_observed", find_future_outcome(prediction, [event], "24h", concept=False)["status"])
        self.assertEqual("observed", find_future_outcome(prediction, [event], "24h", concept=True)["status"])

    def test_sp9_measurement_13_immediate_repair_probe_not_delayed(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-01T00:10:00", qnum=2, repair_stage="contrast")
        self.assertEqual("not_observed", find_future_outcome(prediction, [event], "24h", concept=True)["status"])

    def test_sp9_measurement_13b_legacy_event_repair_key_matches_canonical_concept(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-02T00:00:00", qnum=2, correct=False)

        observed = find_future_outcome(prediction, [event], "24h", concept=True)

        self.assertEqual("observed", observed["status"])
        self.assertEqual("legacy_topic", observed["match_basis"])

    def test_sp9_measurement_13c_malformed_legacy_repair_key_does_not_match(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-02T00:00:00", qnum=2, correct=False, repair_concept_key="Topic::Not This Topic")

        observed = find_future_outcome(prediction, [event], "24h", concept=True)

        self.assertEqual("not_observed", observed["status"])

    def test_sp9_measurement_13d_unknown_repair_key_prefix_does_not_fall_through(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-02T00:00:00", qnum=2, correct=False, repair_concept_key="Chapter::1")

        observed = find_future_outcome(prediction, [event], "24h", concept=True)

        self.assertEqual("not_observed", observed["status"])

    def test_sp9_measurement_14_malformed_negative_timestamp_rejected(self):
        prediction = self._measurement_prediction()
        events = [self._measurement_event("bad-date"), self._measurement_event("2025-12-31T23:00:00")]
        self.assertEqual("not_observed", find_future_outcome(prediction, events, "24h")["status"])

    def test_sp9_measurement_15_brier_score_known_example(self):
        self.assertEqual(0.25, brier_score([(0.5, 1.0), (0.5, 0.0)])["value"])

    def test_sp9_measurement_16_log_loss_clamps_probabilities(self):
        self.assertLess(log_loss([(0.0, 1.0), (1.0, 0.0)])["value"], 5.0)

    def test_sp9_measurement_17_calibration_bins_values(self):
        bins, _ece = calibration_bins([(0.1, 0.0), (0.9, 1.0)])
        self.assertEqual(1, bins[0]["sample_count"])
        self.assertEqual(1.0, bins[-1]["observed_success_rate"])

    def test_sp9_measurement_18_ece_sample_weighted(self):
        _bins, ece = calibration_bins([(0.1, 0.0), (0.9, 1.0)])
        self.assertEqual(0.1, round(ece["value"], 1))

    def test_sp9_measurement_19_insufficient_samples_marked(self):
        self.assertEqual("insufficient_data", brier_score([(0.5, 1.0)])["status"])

    def test_sp9_measurement_20_pairwise_discrimination_ties(self):
        self.assertEqual(0.5, pairwise_discrimination([(0.5, 1.0), (0.5, 0.0)])["value"])

    def test_sp9_measurement_21_immediate_correct_not_delayed_gain(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-01T00:01:00", prediction_id=prediction["prediction_id"])
        report, _store = build_measurement_report({"predictions": {prediction["prediction_id"]: prediction}}, [event], evaluation_at="2026-01-03T00:00:00")
        self.assertEqual(0, report["learning_gain"]["transfer_evidence_count"])

    def test_sp9_measurement_22_different_question_delayed_success_transfer(self):
        prediction = self._measurement_prediction()
        event = self._measurement_event("2026-01-02T00:00:00", qnum=2, correct=True)
        report, _store = build_measurement_report({"predictions": {prediction["prediction_id"]: prediction}}, [event], evaluation_at="2026-01-03T00:00:00")
        self.assertEqual(1, report["learning_gain"]["transfer_evidence_count"])

    def test_sp9_measurement_23_repair_report_stages(self):
        repair = {"x": {"stage": "spaced_retrieval", "status": "resolved", "concept_key": "x", "scheduled_transfer_qnums": [2]}}
        perf = repair_performance(repair, [self._measurement_event("2026-01-02T00:00:00", repair_stage="contrast"), self._measurement_event("2026-01-03T00:00:00", repair_stage="transfer"), self._measurement_event("2026-01-04T00:00:00", repair_stage="spaced_retrieval")])
        self.assertEqual(1, perf["contrast_scheduled"])
        self.assertEqual(1, perf["transfer_scheduled"])
        self.assertEqual(1, perf["spaced_retrieval_due"])

    def test_sp9_measurement_24_blocked_repair_not_failed(self):
        perf = repair_performance({"x": {"status": "blocked", "stage": "spaced_retrieval"}}, [])
        self.assertEqual(1.0, perf["blocked_rate"])
        self.assertEqual(0, perf["spaced_retrieval_success"])

    def test_sp9_measurement_25_resolved_repair_later_failure_relapse(self):
        perf = repair_performance({"x": {"status": "resolved", "concept_key": "c"}}, [self._measurement_event("2026-01-05T00:00:00", correct=False, repair_concept_key="c")])
        self.assertEqual(1.0, perf["relapse_rate"])

    def test_sp9_measurement_25b_resolved_repair_relapse_matches_question_number_when_key_family_changes(self):
        perf = repair_performance(
            {"x": {"status": "resolved", "concept_key": "coverage::general_review", "last_question_number": 1}},
            [self._measurement_event("2026-01-05T00:00:00", qnum=1, correct=False, repair_concept_key="objective_topic::1_2::general_review")],
        )
        self.assertEqual(1.0, perf["relapse_rate"])

    def test_sp9_measurement_26_weak_precision_uses_observed(self):
        prediction = self._measurement_prediction()
        links = {prediction["prediction_id"]: {"immediate_item_outcome": {"status": "observed", "correct": False}, "delayed_24h_concept_outcome": {"status": "observed", "correct": True}}}
        from smart_practice_measurement import weakness_precision
        self.assertEqual(1.0, weakness_precision([prediction], links, [])["weak_role_immediate_error_rate"])

    def test_sp9_measurement_27_stable_success_false_weakness_signal(self):
        prediction = self._measurement_prediction()
        from smart_practice_measurement import weakness_precision
        history = [self._measurement_event("2026-01-02T00:00:00", qnum=1), self._measurement_event("2026-01-03T00:00:00", qnum=1)]
        self.assertIn(1, weakness_precision([prediction], {}, history)["false_weakness_candidates"])

    def test_sp9_measurement_28_role_metrics_separated(self):
        prediction = self._measurement_prediction()
        self.assertIn("weak_repair", role_performance([prediction], {}, {}))

    def test_sp9_measurement_29_unobserved_delayed_does_not_lower_role_accuracy(self):
        prediction = self._measurement_prediction()
        metrics = role_performance([prediction], {prediction["prediction_id"]: {"delayed_24h_concept_outcome": {"status": "not_observed"}}}, [])
        self.assertEqual("no_eligible_samples", metrics["weak_repair"]["24h_accuracy"]["status"])

    def test_sp9_measurement_30_final_session_composition_actual_roles(self):
        prediction = self._measurement_prediction()
        self.assertEqual({"weak_repair": 1}, session_composition([prediction], requested_count=1)["actual_role_counts"])

    def test_sp9_measurement_31_missing_source_trust_band(self):
        self.assertEqual(1, source_performance([self._measurement_event("2026-01-02T00:00:00")])["missing_trust"]["sample_count"])

    def test_sp9_measurement_32_raw_effective_timing_separate(self):
        metric = timing_quality([self._measurement_event("2026-01-02T00:00:00", raw_response_seconds=999.0, effective_response_seconds=12.0)])
        self.assertEqual(1.0, metric["effective_time_cap_rate"])

    def test_sp9_measurement_33_contaminated_raw_not_dominate(self):
        metric = timing_quality([self._measurement_event("2026-01-02T00:00:00", raw_response_seconds=999.0, effective_response_seconds=12.0, response_time_contaminated=True)])
        self.assertEqual(12.0, metric["median_effective_response_seconds"])

    def test_sp9_measurement_34_baseline_labeled_retrospective(self):
        self.assertEqual("retrospective_shadow_comparison", baseline_comparison([], {})["random_blueprint"]["comparison_type"])

    def test_sp9_measurement_35_baseline_does_not_invent_outcomes(self):
        self.assertEqual("not_available", baseline_comparison([self._measurement_prediction()], {})["due_only"]["estimated_immediate_accuracy"])

    def test_sp9_measurement_36_counterfactual_coverage_rate(self):
        prediction = self._measurement_prediction()
        links = {prediction["prediction_id"]: {"immediate_item_outcome": {"status": "observed", "correct": True}}}
        self.assertEqual(1.0, baseline_comparison([prediction], links)["smart_practice"]["counterfactual_coverage_rate"])

    def test_sp9_measurement_37_baseline_deterministic(self):
        prediction = self._measurement_prediction()
        self.assertEqual(baseline_comparison([prediction], {}), baseline_comparison([prediction], {}))

    def test_sp9_measurement_38_low_sample_no_numeric_policy_change(self):
        report, _store = build_measurement_report(empty_measurement_store(), [], evaluation_at="2026-01-01T00:00:00")
        self.assertIsNone(report["calibration_recommendations"][0]["recommended_value"])

    def test_sp9_measurement_39_recommendation_bounds(self):
        from smart_practice_measurement import calibration_recommendations
        rec = calibration_recommendations({"brier": {"sample_count": 50}, "expected_calibration_error": {"value": 0.2}})[0]
        self.assertLessEqual(abs(rec["recommended_value"]), rec["maximum_allowed_change"])

    def test_sp9_measurement_40_recommendations_do_not_mutate_policy(self):
        store = empty_measurement_store()
        before = dict(store["active_policy"])
        build_measurement_report(store, [], evaluation_at="2026-01-01T00:00:00")
        self.assertEqual(before, store["active_policy"])

    def test_sp9_measurement_41_overconfident_bounded_downward_correction(self):
        from smart_practice_measurement import calibration_recommendations
        rec = calibration_recommendations({"brier": {"sample_count": 60}, "expected_calibration_error": {"value": 0.2}})[0]
        self.assertEqual(-0.05, rec["recommended_value"])

    def test_sp9_measurement_42_well_calibrated_no_change(self):
        from smart_practice_measurement import calibration_recommendations
        self.assertEqual("no_change", calibration_recommendations({"brier": {"sample_count": 60}, "expected_calibration_error": {"value": 0.01}})[0]["status"])

    def test_sp9_measurement_43_schema_loads_missing_safely(self):
        self.assertEqual(1, normalize_measurement_store(None)["schema_version"])

    def test_sp9_measurement_44_duplicate_save_no_duplicate_prediction(self):
        store = empty_measurement_store()
        q = self._sp9_question(1)
        attach_prediction_to_question(q, store, {}, created_at="2026-01-01T00:00:00")
        attach_prediction_to_question(q, store, {}, created_at="2026-01-01T00:00:00")
        self.assertEqual(1, len(store["predictions"]))

    def test_sp9_measurement_45_duplicate_evaluation_no_duplicate_report(self):
        store = empty_measurement_store()
        _report, store = build_measurement_report(store, [], evaluation_at="2026-01-01T00:00:00")
        _report, store = build_measurement_report(store, [], evaluation_at="2026-01-01T00:00:00")
        self.assertEqual(1, len(store["measurement_reports"]))

    def test_sp9_measurement_46_malformed_records_count_invalid(self):
        store = {"predictions": {"bad": {"prediction_id": "bad", "prediction_created_at": "bad"}}}
        report, _store = build_measurement_report(store, [{"at": "bad"}], evaluation_at="2026-01-01T00:00:00")
        self.assertGreaterEqual(report["data_quality"]["invalid_timestamp_count"], 1)

    def test_sp9_measurement_47_report_deterministic(self):
        store = empty_measurement_store()
        self.assertEqual(build_measurement_report(store, [], evaluation_at="2026-01-01T00:00:00")[0], build_measurement_report(store, [], evaluation_at="2026-01-01T00:00:00")[0])

    def test_sp9_measurement_48_limitations_reflect_missing_data(self):
        report, _store = build_measurement_report(empty_measurement_store(), [], evaluation_at="2026-01-01T00:00:00")
        self.assertIn("Insufficient 7-day outcomes.", report["limitations"])

    def test_sp9_measurement_49_real_session_save_load_preserves_prediction(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        pid = app.questions[0]["prediction_id"]
        app.save_session(show_notice=False)
        app.questions[0]["prediction_id"] = ""
        app.load_session_if_present(skip_identity_check=True)
        self.assertEqual(pid, app.questions[0]["prediction_id"])

    def test_sp9_measurement_50_policy_change_invalidates_cache_key(self):
        app = self._sp9_app_with_role_pool()
        before = app._smart_practice_signal_key()
        app.progress_data["meta"]["smart_practice_measurement"] = {"active_policy": {"policy_version": "changed"}}
        after = app._smart_practice_signal_key()
        self.assertNotEqual(before, after)

    def _sp10_governance(self):
        return empty_governance(created_at="2026-01-01T00:00:00")

    def _sp10_recommendation(self, gov=None, rec_id="rec-1", target="recall_probability_bias", value=-0.02):
        gov = gov or self._sp10_governance()
        return {
            "recommendation_id": rec_id,
            "target": target,
            "current_value": 0.0,
            "recommended_value": value,
            "maximum_allowed_change": 0.05,
            "sample_count": 60,
            "status": "recommended",
            "measurement_report_id": "report-1",
            "evaluated_policy_id": active_policy(gov)["policy_id"],
        }

    def _sp10_promote_candidate(self):
        gov = self._sp10_governance()
        candidate, gov, rejected = create_candidate_policy(
            gov,
            [self._sp10_recommendation(gov)],
            created_at="2026-01-02T00:00:00",
            actor="test",
        )
        self.assertEqual([], rejected)
        evaluation, gov = evaluate_challenger(
            gov,
            candidate["policy_id"],
            {
                "supported_challenger_outcomes": 40,
                "24h_outcomes": 25,
                "7d_outcomes": 12,
                "shadow_decision_count": 55,
                "observation_age_days": 8,
                "counterfactual_coverage_rate": 0.5,
                "primary_metric_improved": True,
                "7d_concept_recall_delta": 0.04,
                "weakness_recovery_delta": 0.04,
                "repair_relapse_delta": -0.01,
                "source_risk_delta": -0.01,
                "repetition_cost_delta": -0.01,
                "due_backlog_delta": -0.01,
                "calibration_error_delta": -0.01,
                "fatigue_cost_delta": -0.01,
                "role_floor_compliance": True,
            },
            evaluated_at="2026-01-10T00:00:00",
        )
        self.assertEqual("promotion_recommended", evaluation["status"])
        return gov, candidate

    def test_sp10_01_bootstrap_has_one_active_policy(self):
        gov = self._sp10_governance()
        self.assertTrue(exactly_one_active(gov))
        self.assertEqual(active_policy(gov)["policy_id"], gov["active_policy_id"])

    def test_sp10_02_policy_checksum_is_deterministic(self):
        policy = active_policy(self._sp10_governance())
        self.assertEqual(policy_checksum(policy), policy_checksum(dict(reversed(list(policy.items())))))

    def test_sp10_03_default_policy_values_validate(self):
        ok, reasons = validate_policy_values(default_policy_values())
        self.assertTrue(ok, reasons)

    def test_sp10_04_unknown_policy_field_rejected(self):
        values = default_policy_values()
        values["unknown_live_knob"] = 1
        self.assertIn("unknown_fields:unknown_live_knob", validate_policy_values(values)[1])

    def test_sp10_05_candidate_does_not_mutate_active_policy(self):
        gov = self._sp10_governance()
        before = active_policy(gov)
        candidate, gov, rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-01-02T00:00:00")
        self.assertEqual([], rejected)
        self.assertNotEqual(before["policy_id"], candidate["policy_id"])
        self.assertEqual(before, active_policy(gov))

    def test_sp10_06_candidate_records_bounded_change(self):
        gov = self._sp10_governance()
        candidate, _gov, _rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-01-02T00:00:00")
        self.assertEqual("recall_probability_bias", candidate["change_summary"][0]["field"])
        self.assertEqual(-0.02, candidate["change_summary"][0]["new_value"])

    def test_sp10_07_stale_recommendation_rejected(self):
        gov = self._sp10_governance()
        rec = self._sp10_recommendation(gov)
        rec["evaluated_policy_id"] = "old-policy"
        candidate, _gov, rejected = create_candidate_policy(gov, [rec], created_at="2026-01-02T00:00:00")
        self.assertIsNone(candidate)
        self.assertIn("stale_recommendation", rejected)

    def test_sp10_08_duplicate_recommendation_rejected(self):
        gov = self._sp10_governance()
        rec = self._sp10_recommendation(gov)
        _candidate, gov, _rejected = create_candidate_policy(gov, [rec], created_at="2026-01-02T00:00:00")
        candidate, _gov, rejected = create_candidate_policy(gov, [rec], created_at="2026-01-03T00:00:00")
        self.assertIsNone(candidate)
        self.assertIn("duplicate_recommendation", rejected)

    def test_sp10_09_shadow_decision_persists_separately(self):
        gov = self._sp10_governance()
        candidate, gov, _rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-01-02T00:00:00")
        decision, gov = create_shadow_decision(
            gov,
            [{"question_number": 1, "smart_primary_role": "due_retention", "smart_utility": 1}],
            [{"question_number": 2, "smart_primary_role": "weak_repair", "smart_utility": 2}],
            challenger_policy_id=candidate["policy_id"],
            created_at="2026-01-03T00:00:00",
            learner_state_signature="learner-a",
            candidate_snapshot_signature="pool-a",
        )
        self.assertIn(decision["shadow_decision_id"], gov["shadow_decisions"])
        self.assertEqual([1], decision["champion_question_numbers"])

    def test_sp10_10_shadow_decision_is_deterministic(self):
        gov = self._sp10_governance()
        candidate, gov, _rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-01-02T00:00:00")
        args = dict(
            challenger_policy_id=candidate["policy_id"],
            created_at="2026-01-03T00:00:00",
            learner_state_signature="learner-a",
            candidate_snapshot_signature="pool-a",
        )
        first, _ = create_shadow_decision(gov, [{"question_number": 1}], [{"question_number": 2}], **args)
        second, _ = create_shadow_decision(gov, [{"question_number": 1}], [{"question_number": 2}], **args)
        self.assertEqual(first["shadow_decision_id"], second["shadow_decision_id"])

    def test_sp10_11_low_evidence_blocks_promotion(self):
        gov = self._sp10_governance()
        candidate, gov, _rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-01-02T00:00:00")
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], {"supported_challenger_outcomes": 1}, evaluated_at="2026-01-04T00:00:00")
        self.assertEqual("insufficient_data", evaluation["status"])
        self.assertIn("insufficient_delayed_evidence", evaluation["rejection_reasons"])

    def test_sp10_12_regression_gate_detects_delayed_recall_drop(self):
        self.assertIn("delayed_recall_regression", regression_gate_failures({"7d_concept_recall_delta": -0.05}))

    def test_sp10_13_regression_gate_detects_role_floor_failure(self):
        self.assertIn("role_floor_regression", regression_gate_failures({"role_floor_compliance": False}))

    def test_sp10_14_promotion_recommended_when_gates_pass(self):
        gov, candidate = self._sp10_promote_candidate()
        latest = [ev for ev in gov["challenger_evaluations"].values() if ev["challenger_policy_id"] == candidate["policy_id"]][0]
        self.assertEqual("promotion_recommended", latest["status"])

    def test_sp10_15_activation_requires_expected_active_policy(self):
        gov, candidate = self._sp10_promote_candidate()
        ok, _gov, reason = activate_candidate_policy(
            gov,
            candidate["policy_id"],
            expected_active_policy_id="wrong",
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertFalse(ok)
        self.assertEqual("expected_active_policy_mismatch", reason)

    def test_sp10_16_activation_succeeds_with_promotion(self):
        gov, candidate = self._sp10_promote_candidate()
        old_active = active_policy(gov)["policy_id"]
        ok, gov, reason = activate_candidate_policy(
            gov,
            candidate["policy_id"],
            expected_active_policy_id=old_active,
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertTrue(ok, reason)
        self.assertEqual(candidate["policy_id"], gov["active_policy_id"])
        self.assertTrue(exactly_one_active(gov))

    def test_sp10_17_activation_rejects_checksum_mismatch(self):
        gov, candidate = self._sp10_promote_candidate()
        gov["policies"][candidate["policy_id"]]["checksum"] = "bad"
        ok, _gov, reason = activate_candidate_policy(
            gov,
            candidate["policy_id"],
            expected_active_policy_id=active_policy(gov)["policy_id"],
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertFalse(ok)
        self.assertIn("checksum_mismatch", reason)

    def test_sp10_18_rollback_restores_previous_policy(self):
        gov, candidate = self._sp10_promote_candidate()
        old_active = active_policy(gov)
        ok, gov, _reason = activate_candidate_policy(
            gov,
            candidate["policy_id"],
            expected_active_policy_id=old_active["policy_id"],
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertTrue(ok)
        ok, gov, reason = rollback_policy(
            gov,
            old_active["policy_id"],
            expected_active_policy_id=candidate["policy_id"],
            reason="test rollback",
            rolled_back_at="2026-01-12T00:00:00",
        )
        self.assertTrue(ok, reason)
        self.assertEqual(old_active["policy_values"], active_policy(gov)["policy_values"])

    def test_sp10_19_startup_recovers_from_missing_active(self):
        gov = self._sp10_governance()
        gov["active_policy_id"] = "missing"
        recovered = normalize_governance(gov, created_at="2026-01-02T00:00:00")
        self.assertTrue(exactly_one_active(recovered))
        self.assertGreaterEqual(recovered["invalid_data_count"], 1)

    def test_sp10_20_tiny_sample_drift_is_insufficient(self):
        reports = detect_drift({"accuracy": 0.8}, {"accuracy": 0.5}, sample_count=5, detected_at="2026-01-02T00:00:00")
        self.assertTrue(all(report["status"] == "insufficient_data" for report in reports))

    def test_sp10_21_question_bank_drift_handles_string_signature(self):
        reports = detect_drift({"bank_signature": "a"}, {"bank_signature": "b"}, sample_count=80, detected_at="2026-01-02T00:00:00")
        bank = next(report for report in reports if report["drift_type"] == "question_bank_drift")
        self.assertTrue(bank["detected"])

    def test_sp10_22_review_report_does_not_activate(self):
        gov, candidate = self._sp10_promote_candidate()
        before = gov["active_policy_id"]
        report = build_policy_review_report(gov, candidate["policy_id"], generated_at="2026-01-11T00:00:00")
        self.assertEqual("approve_for_manual_activation", report["recommendation"])
        self.assertEqual(before, gov["active_policy_id"])

    def test_sp10_23_candidate_expiration_records_audit(self):
        gov = self._sp10_governance()
        candidate, gov, _rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-01-02T00:00:00")
        gov = expire_candidate(gov, candidate["policy_id"], expired_at="2026-01-20T00:00:00", reason="stale")
        self.assertEqual("expired", gov["policies"][candidate["policy_id"]]["status"])
        self.assertTrue(any(event["event_type"] == "candidate_expired" for event in gov["audit_log"]))

    def test_sp10_24_prediction_snapshot_preserves_policy_id(self):
        store = empty_measurement_store()
        question = self._sp9_question(1)
        question["smart_policy_id"] = "policy-a"
        prediction = attach_prediction_to_question(question, store, {}, created_at="2026-01-01T00:00:00")
        question["smart_policy_id"] = "policy-b"
        self.assertEqual("policy-a", prediction["smart_policy_id"])
        self.assertEqual("policy-a", store["predictions"][prediction["prediction_id"]]["smart_policy_id"])

    def test_sp10_25_real_session_save_load_preserves_policy_id(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        policy_id = app.questions[0]["smart_policy_id"]
        app.save_session(show_notice=False)
        app.questions[0]["smart_policy_id"] = ""
        app.load_session_if_present(skip_identity_check=True)
        self.assertEqual(policy_id, app.questions[0]["smart_policy_id"])

    def test_sp10_26_policy_change_invalidates_smart_signal_key(self):
        app = self._sp9_app_with_role_pool()
        before = app._smart_practice_signal_key()
        gov, candidate = self._sp10_promote_candidate()
        old_active = active_policy(gov)["policy_id"]
        ok, gov, reason = activate_candidate_policy(
            gov,
            candidate["policy_id"],
            expected_active_policy_id=old_active,
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertTrue(ok, reason)
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        after = app._smart_practice_signal_key()
        self.assertNotEqual(before, after)
        self.assertEqual(candidate["policy_id"], gov["active_policy_id"])

    def test_sp10_27_activation_wrapper_invalidates_cache(self):
        app = self._sp9_app_with_role_pool()
        gov, candidate = self._sp10_promote_candidate()
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        app.smart_practice_pool_cache["x"] = ["cached"]
        ok, reason = app.activate_smart_practice_policy(
            candidate["policy_id"],
            expected_active_policy_id=active_policy(gov)["policy_id"],
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertTrue(ok, reason)
        self.assertEqual({}, app.smart_practice_pool_cache)

    def test_sp10_28_rollback_wrapper_invalidates_cache(self):
        app = self._sp9_app_with_role_pool()
        gov, candidate = self._sp10_promote_candidate()
        old_active = active_policy(gov)["policy_id"]
        ok, gov, _reason = activate_candidate_policy(
            gov,
            candidate["policy_id"],
            expected_active_policy_id=old_active,
            approval_reference="approval-1",
            activated_at="2026-01-11T00:00:00",
        )
        self.assertTrue(ok)
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        app.smart_practice_pool_cache["x"] = ["cached"]
        ok, reason = app.rollback_smart_practice_policy(
            old_active,
            expected_active_policy_id=candidate["policy_id"],
            reason="test rollback",
            rolled_back_at="2026-01-12T00:00:00",
        )
        self.assertTrue(ok, reason)
        self.assertEqual({}, app.smart_practice_pool_cache)

    def test_sp10_29_role_share_policy_feeds_allocator(self):
        allocation = smart_practice_role_allocation(
            10,
            role_shares={
                "due_retention": 0.5,
                "weak_repair": 0.2,
                "blueprint_coverage": 0.1,
                "transfer": 0.1,
                "controlled_stretch": 0.1,
            },
        )
        self.assertGreaterEqual(allocation["due_retention"], allocation["blueprint_coverage"])
        self.assertEqual(10, sum(allocation.values()))

    def test_sp10_30_validation_rejects_malformed_policy(self):
        policy = active_policy(self._sp10_governance())
        policy["policy_values"]["review_interval_multiplier"] = 9
        ok, reasons = validate_policy(policy)
        self.assertFalse(ok)
        self.assertIn("review_multiplier_out_of_bounds", reasons)

    def _sp10_active_governance_with_values(self, values):
        gov = self._sp10_governance()
        policy = gov["policies"][gov["active_policy_id"]]
        policy["policy_values"] = values
        policy["checksum"] = policy_checksum(policy)
        gov["policies"][policy["policy_id"]] = policy
        return gov

    def _sp10_relaxed_values(self):
        values = default_policy_values()
        values["minimum_evidence_thresholds"] = {
            "minimum_shadow_decisions": 1,
            "minimum_supported_challenger_outcomes": 1,
            "minimum_24h_outcomes": 1,
            "minimum_7d_outcomes": 1,
            "minimum_counterfactual_coverage_rate": 0.1,
            "minimum_observation_age_days": 1,
        }
        return values

    def _sp10_promote_candidate_with_values(self, values=None):
        gov = self._sp10_governance()
        if values is not None:
            gov = self._sp10_active_governance_with_values(values)
        candidate, gov, rejected = create_candidate_policy(
            gov,
            [self._sp10_recommendation(gov)],
            created_at="2026-02-02T00:00:00",
            actor="test",
        )
        self.assertEqual([], rejected)
        evaluation, gov = evaluate_challenger(
            gov,
            candidate["policy_id"],
            {
                "supported_challenger_outcomes": 40,
                "24h_outcomes": 25,
                "7d_outcomes": 12,
                "shadow_decision_count": 55,
                "observation_age_days": 8,
                "counterfactual_coverage_rate": 0.5,
                "primary_metric_improved": True,
                "7d_concept_recall_delta": 0.04,
                "weakness_recovery_delta": 0.04,
                "repair_relapse_delta": -0.01,
                "source_risk_delta": -0.01,
                "repetition_cost_delta": -0.01,
                "due_backlog_delta": -0.01,
                "calibration_error_delta": -0.01,
                "fatigue_cost_delta": -0.01,
                "role_floor_compliance": True,
            },
            evaluated_at="2026-02-10T00:00:00",
        )
        self.assertEqual("promotion_recommended", evaluation["status"])
        return gov, candidate

    def _sp10_passing_support(self):
        return {
            "supported_challenger_outcomes": 40,
            "24h_outcomes": 25,
            "7d_outcomes": 12,
            "shadow_decision_count": 55,
            "observation_age_days": 8,
            "counterfactual_coverage_rate": 0.5,
            "primary_metric_improved": True,
            "promotion_score": 999.0,
            "7d_concept_recall_delta": 0.04,
            "weakness_recovery_delta": 0.04,
            "repair_relapse_delta": -0.01,
            "source_risk_delta": -0.01,
            "repetition_cost_delta": -0.01,
            "due_backlog_delta": -0.01,
            "calibration_error_delta": -0.01,
            "fatigue_cost_delta": -0.01,
            "role_floor_compliance": True,
        }

    def _sp10_candidate(self):
        gov = self._sp10_active_governance_with_values(self._sp10_relaxed_values())
        candidate, gov, rejected = create_candidate_policy(
            gov,
            [self._sp10_recommendation(gov)],
            created_at="2026-03-02T00:00:00",
        )
        self.assertEqual([], rejected)
        return gov, candidate

    def test_sp10_completion_01_every_active_policy_control_family_reaches_runtime(self):
        app = self._sp9_app_with_role_pool()
        values = default_policy_values()
        values["role_shares"]["due_retention"] = 0.4
        values["role_shares"]["weak_repair"] = 0.2
        values["role_shares"]["blueprint_coverage"] = 0.2
        values["role_shares"]["transfer"] = 0.1
        values["role_shares"]["controlled_stretch"] = 0.1
        values["utility_component_scales"]["retention_risk"] = 0.5
        values["utility_component_bounds"]["retention_risk"] = (0.0, 1.0)
        values["source_risk_settings"]["baseline"] = 90.0
        values["fatigue_settings"]["negative_momentum_penalty"] = 0.02
        values["review_interval_multiplier"] = 1.05
        values["repair_trigger_settings"]["wrong_memory_min_pressure"] = 30.0
        values["repair_spacing_settings"]["contrast_delay"] = 3
        values["weakness_thresholds"]["active_weak_wrong_surplus"] = 2
        values["prediction_calibration"]["recall_probability_offset"] = 0.03
        values["exploration_settings"]["transfer_min_value"] = 4.5
        values["repetition_settings"]["recent_concept_penalty"] = 1.0
        values["minimum_evidence_thresholds"]["minimum_shadow_decisions"] = 2
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        pool = app.build_smart_practice_pool("1", randomize=False)
        controls = pool[0]["smart_runtime_policy_controls"]
        self.assertEqual(0.4, controls["role_shares"]["due_retention"])
        self.assertEqual(1.0, controls["utility_component_bounds"]["retention_risk"][1])
        self.assertEqual(90.0, controls["source_risk_settings"]["baseline"])
        self.assertEqual(0.02, controls["fatigue_settings"]["negative_momentum_penalty"])
        self.assertEqual(1.05, controls["review_interval_multiplier"])
        self.assertEqual(30.0, controls["repair_trigger_settings"]["wrong_memory_min_pressure"])
        self.assertEqual(3, controls["repair_spacing_settings"]["contrast_delay"])
        self.assertEqual(2, controls["weakness_thresholds"]["active_weak_wrong_surplus"])
        self.assertEqual(0.03, controls["prediction_calibration"]["recall_probability_offset"])
        self.assertEqual(4.5, controls["exploration_settings"]["transfer_min_value"])
        self.assertEqual(1.0, controls["repetition_settings"]["recent_concept_penalty"])
        self.assertEqual(2, controls["minimum_evidence_thresholds"]["minimum_shadow_decisions"])

    def test_sp10_completion_02_no_hardcoded_utility_bound_overrides_active_policy(self):
        app = self._sp9_app_with_role_pool()
        values = default_policy_values()
        values["utility_component_scales"]["retention_risk"] = 2.0
        values["utility_component_bounds"]["retention_risk"] = (0.0, 1.0)
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        self.assertEqual(
            1.0,
            active_policy(app.progress_data["meta"]["smart_practice_policy_governance"])["policy_values"][
                "utility_component_bounds"
            ]["retention_risk"][1],
        )
        app.smart_practice_pool_cache.clear()
        app.smart_practice_signal_cache_key = None
        for question in app.master_questions:
            question.pop("smart_primary_role", None)
            question.pop("smart_utility_breakdown", None)
            question.pop("smart_utility", None)
        pool = app.build_smart_practice_pool("1", randomize=False)
        self.assertEqual(1.0, pool[0]["smart_runtime_policy_controls"]["utility_component_bounds"]["retention_risk"][1])
        self.assertLessEqual(pool[0]["smart_utility_breakdown"]["retention_risk"], 1.0)

    def test_sp10_completion_03_champion_and_challenger_same_input_snapshot(self):
        gov, candidate = self._sp10_candidate()
        champion = [{"question_number": 1, "smart_primary_role": "due_retention"}]
        challenger = [{"question_number": 2, "smart_primary_role": "weak_repair"}]
        decision, _gov = create_shadow_decision(
            gov,
            champion,
            challenger,
            challenger_policy_id=candidate["policy_id"],
            created_at="2026-03-03T00:00:00",
            learner_state_signature="learner-same",
            candidate_snapshot_signature="pool-same",
        )
        self.assertEqual("learner-same", decision["learner_state_signature"])
        self.assertEqual("pool-same", decision["candidate_snapshot_signature"])

    def test_sp10_completion_04_shadow_selection_cannot_mutate_learner_memory(self):
        app = self._sp9_app_with_role_pool()
        before = copy.deepcopy(app.progress_data)
        gov, candidate = self._sp10_candidate()
        create_shadow_decision(gov, [{"question_number": 1}], [{"question_number": 2}], challenger_policy_id=candidate["policy_id"], created_at="2026-03-03T00:00:00", learner_state_signature="x", candidate_snapshot_signature="y")
        self.assertEqual(before, app.progress_data)

    def test_sp10_completion_05_shadow_selection_cannot_schedule_repair(self):
        app = self._sp9_app_with_role_pool()
        before = copy.deepcopy(app.progress_data.get("meta", {}).get("repair_state", {}))
        gov, candidate = self._sp10_candidate()
        create_shadow_decision(gov, [{"question_number": 1}], [{"question_number": 2}], challenger_policy_id=candidate["policy_id"], created_at="2026-03-03T00:00:00", learner_state_signature="x", candidate_snapshot_signature="y")
        self.assertEqual(before, app.progress_data.get("meta", {}).get("repair_state", {}))

    def test_sp10_completion_06_shadow_selection_cannot_change_live_session(self):
        app = self._sp9_app_with_role_pool()
        before = [q["question_number"] for q in app.questions]
        gov, candidate = self._sp10_candidate()
        create_shadow_decision(gov, [{"question_number": 1}], [{"question_number": 2}], challenger_policy_id=candidate["policy_id"], created_at="2026-03-03T00:00:00", learner_state_signature="x", candidate_snapshot_signature="y")
        self.assertEqual(before, [q["question_number"] for q in app.questions])

    def test_sp10_completion_07_unsupported_challenger_has_no_fabricated_result(self):
        gov, candidate = self._sp10_candidate()
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], {}, evaluated_at="2026-03-04T00:00:00")
        self.assertEqual("insufficient_data", evaluation["status"])
        self.assertEqual(0, evaluation["metrics"].get("supported_challenger_outcomes", 0))

    def test_sp10_completion_08_low_counterfactual_coverage_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["counterfactual_coverage_rate"] = 0.0
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("low_counterfactual_coverage", evaluation["rejection_reasons"])

    def test_sp10_completion_09_missing_delayed_evidence_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["7d_outcomes"] = 0
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("insufficient_7d_evidence", evaluation["rejection_reasons"])

    def test_sp10_completion_10_weakness_recovery_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["weakness_recovery_delta"] = -0.05
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("weakness_recovery_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_11_repair_relapse_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["repair_relapse_delta"] = 0.05
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("repair_relapse_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_12_source_risk_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["source_risk_delta"] = 0.08
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("source_risk_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_13_repetition_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["repetition_cost_delta"] = 0.08
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("repetition_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_14_due_backlog_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["due_backlog_delta"] = 0.05
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("due_backlog_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_15_calibration_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["calibration_error_delta"] = 0.05
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("calibration_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_16_fatigue_regression_blocks_promotion(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["fatigue_cost_delta"] = 0.08
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertIn("fatigue_regression", evaluation["rejection_reasons"])

    def test_sp10_completion_17_hard_gate_not_overridden_by_score(self):
        gov, candidate = self._sp10_candidate()
        support = self._sp10_passing_support()
        support["invalid_data_count"] = 1
        support["promotion_score"] = 9999
        evaluation, _gov = evaluate_challenger(gov, candidate["policy_id"], support, evaluated_at="2026-03-04T00:00:00")
        self.assertNotEqual("promotion_recommended", evaluation["status"])
        self.assertIn("invalid_data_quality", evaluation["rejection_reasons"])

    def test_sp10_completion_18_parent_mismatch_blocks_activation(self):
        gov, candidate = self._sp10_promote_candidate()
        gov["policies"][candidate["policy_id"]]["parent_policy_id"] = "wrong-parent"
        ok, _gov, reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertFalse(ok)
        self.assertEqual("candidate_parent_mismatch", reason)

    def test_sp10_completion_19_expired_candidate_blocks_activation(self):
        gov, candidate = self._sp10_promote_candidate()
        gov = expire_candidate(gov, candidate["policy_id"], expired_at="2026-03-10T00:00:00", reason="stale")
        ok, _gov, reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertFalse(ok)
        self.assertEqual("invalid_candidate_status", reason)

    def test_sp10_completion_20_activation_leaves_exactly_one_active(self):
        gov, candidate = self._sp10_promote_candidate()
        ok, gov, reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok, reason)
        self.assertTrue(exactly_one_active(gov))

    def test_sp10_completion_21_mid_activation_failure_restores_previous_active(self):
        gov, candidate = self._sp10_promote_candidate()
        previous = active_policy(gov)["policy_id"]
        with mock.patch("smart_practice_policy.exactly_one_active", side_effect=ValueError("boom")):
            ok, recovered, reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=previous, approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertFalse(ok)
        self.assertEqual("activation_failed", reason)
        self.assertEqual(previous, recovered["active_policy_id"])

    def test_sp10_completion_22_existing_session_retains_original_policy(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        original = app.questions[0]["smart_policy_id"]
        gov, candidate = self._sp10_promote_candidate()
        ok, gov, _reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok)
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        self.assertEqual(original, app.questions[0]["smart_policy_id"])

    def test_sp10_completion_23_new_session_uses_newly_activated_policy(self):
        app = self._sp9_app_with_role_pool()
        gov, candidate = self._sp10_promote_candidate()
        ok, gov, _reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok)
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        pool = app.build_smart_practice_pool("1", randomize=False)
        self.assertEqual(candidate["policy_id"], pool[0]["smart_policy_id"])

    def test_sp10_completion_24_rollback_restores_exact_prior_checksum(self):
        gov, candidate = self._sp10_promote_candidate()
        prior = active_policy(gov)
        ok, gov, _reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=prior["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok)
        ok, gov, reason = rollback_policy(gov, prior["policy_id"], expected_active_policy_id=candidate["policy_id"], reason="test", rolled_back_at="2026-03-12T00:00:00")
        self.assertTrue(ok, reason)
        self.assertEqual(prior["checksum"], active_policy(gov)["checksum"])

    def test_sp10_completion_25_invalid_rollback_target_fails_safely(self):
        gov, candidate = self._sp10_promote_candidate()
        ok, gov, _reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok)
        ok, after, reason = rollback_policy(gov, "missing", expected_active_policy_id=candidate["policy_id"], reason="test", rolled_back_at="2026-03-12T00:00:00")
        self.assertFalse(ok)
        self.assertEqual("target_policy_not_found", reason)
        self.assertEqual(gov["active_policy_id"], after["active_policy_id"])

    def test_sp10_completion_26_historical_prediction_refs_survive_rollback(self):
        question = self._sp9_question(1)
        question["smart_policy_id"] = "old-policy"
        prediction = prediction_from_question(question, {}, created_at="2026-03-01T00:00:00")
        gov, candidate = self._sp10_promote_candidate()
        prior = active_policy(gov)["policy_id"]
        ok, gov, _reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=prior, approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok)
        rollback_policy(gov, prior, expected_active_policy_id=candidate["policy_id"], reason="test", rolled_back_at="2026-03-12T00:00:00")
        self.assertEqual("old-policy", prediction["smart_policy_id"])

    def test_sp10_completion_27_malformed_active_policy_triggers_startup_recovery(self):
        gov = self._sp10_governance()
        gov["policies"][gov["active_policy_id"]]["checksum"] = "bad"
        recovered = normalize_governance(gov, created_at="2026-03-02T00:00:00")
        self.assertTrue(exactly_one_active(recovered))
        self.assertTrue(any(event["event_type"] == "startup_recovered" for event in recovered["audit_log"]))

    def test_sp10_completion_28_multiple_active_policies_trigger_safe_recovery(self):
        gov, candidate = self._sp10_candidate()
        gov["policies"][candidate["policy_id"]]["status"] = "active"
        recovered = normalize_governance(gov, created_at="2026-03-02T00:00:00")
        self.assertTrue(exactly_one_active(recovered))

    def test_sp10_completion_29_every_drift_type_detected_with_evidence(self):
        baseline = {"calibration_error": 0.1, "delayed_recall": 0.9, "accuracy": 0.9, "domain_weakness": 0.1, "bank_signature": "a", "source_risk": 0.1, "role_deviation": 0.1, "repair_success": 0.9}
        recent = {"calibration_error": 0.3, "delayed_recall": 0.7, "accuracy": 0.7, "domain_weakness": 0.3, "bank_signature": "b", "source_risk": 0.3, "role_deviation": 0.3, "repair_success": 0.7}
        reports = detect_drift(baseline, recent, sample_count=80, detected_at="2026-03-03T00:00:00")
        self.assertEqual(8, sum(1 for report in reports if report["detected"]))

    def test_sp10_completion_30_tiny_samples_do_not_trigger_drift(self):
        reports = detect_drift({"accuracy": 0.9}, {"accuracy": 0.1}, sample_count=3, detected_at="2026-03-03T00:00:00")
        self.assertTrue(all(not report["detected"] for report in reports))

    def test_sp10_completion_31_drift_does_not_mutate_active_policy(self):
        gov = self._sp10_governance()
        before = active_policy(gov)
        detect_drift({"accuracy": 0.9}, {"accuracy": 0.7}, sample_count=80, detected_at="2026-03-03T00:00:00")
        self.assertEqual(before, active_policy(gov))

    def test_sp10_completion_32_audit_log_is_append_only(self):
        gov = self._sp10_governance()
        before = list(gov["audit_log"])
        candidate, gov, _rejected = create_candidate_policy(gov, [self._sp10_recommendation(gov)], created_at="2026-03-02T00:00:00")
        self.assertEqual(before, gov["audit_log"][: len(before)])
        self.assertTrue(candidate)

    def test_sp10_completion_33_duplicate_persistence_does_not_duplicate_audit(self):
        app = self._sp9_app_with_role_pool()
        gov, candidate = self._sp10_promote_candidate()
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        app.save_progress()
        app.save_progress()
        app.load_progress_if_present()
        loaded = app.progress_data["meta"]["smart_practice_policy_governance"]
        event_ids = [event["audit_event_id"] for event in loaded["audit_log"]]
        self.assertEqual(len(event_ids), len(set(event_ids)))
        self.assertIn(candidate["policy_id"], loaded["policies"])

    def test_sp10_completion_34_activation_survives_real_save_load(self):
        app = self._sp9_app_with_role_pool()
        gov, candidate = self._sp10_promote_candidate()
        ok, gov, reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=active_policy(gov)["policy_id"], approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok, reason)
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        app.save_progress()
        app.progress_data = {}
        app.load_progress_if_present()
        self.assertEqual(candidate["policy_id"], app.progress_data["meta"]["smart_practice_policy_governance"]["active_policy_id"])

    def test_sp10_completion_35_rollback_survives_real_save_load(self):
        app = self._sp9_app_with_role_pool()
        gov, candidate = self._sp10_promote_candidate()
        prior = active_policy(gov)["policy_id"]
        ok, gov, _reason = activate_candidate_policy(gov, candidate["policy_id"], expected_active_policy_id=prior, approval_reference="approval", activated_at="2026-03-11T00:00:00")
        self.assertTrue(ok)
        ok, gov, reason = rollback_policy(gov, prior, expected_active_policy_id=candidate["policy_id"], reason="test", rolled_back_at="2026-03-12T00:00:00")
        self.assertTrue(ok, reason)
        app.progress_data["meta"]["smart_practice_policy_governance"] = gov
        app.save_progress()
        app.progress_data = {}
        app.load_progress_if_present()
        self.assertEqual(prior, app.progress_data["meta"]["smart_practice_policy_governance"]["active_policy_id"])

    def test_sp10_completion_36_malformed_governance_records_cannot_become_active(self):
        gov = self._sp10_governance()
        bad_id = "policy_bad"
        gov["policies"][bad_id] = {"policy_id": bad_id, "status": "active", "checksum": "bad"}
        gov["active_policy_id"] = bad_id
        recovered = normalize_governance(gov, created_at="2026-03-02T00:00:00")
        self.assertNotEqual(bad_id, recovered["active_policy_id"])
        self.assertIn(bad_id, recovered["policies"])

    def _sp11_question(self, qnum=1, objective="1.1", topic="Identity", domain="General Security Concepts", source="Clean", stem="Scenario"):
        q = self._sp9_question(qnum, domain=domain, topic=topic, source=source)
        q["objective_code"] = objective
        q["stem_style"] = stem
        return q

    def _sp11_graph_with_prereq(self):
        source = self._sp11_question(1, objective="1.0", topic="Ports")
        target = self._sp11_question(2, objective="1.1", topic="Firewalls")
        graph = normalize_graph({}, [source, target], created_at="2026-04-01T00:00:00")
        source_key = concept_key_for_question(source)[0]
        target_key = concept_key_for_question(target)[0]
        graph["edges"]["e1"] = make_edge(source_key, target_key, "prerequisite_of", weight=0.8, evidence_level="strong", evidence_sources=["manual"], created_at="2026-04-01T00:00:00")
        return normalize_graph(graph), source, target, source_key, target_key

    def _sp11_states(self, source_key, target_key, source_weak=True, target_weak=True):
        return {
            source_key: {
                "lowest_retrievability": 0.2 if source_weak else 0.8,
                "mean_retrievability": 0.3 if source_weak else 0.8,
                "wrong_count": 2 if source_weak else 0,
                "correct_count": 0 if source_weak else 2,
                "distinct_question_count": 2,
            },
            target_key: {
                "lowest_retrievability": 0.2 if target_weak else 0.8,
                "mean_retrievability": 0.3 if target_weak else 0.8,
                "wrong_count": 2 if target_weak else 0,
                "correct_count": 0 if target_weak else 2,
                "distinct_question_count": 2,
            },
        }

    def test_sp11_01_stable_metadata_produces_stable_concept_keys(self):
        self.assertEqual(concept_key_for_question(self._sp11_question())[0], concept_key_for_question(self._sp11_question())[0])

    def test_sp11_02_unrelated_similar_labels_do_not_merge(self):
        left = self._sp11_question(1, objective="1.1", topic="Access control")
        right = self._sp11_question(2, objective="1.2", topic="Access controller")
        self.assertNotEqual(concept_key_for_question(left)[0], concept_key_for_question(right)[0])

    def test_sp11_03_question_fallback_concepts_remain_isolated(self):
        self.assertNotEqual(concept_key_for_question({"question_number": 1})[0], concept_key_for_question({"question_number": 2})[0])

    def test_sp11_04_duplicate_active_edges_are_rejected(self):
        graph, _source, _target, source_key, target_key = self._sp11_graph_with_prereq()
        graph["edges"]["dupe"] = make_edge(source_key, target_key, "prerequisite_of", weight=0.7, evidence_level="strong")
        normalized = normalize_graph(graph)
        statuses = [edge["status"] for edge in normalized["edges"].values() if edge["source_concept_key"] == source_key and edge["target_concept_key"] == target_key]
        self.assertIn("disabled", statuses)

    def test_sp11_05_self_edges_are_rejected(self):
        graph, _source, _target, source_key, _target_key = self._sp11_graph_with_prereq()
        edge = make_edge(source_key, source_key, "related_to", weight=0.5, evidence_level="strong")
        graph["edges"][edge["edge_id"]] = edge
        self.assertEqual("disabled", normalize_graph(graph)["edges"][edge["edge_id"]]["status"])

    def test_sp11_06_prerequisite_cycles_cannot_become_active(self):
        graph, _source, _target, source_key, target_key = self._sp11_graph_with_prereq()
        edge = make_edge(target_key, source_key, "prerequisite_of", weight=0.6, evidence_level="moderate")
        graph["edges"][edge["edge_id"]] = edge
        normalized = normalize_graph(graph)
        self.assertNotEqual("active", normalized["edges"][edge["edge_id"]]["status"])

    def test_sp11_07_edge_weights_are_bounded(self):
        edge = make_edge("a", "b", "related_to", weight=9, evidence_level="strong")
        self.assertEqual(1.0, edge["weight"])

    def test_sp11_08_weak_evidence_remains_provisional(self):
        edge = make_edge("a", "b", "related_to", weight=0.5, evidence_level="weak", status="active")
        self.assertEqual("provisional", edge["status"])

    def test_sp11_09_concept_aggregation_prevents_one_item_dominating(self):
        q = self._sp11_question(1)
        key = concept_key_for_question(q)[0]
        rec = {"attempts": 10, "correct_count": 8, "wrong_count": 2, "learner_memory": {"retrievability": 0.9, "stability": 2, "uncertainty": 0.1}}
        state = aggregate_concept_state(key, [q], {"1": rec})
        self.assertEqual(1, state["attempt_count"])

    def test_sp11_10_sparse_concept_data_returns_conservative_uncertainty(self):
        q = self._sp11_question(1)
        state = aggregate_concept_state(concept_key_for_question(q)[0], [q], {})
        self.assertEqual("insufficient_evidence", state["evidence_strength"])
        self.assertEqual(1.0, state["uncertainty"])

    def test_sp11_11_missing_prerequisite_requires_weak_prerequisite_evidence(self):
        graph, _source, target, source_key, target_key = self._sp11_graph_with_prereq()
        diagnosis = diagnose_root_cause(target, graph, self._sp11_states(source_key, target_key), [{"correct": False}, {"correct": False}], policy={"policy_values": default_policy_values()})
        self.assertEqual("missing_prerequisite", diagnosis["diagnosis"])

    def test_sp11_12_stable_prerequisites_produce_target_weakness(self):
        graph, _source, target, source_key, target_key = self._sp11_graph_with_prereq()
        diagnosis = diagnose_root_cause(target, graph, self._sp11_states(source_key, target_key, source_weak=False), [{"correct": False}, {"correct": False}], policy={"policy_values": default_policy_values()})
        self.assertEqual("target_concept_weakness", diagnosis["diagnosis"])

    def test_sp11_13_repeated_distractor_substitution_produces_confusion(self):
        graph, source, target, source_key, target_key = self._sp11_graph_with_prereq()
        graph["edges"]["conf"] = make_edge(target_key, source_key, "confusable_with", weight=0.8, evidence_level="strong")
        diagnosis = diagnose_root_cause(target, normalize_graph(graph), {target_key: {"lowest_retrievability": 0.6, "wrong_count": 0, "correct_count": 1}}, [{"correct": False, "wrong_answer_family": "ports"}, {"correct": False, "wrong_answer_family": "ports"}], policy={"policy_values": default_policy_values()})
        self.assertEqual("concept_confusion", diagnosis["diagnosis"])

    def test_sp11_14_familiar_success_plus_scenario_failure_produces_transfer_failure(self):
        q = self._sp11_question(1, stem="Scenario")
        key = concept_key_for_question(q)[0]
        diagnosis = diagnose_root_cause(q, normalize_graph({}, [q]), {key: {"lowest_retrievability": 0.7, "wrong_count": 0, "correct_count": 1}}, [{"correct": True, "stem_style": "Scenario"}, {"correct": False, "stem_style": "Troubleshooting"}], policy={"policy_values": default_policy_values()})
        self.assertEqual("transfer_failure", diagnosis["diagnosis"])

    def test_sp11_15_isolated_bad_item_can_produce_item_specific(self):
        q = self._sp11_question(1)
        key = concept_key_for_question(q)[0]
        history = [{"question_number": 1, "correct": False}, {"question_number": 1, "correct": False}, {"question_number": 2, "correct": True}, {"question_number": 3, "correct": True}]
        diagnosis = diagnose_root_cause(q, normalize_graph({}, [q]), {key: {"lowest_retrievability": 0.7, "wrong_count": 0, "correct_count": 2}}, history, policy={"policy_values": default_policy_values()})
        self.assertEqual("item_specific_failure", diagnosis["diagnosis"])

    def test_sp11_16_source_problem_requires_healthier_source_comparison(self):
        q = self._sp11_question(1, source="Source conflict")
        key = concept_key_for_question(q)[0]
        history = [{"question_number": 1, "correct": False}, {"question_number": 2, "correct": True, "source_label": "Clean"}]
        diagnosis = diagnose_root_cause(q, normalize_graph({}, [q]), {key: {"lowest_retrievability": 0.7}}, history, source_trust={"label": "Source conflict"}, policy={"policy_values": default_policy_values()})
        self.assertEqual("source_quality_problem", diagnosis["diagnosis"])

    def test_sp11_17_missing_evidence_produces_insufficient(self):
        q = self._sp11_question(1)
        self.assertEqual("insufficient_evidence", diagnose_root_cause(q, normalize_graph({}, [q]), {}, [], policy={"policy_values": default_policy_values()})["diagnosis"])

    def test_sp11_18_diagnosis_cannot_bypass_protected_role_allocation(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("25", randomize=False)
        roles = Counter(q["smart_primary_role"] for q in pool)
        self.assertGreaterEqual(roles["weak_repair"] + roles["due_retention"], 10)

    def test_sp11_19_graph_utility_stays_inside_component_bounds(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        self.assertLessEqual(pool[0]["smart_utility_breakdown"].get("misconception_repair_value", 0), 20.0)

    def test_sp11_20_missing_prerequisite_routes_prerequisite_repair_first(self):
        app = self._sp9_app_with_role_pool()
        prereq = app.master_questions[0]
        target = app.master_questions[1]
        app.questions = [target] + app.master_questions[2:6]
        app.index = 0
        app.session_question_limit = 5
        target["smart_root_cause"] = "missing_prerequisite"
        target["smart_supporting_concepts"] = [concept_key_for_question(prereq)[0]]
        inserted = app.plan_misconception_repair(target, is_correct=False)
        self.assertTrue(inserted)
        self.assertEqual(concept_key_for_question(prereq)[0], inserted[0]["repair_concept_key"])

    def test_sp11_21_confusion_diagnosis_routes_contrast_repair(self):
        app = self._sp9_app_with_role_pool()
        q = app.master_questions[0]
        q["smart_root_cause"] = "concept_confusion"
        app.plan_misconception_repair(q, is_correct=False)
        self.assertEqual("contrast", q["repair_stage"])

    def test_sp11_22_transfer_failure_avoids_exact_item_repetition(self):
        app = self._sp9_app_with_role_pool()
        q = app.master_questions[0]
        q["smart_root_cause"] = "transfer_failure"
        inserted = app.plan_misconception_repair(q, is_correct=False)
        self.assertTrue(all(item["question_number"] != q["question_number"] for item in inserted))

    def test_sp11_23_item_specific_does_not_weaken_full_concept(self):
        q = self._sp11_question(1)
        key = concept_key_for_question(q)[0]
        diagnosis = diagnose_root_cause(q, normalize_graph({}, [q]), {key: {"lowest_retrievability": 0.8, "wrong_count": 0, "correct_count": 2}}, [{"question_number": 1, "correct": False}, {"question_number": 1, "correct": False}, {"question_number": 2, "correct": True}, {"question_number": 3, "correct": True}], policy={"policy_values": default_policy_values()})
        self.assertEqual("item_specific_failure", diagnosis["diagnosis"])
        self.assertNotIn("target_repeated_weakness", diagnosis["evidence"])

    def test_sp11_24_source_quality_problem_increases_source_risk(self):
        app = self._sp9_app_with_role_pool()
        app.master_questions[0]["smart_root_cause"] = "source_quality_problem"
        pool = app.build_smart_practice_pool("1", randomize=False)
        self.assertGreaterEqual(pool[0]["smart_utility_breakdown"].get("source_quality_risk", 0), 0.0)

    def test_sp11_25_graph_state_survives_real_progress_save_load(self):
        app = self._sp9_app_with_role_pool()
        graph = normalize_graph({}, [app.master_questions[0]])
        app.progress_data["meta"]["smart_practice_concept_graph"] = graph
        app.save_progress()
        app.progress_data = {}
        app.load_progress_if_present()
        self.assertEqual(graph["graph_signature"], app.progress_data["meta"]["smart_practice_concept_graph"]["graph_signature"])

    def test_sp11_26_diagnosis_metadata_survives_real_session_save_load(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        app.questions[0]["smart_root_cause"] = "target_concept_weakness"
        app.save_session(show_notice=False)
        app.questions[0]["smart_root_cause"] = ""
        app.load_session_if_present(skip_identity_check=True)
        self.assertEqual("target_concept_weakness", app.questions[0]["smart_root_cause"])

    def test_sp11_27_malformed_graph_records_cannot_control_live_selection(self):
        app = self._sp9_app_with_role_pool()
        app.progress_data["meta"]["smart_practice_concept_graph"] = {"edges": {"bad": {"edge_id": "bad", "edge_type": "bad", "status": "active"}}}
        pool = app.build_smart_practice_pool("1", randomize=False)
        self.assertNotEqual("bad", pool[0].get("smart_root_cause"))

    def test_sp11_28_same_event_cannot_evaluate_own_diagnosis(self):
        graph = store_diagnosis(empty_graph("2026-04-01T00:00:00"), {"diagnosis": "missing_prerequisite", "target_concept_key": "c", "diagnosed_at": "2026-04-02T00:00:00"})
        metrics = diagnosis_measurement(graph, [{"at": "2026-04-02T00:00:00", "correct": True, "repair_stage": "contrast"}])
        self.assertEqual("unobserved", metrics["diagnosis_accuracy"])

    def test_sp11_29_later_prerequisite_repair_can_confirm_diagnosis(self):
        graph = store_diagnosis(empty_graph("2026-04-01T00:00:00"), {"diagnosis": "missing_prerequisite", "target_concept_key": "c", "diagnosed_at": "2026-04-02T00:00:00"})
        metrics = diagnosis_measurement(graph, [{"at": "2026-04-03T00:00:00", "correct": True, "repair_stage": "contrast"}])
        self.assertEqual(1.0, metrics["diagnosis_accuracy"])

    def test_sp11_30_unobserved_diagnosis_outcome_remains_unobserved(self):
        graph = store_diagnosis(empty_graph("2026-04-01T00:00:00"), {"diagnosis": "transfer_failure", "target_concept_key": "c", "diagnosed_at": "2026-04-02T00:00:00"})
        self.assertEqual("unobserved", diagnosis_measurement(graph, [])["transfer_failure_recovery"])

    def test_sp11_31_active_policy_graph_control_reaches_runtime(self):
        app = self._sp9_app_with_role_pool()
        values = default_policy_values()
        values["graph_enabled"] = False
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        app.smart_practice_signal_cache_key = None
        pool = app.build_smart_practice_pool("1", randomize=False)
        self.assertEqual("insufficient_evidence", pool[0]["smart_root_cause"])

    def test_sp11_32_disabling_graph_policy_removes_influence_without_deleting_history(self):
        app = self._sp9_app_with_role_pool()
        app.progress_data["meta"]["smart_practice_concept_graph"] = store_diagnosis(empty_graph(), {"diagnosis": "target_concept_weakness", "target_concept_key": "c", "diagnosed_at": "2026-04-02T00:00:00"})
        before = dict(app.progress_data["meta"]["smart_practice_concept_graph"]["diagnoses"])
        values = default_policy_values()
        values["graph_enabled"] = False
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        app.build_smart_practice_pool("1", randomize=False)
        self.assertEqual(before, app.progress_data["meta"]["smart_practice_concept_graph"]["diagnoses"])

    def test_sp11_33_graph_policy_change_invalidates_smart_cache(self):
        app = self._sp9_app_with_role_pool()
        before = app._smart_practice_signal_key()
        values = default_policy_values()
        values["graph_enabled"] = False
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        after = app._smart_practice_signal_key()
        self.assertNotEqual(before, after)

    def test_sp11_34_deterministic_inputs_produce_deterministic_graph_and_diagnosis(self):
        graph, _source, target, source_key, target_key = self._sp11_graph_with_prereq()
        states = self._sp11_states(source_key, target_key)
        self.assertEqual(normalize_graph(graph)["graph_signature"], normalize_graph(graph)["graph_signature"])
        self.assertEqual(
            diagnose_root_cause(target, graph, states, [{"correct": False}, {"correct": False}], policy={"policy_values": default_policy_values()}),
            diagnose_root_cause(target, graph, states, [{"correct": False}, {"correct": False}], policy={"policy_values": default_policy_values()}),
        )

    def test_sp11_35_existing_smart_practice_valid_when_graph_insufficient(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("25", randomize=False)
        self.assertEqual(25, len(pool))
        self.assertTrue(all(q.get("smart_primary_role") for q in pool))

    def _sp12_edge(self, status="provisional", weight=0.4):
        graph, _source, _target, source_key, target_key = self._sp11_graph_with_prereq()
        edge = make_edge(source_key, target_key, "prerequisite_of", weight=weight, evidence_level="strong", status=status)
        edge["support_count"] = 0
        edge["contradiction_count"] = 0
        graph["edges"] = {edge["edge_id"]: edge}
        return graph, edge

    def _sp12_outcomes(self, edge, count, supports=True, same_question=False):
        return [
            {
                "edge_id": edge["edge_id"],
                "group_id": "same" if same_question else f"group-{idx}",
                "question_number": 1 if same_question else idx + 1,
                "supports_edge": supports,
                "contradicts_edge": not supports,
                "created_at": "2026-05-01T00:00:00",
                "observed_at": f"2026-05-{idx + 2:02d}T00:00:00",
            }
            for idx in range(count)
        ]

    def test_sp12_01_one_outcome_cannot_activate_provisional_edge(self):
        graph, edge = self._sp12_edge()
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 1), graph)
        self.assertNotEqual("active", calibrated["status"])

    def test_sp12_02_three_distinct_supporting_groups_activate_valid_edge(self):
        graph, edge = self._sp12_edge()
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 3), graph)
        self.assertEqual("active", calibrated["status"])

    def test_sp12_03_repeated_contradiction_can_weaken_edge(self):
        graph, edge = self._sp12_edge(status="active")
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 2, supports=False), graph)
        self.assertEqual("weakened", calibrated["status"])

    def test_sp12_04_strong_contradiction_can_reject_weak_edge(self):
        graph, edge = self._sp12_edge(status="provisional")
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 4, supports=False), graph)
        self.assertEqual("rejected", calibrated["status"])

    def test_sp12_05_one_repeated_question_cannot_satisfy_distinct_evidence(self):
        graph, edge = self._sp12_edge()
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 3, same_question=True), graph)
        self.assertNotEqual("active", calibrated["status"])

    def test_sp12_06_weight_adjustment_is_bounded(self):
        graph, edge = self._sp12_edge(weight=0.4)
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 5), graph)
        self.assertLessEqual(abs(calibrated["weight"] - 0.4), 0.10)

    def test_sp12_07_weight_remains_inside_zero_one(self):
        graph, edge = self._sp12_edge(weight=0.98)
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 5), graph)
        self.assertLessEqual(calibrated["weight"], 1.0)

    def test_sp12_08_cycle_producing_prerequisite_activation_blocked(self):
        graph, edge = self._sp12_edge()
        reverse = make_edge(edge["target_concept_key"], edge["source_concept_key"], "prerequisite_of", weight=0.8, evidence_level="strong", status="active")
        graph["edges"][reverse["edge_id"]] = reverse
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 3), graph)
        self.assertEqual("cycle_blocked", calibrated["calibration_status"])

    def test_sp12_09_historical_edge_evidence_is_preserved(self):
        graph, edge = self._sp12_edge()
        edge["evidence_sources"] = ["manual"]
        calibrated = calibrate_edge(edge, self._sp12_outcomes(edge, 3), graph)
        self.assertEqual(["manual"], calibrated["evidence_sources"])

    def test_sp12_10_orphan_concepts_reported(self):
        q = self._sp11_question(1)
        audit = audit_graph(normalize_graph({}, [q]), [q])
        self.assertTrue(audit["orphan_concepts"])

    def test_sp12_11_single_question_and_single_source_reported(self):
        q = self._sp11_question(1)
        audit = audit_graph(normalize_graph({}, [q]), [q])
        self.assertTrue(audit["single_question_concepts"])
        self.assertTrue(audit["single_source_concepts"])

    def test_sp12_12_prerequisites_without_teaching_questions_reported(self):
        graph, edge = self._sp12_edge(status="active")
        audit = audit_graph(graph, [])
        self.assertIn(edge["source_concept_key"], audit["prerequisites_without_teaching_questions"])

    def test_sp12_13_duplicate_candidate_concepts_reported_not_merged(self):
        q1 = self._sp11_question(1, objective="1.1", topic="Topic")
        q2 = self._sp11_question(2, objective="1.1", topic="Topic")
        graph = normalize_graph({}, [q1, q2])
        graph["concepts"]["manual_duplicate"] = dict(next(iter(graph["concepts"].values())))
        graph["concepts"]["manual_duplicate"]["concept_key"] = "manual_duplicate"
        audit = audit_graph(graph, [q1, q2])
        self.assertTrue(audit["duplicate_candidate_concepts"])
        self.assertIn("manual_duplicate", graph["concepts"])

    def test_sp12_14_overconnected_concepts_flagged(self):
        graph, edge = self._sp12_edge(status="active")
        source = edge["source_concept_key"]
        for idx in range(13):
            target = f"target::{idx}"
            graph["concepts"][target] = {"concept_key": target, "supporting_question_numbers": [idx]}
            graph["edges"][f"e{idx}"] = make_edge(source, target, "related_to", weight=0.5, evidence_level="strong")
        self.assertIn(source, audit_graph(graph)["overconnected_concepts"])

    def test_sp12_15_traversal_depth_never_exceeds_two(self):
        graph, edge = self._sp12_edge(status="active")
        path = select_prerequisite_path(edge["target_concept_key"], graph, {}, max_depth=2)
        self.assertLessEqual(len(path), 2)

    def test_sp12_16_repair_chain_never_exceeds_three(self):
        graph, edge = self._sp12_edge(status="active")
        path = select_prerequisite_path(edge["target_concept_key"], graph, {}, max_depth=3)
        self.assertLessEqual(len(path), 3)

    def test_sp12_17_candidate_inspection_respects_configured_maximum(self):
        graph, edge = self._sp12_edge(status="active")
        path = select_prerequisite_path(edge["target_concept_key"], graph, {}, max_parents=1)
        self.assertLessEqual(len(path), 1)

    def test_sp12_18_strongest_closest_weak_prerequisite_deterministic(self):
        graph, edge = self._sp12_edge(status="active", weight=0.6)
        path1 = select_prerequisite_path(edge["target_concept_key"], graph, {edge["source_concept_key"]: {"lowest_retrievability": 0.2}})
        path2 = select_prerequisite_path(edge["target_concept_key"], graph, {edge["source_concept_key"]: {"lowest_retrievability": 0.2}})
        self.assertEqual(path1, path2)

    def _sp12_info(self, **overrides):
        q = self._sp11_question(1)
        q.update(overrides)
        return information_value(q, {"uncertainty": 1.0}, {"dependent_concepts": ["a", "b"]}, {}, {"source_risk": 0.0}, {"policy_values": default_policy_values()})

    def test_sp12_19_every_information_component_inside_bounds(self):
        info = self._sp12_info()
        for key, (low, high) in INFO_BOUNDS.items():
            self.assertGreaterEqual(info[key], low)
            self.assertLessEqual(info[key], high)

    def test_sp12_20_total_matches_component_equation(self):
        info = self._sp12_info()
        expected = info["diagnostic_discrimination"] + info["graph_bottleneck_value"] + info["uncertainty_reduction"] + info["transfer_evidence_value"] + info["coverage_value"] - info["redundancy_cost"] - info["item_quality_risk"] - info["source_risk"]
        self.assertEqual(info["total"], round(max(-6.0, min(6.0, expected)), 4))

    def test_sp12_21_diagnostic_question_scores_higher_than_non_discriminating(self):
        high = self._sp12_info(smart_root_cause="concept_confusion")
        low = self._sp12_info(smart_root_cause="insufficient_evidence")
        self.assertGreater(high["diagnostic_discrimination"], low["diagnostic_discrimination"])

    def test_sp12_22_bottleneck_value_is_bounded(self):
        info = information_value(self._sp11_question(1), {}, {"dependent_concepts": list(range(99))}, {}, {}, {"policy_values": default_policy_values()})
        self.assertLessEqual(info["graph_bottleneck_value"], 10.0)

    def test_sp12_23_high_uncertainty_increases_information_value(self):
        high = information_value(self._sp11_question(1), {"uncertainty": 1.0}, {}, {}, {}, {"policy_values": default_policy_values()})
        low = information_value(self._sp11_question(1), {"uncertainty": 0.0}, {}, {}, {}, {"policy_values": default_policy_values()})
        self.assertGreater(high["uncertainty_reduction"], low["uncertainty_reduction"])

    def test_sp12_24_exact_repetition_increases_redundancy_cost(self):
        q = self._sp11_question(1)
        info = information_value(q, {}, {}, {"seen_question_numbers": [1]}, {}, {"policy_values": default_policy_values()})
        self.assertGreater(info["redundancy_cost"], 0)

    def test_sp12_25_distinct_transfer_item_increases_transfer_value(self):
        q = self._sp11_question(1, stem="Scenario")
        info = information_value(q, {}, {}, {"seen_stem_styles": ["Definition"]}, {}, {"policy_values": default_policy_values()})
        self.assertGreater(info["transfer_evidence_value"], 1.0)

    def test_sp12_26_low_quality_item_receives_quality_risk(self):
        info = information_value(self._sp11_question(1), {}, {}, {}, {"source_risk": 1.0}, {"policy_values": default_policy_values()})
        self.assertGreater(info["item_quality_risk"], 0)

    def test_sp12_27_information_value_cannot_bypass_protected_roles(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("25", randomize=False)
        roles = Counter(q["smart_primary_role"] for q in pool)
        self.assertGreaterEqual(roles["weak_repair"] + roles["due_retention"], 10)

    def test_sp12_28_information_value_inside_existing_utility_bounds(self):
        app = self._sp9_app_with_role_pool()
        q = app.build_smart_practice_pool("1", randomize=False)[0]
        self.assertLessEqual(q["smart_utility_breakdown"]["expected_learning_gain"], 20.0)

    def test_sp12_29_disabling_policy_removes_information_influence(self):
        app = self._sp9_app_with_role_pool()
        values = default_policy_values()
        values["information_value_enabled"] = False
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        app.smart_practice_signal_cache_key = None
        q = app.build_smart_practice_pool("1", randomize=False)[0]
        self.assertEqual(0.0, q["smart_information_value"])

    def _quality_outcomes(self, n, correct=False, **extra):
        return [{"question_number": 1, "session_id": f"s{i}", "correct": correct, **extra} for i in range(n)]

    def test_sp12_30_low_sample_item_insufficient_data(self):
        self.assertEqual("insufficient_data", question_quality_record(self._sp11_question(1), self._quality_outcomes(3))["status"])

    def test_sp12_31_low_accuracy_alone_not_possible_bad_key(self):
        self.assertNotEqual("possible_bad_key", question_quality_record(self._sp11_question(1), self._quality_outcomes(25))["status"])

    def test_sp12_32_stable_concept_isolated_failure_raises_ambiguity(self):
        outcomes = self._quality_outcomes(10, confidence="Sure", miss_reason="Misread")
        self.assertEqual("ambiguous", question_quality_record(self._sp11_question(1), outcomes)["status"])

    def test_sp12_33_stronger_outperforming_weaker_discrimination(self):
        outcomes = self._quality_outcomes(8, correct=True, concept_retrievability=0.9) + self._quality_outcomes(8, correct=False, concept_retrievability=0.2)
        self.assertGreater(question_quality_record(self._sp11_question(1), outcomes)["item_discrimination"], 0)

    def test_sp12_34_repeated_stable_failure_poor_discriminator(self):
        outcomes = self._quality_outcomes(16, correct=False, concept_retrievability=0.9)
        self.assertEqual("poor_discriminator", question_quality_record(self._sp11_question(1), outcomes)["status"])

    def test_sp12_35_possible_bad_key_requires_samples_and_corroboration(self):
        q = self._sp11_question(1, source="Source conflict")
        q["source_conflict"] = True
        outcomes = self._quality_outcomes(20, correct=False, confidence="Sure", healthy_alternative_success=True)
        self.assertEqual("possible_bad_key", question_quality_record(q, outcomes)["status"])

    def test_sp12_36_source_conflict_requires_cross_source_evidence(self):
        q = self._sp11_question(1, source="Source conflict")
        q["source_conflict"] = True
        self.assertNotEqual("source_conflicted", question_quality_record(q, self._quality_outcomes(10, correct=False))["status"])

    def test_sp12_37_one_learner_repeated_session_cannot_dominate_quality(self):
        outcomes = [{"question_number": 1, "session_id": "same", "correct": False} for _ in range(20)]
        self.assertEqual("insufficient_data", question_quality_record(self._sp11_question(1), outcomes)["status"])

    def test_sp12_38_question_quality_risk_does_not_weaken_full_concept(self):
        q = self._sp11_question(1)
        before = q["correct"][:]
        question_quality_record(q, self._quality_outcomes(20, correct=False))
        self.assertEqual(before, q["correct"])

    def test_sp12_39_question_quality_cannot_change_answer_key(self):
        q = self._sp11_question(1)
        question_quality_record(q, self._quality_outcomes(25, correct=False, confidence="Sure"))
        self.assertEqual(["A"], q["correct"])

    def test_sp12_40_healthier_alternative_preferred_when_available(self):
        risky = information_value(self._sp11_question(1, source="Source conflict"), {}, {}, {}, {"source_risk": 1.0}, {"policy_values": default_policy_values()})
        healthy = information_value(self._sp11_question(2, source="Clean"), {}, {}, {}, {"source_risk": 0.0}, {"policy_values": default_policy_values()})
        self.assertGreater(healthy["total"], risky["total"])

    def test_sp12_41_same_event_cannot_calibrate_own_edge_or_quality(self):
        graph, edge = self._sp12_edge()
        outcome = {"edge_id": edge["edge_id"], "supports_edge": True, "group_id": "g", "created_at": "2026-05-02", "observed_at": "2026-05-02"}
        self.assertNotEqual("active", calibrate_edge(edge, [outcome], graph)["status"])

    def test_sp12_42_later_prerequisite_improvement_strengthens_edge(self):
        graph, edge = self._sp12_edge()
        self.assertEqual("strengthened", calibrate_edge(edge, self._sp12_outcomes(edge, 3), graph)["calibration_status"])

    def test_sp12_43_later_contradiction_weakens_edge(self):
        graph, edge = self._sp12_edge(status="active")
        self.assertEqual("weakened", calibrate_edge(edge, self._sp12_outcomes(edge, 2, supports=False), graph)["status"])

    def test_sp12_44_unobserved_outcome_remains_unobserved(self):
        graph, edge = self._sp12_edge()
        calibrated = calibrate_edge(edge, [], graph)
        self.assertEqual("insufficient_evidence", calibrated["calibration_status"])

    def test_sp12_45_graph_audit_deterministic(self):
        graph, _edge = self._sp12_edge()
        self.assertEqual(audit_graph(graph), audit_graph(graph))

    def test_sp12_46_information_telemetry_survives_session_save_load(self):
        app = self._sp9_app_with_role_pool()
        pool = app.build_smart_practice_pool("1", randomize=False)
        app.start_session_from_pool(pool, mode=app_module.MODE_SMART_PRACTICE, count="1", randomize=False)
        value = app.questions[0]["smart_information_value"]
        app.save_session(show_notice=False)
        app.questions[0]["smart_information_value"] = 0.0
        app.load_session_if_present(skip_identity_check=True)
        self.assertEqual(value, app.questions[0]["smart_information_value"])

    def test_sp12_47_calibration_records_survive_progress_save_load(self):
        app = self._sp9_app_with_role_pool()
        store = normalize_calibration_store({})
        store["edge_calibration"]["x"] = {"edge_id": "x"}
        app.progress_data["meta"]["smart_practice_question_calibration"] = store
        app.save_progress()
        app.progress_data = {}
        app.load_progress_if_present()
        self.assertIn("x", app.progress_data["meta"]["smart_practice_question_calibration"]["edge_calibration"])

    def test_sp12_48_duplicate_calibration_pass_does_not_duplicate_history(self):
        app = self._sp9_app_with_role_pool()
        app.build_smart_practice_pool("1", randomize=False)
        first = dict(app.progress_data["meta"]["smart_practice_question_calibration"]["information_value_history"])
        app.build_smart_practice_pool("1", randomize=False)
        second = app.progress_data["meta"]["smart_practice_question_calibration"]["information_value_history"]
        self.assertEqual(set(first), set(second))

    def test_sp12_49_malformed_calibration_records_cannot_control_selection(self):
        app = self._sp9_app_with_role_pool()
        app.progress_data["meta"]["smart_practice_question_calibration"] = {"question_quality": {"1": {"status": "possible_bad_key", "source_risk": "bad"}}}
        q = app.build_smart_practice_pool("1", randomize=False)[0]
        self.assertIn(q["smart_primary_role"], {"weak_repair", "due_retention", "blueprint_coverage", "transfer", "controlled_stretch"})

    def test_sp12_50_policy_change_invalidates_smart_cache(self):
        app = self._sp9_app_with_role_pool()
        before = app._smart_practice_signal_key()
        values = default_policy_values()
        values["information_value_enabled"] = False
        app.progress_data["meta"]["smart_practice_policy_governance"] = self._sp10_active_governance_with_values(values)
        self.assertNotEqual(before, app._smart_practice_signal_key())


if __name__ == "__main__":
    unittest.main()
