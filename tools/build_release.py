import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from app_info import APP_VERSION
from pe_validation import pe_file_metadata, validate_pe_file

CHECKOUT_ROOT = SOURCE_ROOT.parent
DIST_EXE = SOURCE_ROOT / "dist" / "SecurityTestingEngine.exe"
RELEASE_DIR = SOURCE_ROOT / "release" / "SecurityTestingEngine"
RELEASE_EXE = RELEASE_DIR / "SecurityTestingEngine.exe"
RELEASE_README = RELEASE_DIR / "README - Start Here.txt"
RELEASE_MANIFEST = RELEASE_DIR / "release_manifest.json"
CHECKOUT_EXE = CHECKOUT_ROOT / "SecurityTestingEngine.exe"
CHECKOUT_README = CHECKOUT_ROOT / "README - Start Here.txt"
SOURCE_README = SOURCE_ROOT / "README - Start Here.txt"
SOURCE_TREE_EXE = SOURCE_ROOT / "SecurityTestingEngine.exe"
BANK_FILE = SOURCE_ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json"
EXPECTED_QUESTION_COUNT = 1231
BUILD_BATCH_FILE = SOURCE_ROOT / "build_windows_v8.bat"
BUILD_RECEIPT = SOURCE_ROOT / "build" / "release_build_receipt.json"
BUILD_INPUT_FINGERPRINT_VERSION = 2
BUILD_INPUT_SET_VERSION = 1


def _copy_required(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Missing required release file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _pe_header_is_valid(path: Path) -> bool:
    return validate_pe_file(path) is None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_bank_file(bank_path: Path | str | None) -> Path:
    if bank_path is None:
        return BANK_FILE
    candidate = Path(bank_path)
    if candidate.is_absolute():
        return candidate
    return SOURCE_ROOT / candidate


def _build_batch_for_source_root(source_root: Path) -> Path:
    return Path(source_root) / BUILD_BATCH_FILE.name


def _input_label(path: Path, source_root: Path) -> str:
    try:
        return path.relative_to(source_root).as_posix()
    except ValueError:
        return f"external/{path.name}"


def _normalized_pyinstaller_command(build_batch_file: Path) -> str:
    if not build_batch_file.exists():
        raise FileNotFoundError(f"Missing required build configuration: {build_batch_file}")
    lines = build_batch_file.read_text(encoding="utf-8").splitlines()
    command_lines: list[str] = []
    collecting = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            if collecting:
                break
            continue
        if not collecting and stripped.lower().startswith("%python_cmd% -m pyinstaller"):
            collecting = True
        if not collecting:
            continue
        command_lines.append(stripped.rstrip("^").strip())
        if not stripped.endswith("^"):
            break
    if not command_lines:
        raise ValueError(f"Could not locate the PyInstaller command in {build_batch_file}")
    return " ".join(command_lines).replace("%BANK_FILE%", "<BANK_FILE>")


def _material_build_input_paths(
    source_root: Path | None = None,
    *,
    bank_file: Path | None = None,
    build_batch_file: Path | None = None,
) -> list[Path]:
    source_root = Path(source_root or SOURCE_ROOT)
    bank_file = Path(bank_file or BANK_FILE)
    build_batch_file = Path(build_batch_file or BUILD_BATCH_FILE)
    runtime_files = sorted(path for path in source_root.glob("*.py") if path.is_file())
    if not runtime_files:
        raise FileNotFoundError(f"No runtime Python modules found in {source_root}")
    required_paths = [*runtime_files, bank_file, build_batch_file]
    material_paths: list[Path] = []
    seen_labels: set[str] = set()
    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing required build input: {path}")
        label = _input_label(path, source_root)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        material_paths.append(path)
    pyinstaller_command = _normalized_pyinstaller_command(build_batch_file)
    for token in pyinstaller_command.replace('"', " ").split():
        if token.lower().endswith(".spec"):
            spec_path = source_root / token
            if not spec_path.exists():
                raise FileNotFoundError(f"Missing required PyInstaller spec: {spec_path}")
            label = _input_label(spec_path, source_root)
            if label not in seen_labels:
                seen_labels.add(label)
                material_paths.append(spec_path)
    return material_paths


def build_input_fingerprint(
    source_root: Path | None = None,
    *,
    bank_file: Path | None = None,
    build_batch_file: Path | None = None,
) -> dict[str, object]:
    digest = hashlib.sha256()
    source_root = Path(source_root or SOURCE_ROOT)
    bank_file = Path(bank_file or BANK_FILE)
    build_batch_file = Path(build_batch_file or BUILD_BATCH_FILE)
    paths = _material_build_input_paths(source_root, bank_file=bank_file, build_batch_file=build_batch_file)
    input_labels: list[str] = []
    for path in paths:
        rel_path = _input_label(path, source_root)
        input_labels.append(rel_path)
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    pyinstaller_command = _normalized_pyinstaller_command(build_batch_file)
    input_labels.append("build_windows_v8.bat#pyinstaller-command")
    digest.update(b"build_windows_v8.bat#pyinstaller-command")
    digest.update(b"\0")
    digest.update(pyinstaller_command.encode("utf-8"))
    digest.update(b"\0")
    return {
        "algorithm": "sha256",
        "version": BUILD_INPUT_FINGERPRINT_VERSION,
        "input_set_version": BUILD_INPUT_SET_VERSION,
        "sha256": digest.hexdigest(),
        "file_count": len(input_labels),
        "input_paths": input_labels,
    }


def _receipt_payload(
    source_root: Path,
    *,
    bank_file: Path,
    dist_exe: Path,
    build_batch_file: Path,
) -> dict[str, object]:
    return {
        "status": "prepared",
        "dist_executable": _input_label(dist_exe, source_root),
        "question_bank": _input_label(bank_file, source_root),
        "build_input_fingerprint": build_input_fingerprint(
            source_root,
            bank_file=bank_file,
            build_batch_file=build_batch_file,
        ),
    }


def prepare_build_receipt(
    source_root: Path | None = None,
    *,
    bank_file: Path | None = None,
    dist_exe: Path | None = None,
    build_batch_file: Path | None = None,
    receipt_path: Path | None = None,
) -> Path:
    source_root = Path(source_root or SOURCE_ROOT)
    bank_file = Path(bank_file or BANK_FILE)
    dist_exe = Path(dist_exe or DIST_EXE)
    build_batch_file = Path(build_batch_file or BUILD_BATCH_FILE)
    receipt_path = Path(receipt_path or BUILD_RECEIPT)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(
            _receipt_payload(
                source_root,
                bank_file=bank_file,
                dist_exe=dist_exe,
                build_batch_file=build_batch_file,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt_path


def _load_build_receipt(receipt_path: Path | None = None) -> dict[str, object]:
    receipt_path = Path(receipt_path or BUILD_RECEIPT)
    if not receipt_path.exists():
        raise FileNotFoundError(f"Missing build receipt: {receipt_path}")
    return json.loads(receipt_path.read_text(encoding="utf-8"))


def record_built_executable(
    source_root: Path | None = None,
    *,
    bank_file: Path | None = None,
    dist_exe: Path | None = None,
    build_batch_file: Path | None = None,
    receipt_path: Path | None = None,
) -> Path:
    source_root = Path(source_root or SOURCE_ROOT)
    bank_file = Path(bank_file or BANK_FILE)
    dist_exe = Path(dist_exe or DIST_EXE)
    build_batch_file = Path(build_batch_file or BUILD_BATCH_FILE)
    receipt_path = Path(receipt_path or BUILD_RECEIPT)
    receipt = _load_build_receipt(receipt_path)
    current_fingerprint = build_input_fingerprint(
        source_root,
        bank_file=bank_file,
        build_batch_file=build_batch_file,
    )
    if receipt.get("build_input_fingerprint") != current_fingerprint:
        raise ValueError("Build inputs changed after the build receipt was prepared; rebuild required.")
    if not dist_exe.exists():
        raise FileNotFoundError(f"Missing built executable: {dist_exe}")
    receipt["status"] = "built"
    receipt["built_executable_sha256"] = _sha256(dist_exe)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt_path


def _verify_build_receipt(
    source_root: Path | None = None,
    *,
    bank_file: Path | None = None,
    dist_exe: Path | None = None,
    build_batch_file: Path | None = None,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    source_root = Path(source_root or SOURCE_ROOT)
    bank_file = Path(bank_file or BANK_FILE)
    dist_exe = Path(dist_exe or DIST_EXE)
    build_batch_file = Path(build_batch_file or BUILD_BATCH_FILE)
    receipt_path = Path(receipt_path or BUILD_RECEIPT)
    receipt = _load_build_receipt(receipt_path)
    if receipt.get("status") != "built":
        raise ValueError("Build receipt is incomplete; rebuild required.")
    current_fingerprint = build_input_fingerprint(
        source_root,
        bank_file=bank_file,
        build_batch_file=build_batch_file,
    )
    if receipt.get("build_input_fingerprint") != current_fingerprint:
        raise ValueError("Build inputs changed since the dist executable was recorded; rebuild required.")
    if receipt.get("built_executable_sha256") != _sha256(dist_exe):
        raise ValueError("Recorded dist executable no longer matches the current build output; rebuild required.")
    return receipt


def _release_manifest(build_profile: str, *, bank_file: Path | None = None) -> dict[str, object]:
    bank_file = Path(bank_file or BANK_FILE)
    source_root = bank_file.parent
    pe_info = pe_file_metadata(RELEASE_EXE)
    return {
        "application_version": APP_VERSION,
        "build_command": build_profile,
        "build_timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "executable_filename": RELEASE_EXE.name,
        "executable_sha256": _sha256(RELEASE_EXE),
        "executable_size": RELEASE_EXE.stat().st_size,
        "expected_bank_count": EXPECTED_QUESTION_COUNT,
        "pe_format": pe_info["format"],
        "pe_machine_type": pe_info["machine_type"],
        "python_version": platform.python_version(),
        "pyinstaller_version": os.environ.get("PYINSTALLER_VERSION", "unavailable"),
        "question_bank_filename": bank_file.name,
        "question_bank_sha256": _sha256(bank_file),
        "build_input_fingerprint": build_input_fingerprint(
            source_root,
            bank_file=bank_file,
            build_batch_file=_build_batch_for_source_root(source_root),
        ),
        "source_revision": os.environ.get("GITHUB_SHA") or os.environ.get("SOURCE_REVISION") or "unavailable",
    }


def _release_readme_text() -> str:
    return "\n".join(
        [
            "Security Testing Engine v8",
            "",
            "Double-click SecurityTestingEngine.exe to study.",
            "",
            "This folder is the clean distributable release.",
            "It contains only the packaged EXE and this launch note.",
            "",
            "Progress and history:",
            "- The packaged EXE stores XP, history, sessions, and settings in:",
            "  %LOCALAPPDATA%\\SecurityTestingEngine",
            "- The app can automatically import older progress from user_data or the older Project Files\\user_data layout when the packaged EXE has little or no progress.",
        ]
    )


def _checkout_readme_text() -> str:
    return "\n".join(
        [
            "Security Testing Engine v8",
            "",
            "This checkout keeps the user launch copy in this folder:",
            "- SecurityTestingEngine.exe",
            "",
            "Clean distributable release folder:",
            "- Project Files\\release\\SecurityTestingEngine",
            "",
            "Developer/source folder:",
            "- Project Files",
            "",
            "Progress and history:",
            "- The packaged EXE stores XP, history, sessions, and settings in:",
            "  %LOCALAPPDATA%\\SecurityTestingEngine",
            "- The app can automatically import older progress from user_data or the older Project Files\\user_data layout when the packaged EXE has little or no progress.",
        ]
    )


def _source_readme_text() -> str:
    return "\n".join(
        [
            "Security Testing Engine v8",
            "",
            "This folder is the authoritative source tree.",
            "",
            "Build outputs:",
            "- dist\\SecurityTestingEngine.exe: latest built EXE",
            "- release\\SecurityTestingEngine: clean distributable release",
            "",
            "Checkout launch copy:",
            "- ..\\SecurityTestingEngine.exe",
        ]
    )


def _clean_release_dir() -> None:
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)


def _remove_stale_source_tree_exe() -> None:
    if SOURCE_TREE_EXE.exists():
        SOURCE_TREE_EXE.unlink()


def build_release(_bank_path=None) -> Path:
    bank_file = _resolve_bank_file(_bank_path)
    source_root = bank_file.parent
    _verify_build_receipt(
        source_root=source_root,
        bank_file=bank_file,
        dist_exe=DIST_EXE,
        build_batch_file=_build_batch_for_source_root(source_root),
        receipt_path=BUILD_RECEIPT,
    )
    _clean_release_dir()
    _copy_required(DIST_EXE, RELEASE_EXE)
    _copy_required(DIST_EXE, CHECKOUT_EXE)
    _remove_stale_source_tree_exe()
    RELEASE_README.write_text(_release_readme_text(), encoding="utf-8")
    CHECKOUT_README.write_text(_checkout_readme_text(), encoding="utf-8")
    SOURCE_README.write_text(_source_readme_text(), encoding="utf-8")
    if not _pe_header_is_valid(RELEASE_EXE):
        raise ValueError(f"Release EXE is not a valid PE file: {RELEASE_EXE}")
    if not _pe_header_is_valid(CHECKOUT_EXE):
        raise ValueError(f"Checkout EXE is not a valid PE file: {CHECKOUT_EXE}")
    RELEASE_MANIFEST.write_text(
        json.dumps(
            _release_manifest("tools.build_release:build_release", bank_file=bank_file), indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    return RELEASE_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bank_path", nargs="?", default=None)
    parser.add_argument("--prepare-build", action="store_true")
    parser.add_argument("--record-built", action="store_true")
    args = parser.parse_args(argv)
    bank_file = _resolve_bank_file(args.bank_path)
    if args.prepare_build and args.record_built:
        parser.error("--prepare-build and --record-built are mutually exclusive")
    if args.prepare_build:
        path = prepare_build_receipt(bank_file=bank_file)
        print(f"Build receipt prepared: {path}")
        return 0
    if args.record_built:
        path = record_built_executable(bank_file=bank_file)
        print(f"Build receipt finalized: {path}")
        return 0
    path = build_release(bank_file)
    print(f"Release folder ready: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
