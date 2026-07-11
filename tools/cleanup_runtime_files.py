import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
USER_DATA_DIR = BASE_DIR / "user_data"
BACKUP_DIR = USER_DATA_DIR / "backups"
CACHE_DIR_NAMES = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")


@dataclass
class CleanupStats:
    cache_dirs_removed: int = 0
    cache_bytes_removed: int = 0
    backup_groups_compacted: int = 0
    backup_files_removed: int = 0
    log_files_removed: int = 0


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def newest_file(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime)


def iter_cache_dirs(base_dir: Path):
    for path in base_dir.rglob("*"):
        if path.is_dir() and path.name in CACHE_DIR_NAMES:
            yield path


def compact_auto_backups(stats: CleanupStats) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    patterns = [
        BASE_DIR.glob("*_progress_auto_backup_*.json"),
        BACKUP_DIR.glob("*_progress_auto_backup_*.json"),
    ]
    auto_backups = [path for group in patterns for path in group if path.is_file()]
    if not auto_backups:
        print("No timestamped auto-backups found.")
        return

    grouped: dict[str, list[Path]] = {}
    marker = "_progress_auto_backup_"
    for path in auto_backups:
        stem = path.name.split(marker, 1)[0]
        grouped.setdefault(stem, []).append(path)

    for stem, files in sorted(grouped.items()):
        keep = newest_file(files)
        rolling = BACKUP_DIR / f"{stem}_progress_auto_backup.json"
        shutil.copy2(keep, rolling)
        removed = 0
        for path in files:
            if path.resolve() == rolling.resolve():
                continue
            path.unlink()
            removed += 1
        stats.backup_groups_compacted += 1
        stats.backup_files_removed += removed
        print(f"{stem}: kept {rolling.name} from {keep.name}; removed {removed} old auto-backups.")


def remove_cache_dirs(base_dir: Path, stats: CleanupStats) -> None:
    removed_any = False
    for path in sorted(iter_cache_dirs(base_dir)):
        size = path_size(path)
        shutil.rmtree(path, ignore_errors=True)
        stats.cache_dirs_removed += 1
        stats.cache_bytes_removed += size
        removed_any = True
        print(f"Removed cache dir: {path.relative_to(base_dir)} ({size:,} bytes)")
    if not removed_any:
        print("No cache directories found.")


def prune_logs(stats: CleanupStats) -> None:
    logs_dir = USER_DATA_DIR / "logs"
    if not logs_dir.exists():
        print("No log directory found.")
        return
    removed_any = False
    for path in sorted(logs_dir.glob("*.log")):
        path.unlink()
        stats.log_files_removed += 1
        removed_any = True
        print(f"Removed log file: {path.relative_to(BASE_DIR)}")
    if not removed_any:
        print("No log files found.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean generated runtime and repository artifacts.")
    parser.add_argument(
        "--skip-backups",
        action="store_true",
        help="Leave auto-backup compaction untouched.",
    )
    parser.add_argument(
        "--skip-caches",
        action="store_true",
        help="Leave Python, pytest, ruff, and mypy caches untouched.",
    )
    parser.add_argument(
        "--prune-logs",
        action="store_true",
        help="Delete generated log files under user_data/logs.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    stats = CleanupStats()

    if not args.skip_backups:
        compact_auto_backups(stats)
    if not args.skip_caches:
        remove_cache_dirs(BASE_DIR, stats)
    if args.prune_logs:
        prune_logs(stats)

    print(
        "\nCleanup summary:"
        f" caches removed={stats.cache_dirs_removed}"
        f", cache bytes reclaimed={stats.cache_bytes_removed:,}"
        f", backup groups compacted={stats.backup_groups_compacted}"
        f", backup files removed={stats.backup_files_removed}"
        f", log files removed={stats.log_files_removed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
