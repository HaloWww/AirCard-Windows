"""AirCard for Windows — focused, recovery-first desktop interface."""

from __future__ import annotations

import asyncio
import base64
import io
import sys
from pathlib import Path
from typing import Optional

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import flet as ft

from aircard.backup import latest_backup
from aircard.config import APP_VERSION, find_apple_dll_dir
from aircard.core_flasher import flash_card_skin_async, restore_original_card_async
from aircard.device import ConnectedDevice, get_connected_devices
from aircard.image_util import prepare_card_skin
from aircard.scanner import (
    load_saved_cards_metadata,
    save_cards_metadata,
    start_card_scan_session,
)

BG = "#0B0D12"
SURFACE = "#141821"
SURFACE_2 = "#1B202B"
BORDER = "#2A3140"
TEXT = "#F6F7FB"
MUTED = "#9AA3B2"
ACCENT = "#6C8CFF"
ACCENT_2 = "#8F6CFF"
SUCCESS = "#42D392"
DANGER = "#FF6B7A"


def _card_label(card: dict[str, str]) -> str:
    name = card.get("name") or "Wallet 卡片"
    value = card.get("hash", "")
    short = f"{value[:8]}…{value[-5:]}" if len(value) > 16 else value
    return f"{name}  ·  {short}"


async def main(page: ft.Page):
    page.title = "AirCard 卡面助手"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.padding = 0
    page.window.width = 1040
    page.window.height = 760
    page.window.min_width = 900
    page.window.min_height = 650
    page.window.resizable = True
    page.theme = ft.Theme(color_scheme_seed=ACCENT)

    file_picker = ft.FilePicker()
    if hasattr(page, "services"):
        page.services.append(file_picker)
    elif hasattr(page, "_services"):
        page._services.append(file_picker)
    else:
        page.overlay.append(file_picker)

    devices: list[ConnectedDevice] = []
    selected_device: Optional[ConnectedDevice] = None
    cards = load_saved_cards_metadata()
    selected_hash = cards[0]["hash"] if cards else ""
    artwork: bytes | None = None
    artwork_name = ""
    scan_stop: asyncio.Event | None = None
    busy = False

    def show_message(message: str, *, error: bool = False):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message, color=TEXT),
                bgcolor="#4A1F29" if error else "#17362C",
            )
        )

    def section_title(number: str, title: str, subtitle: str):
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(number, size=12, weight=ft.FontWeight.BOLD, color=TEXT),
                    width=28,
                    height=28,
                    alignment=ft.Alignment.CENTER,
                    border_radius=14,
                    gradient=ft.LinearGradient(colors=[ACCENT, ACCENT_2]),
                ),
                ft.Column(
                    [
                        ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=TEXT),
                        ft.Text(subtitle, size=11, color=MUTED),
                    ],
                    spacing=1,
                    expand=True,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def panel(content, *, padding=18):
        return ft.Container(
            content=content,
            bgcolor=SURFACE,
            border=ft.Border.all(1, BORDER),
            border_radius=18,
            padding=padding,
        )

    # Header
    device_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor="#596273")
    device_summary = ft.Text("正在查找 iPhone…", size=12, color=MUTED)
    header = ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(ft.Icons.CREDIT_CARD_ROUNDED, color=TEXT, size=24),
                            width=42,
                            height=42,
                            border_radius=13,
                            alignment=ft.Alignment.CENTER,
                            gradient=ft.LinearGradient(colors=[ACCENT, ACCENT_2]),
                        ),
                        ft.Column(
                            [
                                ft.Text("AirCard", size=20, weight=ft.FontWeight.BOLD, color=TEXT),
                                ft.Text(f"Windows · v{APP_VERSION}", size=11, color=MUTED),
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=11,
                ),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Row([device_dot, device_summary], spacing=8),
                    bgcolor=SURFACE_2,
                    border=ft.Border.all(1, BORDER),
                    border_radius=18,
                    padding=ft.Padding(13, 8, 13, 8),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(26, 18, 26, 14),
    )

    # Preview
    preview_image = ft.Image(src="", fit=ft.BoxFit.COVER, visible=False, border_radius=16)
    preview_empty = ft.Column(
        [
            ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, size=38, color="#667085"),
            ft.Text("选择卡面图片进行预览", size=13, color=MUTED),
            ft.Text("PNG · JPG · WebP", size=10, color="#667085"),
        ],
        spacing=6,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    preview_stack = ft.Stack(
        [
            ft.Container(content=preview_empty, alignment=ft.Alignment.CENTER),
            ft.Container(content=preview_image),
            ft.Container(
                content=ft.Text("预览", size=9, color="#FFFFFFB0", weight=ft.FontWeight.BOLD),
                bgcolor="#00000066",
                border_radius=9,
                padding=ft.Padding(8, 3, 8, 3),
                left=12,
                top=12,
            ),
        ],
        width=480,
        height=303,
    )
    preview_card = ft.Container(
        content=preview_stack,
        bgcolor="#202633",
        border=ft.Border.all(1, "#343D4F"),
        border_radius=20,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=ft.BoxShadow(blur_radius=34, color="#00000080", offset=ft.Offset(0, 14)),
    )
    preview_filename = ft.Text("尚未选择卡面图片", size=12, color=MUTED)

    # Step 1 — device
    device_dropdown = ft.Dropdown(
        label="已连接的 iPhone",
        hint_text="请连接、解锁 iPhone 并信任此电脑",
        options=[],
        expand=True,
        border=ft.OutlineInputBorder(side=ft.BorderSide(color=BORDER)),
    )
    refresh_button = ft.IconButton(
        icon=ft.Icons.REFRESH_ROUNDED,
        tooltip="刷新设备列表",
    )
    apple_support = find_apple_dll_dir()
    support_row = ft.Row(
        [
            ft.Icon(
                ft.Icons.CHECK_CIRCLE_ROUNDED if apple_support else ft.Icons.WARNING_AMBER_ROUNDED,
                size=16,
                color=SUCCESS if apple_support else "#FFB454",
            ),
            ft.Text(
                "Apple 移动设备支持已就绪"
                if apple_support
                else "应用卡面前请安装 64 位桌面版 iTunes",
                size=11,
                color=SUCCESS if apple_support else "#FFB454",
            ),
        ],
        spacing=7,
    )

    # Step 2 — card
    card_dropdown = ft.Dropdown(
        label="Wallet 卡片",
        hint_text="扫描或添加一张卡片",
        options=[ft.DropdownOption(key=c["hash"], text=_card_label(c)) for c in cards],
        value=selected_hash or None,
        expand=True,
        border=ft.OutlineInputBorder(side=ft.BorderSide(color=BORDER)),
    )
    scan_button = ft.OutlinedButton(
        content="扫描卡片",
        icon=ft.Icons.RADAR_ROUNDED,
    )
    add_button = ft.IconButton(icon=ft.Icons.ADD_ROUNDED, tooltip="手动添加卡片")
    rename_button = ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, tooltip="重命名所选卡片")
    delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, tooltip="从列表中移除")
    backup_icon = ft.Icon(ft.Icons.CLOUD_OFF_ROUNDED, size=15, color=MUTED)
    backup_text = ft.Text("尚无原始卡面备份", size=11, color=MUTED)
    backup_badge = ft.Container(
        content=ft.Row([backup_icon, backup_text], spacing=6),
        bgcolor=SURFACE_2,
        border_radius=10,
        padding=ft.Padding(9, 5, 9, 5),
    )

    # Step 3 — artwork and actions
    choose_button = ft.FilledButton(
        content="选择卡面图片",
        icon=ft.Icons.IMAGE_OUTLINED,
        style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
    )
    clear_button = ft.TextButton(content="清除", visible=False)
    clean_logo = ft.Switch(
        label="全图模式",
        value=False,
        tooltip="用透明图像替换发卡行与联名 Logo",
    )
    progress = ft.ProgressBar(value=0, color=ACCENT, bgcolor="#252C38", visible=False)
    operation_status = ft.Text("就绪", size=11, color=MUTED)
    flash_button = ft.FilledButton(
        content="应用新卡面",
        icon=ft.Icons.AUTO_AWESOME_ROUNDED,
        disabled=True,
        style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
    )
    restore_button = ft.OutlinedButton(
        content="恢复原始卡面",
        icon=ft.Icons.RESTORE_ROUNDED,
        disabled=True,
    )

    def current_backup():
        if not selected_device or not selected_hash:
            return None
        return latest_backup(selected_device.udid, selected_hash)

    def sync_controls():
        record = current_backup()
        if record:
            backup_icon.name = ft.Icons.VERIFIED_ROUNDED
            backup_icon.color = SUCCESS
            backup_text.value = f"原始卡面已备份 · {record.label}"
            backup_text.color = SUCCESS
        else:
            backup_icon.name = ft.Icons.SHIELD_OUTLINED
            backup_icon.color = MUTED
            backup_text.value = "首次修改前会自动备份原始卡面"
            backup_text.color = MUTED

        ready = bool(selected_device and selected_hash and artwork and apple_support and not busy)
        flash_button.disabled = not ready
        restore_button.disabled = not bool(record and selected_device and selected_hash and not busy)
        choose_button.disabled = busy
        scan_button.disabled = busy or not bool(selected_device)
        refresh_button.disabled = busy
        add_button.disabled = busy
        rename_button.disabled = busy or not bool(selected_hash)
        delete_button.disabled = busy or not bool(selected_hash)

    def set_busy(value: bool, message: str = ""):
        nonlocal busy
        busy = value
        progress.visible = value
        if not value:
            progress.value = 0
        if message:
            operation_status.value = message
        sync_controls()
        page.update()

    def update_progress(step: int, total: int, message: str):
        progress.value = min(1.0, step / max(1, total))
        operation_status.value = message
        page.update()

    async def refresh_devices(_=None):
        nonlocal devices, selected_device
        set_busy(True, "正在查找已信任的 iPhone…")
        try:
            devices = await get_connected_devices()
            device_dropdown.options = [
                ft.DropdownOption(key=d.udid, text=str(d)) for d in devices
            ]
            selected_device = devices[0] if devices else None
            device_dropdown.value = selected_device.udid if selected_device else None
            if selected_device:
                device_dot.bgcolor = SUCCESS
                device_summary.value = f"{selected_device.name} · iOS {selected_device.ios_version}"
                device_summary.color = TEXT
                operation_status.value = "就绪"
            else:
                device_dot.bgcolor = "#596273"
                device_summary.value = "未发现已信任的 USB iPhone"
                device_summary.color = MUTED
                operation_status.value = "请连接、解锁 iPhone 并信任此电脑"
        except Exception as exc:
            selected_device = None
            device_dot.bgcolor = DANGER
            device_summary.value = "设备服务不可用"
            show_message(str(exc), error=True)
        finally:
            set_busy(False)

    def on_device_change(e):
        nonlocal selected_device
        value = getattr(e, "data", None) or device_dropdown.value
        selected_device = next((d for d in devices if d.udid == value), None)
        if selected_device:
            device_dot.bgcolor = SUCCESS
            device_summary.value = f"{selected_device.name} · iOS {selected_device.ios_version}"
        sync_controls()
        page.update()

    def on_card_change(e):
        nonlocal selected_hash
        selected_hash = (getattr(e, "data", None) or card_dropdown.value or "").strip()
        sync_controls()
        page.update()

    async def choose_artwork(_=None):
        nonlocal artwork, artwork_name
        try:
            files = await file_picker.pick_files(
                dialog_title="选择卡面图片",
                allow_multiple=False,
                allowed_extensions=["png", "jpg", "jpeg", "webp"],
            )
            if not files or not files[0].path:
                return
            path = Path(files[0].path)
            artwork = await asyncio.to_thread(prepare_card_skin, path)
            artwork_name = path.name
            preview_image.src = "data:image/png;base64," + base64.b64encode(artwork).decode()
            preview_image.visible = True
            preview_empty.visible = False
            preview_filename.value = artwork_name
            preview_filename.color = TEXT
            clear_button.visible = True
            sync_controls()
            page.update()
        except Exception as exc:
            show_message(f"无法载入卡面图片：{exc}", error=True)

    def clear_artwork(_=None):
        nonlocal artwork, artwork_name
        artwork = None
        artwork_name = ""
        preview_image.src = ""
        preview_image.visible = False
        preview_empty.visible = True
        preview_filename.value = "尚未选择卡面图片"
        preview_filename.color = MUTED
        clear_button.visible = False
        sync_controls()
        page.update()

    def refresh_card_options(value: str | None = None):
        card_dropdown.options = [
            ft.DropdownOption(key=c["hash"], text=_card_label(c)) for c in cards
        ]
        card_dropdown.value = value

    def open_card_editor(*, rename: bool = False):
        nonlocal cards, selected_hash
        selected = next((c for c in cards if c["hash"] == selected_hash), None)
        hash_field = ft.TextField(
            label="卡片哈希",
            value=selected_hash if rename else "",
            disabled=rename,
            autofocus=not rename,
        )
        name_field = ft.TextField(
            label="显示名称",
            value=(selected or {}).get("name", "") if rename else "",
            autofocus=rename,
        )

        def save(_):
            nonlocal cards, selected_hash
            value = (hash_field.value or "").strip()
            name = (name_field.value or "").strip() or "Wallet 卡片"
            if len(value) < 20:
                show_message("卡片哈希长度不足，请检查后重试", error=True)
                return
            existing = next((c for c in cards if c["hash"] == value), None)
            if existing:
                existing["name"] = name
            else:
                cards.append({"hash": value, "name": name})
            selected_hash = value
            save_cards_metadata(cards)
            refresh_card_options(value)
            dialog.open = False
            sync_controls()
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("重命名卡片" if rename else "添加 Wallet 卡片"),
            content=ft.Column([hash_field, name_field], tight=True, width=430),
            actions=[
                ft.TextButton("取消", on_click=lambda _: close_dialog(dialog)),
                ft.FilledButton("保存", on_click=save),
            ],
        )
        page.show_dialog(dialog)

    def close_dialog(dialog):
        dialog.open = False
        page.update()

    def delete_card(_=None):
        nonlocal cards, selected_hash
        if not selected_hash:
            return
        selected = next((c for c in cards if c["hash"] == selected_hash), None)

        def confirm(_):
            nonlocal cards, selected_hash
            cards = [c for c in cards if c["hash"] != selected_hash]
            save_cards_metadata(cards)
            selected_hash = cards[0]["hash"] if cards else ""
            refresh_card_options(selected_hash or None)
            close_dialog(dialog)
            sync_controls()
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("移除已保存的卡片？"),
            content=ft.Text(
                f"此操作只会从 AirCard 列表中移除“{(selected or {}).get('name', '该卡片')}”。"
                "不会从 Apple Wallet 删除卡片，也不会删除其原始备份。"
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _: close_dialog(dialog)),
                ft.FilledButton("移除", on_click=confirm),
            ],
        )
        page.show_dialog(dialog)

    async def scan_wallet(_=None):
        nonlocal scan_stop, cards, selected_hash
        if not selected_device:
            return
        scan_stop = asyncio.Event()
        scan_text = ft.Text(
            "请在 iPhone 上打开 Wallet，完成验证后点选目标卡片。",
            color=MUTED,
            size=13,
        )
        ring = ft.ProgressRing(width=28, height=28, stroke_width=3, color=ACCENT)

        def cancel(_):
            if scan_stop:
                scan_stop.set()
            close_dialog(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("扫描 Wallet 卡片"),
            content=ft.Row([ring, scan_text], spacing=14, width=470),
            actions=[ft.TextButton("取消", on_click=cancel)],
        )
        page.show_dialog(dialog)

        def found(card_hash: str, _count: int, name: str = ""):
            nonlocal cards, selected_hash
            cards = load_saved_cards_metadata()
            selected_hash = card_hash
            refresh_card_options(card_hash)
            scan_text.value = f"已找到：{name or 'Wallet 卡片'}"
            scan_text.color = SUCCESS
            ring.visible = False
            dialog.actions = [ft.FilledButton("完成", on_click=lambda _: close_dialog(dialog))]
            sync_controls()
            page.update()

        try:
            await start_card_scan_session(
                selected_device.udid,
                on_card_found=found,
                stop_event=scan_stop,
            )
        except Exception as exc:
            close_dialog(dialog)
            show_message(f"卡片扫描失败：{exc}", error=True)

    def thread_safe_progress(loop):
        def callback(step: int, total: int, message: str):
            loop.call_soon_threadsafe(update_progress, step, total, message)
        return callback

    async def apply_skin(_=None):
        if not selected_device or not selected_hash or not artwork:
            return
        set_busy(True, "正在准备安全备份…")
        loop = asyncio.get_running_loop()
        try:
            await flash_card_skin_async(
                selected_device.udid,
                selected_hash,
                artwork,
                clean_logo=bool(clean_logo.value),
                progress_callback=thread_safe_progress(loop),
                auto_backup=True,
                device_name=selected_device.name,
                ios_version=selected_device.ios_version,
            )
            operation_status.value = "新卡面已成功应用"
            show_message("卡面已更新。请强制关闭 Wallet 后重新打开。")
        except Exception as exc:
            operation_status.value = "卡面更新失败"
            message = str(exc)
            try:
                ios_major = int(selected_device.ios_version.split(".", 1)[0])
            except (AttributeError, TypeError, ValueError):
                ios_major = 0
            if ios_major and ios_major < 18:
                message = (
                    f"当前设备为 iOS {selected_device.ios_version}；"
                    "上游 AirCard 声明支持 iOS 18 及以上，此版本可能不兼容。\n"
                    + message
                )
            show_message(message, error=True)
        finally:
            set_busy(False)

    async def restore_original(_=None):
        if not selected_device or not selected_hash:
            return
        record = current_backup()
        if not record:
            show_message("此卡片没有可用的原始卡面备份", error=True)
            return
        set_busy(True, "正在恢复原始卡面…")
        loop = asyncio.get_running_loop()
        try:
            await restore_original_card_async(
                selected_device.udid,
                selected_hash,
                backup=record,
                verify=True,
                progress_callback=thread_safe_progress(loop),
            )
            operation_status.value = "原始卡面已恢复"
            show_message("原始卡面已恢复并通过校验。")
        except Exception as exc:
            operation_status.value = "恢复失败"
            show_message(str(exc), error=True)
        finally:
            set_busy(False)

    refresh_button.on_click = lambda _: asyncio.create_task(refresh_devices())
    device_dropdown.on_select = on_device_change
    device_dropdown.on_change = on_device_change
    card_dropdown.on_select = on_card_change
    card_dropdown.on_change = on_card_change
    choose_button.on_click = lambda _: asyncio.create_task(choose_artwork())
    clear_button.on_click = clear_artwork
    add_button.on_click = lambda _: open_card_editor()
    rename_button.on_click = lambda _: open_card_editor(rename=True)
    delete_button.on_click = delete_card
    scan_button.on_click = lambda _: asyncio.create_task(scan_wallet())
    flash_button.on_click = lambda _: asyncio.create_task(apply_skin())
    restore_button.on_click = lambda _: asyncio.create_task(restore_original())

    preview_column = ft.Column(
        [
            ft.Text("卡面预览", size=10, color=MUTED, weight=ft.FontWeight.BOLD),
            ft.Container(height=8),
            preview_card,
            ft.Row(
                [
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, size=15, color=MUTED),
                    preview_filename,
                    ft.Container(expand=True),
                    clear_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=10),
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.SHIELD_ROUNDED, color=SUCCESS, size=18),
                        ft.Column(
                            [
                                ft.Text("优先保障可恢复", size=12, color=TEXT, weight=ft.FontWeight.W_600),
                                ft.Text(
                                    "首次修改前会先在本机保存原始卡面资源。",
                                    size=10,
                                    color=MUTED,
                                ),
                            ],
                            spacing=1,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor="#102B24",
                border=ft.Border.all(1, "#1F5A48"),
                border_radius=13,
                padding=13,
            ),
        ],
        spacing=10,
    )

    workflow = ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_title("1", "连接 iPhone", "USB 连接 · 已解锁 · 已信任"),
                        ft.Row([device_dropdown, refresh_button], spacing=7),
                        support_row,
                    ],
                    spacing=13,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_title("2", "选择 Wallet 卡片", "在设备上扫描，或手动添加卡片哈希"),
                        ft.Row([card_dropdown, scan_button], spacing=9),
                        ft.Row([backup_badge, ft.Container(expand=True), add_button, rename_button, delete_button]),
                    ],
                    spacing=13,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_title("3", "应用卡面", "建议图片尺寸：1536 × 969"),
                        ft.Row([choose_button, clean_logo], spacing=14),
                        progress,
                        operation_status,
                        ft.Row([flash_button, restore_button], spacing=10),
                    ],
                    spacing=13,
                )
            ),
        ],
        spacing=12,
        expand=True,
    )

    body = ft.Container(
        content=ft.Row(
            [
                ft.Container(content=preview_column, width=500),
                ft.VerticalDivider(width=1, color=BORDER),
                workflow,
            ],
            spacing=24,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=ft.Padding(26, 12, 26, 24),
        expand=True,
    )
    page.add(ft.Column([header, body], spacing=0, expand=True))
    sync_controls()
    await refresh_devices()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    ft.run(main)
