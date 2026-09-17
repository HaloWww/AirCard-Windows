"""
Image processing utilities for AirCard Windows.
"""
from pathlib import Path
import io
from PIL import Image, ImageOps
from .config import TARGET_SIZE


def prepare_card_skin(input_path: str | Path) -> bytes:
    path = Path(input_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Card image file not found: {path}")

    with Image.open(path) as img:
        img = img.convert("RGBA")
        fitted = ImageOps.fit(img, TARGET_SIZE, method=Image.Resampling.LANCZOS)
        out_buf = io.BytesIO()
        fitted.save(out_buf, format="PNG", optimize=True)
        return out_buf.getvalue()


def save_prepared_skin(input_path: str | Path, output_path: str | Path) -> Path:
    data = prepare_card_skin(input_path)
    out = Path(output_path)
    out.write_bytes(data)
    return out
