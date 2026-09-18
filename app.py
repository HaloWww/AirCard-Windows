"""
AirCard for Windows - Modern GUI (Beta)
A native desktop interface for flashing custom Apple Wallet card skins,
featuring factory restore, 3D holographic foil, and Apple Cash 3D Metal studio.
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
from aircard.apple_cash import (
    flash_apple_cash_async,
    revert_apple_cash_async,
)
from aircard.device import ConnectedDevice, get_connected_devices
from aircard.image_util import prepare_card_skin, apply_holographic_foil, draw_cardholder_name
from aircard.scanner import (
    load_saved_cards_metadata,
    save_cards_metadata,
    start_card_scan_session,
)


async def main(page: ft.Page):
    # Window configuration
    page.title = "AirCard for Windows (Beta Studio)"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1060
    page.window.height = 760
    page.window.min_width = 920
    page.window.min_height = 660
    page.window.resizable = True
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    page.bgcolor = "#121214"

    # Application state
    active_tab = "bank"  # "bank" or "apple_cash"
    connected_devices: list[ConnectedDevice] = []
    selected_device: Optional[ConnectedDevice] = None

    # Cards metadata
    saved_cards: list[dict[str, str]] = load_saved_cards_metadata()
    selected_card_hash: Optional[str] = saved_cards[0]["hash"] if saved_cards else None

    # Standard bank card skin state
    bank_raw_skin_bytes: Optional[bytes] = None
    bank_active_skin_bytes: Optional[bytes] = None
    bank_skin_name: Optional[str] = None

    # Apple Cash 3D skin state
    ac_raw_skin_bytes: Optional[bytes] = None
    ac_active_skin_bytes: Optional[bytes] = None
    ac_skin_name: Optional[str] = None
    ac_metal_mode: str = "rainbow"  # "rainbow", "matte", "custom"
    ac_icon_mode: str = "apple"  # "apple", "custom", "none", "clean_all"
    ac_custom_logo_text: str = ""
    ac_custom_icon_bytes: Optional[bytes] = None
    ac_custom_icon_name: Optional[str] = None

    scan_stop_event: Optional[asyncio.Event] = None
    ignoring_mockup_click = False

    # File picker setup
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
        content=ft.Text("3D Metal Edition", size=11, weight=ft.FontWeight.W_600, color="#BF5AF2"),
        bgcolor="#BF5AF21E",
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

    # Helper snackbar
    def show_snack(message: str, is_error: bool = False):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message, color="#FFFFFF"),
                bgcolor="#FF453A" if is_error else "#1C1C1E",
            )
        )

    # ==========================================
    # Tab Switcher Navigation
    # ==========================================
    tab_bank_text = ft.Text("Standard Bank Cards", size=13, weight=ft.FontWeight.BOLD, color="#FFFFFF")
    tab_bank_icon = ft.Icon(ft.Icons.CREDIT_CARD_ROUNDED, size=18, color="#0A84FF")
    tab_bank_btn = ft.Container(
        content=ft.Row([tab_bank_icon, tab_bank_text], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        bgcolor="#0A84FF2E",
        border=ft.Border.all(1, "#0A84FF88"),
        border_radius=10,
        padding=ft.Padding(20, 10, 20, 10),
        ink=True,
    )

    tab_ac_text = ft.Text("Apple Cash 3D Studio", size=13, weight=ft.FontWeight.W_500, color="#8E8E93")
    tab_ac_icon = ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=18, color="#8E8E93")
    tab_ac_btn = ft.Container(
        content=ft.Row([tab_ac_icon, tab_ac_text], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=10,
        padding=ft.Padding(20, 10, 20, 10),
        ink=True,
    )

    tab_bar = ft.Container(
        content=ft.Row([tab_bank_btn, tab_ac_btn], spacing=10),
        bgcolor="#161618",
        border=ft.Border.all(1, "#27272A"),
        border_radius=12,
        padding=6,
    )

    def switch_to_tab(tab_name: str):
        nonlocal active_tab
        active_tab = tab_name
        if tab_name == "bank":
            tab_bank_btn.bgcolor = "#0A84FF2E"
            tab_bank_btn.border = ft.Border.all(1, "#0A84FF88")
            tab_bank_text.color = "#FFFFFF"
            tab_bank_text.weight = ft.FontWeight.BOLD
            tab_bank_icon.color = "#0A84FF"

            tab_ac_btn.bgcolor = "#18181B"
            tab_ac_btn.border = ft.Border.all(1, "#27272A")
            tab_ac_text.color = "#8E8E93"
            tab_ac_text.weight = ft.FontWeight.W_500
            tab_ac_icon.color = "#8E8E93"

            bank_view.visible = True
            apple_cash_view.visible = False
        else:
            tab_ac_btn.bgcolor = "#BF5AF22E"
            tab_ac_btn.border = ft.Border.all(1, "#BF5AF288")
            tab_ac_text.color = "#FFFFFF"
            tab_ac_text.weight = ft.FontWeight.BOLD
            tab_ac_icon.color = "#BF5AF2"

            tab_bank_btn.bgcolor = "#18181B"
            tab_bank_btn.border = ft.Border.all(1, "#27272A")
            tab_bank_text.color = "#8E8E93"
            tab_bank_text.weight = ft.FontWeight.W_500
            tab_bank_icon.color = "#8E8E93"

            bank_view.visible = False
            apple_cash_view.visible = True
        page.update()

    tab_bank_btn.on_click = lambda _: switch_to_tab("bank")
    tab_ac_btn.on_click = lambda _: switch_to_tab("apple_cash")

    # ==========================================
    # TAB 1: Standard Bank Cards View
    # ==========================================
    def format_card_label(card_meta: dict[str, str]) -> str:
        return card_meta.get("name") or "Payment Card"

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
        update_bank_ui_state()
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

    bank_skin_info_text = ft.Text(
        "No skin loaded (1536 × 969 PNG recommended)",
        size=12,
        color="#8E8E93",
    )

    bank_browse_btn = ft.FilledTonalButton(
        content="Browse File...",
        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
        expand=True,
    )

    bank_paste_btn = ft.OutlinedButton(
        content="Paste (Ctrl+V)",
        icon=ft.Icons.CONTENT_PASTE_ROUNDED,
        tooltip="Paste image or copied file from clipboard",
        style=ft.ButtonStyle(color="#E5E5EA"),
    )

    bank_clear_btn = ft.OutlinedButton(
        content="Clear",
        icon=ft.Icons.CLEAR_ALL_ROUNDED,
        tooltip="Clear loaded skin preview",
        style=ft.ButtonStyle(color="#FF453A"),
        disabled=True,
    )

    bank_skin_section = ft.Container(
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
                    "Click preview card, browse files, or press Ctrl+V to paste.",
                    size=12,
                    color="#8E8E93",
                ),
                bank_skin_info_text,
                ft.Row([bank_browse_btn, bank_paste_btn, bank_clear_btn], spacing=8),
            ],
            spacing=12,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    bank_preview_placeholder = ft.Container(
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

    bank_card_image = ft.Image(
        src="",
        fit=ft.BoxFit.COVER,
        width=390,
        height=246,
        border_radius=16,
        visible=False,
    )

    bank_clear_badge = ft.Container(
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

    bank_cardholder_label = ft.Container(
        content=ft.Text("CARDHOLDER NAME", size=10, weight=ft.FontWeight.BOLD, color="#FFFFFFE0", font_family="Consolas, monospace"),
        bottom=14,
        left=18,
        visible=False,
    )

    bank_card_mockup = ft.Container(
        content=ft.Stack(
            [
                bank_preview_placeholder,
                bank_card_image,
                bank_cardholder_label,
                ft.Container(
                    border=ft.Border.all(1, "#FFFFFF1A"),
                    border_radius=16,
                    expand=True,
                ),
                bank_clear_badge,
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

    bank_progress_bar = ft.ProgressBar(
        value=0,
        color="#0A84FF",
        bgcolor="#2C2C2E",
        visible=False,
        border_radius=4,
    )

    bank_status_label = ft.Text(
        "Ready to flash",
        size=13,
        color="#8E8E93",
        text_align=ft.TextAlign.CENTER,
    )

    bank_flash_button = ft.FilledButton(
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


    holo_foil_switch = ft.Switch(
        label="3D Holographic Foil",
        value=False,
        active_color="#BF5AF2",
        tooltip="Bakes an iridescent 3D holographic rainbow foil sheen directly into regular cards (Apple Cash style)",
    )

    bank_cardholder_switch = ft.Switch(
        label="Cardholder Name",
        value=False,
        active_color="#0A84FF",
        tooltip="Emboss cardholder name in bottom-left corner using credit card OCR-A font",
    )

    bank_cardholder_field = ft.TextField(
        label="Cardholder Name",
        value="",
        hint_text="e.g. JOHN DOE",
        border_color="#0A84FF",
        dense=True,
        max_length=24,
        visible=False,
    )

    def on_bank_cardholder_switch_change(e):
        bank_cardholder_field.visible = bank_cardholder_switch.value
        update_bank_cardholder_overlay()
        page.update()

    def on_bank_cardholder_text_change(e):
        update_bank_cardholder_overlay()
        page.update()

    bank_cardholder_switch.on_change = on_bank_cardholder_switch_change
    bank_cardholder_field.on_change = on_bank_cardholder_text_change

    bank_action_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        holo_foil_switch,
                        bank_cardholder_switch,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                ),
                bank_cardholder_field,
                bank_progress_bar,
                bank_status_label,
                ft.Row([bank_flash_button]),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    bank_left_col = ft.Column([card_section, bank_skin_section], spacing=16, expand=5)
    bank_right_col = ft.Column(
        [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.VISIBILITY_OUTLINED, size=18, color="#0A84FF"),
                                        ft.Text("Preview & Deploy", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                        ),
                        ft.Container(content=bank_card_mockup, alignment=ft.Alignment.CENTER, padding=10),
                        bank_action_section,
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

    bank_view = ft.Row([bank_left_col, bank_right_col], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START)

    # ==========================================
    # TAB 2: Apple Cash 3D Studio View
    # ==========================================
    default_ac_card = next((c for c in saved_cards if "apple" in c.get("name", "").lower()), saved_cards[0] if saved_cards else None)
    ac_selected_card_hash: Optional[str] = default_ac_card["hash"] if default_ac_card else ""

    ac_card_dropdown = ft.Dropdown(
        label="Select Apple Card",
        hint_text="Choose target card for 3D Metal",
        options=[
            ft.DropdownOption(key=c["hash"], text=format_card_label(c))
            for c in saved_cards
        ],
        value=ac_selected_card_hash,
        expand=True,
        border=ft.OutlineInputBorder(border_radius=10),
        bgcolor="#1C1C1E",
    )

    ac_card_hash_input = ft.TextField(
        label="Apple Card Pass Hash",
        value=ac_selected_card_hash or "",
        hint_text="Enter or paste your Apple card hash",
        border_color="#BF5AF2",
        dense=True,
        expand=True,
    )

    def on_ac_card_selected(e):
        nonlocal ac_selected_card_hash
        val = getattr(e, "data", None) or ac_card_dropdown.value
        ac_selected_card_hash = val or ""
        ac_card_hash_input.value = val or ""
        update_ac_ui_state()
        page.update()

    def on_ac_card_hash_input_change(e):
        nonlocal ac_selected_card_hash
        ac_selected_card_hash = (ac_card_hash_input.value or "").strip()
        update_ac_ui_state()
        page.update()

    ac_card_dropdown.on_select = on_ac_card_selected
    ac_card_dropdown.on_change = on_ac_card_selected
    ac_card_hash_input.on_change = on_ac_card_hash_input_change

    ac_apple_only_notice = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=15, color="#BF5AF2"),
                ft.Text(
                    "Notice: Only for official Apple cards (Apple Cash, Apple Card). Standard bank cards do not support 3D Metal shaders.",
                    size=11,
                    color="#BF5AF2",
                    weight=ft.FontWeight.W_500,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#BF5AF212",
        padding=ft.Padding(8, 5, 8, 5),
        border_radius=6,
    )

    ac_info_card = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=20, color="#BF5AF2"),
                        ft.Text("Apple 3D Metal Studio", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                        ft.Container(
                            content=ft.Text("SceneKit / Metal", size=10, weight=ft.FontWeight.BOLD, color="#BF5AF2"),
                            bgcolor="#BF5AF222",
                            padding=ft.Padding(6, 2, 6, 2),
                            border_radius=8,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Features a live 3D Metal fragment shader in iOS PassKit with gyroscope specular reflection.",
                    size=12,
                    color="#A1A1AA",
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ac_card_dropdown,
                            ac_card_hash_input,
                            ac_apple_only_notice,
                        ],
                        spacing=8,
                    ),
                    bgcolor="#121214",
                    padding=ft.Padding(12, 10, 12, 10),
                    border_radius=10,
                    border=ft.Border.all(1, "#27272A"),
                ),
            ],
            spacing=10,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    ac_skin_info_text = ft.Text(
        "No skin loaded (1536 × 969 PNG recommended, diffuse 764 × 480)",
        size=12,
        color="#8E8E93",
    )

    ac_browse_btn = ft.FilledTonalButton(
        content="Browse File...",
        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
        expand=True,
    )

    ac_paste_btn = ft.OutlinedButton(
        content="Paste (Ctrl+V)",
        icon=ft.Icons.CONTENT_PASTE_ROUNDED,
        tooltip="Paste image from clipboard",
        style=ft.ButtonStyle(color="#E5E5EA"),
    )

    ac_clear_btn = ft.OutlinedButton(
        content="Clear",
        icon=ft.Icons.CLEAR_ALL_ROUNDED,
        tooltip="Clear loaded Apple Cash skin",
        style=ft.ButtonStyle(color="#FF453A"),
        disabled=True,
    )

    ac_skin_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PALETTE_OUTLINED, size=18, color="#BF5AF2"),
                        ft.Text("Apple Cash Artwork", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                    ],
                    spacing=8,
                ),
                ft.Text("Select custom artwork for diffuse & background layers.", size=12, color="#8E8E93"),
                ac_skin_info_text,
                ft.Row([ac_browse_btn, ac_paste_btn, ac_clear_btn], spacing=8),
            ],
            spacing=12,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    # 3D Metal Mode Selector & Custom Studio
    ac_mode_radio = ft.RadioGroup(
        content=ft.Column(
            [
                ft.Radio(
                    value="rainbow",
                    label="🌈 Rainbow Hologram (Classic Apple Cash iridescent gyro sheen)",
                ),
                ft.Radio(
                    value="matte",
                    label="🖤 Stealth Matte (Completely non-reflective, flat matte surface)",
                ),
                ft.Radio(
                    value="custom",
                    label="🎨 Custom Studio (Manual control over metalness, normal map & branding)",
                ),
            ],
            spacing=8,
        ),
        value="rainbow",
    )

    ac_shimmer_label = ft.Text("Rainbow Shimmer Intensity: 80%", size=12, color="#E5E5EA", weight=ft.FontWeight.W_500)
    ac_shimmer_slider = ft.Slider(
        min=0,
        max=100,
        divisions=20,
        value=80,
        label="{value}%",
        active_color="#BF5AF2",
    )

    ac_smooth_switch = ft.Switch(
        label="Smooth Surface (Remove embossed Apple logo 3D stamp)",
        value=False,
        active_color="#BF5AF2",
        tooltip="Replaces normal map with a flat surface, removing the Apple logo 3D impression",
    )

    ac_custom_panel = ft.Container(
        content=ft.Column(
            [
                ft.Divider(color="#27272A", height=1),
                ac_shimmer_label,
                ac_shimmer_slider,
                ac_smooth_switch,
            ],
            spacing=8,
        ),
        visible=False,
    )

    def on_ac_mode_change(e):
        nonlocal ac_metal_mode
        ac_metal_mode = ac_mode_radio.value or "rainbow"
        ac_custom_panel.visible = (ac_metal_mode == "custom")
        update_ac_background()
        page.update()

    def on_ac_slider_change(e):
        ac_shimmer_label.value = f"Rainbow Shimmer Intensity: {int(ac_shimmer_slider.value)}%"
        page.update()

    def on_ac_slider_change_end(e):
        update_ac_background()
        page.update()

    def on_ac_switch_change(e):
        update_ac_background()
        page.update()

    ac_mode_radio.on_change = on_ac_mode_change
    ac_shimmer_slider.on_change = on_ac_slider_change
    ac_shimmer_slider.on_change_end = on_ac_slider_change_end
    ac_smooth_switch.on_change = on_ac_switch_change

    ac_mode_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.TUNE_ROUNDED, size=18, color="#BF5AF2"),
                        ft.Text("3D Metalness & Shimmer Engine", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                    ],
                    spacing=8,
                ),
                ac_mode_radio,
                ac_custom_panel,
            ],
            spacing=12,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    # -------------------------------------------------------------
    # -------------------------------------------------------------
    # Personalization & Branding: Nickname & Photo/Icon
    # -------------------------------------------------------------
    ac_icon_mode_radio = ft.RadioGroup(
        content=ft.Row(
            [
                ft.Radio(value="apple", label=" Apple"),
                ft.Radio(value="custom", label="🖼️ Custom Photo"),
                ft.Radio(value="none", label="No Icon"),
                ft.Radio(value="clean_all", label="Hide All"),
            ],
            wrap=True,
            spacing=10,
        ),
        value="apple",
    )

    ac_nickname_field = ft.TextField(
        label="Custom Corner Text",
        value="",
        hint_text="e.g. CASH, VIP, TITANIUM",
        border_color="#BF5AF2",
        dense=True,
        max_length=20,
        expand=True,
    )

    ac_custom_icon_btn = ft.OutlinedButton(
        content="Choose Photo...",
        icon=ft.Icons.ADD_A_PHOTO_ROUNDED,
        style=ft.ButtonStyle(color="#BF5AF2"),
    )
    ac_custom_icon_label = ft.Text("No photo chosen", size=12, color="#8E8E93")

    ac_custom_icon_row = ft.Container(
        content=ft.Row(
            [
                ac_custom_icon_btn,
                ac_custom_icon_label,
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        visible=False,
    )

    ac_cardholder_switch = ft.Switch(
        label="Cardholder Name",
        value=False,
        active_color="#BF5AF2",
        tooltip="Emboss cardholder name in bottom-left corner with authentic OCR-A font",
    )

    ac_cardholder_field = ft.TextField(
        label="Cardholder Name",
        value="",
        hint_text="e.g. JOHN DOE",
        border_color="#BF5AF2",
        dense=True,
        max_length=26,
        visible=False,
    )

    def on_ac_icon_mode_change(e):
        nonlocal ac_icon_mode
        ac_icon_mode = ac_icon_mode_radio.value or "apple"
        ac_custom_icon_row.visible = (ac_icon_mode == "custom")
        ac_nickname_field.disabled = (ac_icon_mode == "clean_all")
        update_ac_watermark_and_labels()
        page.update()

    def on_ac_nickname_change(e):
        nonlocal ac_custom_logo_text
        ac_custom_logo_text = ac_nickname_field.value or ""
        update_ac_watermark_and_labels()
        page.update()

    def on_ac_cardholder_switch_change(e):
        ac_cardholder_field.visible = ac_cardholder_switch.value
        update_ac_watermark_and_labels()
        page.update()

    def on_ac_cardholder_text_change(e):
        update_ac_watermark_and_labels()
        page.update()

    ac_icon_mode_radio.on_change = on_ac_icon_mode_change
    ac_nickname_field.on_change = on_ac_nickname_change
    ac_cardholder_switch.on_change = on_ac_cardholder_switch_change
    ac_cardholder_field.on_change = on_ac_cardholder_text_change

    ac_branding_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.BADGE_OUTLINED, size=18, color="#BF5AF2"),
                        ft.Text("Personalization: Nickname & Photo", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                    ],
                    spacing=8,
                ),
                ft.Text("Personalize your card with custom corner branding and embossing.", size=12, color="#8E8E93"),
                ft.Row([ac_nickname_field], spacing=10),
                ft.Text("Corner Icon / Avatar:", size=12, color="#E5E5EA", weight=ft.FontWeight.W_500),
                ac_icon_mode_radio,
                ac_custom_icon_row,
                ft.Divider(color="#27272A", height=1),
                ac_cardholder_switch,
                ac_cardholder_field,
            ],
            spacing=10,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    # Apple Cash Mockup Preview
    ac_preview_placeholder = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=46, color="#BF5AF288"),
                ft.Text("Apple Cash 3D Preview", size=15, weight=ft.FontWeight.W_600, color="#E5E5EA"),
                ft.Text("Click card to load skin or press Ctrl+V", size=12, color="#8E8E93"),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=6,
        ),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )

    ac_card_image = ft.Image(
        src="",
        fit=ft.BoxFit.COVER,
        width=390,
        height=246,
        border_radius=16,
        visible=False,
    )

    ac_card_watermark = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.APPLE_ROUNDED, size=16, color="#FFFFFF"),
                ft.Text("Cash", size=14, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
            ],
            spacing=2,
        ),
        top=14,
        left=16,
        bgcolor="#00000066",
        border_radius=12,
        padding=ft.Padding(8, 3, 10, 3),
    )

    ac_cardholder_label = ft.Container(
        content=ft.Text("CARDHOLDER NAME", size=10, weight=ft.FontWeight.BOLD, color="#FFFFFFE0", font_family="Consolas, monospace"),
        bottom=14,
        left=18,
        visible=False,
    )

    ac_clear_badge = ft.Container(
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

    ac_card_mockup = ft.Container(
        content=ft.Stack(
            [
                ac_preview_placeholder,
                ac_card_image,
                ac_card_watermark,
                ac_cardholder_label,
                ft.Container(
                    border=ft.Border.all(1, "#BF5AF244"),
                    border_radius=16,
                    expand=True,
                ),
                ac_clear_badge,
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
            color="#BF5AF21A",
            offset=ft.Offset(0, 14),
        ),
        alignment=ft.Alignment.CENTER,
        ink=True,
        tooltip="Click to select skin for Apple Cash",
    )

    ac_progress_bar = ft.ProgressBar(
        value=0,
        color="#BF5AF2",
        bgcolor="#2C2C2E",
        visible=False,
        border_radius=4,
    )

    ac_status_label = ft.Text(
        "Ready to flash Apple Cash 3D skin",
        size=13,
        color="#8E8E93",
        text_align=ft.TextAlign.CENTER,
    )

    ac_flash_button = ft.FilledButton(
        content="Flash 3D Metal Skin to Apple Cash",
        icon=ft.Icons.AUTO_AWESOME_ROUNDED,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: "#BF5AF2",
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

    ac_revert_button = ft.OutlinedButton(
        content="Reset to Factory Apple White",
        icon=ft.Icons.RESTORE_ROUNDED,
        style=ft.ButtonStyle(color="#FF9F0A"),
        height=48,
        tooltip="Restore pristine official white Apple Cash 3D textures from Apple CDN broker",
        disabled=selected_device is None,
    )

    ac_action_section = ft.Container(
        content=ft.Column(
            [
                ac_progress_bar,
                ac_status_label,
                ft.Row([ac_flash_button, ac_revert_button], spacing=10),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#18181B",
        border=ft.Border.all(1, "#27272A"),
        border_radius=14,
        padding=18,
    )

    ac_left_col = ft.Column([ac_info_card, ac_skin_section, ac_mode_section, ac_branding_section], spacing=16, expand=5)
    ac_right_col = ft.Column(
        [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=18, color="#BF5AF2"),
                                        ft.Text("Apple Cash 3D Studio Preview", size=15, weight=ft.FontWeight.BOLD, color="#F5F5F7"),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                        ),
                        ft.Container(content=ac_card_mockup, alignment=ft.Alignment.CENTER, padding=10),
                        ac_action_section,
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

    apple_cash_view = ft.Row([ac_left_col, ac_right_col], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START, visible=False)

    # Assemble page body
    page.add(
        ft.Column(
            [header, itunes_warning, tab_bar, bank_view, apple_cash_view],
            spacing=16,
            expand=True,
        )
    )

    # ==========================================
    # State Management & Helpers
    # ==========================================
    def update_bank_ui_state():
        can_flash = (
            selected_device is not None
            and selected_card_hash is not None
            and bank_active_skin_bytes is not None
            and dll_dir is not None
        )
        bank_flash_button.disabled = not can_flash
        rename_card_button.disabled = selected_card_hash is None
        delete_card_button.disabled = selected_card_hash is None

        if not selected_device:
            bank_status_label.value = "Connect iPhone via USB to enable flashing"
            bank_status_label.color = "#8E8E93"
        elif not selected_card_hash:
            bank_status_label.value = "Scan or select a target card"
            bank_status_label.color = "#8E8E93"
        elif not bank_active_skin_bytes:
            bank_status_label.value = "Select or load a card skin image"
            bank_status_label.color = "#8E8E93"
        elif dll_dir is None:
            bank_status_label.value = "Apple Mobile Device Support required"
            bank_status_label.color = "#FF9F0A"
        else:
            bank_status_label.value = "Ready to flash skin to iPhone"
            bank_status_label.color = "#30D158"

    def update_ac_ui_state():
        target_hash = (ac_card_hash_input.value or ac_selected_card_hash or "").strip()
        can_flash = (
            selected_device is not None
            and target_hash != ""
            and ac_active_skin_bytes is not None
            and dll_dir is not None
        )
        ac_flash_button.disabled = not can_flash
        ac_revert_button.disabled = selected_device is None or target_hash == "" or dll_dir is None

        if not selected_device:
            ac_status_label.value = "Connect iPhone via USB to enable flashing"
            ac_status_label.color = "#8E8E93"
        elif not target_hash:
            ac_status_label.value = "Select or enter an Apple Card hash"
            ac_status_label.color = "#8E8E93"
        elif not ac_active_skin_bytes:
            ac_status_label.value = "Select or load a card artwork image"
            ac_status_label.color = "#8E8E93"
        elif dll_dir is None:
            ac_status_label.value = "Apple Mobile Device Support required"
            ac_status_label.color = "#FF9F0A"
        else:
            ac_status_label.value = "Ready to flash 3D Metal skin to Apple Card"
            ac_status_label.color = "#BF5AF2"

    def update_bank_cardholder_overlay():
        holder_name = (bank_cardholder_field.value or "").strip()
        if bank_cardholder_switch.value and holder_name:
            bank_cardholder_label.content.value = "  ".join(holder_name.upper())
            bank_cardholder_label.visible = True
        else:
            bank_cardholder_label.visible = False

    def update_bank_background():
        nonlocal bank_active_skin_bytes
        if not bank_raw_skin_bytes:
            return

        if holo_foil_switch.value:
            bank_active_skin_bytes = apply_holographic_foil(bank_raw_skin_bytes, intensity=0.32)
        else:
            bank_active_skin_bytes = bank_raw_skin_bytes

        b64 = base64.b64encode(bank_active_skin_bytes).decode("ascii")
        bank_card_image.src = f"data:image/png;base64,{b64}"
        bank_card_image.visible = True
        bank_preview_placeholder.visible = False
        bank_clear_badge.visible = True
        bank_clear_btn.disabled = False
        update_bank_ui_state()

    def update_bank_preview():
        update_bank_background()
        update_bank_cardholder_overlay()
        page.update()

    def update_ac_watermark_and_labels():
        mode = ac_icon_mode_radio.value or "apple"
        nick = (ac_nickname_field.value or "").strip()

        if mode == "clean_all":
            ac_card_watermark.visible = False
        else:
            row_items = []
            if mode == "apple":
                row_items.append(ft.Icon(ft.Icons.APPLE_ROUNDED, size=16, color="#FFFFFF"))
            elif mode == "custom" and ac_custom_icon_bytes:
                icon_b64 = base64.b64encode(ac_custom_icon_bytes).decode("ascii")
                row_items.append(
                    ft.Container(
                        content=ft.Image(src=f"data:image/png;base64,{icon_b64}", width=20, height=20, fit=ft.BoxFit.COVER),
                        border_radius=5,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    )
                )

            if nick:
                row_items.append(ft.Text(nick, size=13, weight=ft.FontWeight.BOLD, color="#FFFFFF"))
            elif mode == "apple":
                row_items.append(ft.Text("Cash", size=13, weight=ft.FontWeight.BOLD, color="#FFFFFF"))

            if row_items:
                ac_card_watermark.content = ft.Row(row_items, spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                ac_card_watermark.visible = True
            else:
                ac_card_watermark.visible = False

        # Cardholder name preview at bottom-left of mockup
        ac_holder_name = (ac_cardholder_field.value or "").strip()
        if ac_cardholder_switch.value and ac_holder_name:
            ac_cardholder_label.content.value = "  ".join(ac_holder_name.upper())
            ac_cardholder_label.visible = True
        else:
            ac_cardholder_label.visible = False

    def update_ac_background():
        nonlocal ac_active_skin_bytes
        if not ac_raw_skin_bytes:
            return

        chosen_mode = ac_mode_radio.value or "rainbow"
        if chosen_mode == "matte":
            ac_active_skin_bytes = ac_raw_skin_bytes
        elif chosen_mode == "rainbow":
            ac_active_skin_bytes = apply_holographic_foil(ac_raw_skin_bytes, intensity=0.35)
        else:  # custom
            slider_val = float(ac_shimmer_slider.value or 0)
            if slider_val <= 0:
                ac_active_skin_bytes = ac_raw_skin_bytes
            else:
                ac_active_skin_bytes = apply_holographic_foil(ac_raw_skin_bytes, intensity=(slider_val / 100.0) * 0.45)

        b64 = base64.b64encode(ac_active_skin_bytes).decode("ascii")
        ac_card_image.src = f"data:image/png;base64,{b64}"
        ac_card_image.visible = True
        ac_preview_placeholder.visible = False
        ac_clear_badge.visible = True
        ac_clear_btn.disabled = False
        update_ac_ui_state()

    def update_ac_preview():
        update_ac_background()
        update_ac_watermark_and_labels()
        page.update()

    def set_bank_skin(data: bytes, source_name: str):
        nonlocal bank_raw_skin_bytes, bank_skin_name
        bank_raw_skin_bytes = data
        bank_skin_name = source_name
        size_kb = len(data) / 1024
        bank_skin_info_text.value = f"✓ Loaded {source_name} ({size_kb:.1f} KB, 1536 × 969)"
        bank_skin_info_text.color = "#30D158"
        update_bank_preview()

    def set_ac_skin(data: bytes, source_name: str):
        nonlocal ac_raw_skin_bytes, ac_skin_name
        ac_raw_skin_bytes = data
        ac_skin_name = source_name
        size_kb = len(data) / 1024
        ac_skin_info_text.value = f"✓ Loaded {source_name} ({size_kb:.1f} KB, 1536 × 969)"
        ac_skin_info_text.color = "#BF5AF2"
        update_ac_preview()

    def handle_clear_bank_skin(e=None):
        nonlocal bank_raw_skin_bytes, bank_active_skin_bytes, bank_skin_name, ignoring_mockup_click
        ignoring_mockup_click = True
        bank_raw_skin_bytes = None
        bank_active_skin_bytes = None
        bank_skin_name = None

        bank_card_image.visible = False
        bank_card_image.src = ""
        bank_preview_placeholder.visible = True
        bank_clear_badge.visible = False
        bank_clear_btn.disabled = True
        bank_skin_info_text.value = "No skin loaded (1536 × 969 PNG recommended)"
        bank_skin_info_text.color = "#8E8E93"

        update_bank_ui_state()
        page.update()
        show_snack("Card preview cleared.")

    def handle_clear_ac_skin(e=None):
        nonlocal ac_raw_skin_bytes, ac_active_skin_bytes, ac_skin_name, ignoring_mockup_click
        ignoring_mockup_click = True
        ac_raw_skin_bytes = None
        ac_active_skin_bytes = None
        ac_skin_name = None

        ac_card_image.visible = False
        ac_card_image.src = ""
        ac_preview_placeholder.visible = True
        ac_clear_badge.visible = False
        ac_clear_btn.disabled = True
        ac_skin_info_text.value = "No skin loaded (1536 × 969 PNG recommended)"
        ac_skin_info_text.color = "#8E8E93"

        update_ac_ui_state()
        page.update()
        show_snack("Apple Cash preview cleared.")

    bank_clear_btn.on_click = handle_clear_bank_skin
    bank_clear_badge.content.on_click = handle_clear_bank_skin
    ac_clear_btn.on_click = handle_clear_ac_skin
    ac_clear_badge.content.on_click = handle_clear_ac_skin

    # Holographic switch live reactivity
    def on_holo_foil_change(e):
        update_bank_preview()

    holo_foil_switch.on_change = on_holo_foil_change

    # Clipboard & File Picker Handlers
    def handle_paste():
        try:
            from PIL import ImageGrab, Image
            cb_data = ImageGrab.grabclipboard()
            if isinstance(cb_data, Image.Image):
                processed = prepare_card_skin(cb_data)
                if active_tab == "bank":
                    set_bank_skin(processed, "Pasted Image")
                else:
                    set_ac_skin(processed, "Pasted Image")
                show_snack("✓ Pasted image from clipboard")
                return True
            elif isinstance(cb_data, list):
                img_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
                for item in cb_data:
                    p = Path(item)
                    if p.suffix.lower() in img_exts and p.is_file():
                        processed = prepare_card_skin(p)
                        if active_tab == "bank":
                            set_bank_skin(processed, p.name)
                        else:
                            set_ac_skin(processed, p.name)
                        show_snack(f"✓ Loaded {p.name} from clipboard")
                        return True
                show_snack("No image file found in clipboard.", is_error=True)
                return False
            else:
                show_snack("Clipboard does not contain an image.", is_error=True)
                return False
        except Exception as ex:
            show_snack(f"Failed to paste from clipboard: {ex}", is_error=True)
            return False

    bank_paste_btn.on_click = lambda _: handle_paste()
    ac_paste_btn.on_click = lambda _: handle_paste()

    async def handle_browse_file(target_tab: str):
        try:
            files = await file_picker.pick_files(
                dialog_title="Select Card Skin Image",
                allow_multiple=False,
                allowed_extensions=["png", "jpg", "jpeg", "webp"],
            )
            if files and len(files) > 0 and files[0].path:
                file_path = files[0].path
                processed = prepare_card_skin(file_path)
                if target_tab == "bank":
                    set_bank_skin(processed, Path(file_path).name)
                else:
                    set_ac_skin(processed, Path(file_path).name)
        except Exception as ex:
            show_snack(f"Failed to load image: {ex}", is_error=True)

    bank_browse_btn.on_click = lambda _: asyncio.create_task(handle_browse_file("bank"))
    ac_browse_btn.on_click = lambda _: asyncio.create_task(handle_browse_file("apple_cash"))

    async def handle_browse_ac_icon():
        nonlocal ac_custom_icon_bytes, ac_custom_icon_name
        try:
            files = await file_picker.pick_files(
                dialog_title="Choose Photo or Avatar for Apple Cash",
                allow_multiple=False,
                allowed_extensions=["png", "webp", "jpg", "jpeg"],
            )
            if files and len(files) > 0 and files[0].path:
                file_path = Path(files[0].path)
                with open(file_path, "rb") as fp:
                    ac_custom_icon_bytes = fp.read()
                ac_custom_icon_name = file_path.name
                ac_custom_icon_label.value = f"✓ {file_path.name}"
                ac_custom_icon_label.color = "#30D158"
                update_ac_watermark_and_labels()
                page.update()
                show_snack(f"✓ Loaded icon: {file_path.name}")
        except Exception as ex:
            show_snack(f"Failed to load icon: {ex}", is_error=True)

    ac_custom_icon_btn.on_click = lambda _: asyncio.create_task(handle_browse_ac_icon())

    async def handle_bank_mockup_click(e):
        nonlocal ignoring_mockup_click
        if ignoring_mockup_click:
            ignoring_mockup_click = False
            return
        await handle_browse_file("bank")

    async def handle_ac_mockup_click(e):
        nonlocal ignoring_mockup_click
        if ignoring_mockup_click:
            ignoring_mockup_click = False
            return
        await handle_browse_file("apple_cash")

    bank_card_mockup.on_click = lambda e: asyncio.create_task(handle_bank_mockup_click(e))
    ac_card_mockup.on_click = lambda e: asyncio.create_task(handle_ac_mockup_click(e))

    def handle_bank_hover(e):
        bank_card_mockup.border = ft.Border.all(1.5, "#0A84FF") if e.data == "true" else ft.Border.all(1, "#27272A")
        page.update()

    def handle_ac_hover(e):
        ac_card_mockup.border = ft.Border.all(1.5, "#BF5AF2") if e.data == "true" else ft.Border.all(1, "#27272A")
        page.update()

    bank_card_mockup.on_hover = handle_bank_hover
    ac_card_mockup.on_hover = handle_ac_hover

    def on_keyboard(e: ft.KeyboardEvent):
        if e.key.upper() == "V" and (e.ctrl or e.meta):
            handle_paste()

    page.on_keyboard_event = on_keyboard

    # Device Refresh
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

        update_bank_ui_state()
        update_ac_ui_state()
        page.update()

    # ==========================================
    # Flash & Revert Actions
    # ==========================================
    async def perform_bank_flash():
        nonlocal selected_card_hash
        if card_dropdown.value:
            selected_card_hash = card_dropdown.value
        if not selected_device or not selected_card_hash or not bank_active_skin_bytes:
            return

        bank_flash_button.disabled = True
        bank_progress_bar.visible = True
        bank_progress_bar.value = 0
        bank_status_label.color = "#0A84FF"
        bank_status_label.value = "Preparing payload..."
        page.update()

        def progress_cb(cur: int, tot: int, step_desc: str):
            bank_progress_bar.value = cur / tot
            bank_status_label.value = f"[{cur}/{tot}] {step_desc}"
            page.update()

        payload = bank_active_skin_bytes
        holder_name = (bank_cardholder_field.value or "").strip()
        if bank_cardholder_switch.value and holder_name:
            payload = draw_cardholder_name(payload, holder_name)

        try:
            ok = await flash_card_skin_async(
                udid=selected_device.udid,
                card_hash=selected_card_hash,
                skin_png_bytes=payload,
                clean_logo=False,
                progress_callback=progress_cb,
            )

            if ok:
                bank_status_label.value = "✓ Card skin flashed successfully!"
                bank_status_label.color = "#30D158"
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
                bank_status_label.value = "Flashing failed. Check USB connection."
                bank_status_label.color = "#FF453A"
                show_snack("AirTraffic asset sync returned false.", is_error=True)
        except Exception as ex:
            bank_status_label.value = f"Error: {ex}"
            bank_status_label.color = "#FF453A"
            show_snack(f"Flashing failed: {ex}", is_error=True)
        finally:
            update_bank_ui_state()
            bank_progress_bar.visible = False
            page.update()

    bank_flash_button.on_click = lambda _: asyncio.create_task(perform_bank_flash())

    # Apple Cash Actions
    async def perform_ac_flash():
        if not selected_device or not ac_active_skin_bytes:
            return

        ac_flash_button.disabled = True
        ac_revert_button.disabled = True
        ac_progress_bar.visible = True
        ac_progress_bar.value = 0
        ac_status_label.color = "#BF5AF2"
        ac_status_label.value = "Generating 3D Metal textures..."
        page.update()

        def progress_cb(cur: int, tot: int, step_desc: str):
            ac_progress_bar.value = cur / tot
            ac_status_label.value = f"[{cur}/{tot}] {step_desc}"
            page.update()

        chosen_mode = ac_mode_radio.value or "rainbow"
        if chosen_mode == "rainbow":
            m_level = 210
            is_smooth = False
        elif chosen_mode == "matte":
            m_level = 0
            is_smooth = True
        else:  # custom
            m_level = int(((ac_shimmer_slider.value or 0) / 100.0) * 255)
            is_smooth = ac_smooth_switch.value

        imode = ac_icon_mode_radio.value or "apple"
        nick = (ac_nickname_field.value or "").strip()
        ac_holder_name = (ac_cardholder_field.value or "").strip()
        cardholder_txt = ac_holder_name if (ac_cardholder_switch.value and ac_holder_name) else None
        target_hash = (ac_card_hash_input.value or ac_selected_card_hash or "").strip()
        if not selected_device or not target_hash or not (ac_raw_skin_bytes or ac_active_skin_bytes):
            show_snack("Please select or enter an Apple card hash.", is_error=True)
            return

        try:
            ok = await flash_apple_cash_async(
                udid=selected_device.udid,
                card_hash=target_hash,
                skin_bytes=ac_raw_skin_bytes or ac_active_skin_bytes,
                mode=chosen_mode,
                metalness_level=m_level,
                smooth_surface=is_smooth,
                clean_logo=(imode == "clean_all"),
                icon_mode=imode,
                custom_icon_bytes=ac_custom_icon_bytes,
                custom_logo_text=nick if nick else ("Cash" if imode == "apple" else None),
                cardholder_name_text=cardholder_txt,
                progress_callback=progress_cb,
            )

            if ok:
                ac_status_label.value = "✓ Apple Card 3D Metal skin flashed!"
                ac_status_label.color = "#30D158"
                page.update()

                page.show_dialog(
                    ft.AlertDialog(
                        title=ft.Row(
                            [
                                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color="#30D158"),
                                ft.Text("Apple Card 3D Skin Flashed!"),
                            ],
                            spacing=8,
                        ),
                        content=ft.Text(
                            "The 3D Metal diffuse and armed textures (@2x & @3x) have been deployed.\n\n"
                            "• Open Apple Wallet on your iPhone.\n"
                            "• Double-click side button for Apple Pay: your custom 3D card is now active in both Wallet and Apple Pay!\n\n"
                            "💡 Tip: If Apple Pay does not update immediately on the lock screen, perform a quick Reboot of your iPhone to refresh SpringBoard's memory cache.",
                            size=13,
                        ),
                        actions=[
                            ft.FilledButton("Done", on_click=lambda _: page.pop_dialog()),
                        ],
                    )
                )
            else:
                ac_status_label.value = "Flashing failed. Check USB connection."
                ac_status_label.color = "#FF453A"
                show_snack("Apple Card flashing failed.", is_error=True)
        except Exception as ex:
            ac_status_label.value = f"Error: {ex}"
            ac_status_label.color = "#FF453A"
            show_snack(f"Apple Card flashing failed: {ex}", is_error=True)
        finally:
            update_ac_ui_state()
            ac_progress_bar.visible = False
            page.update()

    ac_flash_button.on_click = lambda _: asyncio.create_task(perform_ac_flash())

    async def perform_ac_revert():
        target_hash = (ac_card_hash_input.value or ac_selected_card_hash or "").strip()
        if not selected_device or not target_hash:
            show_snack("Please select or enter an Apple card hash.", is_error=True)
            return

        ac_flash_button.disabled = True
        ac_revert_button.disabled = True
        ac_progress_bar.visible = True
        ac_progress_bar.value = 0
        ac_status_label.color = "#FF9F0A"
        ac_status_label.value = "Restoring official Apple Card textures..."
        page.update()

        def progress_cb(cur: int, tot: int, step_desc: str):
            ac_progress_bar.value = cur / tot
            ac_status_label.value = f"[{cur}/{tot}] {step_desc}"
            page.update()

        try:
            ok = await revert_apple_cash_async(
                udid=selected_device.udid,
                card_hash=target_hash,
                progress_callback=progress_cb,
            )

            if ok:
                ac_status_label.value = "✓ Apple Cash restored to factory design!"
                ac_status_label.color = "#30D158"
                page.update()

                page.show_dialog(
                    ft.AlertDialog(
                        title=ft.Row(
                            [
                                ft.Icon(ft.Icons.RESTORE_ROUNDED, color="#30D158"),
                                ft.Text("Apple Cash Restored to Factory!"),
                            ],
                            spacing=8,
                        ),
                        content=ft.Text(
                            "The official pristine Apple Cash textures have been downloaded from Apple and restored.\n\n"
                            "• Open Apple Wallet on your iPhone.\n"
                            "• The classic white 3D Apple Cash card is now active!",
                            size=14,
                        ),
                        actions=[
                            ft.FilledButton("Done", on_click=lambda _: page.pop_dialog()),
                        ],
                    )
                )
            else:
                ac_status_label.value = "Revert failed. Check USB connection."
                ac_status_label.color = "#FF453A"
                show_snack("Failed to reset Apple Cash.", is_error=True)
        except Exception as ex:
            ac_status_label.value = f"Error: {ex}"
            ac_status_label.color = "#FF453A"
            show_snack(f"Apple Cash reset failed: {ex}", is_error=True)
        finally:
            update_ac_ui_state()
            ac_progress_bar.visible = False
            page.update()

    ac_revert_button.on_click = lambda _: asyncio.create_task(perform_ac_revert())

    # ==========================================
    # Card Scanner Dialog
    # ==========================================
    scan_dialog_ring = ft.ProgressRing(stroke_width=3, color="#0A84FF", width=28, height=28)
    scan_dialog_icon = ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color="#30D158", size=32, visible=False)
    scan_dialog_text = ft.Text("Open Wallet on iPhone and tap your card to scan...", size=13, color="#8E8E93")
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
        title=ft.Row([ft.Icon(ft.Icons.SENSORS_ROUNDED, color="#0A84FF"), ft.Text("Listening for Apple Pay Card...")], spacing=8),
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row([scan_dialog_ring, scan_dialog_icon, ft.Container(content=scan_dialog_text, expand=True)], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
                    scan_log_box,
                ],
                spacing=12,
            ),
            width=420,
            height=160,
        ),
        actions=[scan_dialog_action_btn],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    async def run_scan_session():
        nonlocal scan_stop_event, selected_card_hash, saved_cards
        if not selected_device:
            show_snack("Please connect an iPhone via USB before scanning.", is_error=True)
            return

        scan_stop_event = asyncio.Event()
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
                if card_name and (not existing.get("name") or existing.get("name").startswith("Card ")):
                    existing["name"] = card_name
                    save_cards_metadata(saved_cards)
                name = existing.get("name") or f"Card {len(saved_cards)}"

            selected_card_hash = card_hash
            opts = [ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards]
            card_dropdown.options = opts
            card_dropdown.value = card_hash
            ac_card_dropdown.options = opts
            update_bank_ui_state()
            update_ac_ui_state()

            add_scan_log(f"✅ Card detected: {name}!", "#30D158")
            add_scan_log(f"   Hash: {card_hash[:10]}...{card_hash[-6:]}", "#30D158")
            add_scan_log("✓ Saved and selected for flashing", "#30D158")

            scan_dialog_ring.visible = False
            scan_dialog_icon.visible = True
            scan_dialog_text.value = f"Found: {name}"
            scan_dialog_action_btn.text = "Done"
            scan_dialog_action_btn.style = ft.ButtonStyle(color="#30D158")
            page.update()

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
            await start_card_scan_session(
                udid=selected_device.udid,
                on_card_found=sync_found_callback,
                stop_event=scan_stop_event,
            )
        except Exception as ex:
            if scan_dialog.open:
                page.pop_dialog()
            show_snack(f"Scan interrupted: {ex}", is_error=True)

    scan_button.on_click = lambda _: asyncio.create_task(run_scan_session())

    # Rename Dialog
    rename_input_field = ft.TextField(
        label="Card Name",
        hint_text="e.g. Visa, Mastercard, Chase",
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
            opts = [ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards]
            card_dropdown.options = opts
            card_dropdown.value = cur_card["hash"]
            ac_card_dropdown.options = opts
            page.pop_dialog()
            page.update()
            show_snack(f"Card renamed to \"{new_name}\"")

        rename_dialog = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.EDIT_ROUNDED, color="#0A84FF"), ft.Text("Rename Card")], spacing=8),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(f"Current Name: {cur_card.get('name', 'Card')}", size=12, color="#8E8E93"),
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

    # Manual Hash Dialog
    hash_input_field = ft.TextField(
        label="Card Hash",
        hint_text="Paste 27-char base64 hash...",
        autofocus=True,
        border=ft.OutlineInputBorder(border_radius=8),
    )
    name_input_field = ft.TextField(
        label="Card Name (Optional)",
        hint_text="e.g. Visa, Mastercard, Chase",
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
            saved_cards.append({"hash": val, "name": name_val or f"Card {len(saved_cards) + 1}"})
        save_cards_metadata(saved_cards)

        selected_card_hash = val
        opts = [ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards]
        card_dropdown.options = opts
        card_dropdown.value = val
        ac_card_dropdown.options = opts
        page.pop_dialog()
        hash_input_field.value = ""
        name_input_field.value = ""
        update_bank_ui_state()
        update_ac_ui_state()
        page.update()
        show_snack(f"Saved card {name_val or val[:8]}...")

    manual_hash_dialog = ft.AlertDialog(
        title=ft.Text("Add Card Manually"),
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Text("Enter base64 card hash and optional friendly name.", size=13, color="#8E8E93"),
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
        opts = [ft.DropdownOption(key=c["hash"], text=format_card_label(c)) for c in saved_cards]
        card_dropdown.options = opts
        card_dropdown.value = selected_card_hash
        ac_card_dropdown.options = opts
        update_bank_ui_state()
        update_ac_ui_state()
        page.update()

        name = target_meta.get("name") if target_meta else "Card"
        show_snack(f"Removed \"{name}\" from list.")

    delete_card_button.on_click = handle_delete_card

    # Initial device scan
    await refresh_devices()


if __name__ == "__main__":
    ft.run(main)
