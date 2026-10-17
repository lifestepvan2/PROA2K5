"""Match the faces visible on the Start Game screen against the PCSX2 texture dumps.

The PCSX2 dump file name (`<hash>-<hash>-<family>.png`) is the key used for replacements.
The on-screen face shows only the (0,3)-(102,125) window of the 128x128 dump texture.
Start Game layout (capture 1934x1039 of the window): 2 rows x 5 starters.
Usage: python scripts/texture_scan.py [screenshot.png]   (default: docs/pcsx2_screen.png)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
DUMPS = Path.home() / "Documents/PCSX2/textures/SLES-53022/dumps"
FACE_FAMILY = "00001dd3"
N = 48
WIN = (0, 3, 102, 125)
COL_X = [182, 502, 822, 1142, 1462]
ROW_Y = [332, 625]
BOX_W, BOX_H = 202, 203
SHIFTS = range(-12, 13, 4)


def vec(img, size=N):
    g = np.asarray(img.convert("L").resize((size, size), Image.BOX), dtype=np.float32).ravel()
    g = g - g.mean()
    n = np.linalg.norm(g)
    return g / n if n else g


def load_corpus(family=FACE_FAMILY, folder=DUMPS):
    keys, vecs = [], []
    for f in sorted(folder.glob(f"*-{family}.png")):
        keys.append(f.stem)
        vecs.append(vec(Image.open(f).convert("RGB").crop(WIN)))
    return keys, np.array(vecs)


def match_cell(screen, x, y, keys, vecs):
    """Returns (key, score, runner_up_score) for the best shift."""
    best = (None, -1.0, -1.0)
    for dx in SHIFTS:
        for dy in SHIFTS:
            s = vecs @ vec(screen.crop((x + dx, y + dy, x + dx + BOX_W, y + dy + BOX_H)))
            i = int(np.argmax(s))
            if s[i] > best[1]:
                best = (keys[i], float(s[i]), float(np.partition(s, -2)[-2]))
    return best


def match_screen(screen, keys, vecs):
    """Returns {(row, col): (key, score, runner_up)}; row 0 = away team, row 1 = home team."""
    return {(r, c): match_cell(screen, x, y, keys, vecs)
            for r, y in enumerate(ROW_Y) for c, x in enumerate(COL_X)}


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/pcsx2_screen.png"
    scr = Image.open(path).convert("RGB")
    keys, vecs = load_corpus()
    print(len(keys), "face dumps")
    for cell, m in match_screen(scr, keys, vecs).items():
        print(cell, m[0], round(m[1], 3), round(m[2], 3))
