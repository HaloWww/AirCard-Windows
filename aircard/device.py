"""
Device detection and lockdown utilities using pymobiledevice3.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional


class DeviceDependencyError(RuntimeError):
    pass


def _pymobiledevice_api():
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.usbmux import list_devices
    except ImportError as exc:
        raise DeviceDependencyError(
            "缺少 iPhone 通信组件。请重新运行 AirCard 安装程序。"
        ) from exc
    return list_devices, create_using_usbmux


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
    list_devices, create_using_usbmux = _pymobiledevice_api()
    raw_devices = await list_devices()
    result = []
    for d in raw_devices:
        try:
            lockdown = await create_using_usbmux(serial=d.serial, connection_type=d.connection_type)
            try:
                values = await lockdown.get_value()
                result.append(ConnectedDevice(
                    udid=d.serial,
                    name=values.get("DeviceName", "iPhone"),
                    product_type=values.get("ProductType", "iPhone"),
                    ios_version=values.get("ProductVersion", "未知"),
                    build_version=values.get("BuildVersion", "未知"),
                    connection_type=d.connection_type or "USB",
                ))
            finally:
                close = getattr(lockdown, "close", None)
                if close:
                    result_value = close()
                    if asyncio.iscoroutine(result_value):
                        await result_value
        except Exception:
            result.append(ConnectedDevice(
                udid=d.serial,
                name="iPhone（已锁定或未信任）",
                product_type="iPhone",
                ios_version="未知",
                build_version="未知",
                connection_type=d.connection_type or "USB",
            ))
    return result


def get_first_device() -> Optional[ConnectedDevice]:
    devices = asyncio.run(get_connected_devices())
    return devices[0] if devices else None


async def get_lockdown_client(udid: Optional[str] = None):
    _, create_using_usbmux = _pymobiledevice_api()
    return await create_using_usbmux(serial=udid)


def get_lockdown_client_sync(udid: Optional[str] = None):
    return asyncio.run(get_lockdown_client(udid))
