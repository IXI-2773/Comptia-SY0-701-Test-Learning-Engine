import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from application_bootstrap import BootstrapConfig, prepare_application_bootstrap

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def test_prepare_application_bootstrap_runs_side_effects_only_on_explicit_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = BootstrapConfig(
                user_data_dir=root / "user_data",
                checkpoint_dir=root / "user_data" / "checkpoints",
                backup_dir=root / "user_data" / "backups",
                log_base_dir=root / "logs",
            )
            migrated = []
            logged = []

            def migrate_runtime(path: Path) -> str:
                migrated.append(path)
                return "migrated"

            def setup_logging_fn(path: Path) -> Path:
                logged.append(path)
                return path / "logs" / "security_testing_engine.log"

            self.assertFalse(config.user_data_dir.exists())
            result = prepare_application_bootstrap(
                config,
                migrate_runtime=migrate_runtime,
                setup_logging_fn=setup_logging_fn,
            )

            self.assertTrue(config.user_data_dir.exists())
            self.assertEqual([config.user_data_dir], migrated)
            self.assertEqual([config.log_base_dir], logged)
            self.assertEqual("migrated", result.runtime_migration_notice)

    def test_importing_app_module_does_not_bootstrap_runtime(self):
        app_path = ROOT / "app.py"
        module_name = "test_app_import_no_bootstrap"
        spec = importlib.util.spec_from_file_location(module_name, app_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules.pop(module_name, None)
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        with (
            mock.patch("pathlib.Path.mkdir") as mkdir_mock,
            mock.patch("storage_utils.setup_logging") as setup_logging_mock,
        ):
            spec.loader.exec_module(module)
        self.assertFalse(mkdir_mock.called)
        self.assertFalse(setup_logging_mock.called)


if __name__ == "__main__":
    unittest.main()
