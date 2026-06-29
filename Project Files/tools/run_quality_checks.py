import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = ("ruff", "black", "mypy")
QUALITY_TARGETS = [
    "analytics_models.py",
    "analytics_summary.py",
    "bank_models.py",
    "progress_models.py",
    "progress_store.py",
    "question_bank.py",
    "runtime_persistence.py",
    "save_queue.py",
    "render_cache.py",
    "session_models.py",
    "session_store.py",
    "smart_practice_profile.py",
    "smart_practice_cache.py",
    "source_trust.py",
    "tools/benchmark_engine.py",
    "tools/import_chapter_screenshots.py",
    "tools/run_quality_checks.py",
]


def ensure_modules_installed() -> None:
    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if not missing:
        return
    missing_str = ", ".join(missing)
    requirements = ROOT / "requirements-dev.txt"
    raise SystemExit(f'Missing dev tool(s): {missing_str}. Install them with: py -m pip install -r "{requirements}"')


def run_step(label: str, args: list[str]) -> None:
    print(f'[{label}] {" ".join(args)}')
    completed = subprocess.run(args, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    ensure_modules_installed()
    python = sys.executable
    run_step("ruff", [python, "-m", "ruff", "check", *QUALITY_TARGETS])
    run_step("black", [python, "-m", "black", "--check", *QUALITY_TARGETS])
    run_step("mypy", [python, "-m", "mypy"])
    print("Quality checks passed.")


if __name__ == "__main__":
    main()
