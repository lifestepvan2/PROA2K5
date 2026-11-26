"""Serialize and atomically replace workspace image files."""
import io
import os
import tempfile
from pathlib import Path

from PIL import Image


def image_bytes(path: Path, image: Image.Image) -> bytes:
    fmt = Image.registered_extensions().get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"{path}: unsupported master format")
    if fmt == "JPEG":
        image = image.convert("RGB")
    content = io.BytesIO()
    image.save(content, format=fmt)
    return content.getvalue()


def replace(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp",
                                         delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
