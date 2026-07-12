from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BootstrapConfig:
    user_data_dir: Path
    checkpoint_dir: Path
    backup_dir: Path
    log_base_dir: Path


@dataclass(frozen=True)
class BootstrapResult:
    config: BootstrapConfig
    config_path: Path
    log_path: Path
    runtime_migration_notice: str


def prepare_application_bootstrap(
    config: BootstrapConfig,
    *,
    migrate_runtime: Callable[[Path], str],
    setup_logging_fn: Callable[[Path], Path],
) -> BootstrapResult:
    config.user_data_dir.mkdir(parents=True, exist_ok=True)
    config.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    config.backup_dir.mkdir(parents=True, exist_ok=True)
    runtime_migration_notice = migrate_runtime(config.user_data_dir)
    log_path = setup_logging_fn(config.log_base_dir)
    return BootstrapResult(
        config=config,
        config_path=config.user_data_dir / "config.json",
        log_path=log_path,
        runtime_migration_notice=runtime_migration_notice,
    )
