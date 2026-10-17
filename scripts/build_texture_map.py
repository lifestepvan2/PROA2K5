"""Match the saved Start Game screenshots (docs/_scans/k*.png) against the full dump corpus.

Right-side team slot = 9 + k; the left team (slot 15) appears in every shot and is used as a repeat
check. Lineup position = starter index (PG, SG, SF, PF, C) from data/roster_build/player_map.csv.
Output: data/texture_map/starter_faces.csv (team_slot, starter, record, name, key, votes, score)
Usage: python scripts/build_texture_map.py
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import texture_scan as ts  # noqa: E402

START_SLOT, LEFT_SLOT = 9, 15


def main():
    players = {(int(r["team_slot"]), int(r["slot"])): r
               for r in csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8"))}
    keys, vecs = ts.load_corpus()
    print(len(keys), "face dumps")
    votes = defaultdict(list)
    for shot in sorted((ROOT / "docs/_scans").glob("k*.png")):
        k = int(re.match(r"k(-?\d+)", shot.stem).group(1))
        slot = START_SLOT + k
        faces = ts.match_screen(Image.open(shot).convert("RGB"), keys, vecs)
        for c in range(5):
            votes[(LEFT_SLOT, c)].append(faces[(0, c)][:2])
            if 0 <= slot <= 17:
                votes[(slot, c)].append(faces[(1, c)][:2])
    out, keyuse = [], defaultdict(list)
    for (slot, c), v in sorted(votes.items()):
        key, cnt = Counter(k for k, _ in v).most_common(1)[0]
        score = sum(s for k, s in v if k == key) / cnt
        p = players[(slot, c)]
        out.append({"team_slot": slot, "starter": c, "record": p["record"], "name": f"{p['first']} {p['last']}",
                    "key": key, "votes": f"{cnt}/{len(v)}", "score": round(score, 3)})
        keyuse[key].append((slot, c))
    with open(ROOT / "data/texture_map/starter_faces.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(len(out), "starters;", len({o["team_slot"] for o in out}), "teams")
    for key, users in keyuse.items():
        if len(users) > 1:
            print("shared key", key, users)
    for o in out:
        a, b = o["votes"].split("/")
        if o["score"] < 0.9 or a != b:
            print("check", o)


if __name__ == "__main__":
    main()
