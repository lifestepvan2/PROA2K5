"""Map small team icons (Start Game screen, 32x32 '-00001553' dumps) to NBA team slots.

Uses the screenshots of texture_scan_run.py (right team slot = 9 + k, left team slot 15).
The icon belongs to the NBA team slot (independent of which ProA team sits there); k = -9..20 covers slots 0-29.
Output: data/texture_map/team_icons.csv (nba_slot, nba_team, key, score)
"""
import csv
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from texture_scan import DUMPS  # noqa: E402

ICON_BOX = {0: (398, 339, 466, 389), 1: (398, 634, 466, 684)}  # row -> inner crop of the on-screen icon (col 0)
ICON_BOX_NEW = (424, 626, 490, 676)  # right-team icon in the k9..k20 scans
TEX_WIN = (4, 5, 28, 27)  # part of the 32x32 texture that is visible on screen
OUT = ROOT / "data/texture_map/team_icons.csv"


def vec(im):
    a = np.asarray(im.convert("RGB").resize((40, 40), Image.LANCZOS), float).ravel()
    a -= a.mean()
    return a / (np.linalg.norm(a) + 1e-9)


def main():
    keys, vecs = [], []
    for f in Path(DUMPS).glob("*-00001553.png"):
        im = Image.open(f)
        if im.size == (32, 32):
            keys.append(f.stem)
            vecs.append(vec(im.crop(TEX_WIN)))
    vecs = np.array(vecs)
    names = {}
    for r in csv.DictReader(open(ROOT / "data/texture_map/logo_refs.csv", encoding="utf-8")):
        names[int(r["team_slot"])] = r["team"]
    found = {}
    if OUT.exists():  # keep earlier results, new scans only overwrite with a better score
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            found[int(r["nba_slot"])] = (r["key"], float(r["score"]))
    for shot in sorted((ROOT / "docs/_scans").glob("k*.png")):
        k = int(re.match(r"k(-?\d+)", shot.stem).group(1))
        s = Image.open(shot).convert("RGB")
        # scans k>=9 were taken with a shifted window; their left team (slot 15) shows a replaced icon
        targets = ((1, 9 + k),) if k >= 9 else ((1, 9 + k), (0, 15))
        for row, slot in targets:
            sc = vecs @ vec(s.crop(ICON_BOX_NEW if k >= 9 else ICON_BOX[row]))
            i = int(sc.argmax())
            if 0 <= slot <= 29 and (slot not in found or sc[i] > found[slot][1]):
                found[slot] = (keys[i], float(sc[i]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["nba_slot", "nba_team", "key", "score"])
        for slot in sorted(found):
            w.writerow([slot, names[slot], found[slot][0], round(found[slot][1], 3)])
            print(slot, names[slot], found[slot])
    print(len({v[0] for v in found.values()}), "unique keys for", len(found), "teams")


if __name__ == "__main__":
    main()
