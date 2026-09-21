"""Persistent, checksummed backups of original Wallet card artwork."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .config import BACKUP_ROOT, ensure_app_data_dirs

MANIFEST_NAME = "manifest.json"
BACKUP_VERSION = 1


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupRecord:
    path: Path
    udid: str
    card_hash: str
    created_at: str
    device_name: str
    ios_version: str
    assets: dict[str, dict]

    @property
    def label(self) -> str:
        try:
            timestamp = datetime.fromisoformat(self.created_at).astimezone()
            return timestamp.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return self.created_at


def _safe_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _card_backup_dir(udid: str, card_hash: str) -> Path:
    return BACKUP_ROOT / _safe_key(udid) / _safe_key(card_hash)


def _read_record(path: Path) -> BackupRecord:
    manifest_path = path / MANIFEST_NAME
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"备份清单无效：{manifest_path}") from exc

    if data.get("version") != BACKUP_VERSION or not isinstance(data.get("assets"), dict):
        raise BackupError(f"不支持的备份格式：{manifest_path}")
    return BackupRecord(
        path=path,
        udid=str(data.get("udid", "")),
        card_hash=str(data.get("card_hash", "")),
        created_at=str(data.get("created_at", "")),
        device_name=str(data.get("device_name", "")),
        ios_version=str(data.get("ios_version", "")),
        assets=data["assets"],
    )


def save_backup(
    udid: str,
    card_hash: str,
    assets: Mapping[str, bytes | None],
    *,
    device_name: str = "",
    ios_version: str = "",
) -> BackupRecord:
    """Atomically save a backup. Existing backups are never overwritten."""
    if not udid or not card_hash:
        raise BackupError("必须提供设备和卡片标识")
    if not assets:
        raise BackupError("没有可供备份的卡面资源")

    ensure_app_data_dirs()
    parent = _card_backup_dir(udid, card_hash)
    parent.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    final_name = created.strftime("%Y%m%dT%H%M%S.%fZ")
    temp_path = Path(tempfile.mkdtemp(prefix=".pending-", dir=parent))

    try:
        manifest_assets: dict[str, dict] = {}
        for index, (name, payload) in enumerate(sorted(assets.items())):
            if Path(name).name != name:
                raise BackupError(f"资源名称不安全：{name}")
            if payload is None:
                manifest_assets[name] = {"exists": False}
                continue
            file_name = f"asset-{index:02d}.bin"
            (temp_path / file_name).write_bytes(payload)
            manifest_assets[name] = {
                "exists": True,
                "file": file_name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        manifest = {
            "version": BACKUP_VERSION,
            "created_at": created.isoformat(),
            "udid": udid,
            "card_hash": card_hash,
            "device_name": device_name,
            "ios_version": ios_version,
            "assets": manifest_assets,
        }
        manifest_path = temp_path / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with manifest_path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())

        final_path = parent / final_name
        temp_path.replace(final_path)
        return _read_record(final_path)
    except Exception:
        shutil.rmtree(temp_path, ignore_errors=True)
        raise


def list_backups(udid: str, card_hash: str) -> list[BackupRecord]:
    parent = _card_backup_dir(udid, card_hash)
    if not parent.is_dir():
        return []
    records: list[BackupRecord] = []
    for child in parent.iterdir():
        if not child.is_dir() or child.name.startswith(".pending-"):
            continue
        try:
            record = _read_record(child)
            if record.udid == udid and record.card_hash == card_hash:
                records.append(record)
        except BackupError:
            continue
    return sorted(records, key=lambda item: item.created_at, reverse=True)


def latest_backup(udid: str, card_hash: str) -> BackupRecord | None:
    records = list_backups(udid, card_hash)
    return records[0] if records else None


def load_backup_assets(record: BackupRecord) -> dict[str, bytes | None]:
    result: dict[str, bytes | None] = {}
    for name, metadata in record.assets.items():
        if not metadata.get("exists"):
            result[name] = None
            continue
        file_name = metadata.get("file")
        if not isinstance(file_name, str) or Path(file_name).name != file_name:
            raise BackupError(f"备份条目不安全：{name}")
        try:
            payload = (record.path / file_name).read_bytes()
        except OSError as exc:
            raise BackupError(f"备份数据缺失：{name}") from exc
        expected = metadata.get("sha256")
        if hashlib.sha256(payload).hexdigest() != expected:
            raise BackupError(f"备份校验和不匹配：{name}")
        if len(payload) != metadata.get("size"):
            raise BackupError(f"备份大小不匹配：{name}")
        result[name] = payload
    return result
