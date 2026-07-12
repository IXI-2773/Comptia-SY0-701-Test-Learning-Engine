import json
import struct
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

build_release_module = import_module("tools.build_release")
smoke_test_module = import_module("tools.smoke_test")
pe_validation_module = import_module("pe_validation")


def minimal_valid_pe_bytes() -> bytes:
    data = bytearray(0x80 + 4 + 20 + 0xF0 + 40)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, 0x8664)
    struct.pack_into("<H", data, 0x86, 1)
    struct.pack_into("<H", data, 0x94, 0xF0)
    struct.pack_into("<H", data, 0x98, 0x20B)
    return bytes(data)


class ReleaseToolTests(unittest.TestCase):
    def _write_valid_exe(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(minimal_valid_pe_bytes())

    def test_build_release_stages_only_clean_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "Checkout"
            source_root = checkout / "Project Files"
            dist_exe = source_root / "dist" / "SecurityTestingEngine.exe"
            release_dir = source_root / "release" / "SecurityTestingEngine"
            release_exe = release_dir / "SecurityTestingEngine.exe"
            release_readme = release_dir / "README - Start Here.txt"
            release_manifest = release_dir / "release_manifest.json"
            checkout_exe = checkout / "SecurityTestingEngine.exe"
            checkout_readme = checkout / "README - Start Here.txt"
            source_readme = source_root / "README - Start Here.txt"
            source_tree_exe = source_root / "SecurityTestingEngine.exe"
            bank_file = source_root / "public_sy0701_bank_v4_plus_studyguide_clean.json"
            self._write_valid_exe(dist_exe)
            bank_file.write_text('{"questions":[]}', encoding="utf-8")
            release_dir.mkdir(parents=True, exist_ok=True)
            (release_dir / "old.cache").write_text("stale", encoding="utf-8")
            source_tree_exe.parent.mkdir(parents=True, exist_ok=True)
            source_tree_exe.write_bytes(b"stale")

            with mock.patch.multiple(
                build_release_module,
                DIST_EXE=dist_exe,
                RELEASE_DIR=release_dir,
                RELEASE_EXE=release_exe,
                RELEASE_README=release_readme,
                RELEASE_MANIFEST=release_manifest,
                CHECKOUT_EXE=checkout_exe,
                CHECKOUT_README=checkout_readme,
                SOURCE_README=source_readme,
                SOURCE_TREE_EXE=source_tree_exe,
                BANK_FILE=bank_file,
            ):
                result = build_release_module.build_release()

            self.assertEqual(release_dir, result)
            self.assertEqual(
                ["README - Start Here.txt", "SecurityTestingEngine.exe", "release_manifest.json"],
                sorted(path.name for path in release_dir.iterdir()),
            )
            self.assertEqual(dist_exe.read_bytes(), release_exe.read_bytes())
            self.assertEqual(dist_exe.read_bytes(), checkout_exe.read_bytes())
            self.assertFalse(source_tree_exe.exists())
            self.assertIn("clean distributable release", release_readme.read_text(encoding="utf-8"))
            self.assertIn("Project Files\\release\\SecurityTestingEngine", checkout_readme.read_text(encoding="utf-8"))
            manifest = json.loads(release_manifest.read_text(encoding="utf-8"))
            self.assertEqual("SecurityTestingEngine.exe", manifest["executable_filename"])
            self.assertEqual(bank_file.name, manifest["question_bank_filename"])

    def test_pe_validation_rejects_corrupt_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "empty.exe": b"",
                "mz_only.exe": b"MZ",
                "mz_padded.exe": b"MZ" + (b"\0" * 600),
                "bad_lfanew.exe": (lambda: self._bad_lfanew_fixture())(),
                "missing_pe.exe": (lambda: self._missing_pe_fixture())(),
                "zero_sections.exe": (lambda: self._zero_sections_fixture())(),
                "truncated_optional.exe": (lambda: self._truncated_optional_fixture())(),
                "truncated_sections.exe": (lambda: self._truncated_section_table_fixture())(),
            }
            for name, payload in cases.items():
                path = root / name
                path.write_bytes(payload)
                self.assertIsNotNone(pe_validation_module.validate_pe_file(path), name)

    def test_pe_validation_accepts_minimal_valid_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.exe"
            self._write_valid_exe(path)
            self.assertIsNone(pe_validation_module.validate_pe_file(path))

    def test_pe_validation_accepts_actual_release_executable_when_present(self):
        candidate = ROOT / "release" / "SecurityTestingEngine" / "SecurityTestingEngine.exe"
        if not candidate.exists():
            self.skipTest("release executable not present")
        self.assertIsNone(pe_validation_module.validate_pe_file(candidate))

    def _bad_lfanew_fixture(self) -> bytes:
        data = bytearray(b"MZ" + (b"\0" * 300))
        struct.pack_into("<I", data, 0x3C, 0xFFFF)
        return bytes(data)

    def _missing_pe_fixture(self) -> bytes:
        data = bytearray(b"MZ" + (b"\0" * 600))
        struct.pack_into("<I", data, 0x3C, 0x80)
        return bytes(data)

    def _zero_sections_fixture(self) -> bytes:
        data = bytearray(minimal_valid_pe_bytes())
        struct.pack_into("<H", data, 0x86, 0)
        return bytes(data)

    def _truncated_optional_fixture(self) -> bytes:
        return minimal_valid_pe_bytes()[:-20]

    def _truncated_section_table_fixture(self) -> bytes:
        data = bytearray(minimal_valid_pe_bytes())
        struct.pack_into("<H", data, 0x86, 2)
        return bytes(data[:-20])

    def test_runtime_modules_stay_inside_authoritative_source_root(self):
        import app_question_flow_mixin
        import app_session_builder_mixin
        import smart_practice_measurement

        source_root = ROOT.resolve()
        for module, filename in (
            (app_question_flow_mixin, "app_question_flow_mixin.py"),
            (app_session_builder_mixin, "app_session_builder_mixin.py"),
            (smart_practice_measurement, "smart_practice_measurement.py"),
        ):
            module_path = Path(module.__file__).resolve()
            self.assertTrue(source_root in module_path.parents)
            self.assertEqual(source_root, module_path.parent)
            self.assertEqual(filename, module_path.name)
            self.assertNotIn("release", module_path.relative_to(source_root).parts)
            self.assertNotIn("dist", module_path.relative_to(source_root).parts)


class SmokeToolTests(unittest.TestCase):
    def _write_valid_exe(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(minimal_valid_pe_bytes())

    def _clean_validator_result(self) -> dict:
        return {"question_count": 1231, "issues": [], "warnings": []}

    def test_smoke_ignores_stale_prior_report_and_overwrites_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            report_path = root / "reports" / "bank_validation_report.md"
            bank_path = root / "bank.json"
            self._write_valid_exe(release_exe)
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            release_manifest.write_text(
                json.dumps(
                    {
                        "executable_sha256": smoke_test_module._sha256(release_exe),
                        "question_bank_sha256": smoke_test_module._sha256(bank_path),
                        "expected_bank_count": 1231,
                    }
                ),
                encoding="utf-8",
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("Issues: **0**", encoding="utf-8")

            def validator(_path: Path) -> dict:
                return {"question_count": 1231, "issues": [], "warnings": [("Q1", "warning")]}

            def report_writer(result: dict, path: Path) -> None:
                path.write_text(f"Warnings now: {len(result['warnings'])}", encoding="utf-8")

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, _result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    report_path=report_path,
                    validator=validator,
                    report_writer=report_writer,
                    release_test_runner=lambda: [],
                )

            self.assertIn("Bank validation reported 1 warning(s).", failures)
            self.assertEqual("Warnings now: 1", report_path.read_text(encoding="utf-8"))

    def test_smoke_fails_on_unexpected_bank_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            report_path = root / "report.md"
            bank_path = root / "bank.json"
            self._write_valid_exe(release_exe)
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            release_manifest.write_text(
                json.dumps(
                    {
                        "executable_sha256": smoke_test_module._sha256(release_exe),
                        "question_bank_sha256": smoke_test_module._sha256(bank_path),
                        "expected_bank_count": 1231,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, _result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    report_path=report_path,
                    validator=lambda _path: {"question_count": 1200, "issues": [], "warnings": []},
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertIn("Unexpected bank count: expected 1231, got 1200", failures)

    def test_smoke_fails_on_invalid_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            report_path = root / "report.md"
            bank_path = root / "bank.json"
            release_exe.write_bytes(b"bad")
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            release_manifest.write_text(
                json.dumps(
                    {
                        "executable_sha256": "mismatch",
                        "question_bank_sha256": smoke_test_module._sha256(bank_path),
                        "expected_bank_count": 1231,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, _result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    report_path=report_path,
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertTrue(any("release EXE" in failure for failure in failures))

    def test_smoke_passes_with_fresh_clean_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            report_path = root / "report.md"
            bank_path = root / "bank.json"
            self._write_valid_exe(release_exe)
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            release_manifest.write_text(
                json.dumps(
                    {
                        "executable_sha256": smoke_test_module._sha256(release_exe),
                        "question_bank_sha256": smoke_test_module._sha256(bank_path),
                        "expected_bank_count": 1231,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    report_path=report_path,
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertEqual([], failures)
            self.assertEqual(1231, result["question_count"])
