import io
import plistlib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from aircard import core_flasher
from aircard.backup import BackupError, BackupRecord
from aircard.image_util import build_card_assets, prepare_card_skin


class ImageAndArchiveTests(unittest.TestCase):
    def test_cross_platform_card_assets_include_pdf(self):
        source = io.BytesIO()
        Image.new("RGB", (20, 10), "#336699").save(source, "PNG")
        prepared = prepare_card_skin(source.getvalue())
        assets = build_card_assets(prepared)
        self.assertEqual(set(assets), set(core_flasher.TARGET_ASSETS))
        self.assertTrue(assets["cardBackgroundCombined@3x.png"].startswith(b"\x89PNG"))
        self.assertTrue(assets["cardBackgroundCombined.pdf"].startswith(b"%PDF-"))

    def test_batch_archive_contains_symlink_and_payloads(self):
        raw = core_flasher.build_archive_multi(
            "/var/mobile/Library/Test", [("a.png", b"a"), ("b.png", b"b")]
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn("p0/p1/p2/link", archive.namelist())
            self.assertEqual(archive.read("payload_0"), b"a")
            self.assertEqual(archive.read("payload_1"), b"b")
            self.assertEqual(
                archive.read("p0/p1/p2/link"),
                b"../../../var/mobile/Library/Test",
            )

    def test_books_manifest_preserves_identifier_order(self):
        value = plistlib.loads(core_flasher.build_books_plist(["first", "second"]))
        self.assertEqual(
            [row["Persistent ID"] for row in value["Books"]],
            ["first", "second"],
        )

    def test_rejects_unsafe_leaf(self):
        with self.assertRaises(ValueError):
            core_flasher.build_archive_multi("/var/mobile/Library/Test", [("../x", b"x")])


class FlashOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_flash_backs_up_then_writes_pdf_and_both_caches(self):
        lockdown = Mock(identifier="device")
        with (
            patch.object(core_flasher, "get_lockdown_client", AsyncMock(return_value=lockdown)),
            patch.object(core_flasher, "backup_original_card_async", AsyncMock()) as backup,
            patch.object(
                core_flasher,
                "build_card_assets",
                return_value={
                    "cardBackgroundCombined@3x.png": b"3x",
                    "cardBackgroundCombined@2x.png": b"2x",
                    "cardBackgroundCombined.pdf": b"pdf",
                },
            ),
            patch.object(core_flasher, "write_system_files_async", AsyncMock()) as write,
            patch.object(core_flasher, "invalidate_card_cache_async", AsyncMock(return_value=9)) as cache,
        ):
            result = await core_flasher.flash_card_skin_async(
                "device", "card", b"png", device_name="Phone", ios_version="18"
            )

        self.assertTrue(result)
        backup.assert_awaited_once()
        written = write.await_args.args[2]
        self.assertEqual({name for name, _ in written}, set(core_flasher.TARGET_ASSETS))
        cache.assert_awaited_once()

    async def test_flash_can_hide_all_logo_assets(self):
        lockdown = Mock(identifier="device")
        with (
            patch.object(core_flasher, "get_lockdown_client", AsyncMock(return_value=lockdown)),
            patch.object(core_flasher, "backup_original_card_async", AsyncMock()),
            patch.object(core_flasher, "build_card_assets", return_value={"a": b"1"}),
            patch.object(core_flasher, "get_transparent_pixel_png", return_value=b"transparent"),
            patch.object(core_flasher, "write_system_files_async", AsyncMock()) as write,
            patch.object(core_flasher, "invalidate_card_cache_async", AsyncMock(return_value=1)),
        ):
            await core_flasher.flash_card_skin_async(
                "device", "card", b"png", clean_logo=True
            )
        written = dict(write.await_args.args[2])
        for name in core_flasher.LOGO_ASSETS:
            self.assertEqual(written[name], b"transparent")

    async def test_missing_required_original_blocks_first_write(self):
        with (
            patch.object(core_flasher, "latest_backup", return_value=None),
            patch.object(
                core_flasher, "read_system_file_async", AsyncMock(return_value=None)
            ),
            patch.object(core_flasher, "save_backup") as save,
        ):
            with self.assertRaises(BackupError):
                await core_flasher.backup_original_card_async("device", "card")
        save.assert_not_called()

    async def test_restore_writes_removes_invalidates_and_verifies(self):
        record = BackupRecord(
            path=Path("unused"),
            udid="device",
            card_hash="card",
            created_at="2026-09-21T00:00:00+00:00",
            device_name="Phone",
            ios_version="18",
            assets={},
        )
        assets = {
            "cardBackgroundCombined@3x.png": b"original",
            "cardBackgroundCombined.pdf": None,
        }
        with (
            patch.object(core_flasher, "load_backup_assets", return_value=assets),
            patch.object(core_flasher, "write_system_files_async", AsyncMock()) as write,
            patch.object(core_flasher, "remove_system_file_async", AsyncMock()) as remove,
            patch.object(
                core_flasher, "invalidate_card_cache_async", AsyncMock(return_value=7)
            ) as cache,
            patch.object(
                core_flasher,
                "read_system_file_async",
                AsyncMock(return_value=b"original"),
            ) as read,
        ):
            result = await core_flasher.restore_original_card_async(
                "device", "card", backup=record, verify=True
            )

        self.assertTrue(result)
        self.assertEqual(
            write.await_args.args[2],
            [("cardBackgroundCombined@3x.png", b"original")],
        )
        remove.assert_awaited_once_with(
            "device",
            "/var/mobile/Library/Passes/Cards/card.pkpass",
            "cardBackgroundCombined.pdf",
        )
        cache.assert_awaited_once()
        read.assert_awaited_once()

    async def test_restore_verification_rejects_mismatch(self):
        record = BackupRecord(
            path=Path("unused"),
            udid="device",
            card_hash="card",
            created_at="2026-09-21T00:00:00+00:00",
            device_name="Phone",
            ios_version="18",
            assets={},
        )
        with (
            patch.object(
                core_flasher,
                "load_backup_assets",
                return_value={"cardBackgroundCombined@3x.png": b"original"},
            ),
            patch.object(core_flasher, "write_system_files_async", AsyncMock()),
            patch.object(core_flasher, "invalidate_card_cache_async", AsyncMock()),
            patch.object(
                core_flasher,
                "read_system_file_async",
                AsyncMock(return_value=b"different"),
            ),
        ):
            with self.assertRaises(core_flasher.RestoreError):
                await core_flasher.restore_original_card_async(
                    "device", "card", backup=record, verify=True
                )


if __name__ == "__main__":
    unittest.main()
