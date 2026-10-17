"""Map small team icons (Start Game screen, 32x32 '-00001553' dumps) to team slots.

Uses the same screenshots as build_texture_map.py (right team slot = 9 + k, left team slot 15).
Output: data/texture_map/team_icons.csv (team_slot, team, key, score)
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
TEX_WIN = (4, 5, 28, 27)  # part of the 32x32 texture that is visible on screen


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
    teams = {int(r["team_slot"]): r["sheet"] for r in csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8"))}
    found = {}
    for shot in sorted((ROOT / "docs/_scans").glob("k*.png")):
        k = int(re.match(r"k(-?\d+)", shot.stem).group(1))
        s = Image.open(shot).convert("RGB")
        for row, slot in ((1, 9 + k), (0, 15)):
            sc = vecs @ vec(s.crop(ICON_BOX[row]))
            i = int(sc.argmax())
            if 0 <= slot <= 17 and (slot not in found or sc[i] > found[slot][1]):
                found[slot] = (keys[i], float(sc[i]))
    with open(ROOT / "data/texture_map/team_icons.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team_slot", "team", "key", "score"])
        for slot in sorted(found):
            w.writerow([slot, teams[slot], found[slot][0], round(found[slot][1], 3)])
            print(slot, teams[slot], found[slot])
    print(len({v[0] for v in found.values()}), "unique keys for", len(found), "teams")


if __name__ == "__main__":
    main()
