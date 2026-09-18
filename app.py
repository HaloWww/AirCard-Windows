"""
AirCard for Windows - Modern GUI
A native desktop interface for flashing custom Apple Wallet card skins on Windows.
"""
import asyncio
import base64
import io
from pathlib import Path
import sys
from typing import Optional

# Prevent crashes when running without console under pythonw
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import flet as ft

from aircard.config import CARDS_STORE_PATH, TARGET_SIZE, find_apple_dll_dir
from aircard.core_flasher import flash_card_skin_async
from aircard.device import ConnectedDevice, get_connected_devices
from aircard.image_util import prepare_card_skin
from aircard.scanner import (
    load_saved_cards_metadata,
    save_cards_metadata,
    start_card_scan_session,
)




async def main(page: ft.Page):
    # Window configuration
    page.title = "AirCard for Windows"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1040
    page.window.height = 740
    page.window.min_width = 900
    page.window.min_height = 640
    page.window.resizable = True
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    page.bgcolor = "#121214"

    # Application state
    connected_devices: list[ConnectedDevice] = []
    selected_device: Optional[ConnectedDevice] = None
    saved_cards: list[dict[str, str]] = load_saved_cards_metadata()
    selected_card_hash: Optional[str] = saved_cards[0]["hash"] if saved_cards else None
    current_skin_bytes: Optional[bytes] = None
    current_skin_name: Optional[str] = None
    scan_task: Optional[asyncio.Task] = None
    scan_stop_event: Optional[asyncio.Event] = None

    # File picker setup (Service control in modern Flet)
    file_picker = ft.FilePicker()
    if hasattr(page, "services"):
        page.services.append(file_picker)
    elif hasattr(page, "_services"):
        page._services.append(file_picker)
    else:
        page.overlay.append(file_picker)

    # UI Components - Header
    app_icon = ft.Icon(ft.Icons.PAYMENT_ROUNDED, size=28, color="#0A84FF")
    app_title = ft.Text("AirCard", size=22, weight=ft.FontWeight.BOLD, color="#F5F5F7")
    app_badge = ft.Container(
        content=ft.Text("Windows Edition", size=11, weight=ft.FontWeight.W_600, color="#0A84FF"),
        bgcolor="#0A84FF1E",
        padding=ft.Padding(8, 3, 8, 3),
        border_radius=12,
    )

    device_status_icon = ft.Icon(ft.Icons.PHONE_IPHONE_ROUNDED, size=18, color="#8E8E93")
    device_status_text = ft.Text("Searching for iPhone...", size=13, color="#8E8E93")
    device_refresh_btn = ft.IconButton(
        icon=ft.Icons.REFRESH_ROUNDED,
        icon_size=18,
        tooltip="Refresh device connection",
        on_click=lambda _: asyncio.create_task(refresh_devices()),
    )

    device_chip = ft.Container(
        content=ft.Row(
            [device_status_icon, device_status_text, device_refresh_btn],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        bgcolor="#1C1C1E",
        border=ft.Border.all(1, "#2C2C2E"),
        border_radius=20,
        padding=ft.Padding(12, 4, 8, 4),
    )

    header = ft.Row(
        [
            ft.Row([app_icon, app_title, app_badge], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            device_chip,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # Notice banner for iTunes DLLs if needed
    dll_dir = find_apple_dll_dir()
    itunes_warning = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color="#FF9F0A", size=20),
                ft.Text(
                    "Apple Mobile Device Support not found. Please install iTunes from Apple to enable flashing.",
                    size=13,
                    color="#FFD60A",
                    expand=True,
                ),
            ],
            spacing=10,
        ),
        bgcolor="#FF9F0A1A",
        border=ft.Border.all(1, "#FF9F0A44"),
        border_radius=10,
        padding=ft.Padding(14, 10, 14, 10),
        visible=dll_dir is None,
    )

    # 1. Card Selection Controls
    def format_card_label(card_meta: dict[str, str]) -> str:
        h = card_meta.get("hash", "")
        name = card_meta.get("name") or "Card"
        short_hash = f"{h[:6]}...{h[-4:]}" if len(h) > 12 else h
        return f"{name}  ({short_hash})"

    card_dropdown = ft.Dropdown(
        label="Target Apple Pay Card",
        hint_text="Select a card to customize",
        options=[
            ft.DropdownOption(key=c["hash"], text=format_card_label(c))
            for c in saved_cards
        ],
        value=selected_card_hash,
        expand=True,
        border=ft.OutlineInputBorder(border_radius=10),
        bgcolor="#1C1C1E",
    )

    def on_card_selected(e):
        nonlocal selected_card_hash
        val = getattr(e, "data", None) or card_dropdown.value
        selected_card_hash = val
        card_dropdown.value = val
        update_flash_button_state()
        page.update()

    card_dropdown.on_select = on_card_selected
    card_dropdown.on_change = on_card_selected

    scan_button = ft.FilledTonalButton(
        content="Scan via iPhone",
        icon=ft.Icons.SENSORS_ROUNDED,
        expand=True,
        tooltip="Scan card automatically by double-clicking Side Button on iPhone",
        style=ft.ButtonStyle(bgcolor="#0A84FF22", color="#0A84FF"),
    )

    rename_card_button = ft.OutlinedButton(
        content="Rename Card",
        icon=ft.Icons.EDIT_ROUNDED,
        expand=True,
        tooltip="Rename currently selected card",
        style=ft.ButtonStyle(color="#E5E5EA"),
        disabled=selected_card_hash is None,
    )

    manual_hash_button = ft.OutlinedButton(
        content="Add Hash",
        icon=ft.Icons.ADD_ROUNDED,
        expand=True,
        tooltip="Enter 27-character base64 card hash manually",
        style=ft.ButtonStyle(color="#E5E5EA"),
    )

    delete_card_button = ft.OutlinedButton(
        content="Delete Card",
        icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
        icon_color="#FF453A",
        expand=True,
        tooltip="Delete currently selected card from list",
        style=ft.ButtonStyle(color="#FF453A"),
        disabled=selected_card_hash is None,
    )

    card_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CREDIT_CARD_ROUNDED, size=18, color="#0A84FF"),
                        ft.Text("1. Target Card", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                    ],
                    spacing=8,
                ),
                ft.Text(
                    "Choose an Apple Pay card to restyle, or scan it directly from your device.",
                    size=12,
                    color="#8E8E93",
                ),
                card_dropdown,
                ft.Row([scan_button, rename_card_button], spacing=8),
                ft.Row([manual_hash_button, delete_card_button], spacing=8),
            ],
            spacing=10,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    # 2. Skin Selection Controls
    skin_info_text = ft.Text(
        "No skin loaded (1536 × 969 PNG recommended)",
        size=12,
        color="#8E8E93",
    )

    browse_file_button = ft.FilledTonalButton(
        content="Browse File...",
        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
        expand=True,
    )

    paste_clipboard_button = ft.OutlinedButton(
        content="Paste (Ctrl+V)",
        icon=ft.Icons.CONTENT_PASTE_ROUNDED,
        tooltip="Paste image or copied file from clipboard",
        style=ft.ButtonStyle(color="#E5E5EA"),
    )

    clear_skin_button = ft.OutlinedButton(
        content="Clear",
        icon=ft.Icons.CLEAR_ALL_ROUNDED,
        tooltip="Clear loaded skin preview",
        style=ft.ButtonStyle(color="#FF453A"),
        disabled=True,
    )

    skin_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.IMAGE_OUTLINED, size=18, color="#30D158"),
                        ft.Text("2. Card Skin Artwork", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                    ],
                    spacing=8,
                ),
                ft.Text(
                    "Click the preview card, browse files, or press Ctrl+V to paste.",
                    size=12,
                    color="#8E8E93",
                ),
                skin_info_text,
                ft.Row([browse_file_button, paste_clipboard_button, clear_skin_button], spacing=8),
            ],
            spacing=12,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    # Card Mockup Preview (Right Column)
    preview_placeholder = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, size=46, color="#636366"),
                ft.Text("Live Card Preview", size=15, weight=ft.FontWeight.W_600, color="#E5E5EA"),
                ft.Text("Click card to choose file or press Ctrl+V", size=12, color="#8E8E93"),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=6,
        ),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )

    card_image_view = ft.Image(
        src="",
        fit=ft.BoxFit.COVER,
        width=390,
        height=246,
        border_radius=16,
        visible=False,
    )

    clear_badge_btn = ft.Container(
        content=ft.IconButton(
            icon=ft.Icons.CLOSE_ROUNDED,
            icon_color="#FFFFFF",
            icon_size=15,
            tooltip="Clear skin",
        ),
        bgcolor="#000000B0",
        border_radius=16,
        width=30,
        height=30,
        alignment=ft.Alignment.CENTER,
        top=10,
        right=10,
        visible=False,
    )

    card_mockup_container = ft.Container(
        content=ft.Stack(
            [
                preview_placeholder,
                card_image_view,
                # Subtle border & shine overlay
                ft.Container(
                    border=ft.Border.all(1, "#FFFFFF1A"),
                    border_radius=16,
                    expand=True,
                ),
                clear_badge_btn,
            ]
        ),
        width=390,
        height=246,
        bgcolor="#161618",
        border=ft.Border.all(1, "#27272A"),
        border_radius=16,
        shadow=ft.BoxShadow(
            spread_radius=1,
            blur_radius=30,
            color="#000000B0",
            offset=ft.Offset(0, 14),
        ),
        alignment=ft.Alignment.CENTER,
        ink=True,
        tooltip="Click to select skin image or paste with Ctrl+V",
    )

    clear_header_btn = ft.TextButton(
        content="Clear Skin",
        icon=ft.Icons.CLEAR_ROUNDED,
        icon_color="#FF453A",
        style=ft.ButtonStyle(color="#FF453A"),
        visible=False,
    )

    # Progress & Status View
    flash_progress_bar = ft.ProgressBar(
        value=0,
        color="#0A84FF",
        bgcolor="#2C2C2E",
        visible=False,
        border_radius=4,
    )
    status_label = ft.Text(
        "Ready to flash",
        size=13,
        color="#8E8E93",
        text_align=ft.TextAlign.CENTER,
    )

    flash_button = ft.FilledButton(
        content="Flash Skin to iPhone",
        icon=ft.Icons.BOLT_ROUNDED,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: "#0A84FF",
                ft.ControlState.DISABLED: "#2C2C2E",
            },
            color={
                ft.ControlState.DEFAULT: "#FFFFFF",
                ft.ControlState.DISABLED: "#636366",
            },
        ),
        height=48,
        disabled=True,
        expand=True,
    )

    action_section = ft.Container(
        content=ft.Column(
            [
                flash_progress_bar,
                status_label,
                ft.Row([flash_button]),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    # Layout Assembly
    left_column = ft.Column(
        [card_section, skin_section],
        spacing=16,
        expand=5,
    )

    right_column = ft.Column(
        [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.VISIBILITY_OUTLINED, size=18, color="#BF5AF2"),
                                        ft.Text("Preview & Deploy", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                                    ],
                                    spacing=8,
                                ),
                                clear_header_btn,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(content=card_mockup_container, alignment=ft.Alignment.CENTER, padding=10),
                        action_section,
                    ],
                    spacing=14,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor="#18181B",
                border=ft.Border.all(1, "#27272A"),
                border_radius=14,
                padding=18,
            )
        ],
        spacing=16,
        expand=6,
    )

    body = ft.Row(
        [left_column, right_column],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    page.add(
        ft.Column(
            [header, itunes_warning, body],
            spacing=16,
            expand=True,
        )
    )

    # Business Logic Helpers
    def update_flash_button_state():
        can_flash = (
            selected_device is not None
            and selected_card_hash is not None
            and current_skin_bytes is not None
            and dll_dir is not None
        )
        flash_button.disabled = not can_flash
        rename_card_button.disabled = selected_card_hash is None
        delete_card_button.disabled = selected_card_hash is None
        if not selected_device:
            status_label.value = "Connect iPhone via USB to enable flashing"
            status_label.color = "#8E8E93"
        elif not selected_card_hash:
            status_label.value = "Scan or select a target card"
            status_label.color = "#8E8E93"
        elif not current_skin_bytes:
            status_label.value = "Select or load a card skin image"
            status_label.color = "#8E8E93"
        elif dll_dir is None:
            status_label.value = "Apple Mobile Device Support required"
            status_label.color = "#FF9F0A"
        else:
            status_label.value = "Ready to flash skin to iPhone"
            status_label.color = "#30D158"

    async def refresh_devices():
        nonlocal connected_devices, selected_device
        device_status_icon.name = ft.Icons.HOURGLASS_EMPTY_ROUNDED
        device_status_icon.color = "#8E8E93"
        device_status_text.value = "Checking USB devices..."
        device_status_text.color = "#8E8E93"
        page.update()

        try:
            connected_devices = await get_connected_devices()
            if connected_devices:
                selected_device = connected_devices[0]
                device_status_icon.name = ft.Icons.CHECK_CIRCLE_ROUNDED
                device_status_icon.color = "#30D158"
                device_status_text.value = f"{selected_device.name} (iOS {selected_device.ios_version})"
                device_status_text.color = "#F5F5F7"
            else:
                selected_device = None
                device_status_icon.name = ft.Icons.LINK_OFF_ROUNDED
                device_status_icon.color = "#FF9F0A"
                device_status_text.value = "No iPhone detected via USB"
                device_status_text.color = "#FF9F0A"
        except Exception as err:
            selected_device = None
            device_status_icon.name = ft.Icons.ERROR_OUTLINE_ROUNDED
            device_status_icon.color = "#FF453A"
            device_status_text.value = f"Device error: {err}"
            device_status_text.color = "#FF453A"

        update_flash_button_state()
        page.update()

    # Helper snackbar
    def show_snack(message: str, is_error: bool = False):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message, color="#FFFFFF"),
                bgcolor="#FF453A" if is_error else "#1C1C1E",
            )
        )

    ignoring_mockup_click = False

    def set_skin_from_bytes(data: bytes, source_name: str):
        nonlocal current_skin_bytes, current_skin_name
        current_skin_bytes = data
        current_skin_name = source_name

        b64 = base64.b64encode(data).decode("ascii")
        card_image_view.src = f"data:image/png;base64,{b64}"
        card_image_view.visible = True
        preview_placeholder.visible = False
        clear_badge_btn.visible = True
        clear_header_btn.visible = True
        clear_skin_button.disabled = False

        size_kb = len(data) / 1024
        skin_info_text.value = f"✓ Loaded {source_name} ({size_kb:.1f} KB, 1536 × 969)"
        skin_info_text.color = "#30D158"

        update_flash_button_state()
        page.update()

    def handle_clear_skin(e=None):
        nonlocal current_skin_bytes, current_skin_name, ignoring_mockup_click
        ignoring_mockup_click = True
        current_skin_bytes = None
        current_skin_name = None

        card_image_view.visible = False
        card_image_view.src = ""
        preview_placeholder.visible = True
        clear_badge_btn.visible = False
        clear_header_btn.visible = False
        clear_skin_button.disabled = True

        skin_info_text.value = "No skin loaded (1536 × 969 PNG recommended)"
        skin_info_text.color = "#8E8E93"

        update_flash_button_state()
        page.update()
        show_snack("Card preview cleared.")

    clear_skin_button.on_click = handle_clear_skin
    clear_header_btn.on_click = handle_clear_skin
    clear_badge_btn.content.on_click = handle_clear_skin

    def handle_paste_clipboard(e=None):
        try:
            from PIL import ImageGrab, Image
            cb_data = ImageGrab.grabclipboard()
            if isinstance(cb_data, Image.Image):
                processed_bytes = prepare_card_skin(cb_data)
                set_skin_from_bytes(processed_bytes, "Pasted Image")
                show_snack("✓ Pasted image from clipboard")
                return True
            elif isinstance(cb_data, list):
                img_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
                for item in cb_data:
                    p = Path(item)
                    if p.suffix.lower() in img_exts and p.is_file():
                        processed_bytes = prepare_card_skin(p)
                        set_skin_from_bytes(processed_bytes, p.name)
                        show_snack(f"✓ Loaded {p.name} from clipboard")
                        return True
                show_snack("No image file found in clipboard.", is_error=True)
                return False
            else:
                show_snack("Clipboard does not contain an image or copied image file.", is_error=True)
                return False
        except Exception as ex:
            show_snack(f"Failed to paste from clipboard: {ex}", is_error=True)
            return False

    paste_clipboard_button.on_click = lambda _: handle_paste_clipboard()

    async def handle_browse_file(e=None):
        try:
            files = await file_picker.pick_files(
                dialog_title="Select Card Skin Image",
                allow_multiple=False,
                allowed_extensions=["png", "jpg", "jpeg", "webp"],
            )
            if files and len(files) > 0 and files[0].path:
                file_path = files[0].path
                processed_bytes = prepare_card_skin(file_path)
                set_skin_from_bytes(processed_bytes, Path(file_path).name)
        except Exception as ex:
            show_snack(f"Failed to load image: {ex}", is_error=True)

    browse_file_button.on_click = lambda e: asyncio.create_task(handle_browse_file(e))

    async def handle_mockup_click(e):
        nonlocal ignoring_mockup_click
        if ignoring_mockup_click:
            ignoring_mockup_click = False
            return
        await handle_browse_file(e)

    card_mockup_container.on_click = lambda e: asyncio.create_task(handle_mockup_click(e))

    def handle_mockup_hover(e):
        card_mockup_container.border = ft.Border.all(1.5, "#0A84FF") if e.data == "true" else ft.Border.all(1, "#27272A")
        page.update()

    card_mockup_container.on_hover = handle_mockup_hover

    def on_keyboard(e: ft.KeyboardEvent):
        if e.key.upper() == "V" and (e.ctrl or e.meta):
            handle_paste_clipboard()

    page.on_keyboard_event = on_keyboard

    # Card Scanning Dialog with Mini Log
    scan_dialog_ring = ft.ProgressRing(stroke_width=3, color="#0A84FF", width=28, height=28)
    scan_dialog_icon = ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color="#30D158", size=32, visible=False)
    scan_dialog_text = ft.Text(
        "Open Wallet on iPhone and tap your card to scan...",
        size=13,
        color="#8E8E93",
    )
    scan_log_column = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO)
    scan_log_box = ft.Container(
        content=scan_log_column,
        bgcolor="#121214",
        border=ft.Border.all(1, "#27272A"),
        border_radius=8,
        padding=8,
        width=420,
        height=95,
    )

    def add_scan_log(text: str, color: str = "#8E8E93"):
        scan_log_column.controls.append(
            ft.Text(text, size=11, color=color, font_family="Consolas, monospace")
        )
        page.update()

    def cancel_scan(e):
        nonlocal scan_stop_event
        if scan_stop_event:
            scan_stop_event.set()
        page.pop_dialog()

    scan_dialog_action_btn = ft.TextButton("Cancel", on_click=cancel_scan)

    scan_dialog = ft.AlertDialog(
        title=ft.Row(
            [
                ft.Icon(ft.Icons.SENSORS_ROUNDED, color="#0A84FF"),
                ft.Text("Listening for Apple Pay Card..."),
            ],
            spacing=8,
        ),
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            scan_dialog_ring,
                            scan_dialog_icon,
                            ft.Container(content=scan_dialog_text, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                    ),
                    scan_log_box,
                ],
                spacing=12,
            ),
            width=420,
            height=160,
        ),
        actions=[
            scan_dialog_action_btn,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    async def run_scan_session():
        nonlocal scan_stop_event, selected_card_hash, saved_cards
        if not selected_device:
            show_snack("Please connect an iPhone via USB before scanning.", is_error=True)
            return

        scan_stop_event = asyncio.Event()

        # Reset dialog visuals
        scan_log_column.controls.clear()
        scan_dialog_ring.visible = True
        scan_dialog_icon.visible = False
        scan_dialog_text.value = "Open Wallet on iPhone and tap your card..."
        scan_dialog_action_btn.text = "Cancel"
        scan_dialog_action_btn.style = ft.ButtonStyle(color="#8E8E93")

        add_scan_log(f"Connected to {selected_device.name}", "#8E8E93")
        add_scan_log("Waiting for card tap in Apple Wallet...", "#0A84FF")

        page.show_dialog(scan_dialog)

        def on_found(card_hash: str, total: int, card_name: str = ""):
            nonlocal selected_card_hash, saved_cards
            existing = next((c for c in saved_cards if c["hash"] == card_hash), None)
            if not existing:
                name = card_name or f"Card {len(saved_cards) + 1}"
                saved_cards.append({"hash": card_hash, "name": name})
                save_cards_metadata(saved_cards)
            else:
                name = existing.get("name") or f"Card {len(saved_cards)}"

            selected_card_hash = card_hash
            card_dropdown.options = [
                ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards
            ]
            card_dropdown.value = card_hash
            update_flash_button_state()

            # Update live mini log
            add_scan_log(f"✅ Card detected: {name}!", "#30D158")
            add_scan_log(f"   Hash: {card_hash[:10]}...{card_hash[-6:]}", "#30D158")
            add_scan_log("✓ Saved and selected for flashing", "#30D158")

            # Update dialog header status
            scan_dialog_ring.visible = False
            scan_dialog_icon.visible = True
            scan_dialog_text.value = f"Found: {name}"
            scan_dialog_action_btn.text = "Done"
            scan_dialog_action_btn.style = ft.ButtonStyle(color="#30D158")
            page.update()

            # Auto close after 1.2s if dialog still open
            async def auto_close():
                await asyncio.sleep(1.2)
                if scan_dialog.open:
                    page.pop_dialog()
                    page.update()
            asyncio.create_task(auto_close())

        loop = asyncio.get_running_loop()

        def sync_found_callback(card_hash: str, total: int, card_name: str = ""):
            loop.call_soon_threadsafe(on_found, card_hash, total, card_name)
            if scan_stop_event:
                scan_stop_event.set()

        try:
            detected = await start_card_scan_session(
                udid=selected_device.udid,
                on_card_found=sync_found_callback,
                stop_event=scan_stop_event,
            )
        except Exception as ex:
            if scan_dialog.open:
                page.pop_dialog()
            show_snack(f"Scan interrupted: {ex}", is_error=True)

    scan_button.on_click = lambda _: asyncio.create_task(run_scan_session())

    # Rename Card Dialog
    rename_input_field = ft.TextField(
        label="Card Name",
        hint_text="e.g. Bybit Mastercard, Monobank, Chase",
        autofocus=True,
        border=ft.OutlineInputBorder(border_radius=8),
    )

    def handle_rename_click(e):
        nonlocal selected_card_hash, saved_cards
        if card_dropdown.value:
            selected_card_hash = card_dropdown.value
        if not selected_card_hash:
            return

        cur_card = next((c for c in saved_cards if c["hash"] == selected_card_hash), None)
        if not cur_card:
            return

        rename_input_field.value = cur_card.get("name", "")

        def submit_rename(ev):
            new_name = rename_input_field.value.strip() or "Card"
            cur_card["name"] = new_name
            save_cards_metadata(saved_cards)
            card_dropdown.options = [
                ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards
            ]
            card_dropdown.value = cur_card["hash"]
            page.pop_dialog()
            page.update()
            show_snack(f"Card renamed to \"{new_name}\"")

        rename_dialog = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.EDIT_ROUNDED, color="#0A84FF"),
                    ft.Text("Rename Card"),
                ],
                spacing=8,
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            f"Card hash: {selected_card_hash[:8]}...{selected_card_hash[-6:]}",
                            size=12,
                            color="#8E8E93",
                        ),
                        rename_input_field,
                    ],
                    spacing=12,
                ),
                width=380,
                height=110,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: page.pop_dialog()),
                ft.FilledButton("Save", on_click=submit_rename),
            ],
        )
        page.show_dialog(rename_dialog)

    rename_card_button.on_click = handle_rename_click

    # Manual Card Hash Dialog
    hash_input_field = ft.TextField(
        label="Card Hash",
        hint_text="Paste 27-char base64 hash...",
        autofocus=True,
        border=ft.OutlineInputBorder(border_radius=8),
    )
    name_input_field = ft.TextField(
        label="Card Name (Optional)",
        hint_text="e.g. Bybit, Monobank, Chase",
        border=ft.OutlineInputBorder(border_radius=8),
    )

    def submit_manual_hash(e):
        nonlocal selected_card_hash, saved_cards
        val = hash_input_field.value.strip().strip("'\"")
        name_val = name_input_field.value.strip()
        if not val or len(val) < 20:
            show_snack("Invalid card hash format (expected 20+ chars).", is_error=True)
            return

        existing = next((c for c in saved_cards if c["hash"] == val), None)
        if existing:
            if name_val:
                existing["name"] = name_val
        else:
            saved_cards.append({
                "hash": val,
                "name": name_val or f"Card {len(saved_cards) + 1}",
            })
        save_cards_metadata(saved_cards)

        selected_card_hash = val
        card_dropdown.options = [
            ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards
        ]
        card_dropdown.value = val
        page.pop_dialog()
        hash_input_field.value = ""
        name_input_field.value = ""
        update_flash_button_state()
        page.update()
        show_snack(f"Saved card {name_val or val[:8]}...")

    manual_hash_dialog = ft.AlertDialog(
        title=ft.Text("Add Card Manually"),
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Enter the base64 card hash and an optional friendly name.",
                        size=13,
                        color="#8E8E93",
                    ),
                    hash_input_field,
                    name_input_field,
                ],
                spacing=10,
            ),
            width=380,
            height=160,
        ),
        actions=[
            ft.TextButton("Cancel", on_click=lambda _: page.pop_dialog()),
            ft.FilledButton("Add Card", on_click=submit_manual_hash),
        ],
    )

    manual_hash_button.on_click = lambda _: page.show_dialog(manual_hash_dialog)

    # Delete selected card handler
    def handle_delete_card(e):
        nonlocal saved_cards, selected_card_hash
        if card_dropdown.value:
            selected_card_hash = card_dropdown.value
        if not selected_card_hash:
            return

        target_hash = selected_card_hash
        target_meta = next((c for c in saved_cards if c["hash"] == target_hash), None)
        saved_cards = [c for c in saved_cards if c["hash"] != target_hash]
        save_cards_metadata(saved_cards)

        selected_card_hash = saved_cards[0]["hash"] if saved_cards else None
        card_dropdown.options = [
            ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards
        ]
        card_dropdown.value = selected_card_hash
        update_flash_button_state()
        page.update()

        name = target_meta.get("name") if target_meta else "Card"
        show_snack(f"Removed \"{name}\" from list.")

    delete_card_button.on_click = handle_delete_card

    # Flashing logic
    async def perform_flash():
        nonlocal selected_card_hash
        if card_dropdown.value:
            selected_card_hash = card_dropdown.value
        if not selected_device or not selected_card_hash or not current_skin_bytes:
            return

        flash_button.disabled = True
        flash_progress_bar.visible = True
        flash_progress_bar.value = 0
        status_label.color = "#0A84FF"
        status_label.value = "Preparing payload..."
        page.update()

        def progress_cb(cur: int, tot: int, step_desc: str):
            flash_progress_bar.value = cur / tot
            status_label.value = f"[{cur}/{tot}] {step_desc}"
            page.update()

        try:
            ok = await flash_card_skin_async(
                udid=selected_device.udid,
                card_hash=selected_card_hash,
                skin_png_bytes=current_skin_bytes,
                progress_callback=progress_cb,
            )

            if ok:
                status_label.value = "✓ Card skin flashed successfully!"
                status_label.color = "#30D158"
                page.update()

                page.show_dialog(
                    ft.AlertDialog(
                        title=ft.Row(
                            [
                                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color="#30D158"),
                                ft.Text("Card Flashed Successfully!"),
                            ],
                            spacing=8,
                        ),
                        content=ft.Text(
                            "The custom skin has been deployed to Apple Wallet.\n\n"
                            "• Open the Apple Wallet app on your iPhone.\n"
                            "• Or double-click the side button to enjoy your new card look!",
                            size=14,
                        ),
                        actions=[
                            ft.FilledButton("Done", on_click=lambda _: page.pop_dialog()),
                        ],
                    )
                )
            else:
                status_label.value = "Flashing failed. Check USB connection."
                status_label.color = "#FF453A"
                show_snack("AirTraffic asset sync returned false.", is_error=True)
        except Exception as ex:
            status_label.value = f"Error: {ex}"
            status_label.color = "#FF453A"
            show_snack(f"Flashing failed: {ex}", is_error=True)
        finally:
            flash_button.disabled = False
            flash_progress_bar.visible = False
            page.update()

    flash_button.on_click = lambda _: asyncio.create_task(perform_flash())

    # Initial device scan
    await refresh_devices()


if __name__ == "__main__":
    ft.run(main)
