"""
Specialized 3D Metal shader flasher for Apple Cash and Apple Card.
Handles diffuse, metalness, normal maps, and watch assets.
"""
from typing import Callable, Optional
from pathlib import Path
import io
import asyncio
from PIL import Image, ImageOps

from .core_flasher import write_system_file_async, invalidate_card_cache_async
from .device import get_lockdown_client
from .image_util import draw_cardholder_name


APPLE_CASH_FACTORY_URLS = {
    "diffuse@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/874f9418715846ff9fe9ed53331cbbaa",
    "diffuse@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/fb3434540446493e9b8f04ff5849b2b4",
    "diffuseArmed@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/93c368087fc24b44b8eca1b80996f3d9",
    "diffuseArmed@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/2f670eca736e4f54bdd5def881361516",
    "metalness@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/d4485331eac6427e92d0c662a3bec244",
    "metalness@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/82458a3b9aaa4cfba7c76c4ca6703bbd",
    "metalnessArmed@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/330ef1a4e775469b8776c20048e45a9d",
    "metalnessArmed@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/17dd936bb32b4dd8a481c0e1e5a0bf28",
    "normal@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/42cc577d32a24efdb5cb0694bcb31c5f",
    "normal@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/53b1115dffa645c5bbaf90ebd77802ad",
    "normalArmed@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/9c0643448300419c8fb5868d9b63ba38",
    "normalArmed@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/a4118224bac94cbbbd99efa7c1d91db3",
    "cardBackgroundCombined@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/eea8087f996d4feeace209f5bf818503",
    "cardBackgroundCombined@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/fef59b6f304a490cbe7a31ba6eb64737",
    "logo@3x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/af5507180af8438bb2a709ed62e30563",
    "logo@2x.png": "https://pr-pod12-smp-device-asset.apple.com:443/broker/v1/assets/28165afee77b41f6b86c393957737864",
}


_CACHED_OFFICIAL_LOGOS: dict[str, bytes] = {}


def get_official_apple_cash_logo(asset_name: str) -> Optional[bytes]:
    """Fetch official Apple Cash logo asset from Apple CDN broker with caching."""
    global _CACHED_OFFICIAL_LOGOS
    if asset_name in _CACHED_OFFICIAL_LOGOS:
        return _CACHED_OFFICIAL_LOGOS[asset_name]
    url = APPLE_CASH_FACTORY_URLS.get(asset_name)
    if not url:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Passbook/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
            _CACHED_OFFICIAL_LOGOS[asset_name] = data
            return data
    except Exception:
        return None




def generate_custom_apple_cash_logo(
    icon_mode: str = "apple",  # "apple", "custom", "none", "clean_all"
    custom_icon_bytes: Optional[bytes] = None,
    text: Optional[str] = None,
) -> tuple[bytes, bytes]:
    """Generate both (logo@3x, logo@2x) combining an optional icon (Apple  or custom avatar/photo)
    with a custom nickname/text. Allows both icon AND nickname together!"""
    from .image_util import get_transparent_pixel_png

    clean_text = (text or "").strip()
    if icon_mode == "clean_all" or (icon_mode == "none" and not clean_text):
        tp = get_transparent_pixel_png()
        return tp, tp

    # If pure default apple watermark with no custom text
    if icon_mode == "apple" and not clean_text:
        off3x = get_official_apple_cash_logo("logo@3x.png")
        off2x = get_official_apple_cash_logo("logo@2x.png")
        if off3x and off2x:
            return off3x, off2x

    from PIL import ImageDraw, ImageFont
    import os

    canvas = Image.new("RGBA", (384, 126), (0, 0, 0, 0))
    x_cursor = 52

    # 1. Place icon (Apple  or custom user photo/avatar)
    if icon_mode == "apple":
        off3x = get_official_apple_cash_logo("logo@3x.png")
        if off3x:
            try:
                off_im = Image.open(io.BytesIO(off3x)).convert("RGBA")
                apple_crop = off_im.crop((54, 52, 104, 122))
                canvas.paste(apple_crop, (x_cursor, 52), apple_crop)
                x_cursor += apple_crop.width + 8
            except Exception:
                pass
    elif icon_mode == "custom" and custom_icon_bytes:
        try:
            custom_im = Image.open(io.BytesIO(custom_icon_bytes)).convert("RGBA")
            custom_im.thumbnail((54, 54), Image.Resampling.LANCZOS)
            mask = Image.new("L", custom_im.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle((0, 0, custom_im.size[0], custom_im.size[1]), radius=10, fill=255)
            y_pos = 52 + max(0, (62 - custom_im.height) // 2)
            canvas.paste(custom_im, (x_cursor, y_pos), mask)
            x_cursor += custom_im.width + 12
        except Exception:
            pass

    # 2. Place nickname / text next to the icon
    if clean_text:
        font_paths = [
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\tahomabd.ttf",
        ]
        font_file = next((p for p in font_paths if os.path.isfile(p)), None)
        avail_w = 374 - x_cursor
        size = 40 if x_cursor > 52 else 44
        while size > 14:
            try:
                font = ImageFont.truetype(font_file, size) if font_file else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()
                break
            dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            bbox = dummy.textbbox((0, 0), clean_text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            if tw <= avail_w and th <= 60:
                break
            size -= 2

        draw = ImageDraw.Draw(canvas)
        ty = 52 + max(0, (60 - th) // 2)
        draw.text((x_cursor, ty), clean_text, fill=(255, 255, 255, 255), font=font)

    # Save @3x PNG
    buf3x = io.BytesIO()
    canvas.save(buf3x, format="PNG")
    logo_3x = buf3x.getvalue()

    # Save @2x PNG (262x86)
    l2x_im = canvas.resize((262, 86), Image.Resampling.LANCZOS)
    buf2x = io.BytesIO()
    l2x_im.save(buf2x, format="PNG")
    logo_2x = buf2x.getvalue()

    return logo_3x, logo_2x


def prepare_apple_cash_assets(
    skin_bytes: bytes,
    metalness_level: int = 210,
    smooth_surface: bool = False,
    clean_logo: bool = False,
    rainbow_effect: bool = True,
    mode: str = "rainbow",
    icon_mode: str = "apple",
    custom_icon_bytes: Optional[bytes] = None,
    custom_logo_text: Optional[str] = None,
    cardholder_name_text: Optional[str] = None,
    logo_mode: str = "apple",  # backwards compat
    custom_logo_bytes: Optional[bytes] = None,  # backwards compat
) -> dict[str, bytes]:
    img = Image.open(io.BytesIO(skin_bytes)).convert("RGB")
    img = ImageOps.fit(img, (1536, 969), method=Image.Resampling.LANCZOS)

    # Optional cardholder name embossed at the bottom
    if cardholder_name_text and cardholder_name_text.strip():
        img = draw_cardholder_name(img, cardholder_name_text.strip())

    # 1. 2D fallback backgrounds (1536x969 and 1024x646)
    bg_3x = img
    b3x_buf = io.BytesIO()
    bg_3x.save(b3x_buf, format="PNG", optimize=True)

    bg_2x = ImageOps.fit(img, (1024, 646), method=Image.Resampling.LANCZOS)
    b2x_buf = io.BytesIO()
    bg_2x.save(b2x_buf, format="PNG", optimize=True)

    # 2. 3D Metal diffuse maps (@3x: 1146x720, @2x: 764x480)
    diffuse_3x = ImageOps.fit(img, (1146, 720), method=Image.Resampling.LANCZOS)
    diff3x_buf = io.BytesIO()
    diffuse_3x.save(diff3x_buf, format="PNG", optimize=True)
    diff3x_bytes = diff3x_buf.getvalue()

    diffuse_2x = ImageOps.fit(img, (764, 480), method=Image.Resampling.LANCZOS)
    diff2x_buf = io.BytesIO()
    diffuse_2x.save(diff2x_buf, format="PNG", optimize=True)
    diff2x_bytes = diff2x_buf.getvalue()

    # 3. Metalness map: Controls gyroscope rainbow iridescent intensity
    if mode == "matte" or (not rainbow_effect and mode == "rainbow"):
        val = 0
    elif mode == "rainbow":
        val = 210
    else:  # custom
        val = max(0, min(255, metalness_level))

    metal_val = (val, val, val)

    metal_3x_img = Image.new("RGB", (1146, 720), metal_val)
    metal_3x_buf = io.BytesIO()
    metal_3x_img.save(metal_3x_buf, format="PNG")
    metal_3x_bytes = metal_3x_buf.getvalue()

    metal_2x_img = Image.new("RGB", (764, 480), metal_val)
    metal_2x_buf = io.BytesIO()
    metal_2x_img.save(metal_2x_buf, format="PNG")
    metal_2x_bytes = metal_2x_buf.getvalue()

    assets = {
        "cardBackgroundCombined@3x.png": b3x_buf.getvalue(),
        "cardBackgroundCombined@2x.png": b2x_buf.getvalue(),
        "diffuse@3x.png": diff3x_bytes,
        "diffuse@2x.png": diff2x_bytes,
        "diffuseArmed@3x.png": diff3x_bytes,
        "diffuseArmed@2x.png": diff2x_bytes,
        "metalness@3x.png": metal_3x_bytes,
        "metalness@2x.png": metal_2x_bytes,
        "metalnessArmed@3x.png": metal_3x_bytes,
        "metalnessArmed@2x.png": metal_2x_bytes,
    }

    # 4. Smooth Surface: Normal map override (removes Apple logo 3D stamp)
    if smooth_surface:
        flat_val = (128, 128, 255)
        norm_3x = Image.new("RGB", (1146, 720), flat_val)
        n3x_buf = io.BytesIO()
        norm_3x.save(n3x_buf, format="PNG")
        n3x_bytes = n3x_buf.getvalue()

        norm_2x = Image.new("RGB", (764, 480), flat_val)
        n2x_buf = io.BytesIO()
        norm_2x.save(n2x_buf, format="PNG")
        n2x_bytes = n2x_buf.getvalue()

        assets["normal@3x.png"] = n3x_bytes
        assets["normal@2x.png"] = n2x_bytes
        assets["normalArmed@3x.png"] = n3x_bytes
        assets["normalArmed@2x.png"] = n2x_bytes

    # 5. Logo & Branding handling (top-left corner overlay)
    eff_icon_mode = "clean_all" if clean_logo else (icon_mode or logo_mode or "apple")
    eff_icon_bytes = custom_icon_bytes if custom_icon_bytes is not None else custom_logo_bytes

    logo_3x, logo_2x = generate_custom_apple_cash_logo(
        icon_mode=eff_icon_mode,
        custom_icon_bytes=eff_icon_bytes,
        text=custom_logo_text,
    )
    if logo_3x and logo_2x:
        assets["logo@3x.png"] = logo_3x
        assets["logo@2x.png"] = logo_2x

    return assets


async def flash_apple_cash_async(
    udid: Optional[str],
    card_hash: str,
    skin_bytes: bytes,
    mode: str = "rainbow",
    metalness_level: int = 210,
    smooth_surface: bool = False,
    clean_logo: bool = False,
    rainbow_effect: bool = True,
    icon_mode: str = "apple",
    custom_icon_bytes: Optional[bytes] = None,
    custom_logo_text: Optional[str] = None,
    cardholder_name_text: Optional[str] = None,
    logo_mode: str = "apple",
    custom_logo_bytes: Optional[bytes] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> bool:
    lockdown = await get_lockdown_client(udid)
    actual_udid = udid or lockdown.identifier
    pkpass_dir = f"/var/mobile/Library/Passes/Cards/{card_hash}.pkpass"

    if progress_callback:
        progress_callback(1, 20, "Generating 3D Metal shader textures & branding...")

    eff_icon_mode = icon_mode or logo_mode or "apple"
    eff_icon_bytes = custom_icon_bytes if custom_icon_bytes is not None else custom_logo_bytes

    assets = await asyncio.to_thread(
        prepare_apple_cash_assets,
        skin_bytes,
        metalness_level=metalness_level,
        smooth_surface=smooth_surface,
        clean_logo=clean_logo,
        rainbow_effect=rainbow_effect,
        mode=mode,
        icon_mode=eff_icon_mode,
        custom_icon_bytes=eff_icon_bytes,
        custom_logo_text=custom_logo_text,
        cardholder_name_text=cardholder_name_text,
    )
    cache_steps = 3
    total_steps = len(assets) + cache_steps
    step = 0

    for asset_name, asset_payload in assets.items():
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, f"Writing 3D {asset_name}...")
        ok = await write_system_file_async(actual_udid, pkpass_dir, asset_name, asset_payload)
        if not ok:
            return False

    step = await invalidate_card_cache_async(
        actual_udid, card_hash, progress_callback, current_step=step, total_steps=total_steps
    )

    return True


async def revert_apple_cash_async(
    udid: Optional[str],
    card_hash: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> bool:
    """Restore official factory pristine Apple Cash assets from Apple CDN broker."""
    import urllib.request

    lockdown = await get_lockdown_client(udid)
    actual_udid = udid or lockdown.identifier
    pkpass_dir = f"/var/mobile/Library/Passes/Cards/{card_hash}.pkpass"

    total_assets = len(APPLE_CASH_FACTORY_URLS)
    cache_steps = 3
    total_steps = total_assets + cache_steps
    step = 0

    for asset_name, url in APPLE_CASH_FACTORY_URLS.items():
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, f"Downloading official {asset_name} from Apple...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Passbook/1.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                asset_data = resp.read()
            ok = await write_system_file_async(actual_udid, pkpass_dir, asset_name, asset_data)
            if not ok:
                return False
        except Exception as e:
            if progress_callback:
                progress_callback(step, total_steps, f"Download failed for {asset_name}: {e}")

    # Invalidate all caches across .cache and .pkcache
    step = await invalidate_card_cache_async(
        actual_udid, card_hash, progress_callback, current_step=step, total_steps=total_steps
    )

    return True
