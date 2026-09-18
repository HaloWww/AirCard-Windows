"""
Core flasher engine implementing the airlift file write mechanism on Windows.
Integrates pymobiledevice3 and AirTrafficHost.dll.
"""
from typing import Callable, Optional
import asyncio
import io
import plistlib
import posixpath
import secrets
import stat
import struct
import zipfile
from pymobiledevice3.services.afc import AfcService
from pymobiledevice3.service_connection import build_plist
from .device import get_lockdown_client
from .airtraffic import sync_assets_via_airtraffic
from .config import TARGET_ASSETS, LOGO_ASSETS, CACHE_FILES
from .image_util import get_transparent_pixel_png

SOURCE_PREFIX = "airlift-src-"
LINK_PREFIX = "airlift-link-"
RECOVERED_PREFIX = "airlift-recovered-"
SZ_EXTRA_ID = 0x5A53

TRACKED_BOOKS_FILES = [
    "Books/Books.plist",
    "Books/Sync/Books.plist",
    "Books/Sync/Upload.plist",
    "Books/Sync/Database/OutstandingAssets_4.sqlite",
    "Books/Sync/Database/OutstandingAssets_4.sqlite-shm",
    "Books/Sync/Database/OutstandingAssets_4.sqlite-wal",
]


def zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 9, 14, 5, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (mode & 0xFFFF) << 16
    info.extra = struct.pack("<HHH", SZ_EXTRA_ID, 2, mode & 0xFFFF)
    return info


def build_archive(target: str, payload: bytes) -> bytes:
    target_tail = target[1:] if target.startswith("/") else target
    metadata = plistlib.dumps({"Version": 2}, fmt=plistlib.FMT_BINARY, sort_keys=True)
    output = io.BytesIO()

    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        archive.writestr(zip_info("META-INF/", stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            zip_info("META-INF/com.apple.ZipMetadata.plist", stat.S_IFREG | 0o600),
            metadata,
        )
        for directory in ("p0/", "p0/p1/", "p0/p1/p2/"):
            archive.writestr(zip_info(directory, stat.S_IFDIR | 0o755), b"")

        archive.writestr(
            zip_info("p0/p1/p2/link", stat.S_IFLNK | 0o777),
            f"../../../{target_tail}".encode(),
        )

        cursor = ""
        for component in target_tail.split("/"):
            cursor += component + "/"
            archive.writestr(zip_info(cursor, stat.S_IFDIR | 0o755), b"")

        archive.writestr(zip_info("payload", stat.S_IFREG | 0o600), payload)

    return output.getvalue()


def build_books_plist(identifiers: list[str]) -> bytes:
    rows = [
        {"Persistent ID": ident, "Item ID": str(idx), "DSID": "1"}
        for idx, ident in enumerate(identifiers, 1)
    ]
    return plistlib.dumps({"Books": rows}, fmt=plistlib.FMT_BINARY, sort_keys=True)


async def snapshot_books(afc: AfcService) -> dict[str, Optional[bytes]]:
    snapshot = {}
    for path in TRACKED_BOOKS_FILES:
        try:
            if await afc.exists(path):
                snapshot[path] = await afc.get_file_contents(path)
            else:
                snapshot[path] = None
        except Exception:
            snapshot[path] = None
    return snapshot


async def restore_books(afc: AfcService, snapshot: dict[str, Optional[bytes]]):
    for path, data in snapshot.items():
        try:
            if data is not None:
                parent = posixpath.dirname(path)
                if parent and not await afc.exists(parent):
                    await afc.makedirs(parent)
                await afc.set_file_contents(path, data)
            else:
                if await afc.exists(path):
                    await afc.rm(path)
        except Exception:
            pass


async def remove_tree(afc: AfcService, path: str):
    try:
        if not await afc.exists(path):
            return
        for item in await afc.listdir(path):
            if item in (".", ".."):
                continue
            child = posixpath.join(path, item)
            try:
                if await afc.isdir(child):
                    await remove_tree(afc, child)
                else:
                    await afc.rm(child)
            except Exception:
                pass
        await afc.rm(path)
    except Exception:
        pass


async def write_system_file_async(
    udid: str,
    target_dir: str,
    leaf_name: str,
    payload: bytes
) -> bool:
    token = secrets.token_hex(10)
    source = f"{SOURCE_PREFIX}{token}"
    link_dest = f"{LINK_PREFIX}{token}"
    recovered = f"{RECOVERED_PREFIX}{token}"

    link_ident = f"../../{source}/p0/p1/p2/link"
    payload_ident = f"../../{source}/payload"

    identifiers = [link_ident, payload_ident]
    destinations = [
        link_dest,
        posixpath.join(link_dest, leaf_name),
    ]

    lockdown = await get_lockdown_client(udid)

    async with AfcService(lockdown) as afc:
        snapshot = await snapshot_books(afc)

        try:
            archive_data = build_archive(target_dir, payload)
            books_plist_data = build_books_plist(identifiers)

            zip_service = await lockdown.start_lockdown_service("com.apple.streaming_zip_conduit")
            header_pkt = build_plist({"MediaSubdir": source}, endianity=">", fmt=plistlib.FMT_BINARY)
            await zip_service.sendall(header_pkt)
            await zip_service.sendall(archive_data)
            _ = await zip_service.recv_plist(endianity=">")
            await zip_service.close()

            if not await afc.exists("Books/Sync"):
                await afc.makedirs("Books/Sync")
            await afc.set_file_contents("Books/Sync/Books.plist", books_plist_data)

            assets_to_sync = list(zip(identifiers, destinations))
            ok = await asyncio.to_thread(sync_assets_via_airtraffic, udid, assets_to_sync)
            return ok

        finally:
            try:
                if await afc.exists(link_dest):
                    await afc.rm(link_dest)
                if await afc.exists(recovered):
                    await afc.rm(recovered)
                await remove_tree(afc, source)
            except Exception:
                pass
            await asyncio.sleep(0.3)
            await restore_books(afc, snapshot)


async def invalidate_card_cache_async(
    udid: Optional[str],
    card_hash: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    current_step: int = 0,
    total_steps: int = 0,
) -> int:
    """Corrupt FrontFace, PlaceHolder, and Preview in .cache
    so both Apple Wallet and Apple Pay double-click presentation re-render with new artwork."""
    lockdown = await get_lockdown_client(udid)
    actual_udid = udid or lockdown.identifier

    cache_dir = f"/var/mobile/Library/Passes/Cards/{card_hash}.cache"
    for leaf in CACHE_FILES:
        current_step += 1
        if progress_callback and total_steps > 0:
            progress_callback(current_step, total_steps, f"Invalidating {leaf} cache (Apple Pay sync)...")
        try:
            await write_system_file_async(actual_udid, cache_dir, leaf, b"corrupted")
        except Exception:
            pass
    return current_step


async def flash_card_skin_async(
    udid: Optional[str],
    card_hash: str,
    skin_png_bytes: bytes,
    clean_logo: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> bool:
    extra_assets = LOGO_ASSETS if clean_logo else []
    cache_steps = len(CACHE_FILES)
    total_steps = len(TARGET_ASSETS) + len(extra_assets) + cache_steps
    step = 0

    lockdown = await get_lockdown_client(udid)
    actual_udid = udid or lockdown.identifier
    pkpass_dir = f"/var/mobile/Library/Passes/Cards/{card_hash}.pkpass"

    for asset in TARGET_ASSETS:
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, f"Writing {asset}...")
        ok = await write_system_file_async(actual_udid, pkpass_dir, asset, skin_png_bytes)
        if not ok:
            return False

    if clean_logo:
        transparent_bytes = get_transparent_pixel_png()
        for logo_asset in LOGO_ASSETS:
            step += 1
            if progress_callback:
                progress_callback(step, total_steps, f"Hiding {logo_asset}...")
            ok = await write_system_file_async(actual_udid, pkpass_dir, logo_asset, transparent_bytes)
            if not ok:
                return False

    # Invalidate all caches (FrontFace, PlaceHolder, Preview) in .cache and .pkcache
    step = await invalidate_card_cache_async(
        actual_udid, card_hash, progress_callback, current_step=step, total_steps=total_steps
    )

    return True


def flash_card_skin(
    udid: Optional[str],
    card_hash: str,
    skin_png_bytes: bytes,
    clean_logo: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> bool:
    return asyncio.run(flash_card_skin_async(udid, card_hash, skin_png_bytes, clean_logo, progress_callback))

