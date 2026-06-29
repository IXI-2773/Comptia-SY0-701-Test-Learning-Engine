from pathlib import Path
import shutil


BASE_DIR = Path(__file__).resolve().parents[1]
USER_DATA_DIR = BASE_DIR / 'user_data'
BACKUP_DIR = USER_DATA_DIR / 'backups'


def newest_file(paths):
    return max(paths, key=lambda p: p.stat().st_mtime)


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    patterns = [
        BASE_DIR.glob('*_progress_auto_backup_*.json'),
        BACKUP_DIR.glob('*_progress_auto_backup_*.json'),
    ]
    auto_backups = [p for group in patterns for p in group if p.is_file()]
    if not auto_backups:
        print('No timestamped auto-backups found.')
        return

    grouped = {}
    for path in auto_backups:
        marker = '_progress_auto_backup_'
        stem = path.name.split(marker, 1)[0]
        grouped.setdefault(stem, []).append(path)

    for stem, files in grouped.items():
        keep = newest_file(files)
        rolling = BACKUP_DIR / f'{stem}_progress_auto_backup.json'
        shutil.copy2(keep, rolling)
        removed = 0
        for path in files:
            if path.resolve() == rolling.resolve():
                continue
            path.unlink()
            removed += 1
        print(f'{stem}: kept {rolling.name} from {keep.name}; removed {removed} old auto-backups.')


if __name__ == '__main__':
    main()
