from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from storage_utils import load_json_or_backup, safe_write_json


@dataclass(slots=True)
class RuntimePersistence:
    checkpoint_dir: Path
    backup_dir: Path

    def load_json_with_backup(self, path: Path):
        return load_json_or_backup(path)

    def write_json(self, path: Path, payload: Any, *, indent: int = 2) -> None:
        safe_write_json(path, payload, indent=indent)

    def copy_file(self, source: Path, destination: Path, *, label: str = "file") -> Path:
        source = Path(source)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        logging.info("Copied %s: %s -> %s", label, source, destination)
        return destination

    def migrate_runtime_file(self, legacy_path: Path, new_path: Path, *, label: str) -> bool:
        legacy_path = Path(legacy_path)
        new_path = Path(new_path)
        if new_path.exists() or not legacy_path.exists():
            return False
        self.copy_file(legacy_path, new_path, label=f"{label} migration")
        return True

    def progress_backup_path(self, progress_path: Path, suffix: str = "manual") -> Path:
        progress_path = Path(progress_path)
        if suffix == "auto_backup":
            return self.backup_dir / f"{progress_path.stem}_auto_backup.json"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.backup_dir / f"{progress_path.stem}_{suffix}_{timestamp}.json"

    def backup_progress_file(
        self,
        progress_path: Path | None,
        *,
        suffix: str = "manual",
        destination: Path | None = None,
    ) -> Path | None:
        if not progress_path:
            return None
        source = Path(progress_path)
        if not source.exists():
            return None
        target = Path(destination) if destination is not None else self.progress_backup_path(source, suffix=suffix)
        return self.copy_file(source, target, label=f"progress {suffix}")

    def write_checkpoint(self, path: Path, payload: Any) -> None:
        self.write_json(path, payload)
        logging.info("Saved checkpoint file: %s", path)
