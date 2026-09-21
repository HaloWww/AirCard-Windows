import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aircard import backup


class BackupTests(unittest.TestCase):
    def test_round_trip_and_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(backup, "BACKUP_ROOT", root):
                record = backup.save_backup(
                    "device-1",
                    "card-1",
                    {"front.png": b"original", "optional.pdf": None},
                    device_name="My iPhone",
                    ios_version="18.0",
                )
                latest = backup.latest_backup("device-1", "card-1")
                self.assertIsNotNone(latest)
                self.assertEqual(latest.path, record.path)
                self.assertEqual(
                    backup.load_backup_assets(latest),
                    {"front.png": b"original", "optional.pdf": None},
                )

    def test_tampered_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(backup, "BACKUP_ROOT", Path(temporary)):
                record = backup.save_backup("device", "card", {"front.png": b"ok"})
                manifest = json.loads(
                    (record.path / backup.MANIFEST_NAME).read_text(encoding="utf-8")
                )
                data_file = manifest["assets"]["front.png"]["file"]
                (record.path / data_file).write_bytes(b"changed")
                with self.assertRaises(backup.BackupError):
                    backup.load_backup_assets(record)


if __name__ == "__main__":
    unittest.main()
