"""
Image processing utilities for AirCard Windows.
"""
from pathlib import Path
import io
from PIL import Image, ImageOps
from .config import TARGET_SIZE


def prepare_card_skin(source: str | Path | Image.Image | bytes | io.BytesIO) -> bytes:
    if isinstance(source, Image.Image):
        img = source
        should_close = False
    elif isinstance(source, (bytes, io.BytesIO)):
        buf = io.BytesIO(source) if isinstance(source, bytes) else source
        img = Image.open(buf)
        should_close = True
    else:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Card image file not found: {path}")
        img = Image.open(path)
        should_close = True

    try:
        img = img.convert("RGBA")
        fitted = ImageOps.fit(img, TARGET_SIZE, method=Image.Resampling.LANCZOS)
        out_buf = io.BytesIO()
        fitted.save(out_buf, format="PNG", optimize=True)
        return out_buf.getvalue()
    finally:
        if should_close:
            img.close()


def save_prepared_skin(input_path: str | Path, output_path: str | Path) -> Path:
    data = prepare_card_skin(input_path)
    out = Path(output_path)
    out.write_bytes(data)
    return out


def get_transparent_pixel_png() -> bytes:
    """Return a 1x1 32-bit RGBA transparent PNG bytes."""
    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def apply_holographic_foil(skin_bytes: bytes, intensity: float = 0.30) -> bytes:
    """Apply an iridescent 3D holographic rainbow foil sheen inspired by Apple Cash."""
    import math
    from PIL import ImageChops

    base = Image.open(io.BytesIO(skin_bytes)).convert("RGB")
    w, h = base.size

    gw, gh = 256, 160
    grad = Image.new("RGB", (gw, gh))
    pixels = grad.load()
    for y in range(gh):
        for x in range(gw):
            pos = (x / gw + y / gh) * 3.14159 * 3
            r = int(128 + 127 * math.sin(pos))
            g = int(128 + 127 * math.sin(pos + 2.094))
            b = int(128 + 127 * math.sin(pos + 4.188))
            pixels[x, y] = (r, g, b)

    grad = grad.resize((w, h), Image.Resampling.BILINEAR)
    blended = Image.blend(base, ImageChops.soft_light(base, grad), intensity)

    out = io.BytesIO()
    blended.save(out, format="PNG", optimize=True)
    return out.getvalue()


def draw_cardholder_name(source: Image.Image | bytes, name: str) -> Image.Image | bytes:
    """Emboss uppercase cardholder name in bottom-left corner of the card using official ISO/IEC 7813 OCR-A font."""
    import os
    from PIL import ImageDraw, ImageFont

    is_bytes = isinstance(source, bytes)
    if is_bytes:
        im = Image.open(io.BytesIO(source)).convert("RGBA")
    else:
        im = source.copy().convert("RGBA")

    clean_name = name.strip().upper()
    if not clean_name:
        return source

    font_paths = [
        r"C:\Windows\Fonts\ocraext.ttf",  # Classic ISO Credit Card OCR-A Extended font
        r"C:\Windows\Fonts\consolab.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ]
    font_file = next((p for p in font_paths if os.path.isfile(p)), None)

    w, h = im.size
    x = int(w * 0.072)
    y = int(h * 0.857)

    # Dynamic font scaling to ensure it fits comfortably in bottom left
    max_font_size = max(18, int(h * 0.042))
    min_font_size = max(12, int(h * 0.020))
    max_w = int(w * 0.55)
    max_h = int(h * 0.060)

    size = max_font_size
    while size > min_font_size:
        try:
            font = ImageFont.truetype(font_file, size) if font_file else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
            break
        dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = dummy.textbbox((0, 0), clean_name, font=font)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        if bw <= max_w and bh <= max_h:
            break
        size -= 2

    draw = ImageDraw.Draw(im)
    shadow_off = max(1, int(h * 0.002))

    # Authentic 3D embossed plastic effect:
    # 1. Dark bottom-right shadow
    draw.text((x + shadow_off, y + shadow_off), clean_name, fill=(0, 0, 0, 210), font=font)
    # 2. Specular top-left silver highlight
    draw.text((x - 1, y - 1), clean_name, fill=(255, 255, 255, 140), font=font)
    # 3. Main metallic foil text body
    draw.text((x, y), clean_name, fill=(242, 242, 246, 245), font=font)

    if is_bytes:
        out_buf = io.BytesIO()
        im.save(out_buf, format="PNG", optimize=True)
        return out_buf.getvalue()
    return im.convert("RGB")


