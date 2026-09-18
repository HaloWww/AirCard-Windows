"""
Configuration and constants for AirCard Windows.
"""
from pathlib import Path
import re

TARGET_WIDTH = 1536
TARGET_HEIGHT = 969
TARGET_SIZE = (TARGET_WIDTH, TARGET_HEIGHT)

TARGET_ASSETS = [
    "cardBackgroundCombined@3x.png",
    "cardBackgroundCombined@2x.png",
]

LOGO_ASSETS = [
    "logo@3x.png",
    "logo@2x.png",
    "cobrand@3x.png",
    "cobrand@2x.png",
]

CACHE_FILES = ["FrontFace", "PlaceHolder", "Preview"]

APP_ROOT_DIR = Path(__file__).resolve().parent.parent
CARDS_STORE_PATH = APP_ROOT_DIR / "cards.json"
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
    for d in APPLE_MOBILE_DEVICE_DIRS:
        if (d / "AirTrafficHost.dll").is_file() and (d / "MobileDevice.dll").is_file():
            return d
    return None
