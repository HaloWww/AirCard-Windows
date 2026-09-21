"""
AirTrafficHost bridge for Windows via ctypes and iTunes support DLLs.
"""
from typing import Any, Callable, Iterable
import os
import time
import uuid
import plistlib
import ctypes
from .config import find_apple_dll_dir

kCFStringEncodingUTF8 = 0x08000100


class AirTrafficError(RuntimeError):
    """Base error for the proprietary Apple AirTraffic bridge."""


class MissingRemoteAssetError(AirTrafficError):
    """The device did not advertise one or more requested source assets."""

    def __init__(self, identifiers: list[str]):
        super().__init__(f"Remote assets were not present: {', '.join(identifiers)}")
        self.identifiers = identifiers


class CFBridge:
    def __init__(self, dll_dir: str):
        os.add_dll_directory(dll_dir)
        self.cf = ctypes.CDLL(os.path.join(dll_dir, "CoreFoundation.dll"))
        self.ath = ctypes.CDLL(os.path.join(dll_dir, "AirTrafficHost.dll"))
        self._bind()

    def _bind(self):
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p

        self.cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
        self.cf.CFStringGetLength.restype = ctypes.c_long

        self.cf.CFStringGetMaximumSizeForEncoding.argtypes = [ctypes.c_long, ctypes.c_uint32]
        self.cf.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long

        self.cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        self.cf.CFStringGetCString.restype = ctypes.c_bool

        self.cf.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
        self.cf.CFDataCreate.restype = ctypes.c_void_p

        self.cf.CFPropertyListCreateWithData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        self.cf.CFPropertyListCreateWithData.restype = ctypes.c_void_p

        self.cf.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
        self.cf.CFPropertyListCreateData.restype = ctypes.c_void_p

        self.cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        self.cf.CFDataGetBytePtr.restype = ctypes.c_void_p

        self.cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
        self.cf.CFDataGetLength.restype = ctypes.c_long

        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

        self.ath.ATHostConnectionCreate.argtypes = [ctypes.c_void_p]
        self.ath.ATHostConnectionCreate.restype = ctypes.c_void_p

        self.ath.ATHostConnectionRelease.argtypes = [ctypes.c_void_p]
        self.ath.ATHostConnectionRelease.restype = None

        self.ath.ATHostConnectionSendHostInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.ath.ATHostConnectionSendHostInfo.restype = None

        self.ath.ATHostConnectionSendSyncRequest.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.ath.ATHostConnectionSendSyncRequest.restype = None

        self.ath.ATHostConnectionSendMetadataSyncFinished.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.ath.ATHostConnectionSendMetadataSyncFinished.restype = None

        self.ath.ATHostConnectionSendAssetCompleted.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.ath.ATHostConnectionSendAssetCompleted.restype = None

        self.ath.ATHostConnectionReadMessage.argtypes = [ctypes.c_void_p]
        self.ath.ATHostConnectionReadMessage.restype = ctypes.c_void_p

        self.ath.ATCFMessageGetName.argtypes = [ctypes.c_void_p]
        self.ath.ATCFMessageGetName.restype = ctypes.c_void_p

        self.ath.ATCFMessageGetParam.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.ath.ATCFMessageGetParam.restype = ctypes.c_void_p

    def cf_string(self, s: str):
        return self.cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

    def py_string(self, cf_str) -> str:
        if not cf_str:
            return ""
        length = self.cf.CFStringGetLength(cf_str)
        max_size = self.cf.CFStringGetMaximumSizeForEncoding(length, kCFStringEncodingUTF8) + 1
        buf = ctypes.create_string_buffer(max_size)
        if self.cf.CFStringGetCString(cf_str, buf, max_size, kCFStringEncodingUTF8):
            return buf.value.decode("utf-8")
        return ""

    def cf_plist(self, obj: Any):
        data_bytes = plistlib.dumps(obj, fmt=plistlib.FMT_BINARY)
        cf_data = self.cf.CFDataCreate(None, data_bytes, len(data_bytes))
        plist = self.cf.CFPropertyListCreateWithData(None, cf_data, 0, None, None)
        self.cf.CFRelease(cf_data)
        return plist

    def py_plist(self, cf_obj) -> Any:
        if not cf_obj:
            return None
        cf_data = self.cf.CFPropertyListCreateData(None, cf_obj, 200, 0, None)
        if not cf_data:
            return None
        ptr = self.cf.CFDataGetBytePtr(cf_data)
        length = self.cf.CFDataGetLength(cf_data)
        raw_bytes = ctypes.string_at(ptr, length)
        self.cf.CFRelease(cf_data)
        return plistlib.loads(raw_bytes)


def sync_assets_via_airtraffic(
    udid: str,
    assets: Iterable[tuple[str, str]],
    timeout_sec: int = 45,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> bool:
    assets = list(assets)
    if not assets:
        return True
    dll_dir = find_apple_dll_dir()
    if not dll_dir:
            raise AirTrafficError(
                "Apple Mobile Device Support was not found. Install the 64-bit desktop iTunes package."
            )

    bridge = CFBridge(str(dll_dir))
    cf_udid = bridge.cf_string(udid)
    conn = bridge.ath.ATHostConnectionCreate(cf_udid)
    bridge.cf.CFRelease(cf_udid)

    if not conn:
        raise AirTrafficError(f"AirTraffic could not connect to device {udid}")

    try:
        sync_allowed = False
        for _ in range(8):
            msg = bridge.ath.ATHostConnectionReadMessage(conn)
            if not msg:
                time.sleep(0.1)
                continue
            name_ref = bridge.ath.ATCFMessageGetName(msg)
            name = bridge.py_string(name_ref)
            bridge.cf.CFRelease(msg)
            if name == "SyncAllowed":
                sync_allowed = True
                break

        if not sync_allowed:
            raise AirTrafficError("SyncAllowed was not received from the device")

        host_info_py = {
            "Type": "iTunes",
            "Version": "13.7.0.161",
            "MacOSVersion": "Windows NT 10.0",
            "SyncHostName": "airlift",
            "LibraryID": str(uuid.uuid4()),
            "SyncedDataclasses": ["Book"],
            "SyncedAssetTypes": ["Book"],
            "Wakeable": False,
        }
        cf_host_info = bridge.cf_plist(host_info_py)
        bridge.ath.ATHostConnectionSendHostInfo(conn, cf_host_info)
        time.sleep(0.2)

        cf_dataclasses = bridge.cf_plist(["Book"])
        cf_anchors = bridge.cf_plist({})
        bridge.ath.ATHostConnectionSendSyncRequest(conn, cf_dataclasses, cf_anchors, cf_host_info)
        bridge.cf.CFRelease(cf_dataclasses)
        bridge.cf.CFRelease(cf_anchors)
        bridge.cf.CFRelease(cf_host_info)

        ready_for_sync = False
        for _ in range(12):
            msg = bridge.ath.ATHostConnectionReadMessage(conn)
            if not msg:
                time.sleep(0.1)
                continue
            name_ref = bridge.ath.ATCFMessageGetName(msg)
            name = bridge.py_string(name_ref)
            bridge.cf.CFRelease(msg)
            if name == "ReadyForSync":
                ready_for_sync = True
                break

        if not ready_for_sync:
            raise AirTrafficError("ReadyForSync was not received from the device")

        cf_sync_types = bridge.cf_plist({"Book": 1})
        cf_empty_anchors = bridge.cf_plist({})
        bridge.ath.ATHostConnectionSendMetadataSyncFinished(conn, cf_sync_types, cf_empty_anchors)
        bridge.cf.CFRelease(cf_sync_types)
        bridge.cf.CFRelease(cf_empty_anchors)

        manifest_obj = None
        key_manifest = bridge.cf_string("AssetManifest")

        for _ in range(20):
            msg = bridge.ath.ATHostConnectionReadMessage(conn)
            if not msg:
                time.sleep(0.1)
                continue
            name_ref = bridge.ath.ATCFMessageGetName(msg)
            name = bridge.py_string(name_ref)
            if name == "AssetManifest":
                param = bridge.ath.ATCFMessageGetParam(msg, key_manifest)
                manifest_obj = bridge.py_plist(param)
                bridge.cf.CFRelease(msg)
                break
            elif name in ("SyncFailed", "SyncFinished"):
                bridge.cf.CFRelease(msg)
                break
            bridge.cf.CFRelease(msg)

        bridge.cf.CFRelease(key_manifest)

        if not manifest_obj or "Book" not in manifest_obj:
            raise AirTrafficError("The AirTraffic asset manifest was missing or empty")

        download_ids = {
            b["AssetID"] for b in manifest_obj.get("Book", [])
            if isinstance(b, dict) and b.get("IsDownload")
        }

        missing = [ident for ident, _ in assets if ident not in download_ids]
        if missing:
            raise MissingRemoteAssetError(missing)

        cf_dataclass = bridge.cf_string("Book")
        for idx, (ident, dest) in enumerate(assets):
            cf_ident = bridge.cf_string(ident)
            cf_dest = bridge.cf_string(dest)
            bridge.ath.ATHostConnectionSendAssetCompleted(conn, cf_ident, cf_dataclass, cf_dest)
            bridge.cf.CFRelease(cf_ident)
            bridge.cf.CFRelease(cf_dest)
            if progress_callback:
                progress_callback(idx + 1, len(assets), dest)
            if idx + 1 < len(assets):
                time.sleep(0.35 if idx else 0.55)

        bridge.cf.CFRelease(cf_dataclass)
        time.sleep(2.0)
        return True

    finally:
        bridge.ath.ATHostConnectionRelease(conn)
