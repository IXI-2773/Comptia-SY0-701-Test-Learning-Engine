import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
logger.propagate = False


def setup_logging(base_dir: Path):
    log_dir = base_dir / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / 'security_testing_engine.log'
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        encoding='utf-8',
    )
    logger.propagate = True
    return log_path


def safe_write_json(path: Path, payload, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=indent)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    logger.info('Wrote JSON safely: %s', path)


def backup_bad_json_file(path: Path):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = path.with_name(f'{path.stem}.{timestamp}.bad.json')
    counter = 1
    while backup.exists():
        backup = path.with_name(f'{path.stem}.{timestamp}_{counter}.bad.json')
        counter += 1
    path.rename(backup)
    logger.warning('Moved unreadable JSON aside: %s -> %s', path, backup)
    return backup


def load_json_or_backup(path: Path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f), None, None
    except Exception as e:
        backup = backup_bad_json_file(path)
        logger.warning('Failed to read JSON: %s (%s)', path, e)
        return None, backup, e
