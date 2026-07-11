import argparse
import json
import statistics
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


DEFAULT_BANK = ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json"
DEFAULT_REPORT = ROOT / "reports" / "performance_benchmark.json"


@contextmanager
def benchmark_app(bank_path: Path):
    import app as app_module

    tmpdir_ctx = tempfile.TemporaryDirectory()
    tmpdir = Path(tmpdir_ctx.name)
    user_data = tmpdir / "user_data"
    checkpoints = user_data / "checkpoints"
    backups = user_data / "backups"
    logs = user_data / "logs"
    for folder in (user_data, checkpoints, backups, logs):
        folder.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(app_module, "APP_DIR", tmpdir))
        stack.enter_context(mock.patch.object(app_module, "USER_DATA_DIR", user_data))
        stack.enter_context(mock.patch.object(app_module, "CHECKPOINT_DIR", checkpoints))
        stack.enter_context(mock.patch.object(app_module, "BACKUP_DIR", backups))
        stack.enter_context(mock.patch.object(app_module, "CONFIG_PATH", user_data / "config.json"))
        stack.enter_context(mock.patch.object(app_module, "DEFAULT_BANK", bank_path))
        stack.enter_context(mock.patch.object(app_module.TestingEngineApp, "_tick", lambda self: None))
        stack.enter_context(mock.patch.object(app_module.messagebox, "showwarning", return_value=None))
        stack.enter_context(mock.patch.object(app_module.messagebox, "showerror", return_value=None))
        stack.enter_context(mock.patch.object(app_module.messagebox, "showinfo", return_value=None))
        stack.enter_context(mock.patch.object(app_module.messagebox, "askyesno", return_value=True))
        root = app_module.tk.Tk()
        try:
            root.withdraw()
            app = app_module.TestingEngineApp(root)
            yield app
        finally:
            root.destroy()
            tmpdir_ctx.cleanup()


def run_benchmark(
    bank_path: Path = DEFAULT_BANK,
    *,
    smart_count: str = "50",
    pool_randomize: bool = False,
    repeat_count: int = 3,
    pool_threshold_seconds: float | None = None,
    warm_pool_threshold_seconds: float | None = None,
    analytics_threshold_seconds: float | None = None,
):
    import app as app_module

    with benchmark_app(bank_path) as app:
        app.session_mode_var.set(app_module.MODE_SMART_PRACTICE)
        app.session_count_var.set(str(smart_count))
        app.session_source_var.set("All")
        app.session_random_var.set(bool(pool_randomize))

        repeats = max(1, int(repeat_count or 1))
        app.invalidate_learning_state(prewarm=False)
        started = time.perf_counter()
        pool = app.build_smart_practice_pool(str(smart_count), randomize=pool_randomize)
        cold_pool_seconds = round(time.perf_counter() - started, 4)

        pool_timings = []
        analytics_timings = []
        analytics = {}
        for _ in range(repeats):
            started = time.perf_counter()
            pool = app.build_smart_practice_pool(str(smart_count), randomize=pool_randomize)
            pool_timings.append(round(time.perf_counter() - started, 4))

            started = time.perf_counter()
            analytics = app.compute_analytics(source=app.master_questions)
            analytics_timings.append(round(time.perf_counter() - started, 4))

        pool_seconds = round(statistics.median(pool_timings), 4)
        warm_pool_seconds = pool_seconds
        analytics_seconds = round(statistics.median(analytics_timings), 4)

        result = {
            "bank_path": str(bank_path),
            "question_count": len(app.master_questions),
            "smart_count": str(smart_count),
            "repeat_count": repeats,
            "pool_size": len(pool),
            "pool_seconds": pool_seconds,
            "cold_pool_seconds": cold_pool_seconds,
            "warm_pool_seconds": warm_pool_seconds,
            "pool_timings": pool_timings,
            "analytics_seconds": analytics_seconds,
            "analytics_timings": analytics_timings,
            "coverage_gap_count": len(analytics.get("coverage_gaps", [])),
            "objective_mastery_count": len(analytics.get("objective_mastery", [])),
            "source_agreement_count": len(analytics.get("source_agreement", [])),
        }

    if pool_threshold_seconds is not None and cold_pool_seconds > pool_threshold_seconds:
        raise AssertionError(
            f"Cold Smart Practice pool regression: {cold_pool_seconds:.4f}s exceeded {pool_threshold_seconds:.4f}s"
        )
    if warm_pool_threshold_seconds is not None and warm_pool_seconds > warm_pool_threshold_seconds:
        raise AssertionError(
            f"Warmed Smart Practice regression: {warm_pool_seconds:.4f}s exceeded {warm_pool_threshold_seconds:.4f}s"
        )
    if analytics_threshold_seconds is not None and analytics_seconds > analytics_threshold_seconds:
        raise AssertionError(
            f"Analytics regression: {analytics_seconds:.4f}s exceeded {analytics_threshold_seconds:.4f}s"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description="Benchmark Smart Practice pool building and analytics.")
    parser.add_argument("--bank", default=str(DEFAULT_BANK))
    parser.add_argument("--count", default="50")
    parser.add_argument("--randomize", action="store_true")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--assert-pool-max", type=float, default=None)
    parser.add_argument("--assert-warm-pool-max", type=float, default=None)
    parser.add_argument("--assert-analytics-max", type=float, default=None)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()

    result = run_benchmark(
        Path(args.bank),
        smart_count=args.count,
        pool_randomize=args.randomize,
        repeat_count=args.repeat,
        pool_threshold_seconds=args.assert_pool_max,
        warm_pool_threshold_seconds=args.assert_warm_pool_max,
        analytics_threshold_seconds=args.assert_analytics_max,
    )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.print_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Benchmark complete for {result['question_count']} questions.")
        print(f"Smart Practice pool: {result['pool_seconds']:.4f}s")
        print(f"Smart Practice cold/warm: {result['cold_pool_seconds']:.4f}s / {result['warm_pool_seconds']:.4f}s")
        print(f"Analytics: {result['analytics_seconds']:.4f}s")
        print(f"Report: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        sys.exit(1)
