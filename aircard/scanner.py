"""
Live Apple Wallet card scanner for Windows via pymobiledevice3 syslog.
"""
from typing import Callable, Optional, Set
from pathlib import Path
import asyncio
import json
from .config import CARDS_STORE_PATH, LEGACY_STORE_PATH, CARD_REGEXES, APP_ROOT_DIR
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


from collections import deque
import re

DESC_PATTERNS = [
    re.compile(r'(?:organizationName|organization|issuerName|issuer|bankName)\s*[:=]\s*["\']?([^"\'\n,;]{2,40})["\']?', re.IGNORECASE),
    re.compile(r'(?:passDescription|description|localizedDescription|passName|cardDisplayName|cardName|title)\s*[:=]\s*["\']?([^"\'\n,;]{2,40})["\']?', re.IGNORECASE),
    re.compile(r'Pass\s+<[^>]+>\s+\(([^)]{2,40})\)', re.IGNORECASE),
]

SUFFIX_PATTERNS = [
    re.compile(r'(?:primaryAccountSuffix|dpanSuffix|fpanSuffix|sanitizedPan|suffix|last4)\s*[:=]\s*["\']?[•\s*]*([0-9]{4})["\']?', re.IGNORECASE),
    re.compile(r'(?:••••|•{4}|\*{4})\s*([0-9]{4})'),
]

KNOWN_ISSUERS = [
    "Freedom Bank", "Freedom", "Bybit", "Kaspi", "Halyk", "BCC", "Jusan",
    "Tinkoff", "T-Bank", "Sberbank", "Sber", "Alfa-Bank", "Alfa", "VTB", "Raiffeisen",
    "Monobank", "PrivatBank", "Revolut", "Wise", "Chase", "Bank of America",
    "Wells Fargo", "Citi", "Capital One", "Amex", "American Express", "Apple Card", "Apple Cash",
    "Suica", "Pasmo", "ICOCA", "Octopus", "Metrolinx", "PRESTO", "TTC", "Oyster", "Navigo"
]


def extract_smart_card_name(lines: list[str]) -> Optional[str]:
    """Analyze a buffer of recent syslog lines to reconstruct the clean card name and suffix."""
    found_org: Optional[str] = None
    found_suffix: Optional[str] = None

    joined = "\n".join(lines)

    # 1. Search for 4-digit card suffix
    for p in SUFFIX_PATTERNS:
        m = p.search(joined)
        if m:
            found_suffix = m.group(1).strip()
            break

    # 2. Check for known banks/issuers
    for issuer in KNOWN_ISSUERS:
        if re.search(r'\b' + re.escape(issuer) + r'\b', joined, re.IGNORECASE):
            found_org = issuer
            break

    # 3. If no known issuer, extract from formal descriptors
    if not found_org:
        for p in DESC_PATTERNS:
            m = p.search(joined)
            if m:
                cand = m.group(1).strip()
                if len(cand) > 1 and "<private>" not in cand.lower() and "paymentpass" not in cand.lower():
                    found_org = cand
                    break

    # 4. Construct human-friendly label
    if found_org and found_suffix:
        return f"{found_org} (•••• {found_suffix})"
    elif found_org:
        return found_org
    elif found_suffix:
        return f"Card (•••• {found_suffix})"

    return None


def extract_card_name_from_line(line: str) -> Optional[str]:
    return extract_smart_card_name([line])


def import_cards_from_sqlite(db_path: Path | str) -> list[dict[str, str]]:
    """Extract all cards with real organization names and suffixes from passes23.sqlite."""
    db_file = Path(db_path).resolve()
    if not db_file.is_file():
        return []
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_file))
        c = conn.cursor()
        rows = c.execute("""
            SELECT unique_id, organization_name, primary_account_suffix 
            FROM pass 
            WHERE unique_id IS NOT NULL
        """).fetchall()
        conn.close()

        cards = []
        for uid, org, suffix in rows:
            if not uid:
                continue
            if org and suffix:
                name = f"{org} (•••• {suffix})"
            elif org:
                name = org
            elif suffix:
                name = f"Card (•••• {suffix})"
            else:
                name = "Apple Pay Card"
            cards.append({"hash": uid, "name": name})
        return cards
    except Exception:
        return []


def find_local_passes_sqlite() -> Optional[Path]:
    """Look for passes23.sqlite in the app root directory if provided by user."""
    candidates = [
        APP_ROOT_DIR / "passes23.sqlite",
    ]
    for p in candidates:
        if p.is_file():
            return p
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

    res = []
    if CARDS_STORE_PATH.is_file():
        try:
            data = json.loads(CARDS_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for idx, item in enumerate(data, 1):
                    if isinstance(item, str):
                        res.append({"hash": item, "name": f"Card {idx}"})
                    elif isinstance(item, dict) and "hash" in item:
                        res.append({
                            "hash": item["hash"],
                            "name": item.get("name") or f"Card {idx}"
                        })
        except Exception:
            pass

    # Auto-enrich from local passes23.sqlite if available
    db_path = find_local_passes_sqlite()
    if db_path:
        db_cards = import_cards_from_sqlite(db_path)
        db_map = {c["hash"]: c["name"] for c in db_cards}

        updated = False
        # Enrich existing cards that have generic names
        for c in res:
            if c["hash"] in db_map:
                if not c.get("name") or c.get("name").startswith("Card "):
                    c["name"] = db_map[c["hash"]]
                    updated = True

        # Add any new cards from db not yet in list
        existing_hashes = {c["hash"] for c in res}
        for db_c in db_cards:
            if db_c["hash"] not in existing_hashes:
                res.append(db_c)
                existing_hashes.add(db_c["hash"])
                updated = True

        if updated:
            save_cards_metadata(res)

    return res


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
    on_card_found: Optional[Callable[[str, int, str], None]] = None,
    stop_event: Optional[asyncio.Event] = None
) -> list[str]:
    from pymobiledevice3.services.syslog import SyslogService

    lockdown = await get_lockdown_client(udid)
    known_cards: Set[str] = set(load_saved_cards())
    rolling_buffer = deque(maxlen=30)
    pending_hash: Optional[str] = None
    collect_countdown = 0

    try:
        async with SyslogService(lockdown) as syslog:
            async for entry in syslog.watch():
                if stop_event and stop_event.is_set():
                    break

                line = entry if isinstance(entry, str) else entry.decode("utf-8", errors="replace")
                rolling_buffer.append(line)

                if pending_hash:
                    collect_countdown -= 1
                    if collect_countdown <= 0:
                        card_name = extract_smart_card_name(list(rolling_buffer)) or f"Card {len(known_cards)}"
                        meta = load_saved_cards_metadata()
                        meta.append({"hash": pending_hash, "name": card_name})
                        save_cards_metadata(meta)
                        if on_card_found:
                            try:
                                on_card_found(pending_hash, len(known_cards), card_name)
                            except TypeError:
                                on_card_found(pending_hash, len(known_cards))
                        if stop_event:
                            stop_event.set()
                        break
                    continue

                card_hash = extract_card_hash_from_line(line)
                if card_hash and card_hash not in known_cards:
                    known_cards.add(card_hash)
                    pending_hash = card_hash
                    # Gather 6 more syslog lines to ensure we capture full passd context
                    collect_countdown = 6
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    return list(known_cards)
