import tempfile
import unittest
from pathlib import Path

from deploygrade.engine.control_plane import ControlPlaneStorage, ControlPlaneStore, validate_sqlite_database_path


class StorageConfigurationTests(unittest.TestCase):
    def test_memory_is_test_only_and_store_implements_protocol(self):
        self.assertEqual(validate_sqlite_database_path(":memory:", allow_memory=True), Path(":memory:"))
        with self.assertRaisesRegex(ValueError, "cannot use :memory:"):
            validate_sqlite_database_path(":memory:")
        store = ControlPlaneStore()
        self.assertIsInstance(store, ControlPlaneStorage)
        self.assertEqual(store.readiness(), {"backend": "sqlite", "durable": False, "ready": True})
        store.close()

    def test_durable_store_requires_safe_absolute_regular_path(self):
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            validate_sqlite_database_path("relative.db")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "control-plane.db"
            self.assertEqual(validate_sqlite_database_path(target), target)
            store = ControlPlaneStore(target)
            self.assertEqual(store.readiness(), {"backend": "sqlite", "durable": True, "ready": True})
            self.assertEqual(store.connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            store.close()

    def test_symlinked_database_location_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "not be a symlink"):
                validate_sqlite_database_path(root / "link" / "control-plane.db")


if __name__ == "__main__":
    unittest.main()
