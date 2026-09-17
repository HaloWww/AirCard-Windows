"""
Live Apple Wallet card scanner for Windows via pymobiledevice3 syslog.
"""
from typing import Callable, Optional, Set
import asyncio
import json
from .config import CARDS_STORE_PATH, LEGACY_STORE_PATH, CARD_REGEXES
from .device import get_lockdown_client

DUMMY_HASHES = {
    "M6nDwZrkYbFlsodLgCbvyFZQ1cc=",
    "kJL-D0rr-SZhbj2c8nK-OQ9hCMY=",
    "hwAtAmHKYwsQrJbT5cTNDsaxVME=",
}

WALLET_KEYWORDS = (
    "passd",
    "passbook",
    "passkit",
    "stockholm",
    "nanopassd",
    "wallet",
    "/cards/",
)

CONTEXT_KEYWORDS = (
    "card",
    "pass",
    "payment",
    "pkpass",
    "uniqueid",
    "identifier",
    "face",
    "cache",
    "stockholm",
    "/cards/",
)


import re

DESC_REGEX = re.compile(
    r"(?:description|localizedDescription|passName|title)\s*[:=]\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def extract_card_name_from_line(line: str) -> Optional[str]:
    m = DESC_REGEX.search(line)
    if m:
        name = m.group(1).strip()
        if len(name) > 1 and "<private>" not in name.lower():
            return name
    return None


def load_saved_cards_metadata() -> list[dict[str, str]]:
    # Auto-migrate legacy cards file from user profile into local installation folder
    if not CARDS_STORE_PATH.is_file() and LEGACY_STORE_PATH.is_file():
        try:
            legacy_data = json.loads(LEGACY_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(legacy_data, list):
                res = []
                for idx, item in enumerate(legacy_data, 1):
                    if isinstance(item, str):
                        res.append({"hash": item, "name": f"Card {idx}"})
                    elif isinstance(item, dict) and "hash" in item:
                        res.append({
                            "hash": item["hash"],
                            "name": item.get("name") or f"Card {idx}"
                        })
                save_cards_metadata(res)
            LEGACY_STORE_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    if CARDS_STORE_PATH.is_file():
        try:
            data = json.loads(CARDS_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                res = []
                for idx, item in enumerate(data, 1):
                    if isinstance(item, str):
                        res.append({"hash": item, "name": f"Card {idx}"})
                    elif isinstance(item, dict) and "hash" in item:
                        res.append({
                            "hash": item["hash"],
                            "name": item.get("name") or f"Card {idx}"
                        })
                return res
        except Exception:
            pass
    return []


def save_cards_metadata(cards: list[dict[str, str]]) -> None:
    seen = set()
    unique = []
    for c in cards:
        h = c.get("hash")
        if h and h not in seen:
            seen.add(h)
            unique.append({"hash": h, "name": c.get("name", "")})
    try:
        CARDS_STORE_PATH.write_text(json.dumps(unique, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_saved_cards() -> list[str]:
    meta = load_saved_cards_metadata()
    return [c["hash"] for c in meta]


def save_cards(cards: list[str]) -> None:
    existing = {c["hash"]: c["name"] for c in load_saved_cards_metadata()}
    meta = []
    for idx, h in enumerate(cards, 1):
        meta.append({"hash": h, "name": existing.get(h, f"Card {idx}")})
    save_cards_metadata(meta)


def extract_card_hash_from_line(line: str) -> Optional[str]:
    lower = line.lower()
    if not any(k in lower for k in WALLET_KEYWORDS):
        return None
    if not any(k in lower for k in CONTEXT_KEYWORDS):
        return None

    for r in CARD_REGEXES:
        m = r.search(line)
        if m:
            h = m.group(1).strip().strip("'\"").rstrip(".").rstrip(",")
            if len(h) == 36 and "-" in h:
                continue
            if h in DUMMY_HASHES:
                continue
            if len(h) >= 20:
                return h
    return None


async def start_card_scan_session(
    udid: Optional[str] = None,
    on_card_found: Optional[Callable[[str, int], None]] = None,
    stop_event: Optional[asyncio.Event] = None
) -> list[str]:
    from pymobiledevice3.services.syslog import SyslogService

    lockdown = await get_lockdown_client(udid)
    known_cards: Set[str] = set(load_saved_cards())

    try:
        async with SyslogService(lockdown) as syslog:
            async for entry in syslog.watch():
                if stop_event and stop_event.is_set():
                    break

                line = entry if isinstance(entry, str) else entry.decode("utf-8", errors="replace")
                card_hash = extract_card_hash_from_line(line)

                if card_hash and card_hash not in known_cards:
                    known_cards.add(card_hash)
                    card_name = extract_card_name_from_line(line) or f"Card {len(known_cards)}"
                    meta = load_saved_cards_metadata()
                    meta.append({"hash": card_hash, "name": card_name})
                    save_cards_metadata(meta)
                    if on_card_found:
                        try:
                            on_card_found(card_hash, len(known_cards), card_name)
                        except TypeError:
                            on_card_found(card_hash, len(known_cards))
                    if stop_event:
                        stop_event.set()
                    break
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    return list(known_cards)
