"""Match the injected-starter screenshots (docs/_faces/b*.png, see face_scan_inject.py) to dump keys.

Row 0 of each shot shows records r0..r4, row 1 shows r5..r9 (data/texture_map/face_scan_batches.csv).
Output: data/texture_map/record_faces.csv (record, key, score, runner_up, shared)
  shared = number of records that resolve to the same key (>1 means the portrait is a shared texture,
  e.g. a placeholder; such records cannot be given an individual face).
Usage: python scripts/build_record_faces.py
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import texture_scan as ts  # noqa: E402


def main():
    keys, vecs = ts.load_corpus()
    print(len(keys), "face dumps")
    best = {}
    for row in csv.DictReader(open(ROOT / "data/texture_map/face_scan_batches.csv")):
        shot = ROOT / "docs/_faces" / row["file"]
        if not shot.exists():
            continue
        faces = ts.match_screen(ts.normalize(Image.open(shot)), keys, vecs)
        for i in range(10):
            rec = int(row[f"r{i}"])
            key, score, runner = faces[(i // 5, i % 5)]
            if rec not in best or score > best[rec][1]:
                best[rec] = (key, score, runner)
    users = defaultdict(list)
    for rec, (key, _, _) in best.items():
        users[key].append(rec)
    out = ROOT / "data/texture_map/record_faces.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["record", "key", "score", "runner_up", "shared"])
        for rec in sorted(best):
            key, score, runner = best[rec]
            w.writerow([rec, key, round(score, 3), round(runner, 3), len(users[key])])
    low = [r for r, b in best.items() if b[1] < 0.88]
    print(len(best), "records;", len([k for k, v in users.items() if len(v) > 1]), "shared keys;", len(low), "low scores")
    for k, v in users.items():
        if len(v) > 1:
            print("shared", k, v)
    print("low", sorted(low)[:40])


if __name__ == "__main__":
    main()
