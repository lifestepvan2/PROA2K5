"""Shared helpers for the PCSX2 texture tools (dump folder access, PS2-alpha aware loading)."""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
TEX_ROOT = Path.home() / "Documents/PCSX2/textures/SLES-53022"
DUMP_DIRS = [TEX_ROOT / "dumps", TEX_ROOT / "bu"]  # bu = older, larger dump session
REPL_DIR = TEX_ROOT / "replacements"
FACE_FAMILIES = {"00001dd3", "00001dd4"}


def family(key):
    return key.split("-")[-1]


def dump_files():
    """key -> path over all dump folders (first folder wins)."""
    out = {}
    for d in DUMP_DIRS:
        if d.is_dir():
            for p in d.glob("*.png"):
                out.setdefault(p.stem, p)
    return out


def load_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def over_white(rgba, bg=255):
    """Composite a dump over a flat background. PS2 alpha is 0..128 (128 = opaque)."""
    a = np.clip(rgba[..., 3:].astype(np.float32) / 128, 0, 1)
    return (rgba[..., :3] * a + bg * (1 - a)).astype(np.uint8)


def load_white(path, bg=255):
    return over_white(load_rgba(path), bg)
