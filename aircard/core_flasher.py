"""Safe AirLift-based Wallet artwork operations for Windows.

The module keeps Apple Books sync state transactional, batches writes, backs up
original Wallet assets before the first modification, and can restore those
assets later. Apple DLL calls remain isolated in :mod:`aircard.airtraffic`.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import plistlib
import posixpath
import secrets
import stat
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .airtraffic import (
    AirTrafficError,
    MissingRemoteAssetError,
    sync_assets_via_airtraffic,
)
from .backup import (
    BackupError,
    BackupRecord,
    latest_backup,
    load_backup_assets,
    save_backup,
)
from .config import (
    APP_DATA_DIR,
    CACHE_EXTENSIONS,
    CACHE_FILES,
    LOGO_ASSETS,
    TARGET_ASSETS,
    ensure_app_data_dirs,
)
from .device import get_lockdown_client
from .image_util import build_card_assets, get_transparent_pixel_png

ProgressCallback = Callable[[int, int, str], None]

AIRLOCK_ROOT = "/var/mobile/Media/Airlock/Book"
SOURCE_PREFIX = "airlift-src-"
LINK_PREFIX = "airlift-link-"
RECOVERED_PREFIX = "airlift-recovered-"
SZ_EXTRA_ID = 0x5A53
READ_SYNC_TIMEOUT = 45
WRITE_SYNC_TIMEOUT = 90

TRACKED_BOOKS_FILES = (
    "Books/Books.plist",
    "Books/Sync/Books.plist",
    "Books/Sync/Upload.plist",
    "Books/Sync/Database/OutstandingAssets_4.sqlite",
    "Books/Sync/Database/OutstandingAssets_4.sqlite-shm",
    "Books/Sync/Database/OutstandingAssets_4.sqlite-wal",
)
TRACKED_BOOKS_DIRECTORIES = ("Books", "Books/Sync", "Books/Sync/Database")
BACKUP_ASSETS = tuple(dict.fromkeys((*TARGET_ASSETS, *LOGO_ASSETS)))
REQUIRED_BACKUP_ASSETS = {
    "cardBackgroundCombined@3x.png",
    "cardBackgroundCombined@2x.png",
}


class FlashError(RuntimeError):
    pass


class RestoreError(RuntimeError):
    pass


def _validate_target(target: str) -> str:
    normalized = posixpath.normpath(target)
    if not normalized.startswith("/") or normalized == "/" or "\x00" in normalized:
        raise ValueError("目标必须是非根目录的 iOS 绝对路径")
    if any(part in ("", ".", "..") for part in normalized[1:].split("/")):
        raise ValueError("目标路径包含不安全的路径片段")
    return normalized


def _validate_leaf(leaf: str) -> str:
    if not leaf or Path(leaf).name != leaf or "/" in leaf or "\\" in leaf or "\x00" in leaf:
        raise ValueError(f"资源名称不安全：{leaf}")
    return leaf


def zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 9, 14, 5, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (mode & 0xFFFF) << 16
    info.extra = struct.pack("<HHH", SZ_EXTRA_ID, 2, mode & 0xFFFF)
    return info


def build_archive_multi(target: str, files: Iterable[tuple[str, bytes]]) -> bytes:
    target = _validate_target(target)
    files = [(_validate_leaf(name), payload) for name, payload in files]
    target_tail = target[1:]
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
        for index, (_, payload) in enumerate(files):
            archive.writestr(
                zip_info(f"payload_{index}", stat.S_IFREG | 0o600), payload
            )
    return output.getvalue()


def build_books_plist(identifiers: Iterable[str]) -> bytes:
    rows = [
        {"Persistent ID": ident, "Item ID": str(index), "DSID": "1"}
        for index, ident in enumerate(identifiers, 1)
    ]
    return plistlib.dumps({"Books": rows}, fmt=plistlib.FMT_BINARY, sort_keys=True)


async def _ensure_parent(afc: Any, path: str) -> None:
    parent = posixpath.dirname(path)
    if parent and not await afc.exists(parent):
        await afc.makedirs(parent)


async def snapshot_books(afc: Any) -> dict[str, Any]:
    files: dict[str, bytes | None] = {}
    directories: dict[str, bool] = {}
    for directory in TRACKED_BOOKS_DIRECTORIES:
        directories[directory] = bool(await afc.exists(directory))
    for path in TRACKED_BOOKS_FILES:
        if await afc.exists(path):
            files[path] = await afc.get_file_contents(path)
        else:
            files[path] = None
    return {"files": files, "directories": directories}


async def restore_books(afc: Any, snapshot: dict[str, Any]) -> None:
    failures: list[str] = []
    for path, payload in snapshot["files"].items():
        try:
            if payload is None:
                if await afc.exists(path):
                    await afc.rm(path)
            else:
                await _ensure_parent(afc, path)
                await afc.set_file_contents(path, payload)
        except Exception:
            failures.append(path)

    for directory in reversed(TRACKED_BOOKS_DIRECTORIES):
        if snapshot["directories"].get(directory):
            continue
        try:
            if await afc.exists(directory) and not await afc.listdir(directory):
                await afc.rm(directory)
        except Exception:
            pass

    for path, expected in snapshot["files"].items():
        try:
            exists = bool(await afc.exists(path))
            if expected is None and exists:
                failures.append(path)
            elif expected is not None:
                observed = await afc.get_file_contents(path) if exists else None
                if observed != expected:
                    failures.append(path)
        except Exception:
            failures.append(path)
    if failures:
        raise FlashError(
            "无法恢复 Apple Books 同步状态："
            + ", ".join(sorted(set(failures)))
        )


async def _remove_tree(afc: Any, path: str, depth: int = 0) -> None:
    if depth > 32 or not await afc.exists(path):
        return
    if await afc.isdir(path):
        for name in await afc.listdir(path):
            if name in (".", ".."):
                continue
            await _remove_tree(afc, posixpath.join(path, name), depth + 1)
    await afc.rm(path)


async def _cleanup_generated(afc: Any, source: str, link_destination: str) -> None:
    # Remove the relocated symlink first so recursive cleanup can never follow it.
    for path in (link_destination, f"{source}/p0/p1/p2/link"):
        if await afc.exists(path):
            await afc.rm(path)
    if await afc.exists(source):
        await _remove_tree(afc, source)


async def _stage_archive(
    lockdown: Any,
    afc: Any,
    source: str,
    target: str,
    files: list[tuple[str, bytes]],
) -> None:
    from pymobiledevice3.service_connection import build_plist

    archive_data = build_archive_multi(target, files)
    zip_service = await lockdown.start_lockdown_service("com.apple.streaming_zip_conduit")
    try:
        header = build_plist(
            {"MediaSubdir": source}, endianity=">", fmt=plistlib.FMT_BINARY
        )
        await zip_service.sendall(header)
        await zip_service.sendall(archive_data)
        await zip_service.recv_plist(endianity=">")
    finally:
        await zip_service.close()

    expected = [f"{source}/p0/p1/p2/link"] + [
        f"{source}/payload_{index}" for index in range(len(files))
    ]
    missing = [path for path in expected if not await afc.exists(path)]
    if missing:
        raise FlashError("StreamingZip 未能创建：" + ", ".join(missing))


async def _write_files_in_session(
    lockdown: Any,
    afc: Any,
    udid: str,
    target: str,
    files: list[tuple[str, bytes]],
    *,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if not files:
        return
    target = _validate_target(target)
    files = [(_validate_leaf(name), payload) for name, payload in files]
    token = secrets.token_hex(10)
    source = f"{SOURCE_PREFIX}{token}"
    link_destination = f"{LINK_PREFIX}{token}"
    link_identifier = f"../../{source}/p0/p1/p2/link"
    identifiers = [link_identifier] + [
        f"../../{source}/payload_{index}" for index in range(len(files))
    ]
    destinations = [link_destination] + [
        posixpath.join(link_destination, name) for name, _ in files
    ]

    if await afc.exists(source) or await afc.exists(link_destination):
        raise FlashError("AirLift 临时路径已存在，请重试")
    await _stage_archive(lockdown, afc, source, target, files)
    try:
        await _ensure_parent(afc, "Books/Sync/Books.plist")
        await afc.set_file_contents(
            "Books/Sync/Books.plist", build_books_plist(identifiers)
        )
        await asyncio.to_thread(
            sync_assets_via_airtraffic,
            udid,
            list(zip(identifiers, destinations)),
            WRITE_SYNC_TIMEOUT,
            progress_callback,
        )
    finally:
        await _cleanup_generated(afc, source, link_destination)


async def write_system_files_async(
    udid: str,
    target: str,
    files: Iterable[tuple[str, bytes]],
    *,
    retries: int = 3,
    progress_callback: ProgressCallback | None = None,
) -> bool:
    files = list(files)
    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        lockdown = await get_lockdown_client(udid)
        from pymobiledevice3.services.afc import AfcService

        try:
            async with AfcService(lockdown) as afc:
                books = await snapshot_books(afc)
                try:
                    await _write_files_in_session(
                        lockdown,
                        afc,
                        udid,
                        target,
                        files,
                        progress_callback=progress_callback,
                    )
                finally:
                    await restore_books(afc, books)
            return True
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(0.4 * attempt)
    raise FlashError(f"写入 Wallet 卡面失败：{last_error}") from last_error


async def write_system_file_async(
    udid: str,
    target_dir: str,
    leaf_name: str,
    payload: bytes,
) -> bool:
    return await write_system_files_async(
        udid, target_dir, [(leaf_name, payload)], retries=3
    )


def _save_emergency_copy(target: str, leaf: str, payload: bytes) -> Path:
    ensure_app_data_dirs()
    recovery = APP_DATA_DIR / "recovery"
    recovery.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{target}/{leaf}".encode()).hexdigest()[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data_path = recovery / f"{stamp}-{key}.bin"
    data_path.write_bytes(payload)
    metadata = {
        "target": target,
        "leaf": leaf,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    data_path.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return data_path


async def read_system_file_async(
    udid: str,
    target_dir: str,
    leaf_name: str,
    progress_callback: ProgressCallback | None = None,
) -> bytes | None:
    """Read a known file by temporarily relocating it into AFC-visible Media.

    AirTraffic performs a move rather than a copy, so the original bytes are
    written back before this function returns. If that write-back fails an
    emergency local copy and the AFC-visible recovered file are both retained.
    """
    target_dir = _validate_target(target_dir)
    leaf_name = _validate_leaf(leaf_name)
    lockdown = await get_lockdown_client(udid)
    from pymobiledevice3.services.afc import AfcService

    async with AfcService(lockdown) as afc:
        books = await snapshot_books(afc)
        token = secrets.token_hex(10)
        recovered = f"{RECOVERED_PREFIX}{token}"
        target_path = posixpath.join(target_dir, leaf_name)
        identifier = posixpath.relpath(target_path, AIRLOCK_ROOT)
        payload: bytes | None = None
        restored = False
        sync_error: Exception | None = None
        try:
            await _ensure_parent(afc, "Books/Sync/Books.plist")
            await afc.set_file_contents(
                "Books/Sync/Books.plist", build_books_plist([identifier])
            )
            try:
                await asyncio.to_thread(
                    sync_assets_via_airtraffic,
                    udid,
                    [(identifier, recovered)],
                    READ_SYNC_TIMEOUT,
                    progress_callback,
                )
            except MissingRemoteAssetError:
                return None
            except Exception as exc:
                # The Apple DLL may block after the device has already moved
                # the requested resource into Media.  Recover that file before
                # surfacing the timeout/error to the caller.
                sync_error = exc

            if not await afc.exists(recovered):
                if sync_error:
                    raise sync_error
                return None
            payload = await afc.get_file_contents(recovered)
            for attempt in range(1, 4):
                try:
                    await _write_files_in_session(
                        lockdown, afc, udid, target_dir, [(leaf_name, payload)]
                    )
                    restored = True
                    break
                except Exception:
                    if attempt < 3:
                        await asyncio.sleep(0.5 * attempt)
            if not restored:
                recovery_path = _save_emergency_copy(target_dir, leaf_name, payload)
                raise RestoreError(
                    "已读取原始文件，但无法将其写回设备。"
                    f"紧急恢复副本已保存到 {recovery_path}。"
                )
            await afc.rm(recovered)
            if sync_error:
                raise AirTrafficError(
                    "设备同步未正常结束，但已将临时移出的原始文件安全写回设备。"
                ) from sync_error
            return payload
        finally:
            await restore_books(afc, books)
            if restored and await afc.exists(recovered):
                await afc.rm(recovered)


async def remove_system_file_async(udid: str, target_dir: str, leaf_name: str) -> bool:
    """Delete a known system file by moving it into Media and removing it."""
    target_dir = _validate_target(target_dir)
    leaf_name = _validate_leaf(leaf_name)
    lockdown = await get_lockdown_client(udid)
    from pymobiledevice3.services.afc import AfcService

    async with AfcService(lockdown) as afc:
        books = await snapshot_books(afc)
        recovered = f"{RECOVERED_PREFIX}{secrets.token_hex(10)}"
        target_path = posixpath.join(target_dir, leaf_name)
        identifier = posixpath.relpath(target_path, AIRLOCK_ROOT)
        try:
            await _ensure_parent(afc, "Books/Sync/Books.plist")
            await afc.set_file_contents(
                "Books/Sync/Books.plist", build_books_plist([identifier])
            )
            try:
                await asyncio.to_thread(
                    sync_assets_via_airtraffic,
                    udid,
                    [(identifier, recovered)],
                    READ_SYNC_TIMEOUT,
                )
            except MissingRemoteAssetError:
                return True
            if await afc.exists(recovered):
                await afc.rm(recovered)
            return True
        finally:
            await restore_books(afc, books)


async def backup_original_card_async(
    udid: str,
    card_hash: str,
    *,
    device_name: str = "",
    ios_version: str = "",
    progress_callback: ProgressCallback | None = None,
) -> BackupRecord:
    existing = latest_backup(udid, card_hash)
    if existing:
        return existing

    target = f"/var/mobile/Library/Passes/Cards/{card_hash}.pkpass"
    assets: dict[str, bytes | None] = {}
    total = len(BACKUP_ASSETS)
    for index, name in enumerate(BACKUP_ASSETS, 1):
        if progress_callback:
            progress_callback(index - 1, total, f"正在备份原始资源：{name}…")
        assets[name] = await read_system_file_async(
            udid,
            target,
            name,
            (
                lambda _step, _sync_total, message, current=index - 1: progress_callback(
                    current, total, message
                )
            )
            if progress_callback
            else None,
        )

    missing_required = [name for name in REQUIRED_BACKUP_ASSETS if assets.get(name) is None]
    if missing_required:
        raise BackupError(
            "无法备份原始卡面资源：" + ", ".join(missing_required)
        )
    record = save_backup(
        udid,
        card_hash,
        assets,
        device_name=device_name,
        ios_version=ios_version,
    )
    if progress_callback:
        progress_callback(total, total, "原始卡面已备份")
    return record


async def invalidate_card_cache_async(
    udid: Optional[str],
    card_hash: str,
    progress_callback: Optional[ProgressCallback] = None,
    current_step: int = 0,
    total_steps: int = 0,
) -> int:
    lockdown = await get_lockdown_client(udid)
    actual_udid = udid or lockdown.identifier
    cache_payloads = [(name, b"corrupted") for name in CACHE_FILES]
    for extension in CACHE_EXTENSIONS:
        if progress_callback and total_steps:
            progress_callback(
                current_step,
                total_steps,
                f"正在刷新 Wallet 缓存（{extension}）…",
            )
        await write_system_files_async(
            actual_udid,
            f"/var/mobile/Library/Passes/Cards/{card_hash}{extension}",
            cache_payloads,
        )
        current_step += len(CACHE_FILES)
    return current_step


async def flash_card_skin_async(
    udid: Optional[str],
    card_hash: str,
    skin_png_bytes: bytes,
    clean_logo: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
    *,
    auto_backup: bool = True,
    device_name: str = "",
    ios_version: str = "",
) -> bool:
    lockdown = await get_lockdown_client(udid)
    actual_udid = udid or lockdown.identifier
    if auto_backup:
        await backup_original_card_async(
            actual_udid,
            card_hash,
            device_name=device_name,
            ios_version=ios_version,
            progress_callback=progress_callback,
        )

    artwork = build_card_assets(skin_png_bytes)
    files = list(artwork.items())
    if clean_logo:
        transparent = get_transparent_pixel_png()
        files.extend((name, transparent) for name in LOGO_ASSETS)

    total = len(files) + len(CACHE_FILES) * len(CACHE_EXTENSIONS)
    if progress_callback:
        progress_callback(0, total, "正在写入新卡面…")
    target = f"/var/mobile/Library/Passes/Cards/{card_hash}.pkpass"
    await write_system_files_async(actual_udid, target, files)
    await invalidate_card_cache_async(
        actual_udid,
        card_hash,
        progress_callback,
        current_step=len(files),
        total_steps=total,
    )
    if progress_callback:
        progress_callback(total, total, "新卡面已应用")
    return True


async def restore_original_card_async(
    udid: str,
    card_hash: str,
    *,
    backup: BackupRecord | None = None,
    verify: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> bool:
    record = backup or latest_backup(udid, card_hash)
    if not record:
        raise RestoreError("此设备和卡片没有可用的原始卡面备份")
    assets = load_backup_assets(record)
    target = f"/var/mobile/Library/Passes/Cards/{card_hash}.pkpass"
    existing = [(name, payload) for name, payload in assets.items() if payload is not None]
    absent = [name for name, payload in assets.items() if payload is None]
    total = len(existing) + len(absent) + len(CACHE_FILES) * len(CACHE_EXTENSIONS)

    if progress_callback:
        progress_callback(0, total, "正在恢复原始卡面…")
    await write_system_files_async(udid, target, existing)
    step = len(existing)
    for name in absent:
        await remove_system_file_async(udid, target, name)
        step += 1
        if progress_callback:
            progress_callback(step, total, f"正在移除后来添加的资源：{name}…")

    await invalidate_card_cache_async(
        udid,
        card_hash,
        progress_callback,
        current_step=step,
        total_steps=total,
    )

    if verify:
        for name, expected in existing:
            observed = await read_system_file_async(udid, target, name)
            if observed != expected:
                raise RestoreError(f"恢复校验失败：{name}")
    if progress_callback:
        progress_callback(total, total, "原始卡面已恢复并通过校验")
    return True


def flash_card_skin(
    udid: Optional[str],
    card_hash: str,
    skin_png_bytes: bytes,
    clean_logo: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> bool:
    return asyncio.run(
        flash_card_skin_async(
            udid,
            card_hash,
            skin_png_bytes,
            clean_logo,
            progress_callback,
        )
    )
