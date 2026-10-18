"""Match loaded TXTR textures in a PS2 RAM snapshot to texture dump keys (exact RGBA compare against the dump PNGs).

Texture data header: +0x18 pixel ptr, +0x2C/+0x2E width/height (u16); PSMT8 pixels followed by a CSM1-swizzled palette.
Usage: python scripts/txtr_match.py [snapshot.bin]   -> data/texture_map/live_txtr.csv
"""
import csv
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from txtr_inventory import find_txtr, wstr  # noqa: E402

DUMPS = Path(r"C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\dumps")
SWZ = np.array([i ^ (((i >> 3) & 1) ^ ((i >> 4) & 1)) * 0x18 for i in range(256)])
NAMES = {"face", "arm", "neck", "hair"}
_cache = {}


def rgba_of(ram, pix, w, h):
    pal = np.frombuffer(ram, dtype="<u4", count=256, offset=pix + w * h)
    ind = np.frombuffer(ram, dtype=np.uint8, count=w * h, offset=pix).astype(int)
    return pal[SWZ[ind]].reshape(h, w)


def dump_hashes(size):
    """{rgba bytes: key} for every dump PNG of the given (w, h)."""
    if size not in _cache:
        out = {}
        for p in DUMPS.glob("*.png"):
            im = Image.open(p)
            if im.size == size:
                out[np.array(im.convert("RGBA")).tobytes()] = p.stem
        _cache[size] = out
    return _cache[size]


def match_ram(ram, names=NAMES):
    """Return [(obj, name, pix, w, h, key or '')] for the named TXTR objects in the snapshot."""
    rows = []
    for o, n, d in sorted(find_txtr(ram)):
        nm = wstr(ram, n)
        if nm not in names:
            continue
        pix = struct.unpack_from("<I", ram, d + 0x18)[0]
        w, h = struct.unpack_from("<HH", ram, d + 0x2C)
        key = ""
        if w * h and pix + w * h + 1024 <= len(ram):
            key = dump_hashes((w, h)).get(rgba_of(ram, pix, w, h).tobytes(), "")
        rows.append((f"{o:08x}", nm, f"{pix:08x}", w, h, key))
    return rows


if __name__ == "__main__":
    ram = open(sys.argv[1], "rb").read() if len(sys.argv) > 1 else open(ROOT / "docs/_snap.bin", "rb").read()
    rows = match_ram(ram)
    with open(ROOT / "data/texture_map/live_txtr.csv", "w", newline="") as f:
        w_ = csv.writer(f)
        w_.writerow(["obj", "name", "pix", "w", "h", "key"])
        w_.writerows(rows)
    print(len(rows), "textures,", sum(1 for r in rows if r[5]), "matched")
