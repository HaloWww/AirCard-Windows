"""Configuration and constants for AirCard Windows."""

from __future__ import annotations

import os
import re
import winreg
from pathlib import Path

TARGET_WIDTH = 1536
TARGET_HEIGHT = 969
TARGET_SIZE = (TARGET_WIDTH, TARGET_HEIGHT)

TARGET_ASSETS = [
    "cardBackgroundCombined@3x.png",
    "cardBackgroundCombined@2x.png",
    "cardBackgroundCombined.pdf",
]

LOGO_ASSETS = [
    "logo@3x.png",
    "logo@2x.png",
    "cobrand@3x.png",
    "cobrand@2x.png",
]

CACHE_FILES = ["FrontFace", "PlaceHolder", "Preview"]
CACHE_EXTENSIONS = [".cache", ".pkcache"]

APP_NAME = "AirCard"
APP_VERSION = "2.0.0-beta.5"

APP_ROOT_DIR = Path(__file__).resolve().parent.parent
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
APP_DATA_DIR = LOCAL_APP_DATA / APP_NAME
BACKUP_ROOT = APP_DATA_DIR / "backups"
CARDS_STORE_PATH = APP_DATA_DIR / "cards.json"
PORTABLE_CARDS_STORE_PATH = APP_ROOT_DIR / "cards.json"
LEGACY_STORE_PATH = Path.home() / ".aircard_cards_win.json"

CARD_REGEXES = [
    re.compile(r"/(?:Cards|Passes/Cards)/([-A-Za-z0-9_+=]{20,44})(?:\.pkpass|\.cache|\.pkcache|/|\s|\"|\'|\)|,|$)"),
    re.compile(r"/([-A-Za-z0-9_+=]{20,44})\.(?:pkpass|cache|pkcache)"),
    re.compile(r"(?<![A-Za-z0-9+/_-])([A-Za-z0-9+/_-]{27}=)(?![A-Za-z0-9+/_-])"),
]

APPLE_MOBILE_DEVICE_DIRS = [
    Path(r"C:\Program Files\Common Files\Apple\Mobile Device Support"),
    Path(r"C:\Program Files (x86)\Common Files\Apple\Mobile Device Support"),
]


def find_apple_dll_dir() -> Path | None:
    candidates: list[Path] = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Apple Inc.\Apple Mobile Device Support",
                0,
                winreg.KEY_READ | view,
            ) as key:
                install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                candidates.append(Path(install_dir))
        except OSError:
            pass

    candidates.extend(APPLE_MOBILE_DEVICE_DIRS)
    seen: set[str] = set()
    for d in candidates:
        key = os.path.normcase(os.fspath(d))
        if key in seen:
            continue
        seen.add(key)
        if (d / "AirTrafficHost.dll").is_file() and (d / "MobileDevice.dll").is_file():
            return d
    return None


def find_desktop_itunes_dir() -> Path | None:
    """Locate the classic desktop iTunes runtime required for Grappa sync."""
    candidates: list[Path] = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Apple Computer, Inc.\iTunes",
                0,
                winreg.KEY_READ | view,
            ) as key:
                install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                candidates.append(Path(install_dir))
        except OSError:
            pass

    candidates.extend(
        [Path(r"C:\Program Files\iTunes"), Path(r"C:\Program Files (x86)\iTunes")]
    )
    seen: set[str] = set()
    for directory in candidates:
        key = os.path.normcase(os.fspath(directory))
        if key in seen:
            continue
        seen.add(key)
        # Current standalone x64 iTunes releases (including 12.13.11.1) no
        # longer ship iTunes.dll.  AirCard talks to the separate Apple Mobile
        # Device Support runtime, so iTunes.exe is the correct desktop-edition
        # marker; find_apple_dll_dir() validates the required DLLs separately.
        if (directory / "iTunes.exe").is_file():
            return directory
    return None


def ensure_app_data_dirs() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
