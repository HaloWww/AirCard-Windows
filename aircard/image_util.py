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

