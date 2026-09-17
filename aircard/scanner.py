"""
Live Apple Wallet card scanner for Windows via pymobiledevice3 syslog.
"""
from typing import Callable, Optional, Set
import asyncio
import json
from .config import CARDS_STORE_PATH, CARD_REGEXES
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


def load_saved_cards() -> list[str]:
    if CARDS_STORE_PATH.is_file():
        try:
            data = json.loads(CARDS_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_cards(cards: list[str]) -> None:
    unique = list(dict.fromkeys(cards))
    try:
        CARDS_STORE_PATH.write_text(json.dumps(unique, indent=2), encoding="utf-8")
    except Exception:
        pass


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
                    card_list = list(known_cards)
                    save_cards(card_list)
                    if on_card_found:
                        on_card_found(card_hash, len(known_cards))
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    return list(known_cards)
