"""
Device detection and lockdown utilities using pymobiledevice3.
"""
from dataclasses import dataclass
import asyncio
from typing import Optional
from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.lockdown import create_using_usbmux, UsbmuxLockdownClient


@dataclass
class ConnectedDevice:
    udid: str
    name: str
    product_type: str
    ios_version: str
    build_version: str
    connection_type: str

    def __str__(self) -> str:
        return f"{self.name} ({self.product_type}, iOS {self.ios_version} [{self.build_version}])"


async def get_connected_devices() -> list[ConnectedDevice]:
    raw_devices = await list_devices()
    result = []
    for d in raw_devices:
        try:
            lockdown = await create_using_usbmux(serial=d.serial, connection_type=d.connection_type)
            values = await lockdown.get_value()
            result.append(ConnectedDevice(
                udid=d.serial,
                name=values.get("DeviceName", "iPhone"),
                product_type=values.get("ProductType", "iPhone"),
                ios_version=values.get("ProductVersion", "Unknown"),
                build_version=values.get("BuildVersion", "Unknown"),
                connection_type=d.connection_type or "USB",
            ))
        except Exception:
            result.append(ConnectedDevice(
                udid=d.serial,
                name="iPhone (Locked or Untrusted)",
                product_type="iPhone",
                ios_version="Unknown",
                build_version="Unknown",
                connection_type=d.connection_type or "USB",
            ))
    return result


def get_first_device() -> Optional[ConnectedDevice]:
    devices = asyncio.run(get_connected_devices())
    return devices[0] if devices else None


async def get_lockdown_client(udid: Optional[str] = None) -> UsbmuxLockdownClient:
    return await create_using_usbmux(serial=udid)


def get_lockdown_client_sync(udid: Optional[str] = None) -> UsbmuxLockdownClient:
    return asyncio.run(create_using_usbmux(serial=udid))
