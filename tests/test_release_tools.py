import json
import os
import struct
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from subprocess import run
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


def _flatten_suite(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_suite(item)
        else:
            yield item


class ReleaseToolTests(unittest.TestCase):
    def _write_valid_exe(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(minimal_valid_pe_bytes())

    def _write_build_batch(self, path: Path) -> None:
        path.write_text(
            "\n".join(
                [
                    "@echo off",
                    "%PYTHON_CMD% -m PyInstaller --clean --noconfirm --onefile --windowed --name SecurityTestingEngine ^",
                    '  --add-data "%BANK_FILE%;." ^',
                    "  app.py",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_build_release_script_help_runs_as_direct_script(self):
        result = run(
            [sys.executable, "tools\\build_release.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertIn("usage:", result.stdout.lower())

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
            build_batch_file = source_root / "build_windows_v8.bat"
            receipt_path = source_root / "build" / "release_build_receipt.json"
            self._write_valid_exe(dist_exe)
            bank_file.write_text('{"questions":[]}', encoding="utf-8")
            (source_root / "app.py").write_text("print('release')\n", encoding="utf-8")
            self._write_build_batch(build_batch_file)
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
                BUILD_BATCH_FILE=build_batch_file,
                BUILD_RECEIPT=receipt_path,
            ):
                build_release_module.prepare_build_receipt(
                    source_root,
                    bank_file=bank_file,
                    dist_exe=dist_exe,
                    build_batch_file=build_batch_file,
                    receipt_path=receipt_path,
                )
                build_release_module.record_built_executable(
                    source_root,
                    bank_file=bank_file,
                    dist_exe=dist_exe,
                    build_batch_file=build_batch_file,
                    receipt_path=receipt_path,
                )
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
            self.assertIn("build_input_fingerprint", manifest)
            self.assertEqual(2, manifest["build_input_fingerprint"]["version"])
            self.assertIn(
                "build_windows_v8.bat#pyinstaller-command", manifest["build_input_fingerprint"]["input_paths"]
            )

    def test_build_input_fingerprint_changes_when_runtime_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "public_sy0701_bank_v4_plus_studyguide_clean.json"
            runtime_path = root / "app.py"
            build_batch_file = root / "build_windows_v8.bat"
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            runtime_path.write_text("print('alpha')\n", encoding="utf-8")
            self._write_build_batch(build_batch_file)

            first = build_release_module.build_input_fingerprint(
                root, bank_file=bank_path, build_batch_file=build_batch_file
            )
            runtime_path.write_text("print('beta')\n", encoding="utf-8")
            second = build_release_module.build_input_fingerprint(
                root,
                bank_file=bank_path,
                build_batch_file=build_batch_file,
            )

        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_build_input_fingerprint_changes_when_bank_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "public_sy0701_bank_v4_plus_studyguide_clean.json"
            runtime_path = root / "app.py"
            build_batch_file = root / "build_windows_v8.bat"
            runtime_path.write_text("print('alpha')\n", encoding="utf-8")
            bank_path.write_text('{"questions":[1]}', encoding="utf-8")
            self._write_build_batch(build_batch_file)

            first = build_release_module.build_input_fingerprint(
                root, bank_file=bank_path, build_batch_file=build_batch_file
            )
            bank_path.write_text('{"questions":[2]}', encoding="utf-8")
            second = build_release_module.build_input_fingerprint(
                root,
                bank_file=bank_path,
                build_batch_file=build_batch_file,
            )

        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_build_input_fingerprint_is_stable_across_root_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "A"
            root_b = Path(tmp) / "B"
            for root in (root_a, root_b):
                root.mkdir(parents=True, exist_ok=True)
                (root / "app.py").write_text("print('same')\n", encoding="utf-8")
                (root / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
                (root / "public_sy0701_bank_v4_plus_studyguide_clean.json").write_text(
                    '{"questions":[1]}',
                    encoding="utf-8",
                )
                self._write_build_batch(root / "build_windows_v8.bat")

            first = build_release_module.build_input_fingerprint(
                root_a,
                bank_file=root_a / "public_sy0701_bank_v4_plus_studyguide_clean.json",
                build_batch_file=root_a / "build_windows_v8.bat",
            )
            second = build_release_module.build_input_fingerprint(
                root_b,
                bank_file=root_b / "public_sy0701_bank_v4_plus_studyguide_clean.json",
                build_batch_file=root_b / "build_windows_v8.bat",
            )

        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["input_paths"], second["input_paths"])

    def test_build_input_fingerprint_ignores_irrelevant_test_report_and_log_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "public_sy0701_bank_v4_plus_studyguide_clean.json"
            build_batch_file = root / "build_windows_v8.bat"
            (root / "app.py").write_text("print('same')\n", encoding="utf-8")
            bank_path.write_text('{"questions":[1]}', encoding="utf-8")
            self._write_build_batch(build_batch_file)

            first = build_release_module.build_input_fingerprint(
                root, bank_file=bank_path, build_batch_file=build_batch_file
            )
            (root / "tests").mkdir()
            (root / "tests" / "test_noise.py").write_text("assert True\n", encoding="utf-8")
            (root / "reports").mkdir()
            (root / "reports" / "out.md").write_text("noise\n", encoding="utf-8")
            (root / "logs").mkdir()
            (root / "logs" / "app.log").write_text("noise\n", encoding="utf-8")
            second = build_release_module.build_input_fingerprint(
                root,
                bank_file=bank_path,
                build_batch_file=build_batch_file,
            )

        self.assertEqual(first["sha256"], second["sha256"])

    def test_build_input_fingerprint_requires_material_build_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "public_sy0701_bank_v4_plus_studyguide_clean.json"
            bank_path.write_text('{"questions":[]}', encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                build_release_module.build_input_fingerprint(
                    root, bank_file=bank_path, build_batch_file=root / "build_windows_v8.bat"
                )

    def test_build_release_refuses_staging_after_runtime_source_changes_since_recording(self):
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
            build_batch_file = source_root / "build_windows_v8.bat"
            receipt_path = source_root / "build" / "release_build_receipt.json"
            runtime_path = source_root / "app.py"
            self._write_valid_exe(dist_exe)
            bank_file.write_text('{"questions":[]}', encoding="utf-8")
            runtime_path.write_text("print('before')\n", encoding="utf-8")
            self._write_build_batch(build_batch_file)

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
                BUILD_BATCH_FILE=build_batch_file,
                BUILD_RECEIPT=receipt_path,
            ):
                build_release_module.prepare_build_receipt(
                    source_root,
                    bank_file=bank_file,
                    dist_exe=dist_exe,
                    build_batch_file=build_batch_file,
                    receipt_path=receipt_path,
                )
                build_release_module.record_built_executable(
                    source_root,
                    bank_file=bank_file,
                    dist_exe=dist_exe,
                    build_batch_file=build_batch_file,
                    receipt_path=receipt_path,
                )
                runtime_path.write_text("print('after')\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "rebuild required"):
                    build_release_module.build_release()

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

    def test_loader_union_matches_combined_unique_ids(self):
        loader = unittest.defaultTestLoader
        release_ids = {case.id() for case in _flatten_suite(loader.loadTestsFromName("tests.test_release_tools"))}
        smart_practice_ids = {
            case.id()
            for case in _flatten_suite(
                loader.loadTestsFromNames(
                    [
                        "tests.test_smart_practice_core",
                        "tests.test_smart_practice_worker",
                        "tests.test_smart_practice_audit",
                    ]
                )
            )
        }
        combined = [
            case.id()
            for case in _flatten_suite(
                loader.loadTestsFromNames(
                    [
                        "tests.test_release_tools",
                        "tests.test_smart_practice_core",
                        "tests.test_smart_practice_worker",
                        "tests.test_smart_practice_audit",
                    ]
                )
            )
        ]

        self.assertEqual(release_ids | smart_practice_ids, set(combined))
        self.assertEqual(len(combined), len(set(combined)))


class SmokeToolTests(unittest.TestCase):
    def _write_valid_exe(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(minimal_valid_pe_bytes())

    def _write_build_batch(self, path: Path) -> None:
        path.write_text(
            "\n".join(
                [
                    "@echo off",
                    "%PYTHON_CMD% -m PyInstaller --clean --noconfirm --onefile --windowed --name SecurityTestingEngine ^",
                    '  --add-data "%BANK_FILE%;." ^',
                    "  app.py",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _clean_validator_result(self) -> dict:
        return {"question_count": 1231, "issues": [], "warnings": []}

    def _manifest_with_fingerprint(self, source_root: Path, bank_path: Path, release_exe: Path) -> dict:
        build_batch_file = source_root / "build_windows_v8.bat"
        self._write_build_batch(build_batch_file)
        return {
            "executable_sha256": smoke_test_module._sha256(release_exe),
            "question_bank_sha256": smoke_test_module._sha256(bank_path),
            "expected_bank_count": 1231,
            "build_input_fingerprint": build_release_module.build_input_fingerprint(
                source_root,
                bank_file=bank_path,
                build_batch_file=build_batch_file,
            ),
        }

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
            (root / "app.py").write_text("print('release')\n", encoding="utf-8")
            release_manifest.write_text(
                json.dumps(self._manifest_with_fingerprint(root, bank_path, release_exe)),
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
            (root / "app.py").write_text("print('release')\n", encoding="utf-8")
            release_manifest.write_text(
                json.dumps(self._manifest_with_fingerprint(root, bank_path, release_exe)),
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
            (root / "app.py").write_text("print('release')\n", encoding="utf-8")
            manifest = self._manifest_with_fingerprint(root, bank_path, checkout_exe)
            manifest["executable_sha256"] = "mismatch"
            release_manifest.write_text(json.dumps(manifest), encoding="utf-8")

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

    def test_smoke_fails_on_executable_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            bank_path = root / "bank.json"
            self._write_valid_exe(release_exe)
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            (root / "app.py").write_text("print('release')\n", encoding="utf-8")
            manifest = self._manifest_with_fingerprint(root, bank_path, release_exe)
            manifest["executable_sha256"] = "bad"
            release_manifest.write_text(json.dumps(manifest), encoding="utf-8")

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, _result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertIn("Release manifest executable hash mismatch.", failures)

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
            (root / "app.py").write_text("print('release')\n", encoding="utf-8")
            release_manifest.write_text(
                json.dumps(self._manifest_with_fingerprint(root, bank_path, release_exe)),
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

    def test_smoke_fails_when_build_input_fingerprint_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
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
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertIn("Release manifest is missing a build-input fingerprint; rebuild required.", failures)

    def test_smoke_fails_when_runtime_source_changes_after_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            bank_path = root / "bank.json"
            runtime_path = root / "app.py"
            self._write_valid_exe(release_exe)
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            bank_path.write_text('{"questions":[]}', encoding="utf-8")
            runtime_path.write_text("print('before')\n", encoding="utf-8")
            release_manifest.write_text(
                json.dumps(self._manifest_with_fingerprint(root, bank_path, release_exe)),
                encoding="utf-8",
            )
            runtime_path.write_text("print('after')\n", encoding="utf-8")

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, _result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertIn("Release build inputs changed since packaging; rebuild required.", failures)

    def test_smoke_fails_when_bank_changes_after_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_exe = root / "release.exe"
            checkout_exe = root / "checkout.exe"
            release_readme = root / "README - Start Here.txt"
            release_manifest = root / "release_manifest.json"
            bank_path = root / "bank.json"
            runtime_path = root / "app.py"
            self._write_valid_exe(release_exe)
            self._write_valid_exe(checkout_exe)
            release_readme.write_text("ready", encoding="utf-8")
            runtime_path.write_text("print('release')\n", encoding="utf-8")
            bank_path.write_text('{"questions":[1]}', encoding="utf-8")
            release_manifest.write_text(
                json.dumps(self._manifest_with_fingerprint(root, bank_path, release_exe)),
                encoding="utf-8",
            )
            bank_path.write_text('{"questions":[2]}', encoding="utf-8")

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, _result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_path,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertTrue(
                any(
                    failure in failures
                    for failure in (
                        "Release manifest bank hash mismatch.",
                        "Release build inputs changed since packaging; rebuild required.",
                    )
                )
            )

    def test_direct_smoke_script_executes_and_reports_truthful_release_state(self):
        expected_failures, _result, _report = smoke_test_module.run_smoke_checks(
            release_test_runner=lambda: [],
        )
        completed = run(
            [sys.executable, "tools\\smoke_test.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "STE_SMOKE_SKIP_RELEASE_TESTS": "1"},
        )

        self.assertEqual(1 if expected_failures else 0, completed.returncode)
        if expected_failures:
            self.assertTrue(completed.stderr.strip())
            self.assertIn(expected_failures[0], completed.stderr)
        else:
            self.assertIn("Smoke test passed.", completed.stdout)

    def test_module_smoke_executes_and_reports_truthful_release_state(self):
        expected_failures, _result, _report = smoke_test_module.run_smoke_checks(
            release_test_runner=lambda: [],
        )
        completed = run(
            [sys.executable, "-m", "tools.smoke_test"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "STE_SMOKE_SKIP_RELEASE_TESTS": "1"},
        )

        self.assertEqual(1 if expected_failures else 0, completed.returncode)
        if expected_failures:
            self.assertTrue(completed.stderr.strip())
            self.assertIn(expected_failures[0], completed.stderr)
        else:
            self.assertIn("Smoke test passed.", completed.stdout)

    def test_staged_release_from_fresh_recorded_build_passes_smoke(self):
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
            build_batch_file = source_root / "build_windows_v8.bat"
            receipt_path = source_root / "build" / "release_build_receipt.json"
            source_root.mkdir(parents=True, exist_ok=True)
            (source_root / "app.py").write_text("print('release')\n", encoding="utf-8")
            bank_file.write_text('{"questions":[]}', encoding="utf-8")
            self._write_build_batch(build_batch_file)
            self._write_valid_exe(dist_exe)

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
                BUILD_BATCH_FILE=build_batch_file,
                BUILD_RECEIPT=receipt_path,
            ):
                build_release_module.prepare_build_receipt(
                    source_root,
                    bank_file=bank_file,
                    dist_exe=dist_exe,
                    build_batch_file=build_batch_file,
                    receipt_path=receipt_path,
                )
                build_release_module.record_built_executable(
                    source_root,
                    bank_file=bank_file,
                    dist_exe=dist_exe,
                    build_batch_file=build_batch_file,
                    receipt_path=receipt_path,
                )
                build_release_module.build_release()

            with mock.patch.object(smoke_test_module, "RELEASE_MANIFEST", release_manifest):
                failures, result, _report = smoke_test_module.run_smoke_checks(
                    bank_path=bank_file,
                    release_exe=release_exe,
                    release_readme=release_readme,
                    checkout_exe=checkout_exe,
                    validator=lambda _path: self._clean_validator_result(),
                    report_writer=lambda result, path: path.write_text("fresh", encoding="utf-8"),
                    release_test_runner=lambda: [],
                )

            self.assertEqual([], failures)
            self.assertEqual(1231, result["question_count"])
