"""Locate a dumped texture's palette/pixels in live PS2 RAM (to find where the game keeps per-player face assets).

Usage: python scripts/head_ram_probe.py <dump key>
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fast_scan import read_ps2_ram  # noqa: E402

DUMPS = Path(r"C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\dumps")


def load(key):
    im = np.array(Image.open(DUMPS / f"{key}.png").convert("RGBA"))
    return im


def palette_hits(ram, im, min_frac=0.9):
    flat = im.reshape(-1, 4)
    words = flat.view("<u4").ravel()
    uniq = np.unique(words)
    ram_w = np.frombuffer(ram, dtype="<u4")
    inset = np.isin(ram_w, uniq)
    # sliding count of in-set words over a 256 entry window
    c = np.concatenate([[0], np.cumsum(inset)])
    win = c[256:] - c[:-256]
    idx = np.where(win >= int(256 * min_frac))[0]
    return uniq, idx


if __name__ == "__main__":
    key = sys.argv[1]
    im = load(key)
    print("size", im.shape, "unique colors", len(np.unique(im.reshape(-1, 4).view("<u4"))), "alpha max", im[..., 3].max())
    ram = read_ps2_ram()
    uniq, idx = palette_hits(ram, im)
    print("hits", len(idx))
    for i in idx[:20]:
        print(hex(i * 4))
