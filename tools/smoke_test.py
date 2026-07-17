import hashlib
import io
import json
import os
import sys
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

build_release_module = import_module("tools.build_release")
validate_pe_file = import_module("pe_validation").validate_pe_file
validate_bank_module = import_module("tools.validate_bank")
validate_bank = validate_bank_module.validate_bank
write_markdown_report = validate_bank_module.write_markdown_report

RELEASE = ROOT / "release" / "SecurityTestingEngine"
RELEASE_EXE = RELEASE / "SecurityTestingEngine.exe"
RELEASE_README = RELEASE / "README - Start Here.txt"
RELEASE_MANIFEST = RELEASE / "release_manifest.json"
CHECKOUT_EXE = CHECKOUT_ROOT / "SecurityTestingEngine.exe"
DEFAULT_BANK = ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json"
EXPECTED_QUESTION_COUNT = 1231


def _validate_pe_file(path: Path, label: str) -> str | None:
    failure = validate_pe_file(path)
    return None if failure is None else f"{label} failed validation: {failure}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_release_tests() -> list[str]:
    if os.environ.get("STE_SMOKE_SKIP_RELEASE_TESTS") == "1":
        return []
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_release_tools.ReleaseToolTests")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    if result.wasSuccessful():
        return []
    details = []
    for case, traceback in result.failures + result.errors:
        summary = traceback.strip().splitlines()[-1] if traceback.strip() else "unknown failure"
        details.append(f"{case.id()}: {summary}")
    return details or ["Focused release tests failed."]


def _build_input_staleness_failure(manifest: dict[str, object], bank_path: Path) -> str | None:
    fingerprint = manifest.get("build_input_fingerprint")
    if not isinstance(fingerprint, dict):
        return "Release manifest is missing a build-input fingerprint; rebuild required."
    version = int(fingerprint.get("version", 0) or 0)
    if version <= 0:
        return "Release manifest build-input fingerprint is invalid; rebuild required."
    expected_sha = str(fingerprint.get("sha256") or "").strip().lower()
    if not expected_sha:
        return "Release manifest build-input fingerprint is incomplete; rebuild required."
    current = build_release_module.build_input_fingerprint(
        bank_path.parent,
        bank_file=bank_path,
        build_batch_file=bank_path.parent / "build_windows_v8.bat",
    )
    current_sha = str(current.get("sha256") or "").strip().lower()
    if current_sha != expected_sha:
        return "Release build inputs changed since packaging; rebuild required."
    return None


def run_smoke_checks(
    *,
    bank_path: Path = DEFAULT_BANK,
    release_exe: Path = RELEASE_EXE,
    release_readme: Path = RELEASE_README,
    checkout_exe: Path = CHECKOUT_EXE,
    report_path: Path | None = None,
    expected_question_count: int = EXPECTED_QUESTION_COUNT,
    validator=validate_bank,
    report_writer=write_markdown_report,
    release_test_runner=_run_release_tests,
) -> tuple[list[str], dict | None, Path]:
    failures: list[str] = []
    for label, path in (
        ("release EXE", release_exe),
        ("checkout EXE", checkout_exe),
    ):
        failure = _validate_pe_file(path, label)
        if failure:
            failures.append(failure)
    if not release_readme.exists():
        failures.append(f"Missing release README: {release_readme}")
    if not RELEASE_MANIFEST.exists():
        failures.append(f"Missing release manifest: {RELEASE_MANIFEST}")
    else:
        try:
            manifest = json.loads(RELEASE_MANIFEST.read_text(encoding="utf-8"))
            if manifest.get("executable_sha256") != _sha256(release_exe):
                failures.append("Release manifest executable hash mismatch.")
            if manifest.get("question_bank_sha256") != _sha256(bank_path):
                failures.append("Release manifest bank hash mismatch.")
            if int(manifest.get("expected_bank_count", -1)) != expected_question_count:
                failures.append("Release manifest expected bank count mismatch.")
            stale_failure = _build_input_staleness_failure(manifest, bank_path)
            if stale_failure:
                failures.append(stale_failure)
        except Exception as exc:
            failures.append(f"Release manifest is unreadable: {exc}")

    try:
        result = validator(bank_path)
    except Exception as exc:
        return (
            [f"Bank validation raised {exc.__class__.__name__}: {exc}"],
            None,
            (report_path or ROOT / "reports" / "bank_validation_report.md"),
        )

    if not isinstance(result, dict):
        failures.append("Bank validator returned malformed output.")
        return failures, None, (report_path or ROOT / "reports" / "bank_validation_report.md")

    try:
        question_count = int(result["question_count"])
        issues = list(result["issues"])
        warnings = list(result.get("warnings", []))
    except Exception as exc:
        failures.append(f"Bank validator returned malformed fields: {exc}")
        return failures, result, (report_path or ROOT / "reports" / "bank_validation_report.md")

    report_path = report_path or ROOT / "reports" / "bank_validation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_writer(result, report_path)

    if question_count != expected_question_count:
        failures.append(f"Unexpected bank count: expected {expected_question_count}, got {question_count}")
    if issues:
        failures.append(f"Bank validation reported {len(issues)} issue(s).")
    if warnings:
        failures.append(f"Bank validation reported {len(warnings)} warning(s).")

    release_test_failures = release_test_runner()
    failures.extend(release_test_failures)
    return failures, result, report_path


def main() -> int:
    failures, result, report_path = run_smoke_checks()
    if failures:
        for failure in failures:
            print(f"Smoke test failed: {failure}", file=sys.stderr)
        return 1
    print("Smoke test passed.")
    print(f"Validated release: {RELEASE}")
    print(f"Validation report: {report_path}")
    print(f"Question count: {result['question_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
