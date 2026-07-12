import hashlib
import json
import os
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app_info import APP_VERSION
from pe_validation import pe_file_metadata, validate_pe_file

SOURCE_ROOT = Path(__file__).resolve().parents[1]
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


def _release_manifest(build_profile: str) -> dict[str, object]:
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
        "question_bank_filename": BANK_FILE.name,
        "question_bank_sha256": _sha256(BANK_FILE),
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
        json.dumps(_release_manifest("tools.build_release:build_release"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RELEASE_DIR


def main() -> None:
    path = build_release()
    print(f"Release folder ready: {path}")


if __name__ == "__main__":
    main()
