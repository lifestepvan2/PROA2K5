"""Find every dumped texture that shows a team logo (any size, full or partial, alone or inside a bigger texture).

References are full logo textures listed in data/texture_map/logo_refs.csv. Two directions are tried per
candidate with an isotropic scale search (normalised cross correlation, colour):
  A  the candidate is a window of the reference frame (full logos at other resolutions, split/cropped logos)
  B  the reference sits inside the candidate (logo on a sign / composite texture)
Output: data/texture_map/logo_variants.csv. gen_logo_replacements.py turns the A matches into replacements.
Usage: python scripts/build_logo_map.py [--min 0.6] [--since "2026-10-18 12:00"] [--families 00001dd3,00001dd4]
"""
import argparse
import csv
import multiprocessing as mp
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from texlib import ROOT, dump_files, family, load_white

OUT = ROOT / "data/texture_map/logo_variants.csv"
SKIP_FAMILIES = {"00001994", "00001553", "00001554"}  # video tiles, small team icons
WIN_A = [128, 112, 96, 80, 64, 48, 40, 32, 24, 16]  # candidate size inside the 128-px reference frame
REF_B = [192, 128, 96, 64, 48, 32, 24]
PAD = 64

REFS = []
FILES = {}


def init():
    global REFS, FILES
    FILES = dump_files()
    REFS = []
    for r in csv.DictReader(open(ROOT / "data/texture_map/logo_refs.csv", encoding="utf-8")):
        c = load_white(FILES[r["ref_key"]])
        r128 = cv2.resize(c, (128, 128), interpolation=cv2.INTER_AREA)
        pad = cv2.copyMakeBorder(r128, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        scaled = {s: cv2.resize(c, (s, s), interpolation=cv2.INTER_AREA) for s in REF_B}
        REFS.append((int(r["team_slot"]), r["team"], r["ref_key"], pad, scaled))


def content(c):
    return float(((255 - c.astype(np.int16)).max(axis=2) > 40).mean())


def best_loc(img, tmpl):
    if tmpl.shape[0] > img.shape[0] or tmpl.shape[1] > img.shape[1]:
        return -1, (0, 0)
    m = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    m = np.nan_to_num(m, nan=-1, posinf=-1, neginf=-1)
    _, mx, _, loc = cv2.minMaxLoc(m)
    return mx, loc


def mae(img, tmpl, x, y):
    h, w = tmpl.shape[:2]
    return float(np.abs(img[y:y + h, x:x + w].astype(np.int16) - tmpl.astype(np.int16)).mean())


def match(key):
    c = load_white(FILES[key])
    h, w = c.shape[:2]
    if min(h, w) < 12 or content(c) < 0.08:
        return key, None
    best = (-1,)
    for tw in WIN_A:
        k = tw / max(h, w)
        nh, nw = round(h * k), round(w * k)
        if min(nh, nw) < 10:
            continue
        cs = cv2.resize(c, (nw, nh), interpolation=cv2.INTER_AREA)
        if cs.std() < 15 or content(cs) < 0.08:
            continue
        for slot, team, rk, pad, _ in REFS:
            sc, (x, y) = best_loc(pad, cs)
            if sc > best[0]:
                best = (sc, "A", slot, team, rk, (x - PAD) / 128, (y - PAD) / 128, nw / 128, nh / 128,
                        mae(pad, cs, x, y), content(cs))
    if max(h, w) >= 40:
        k = min(1.0, 256 / max(h, w))
        cw = cv2.resize(c, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else c
        H, W = cw.shape[:2]
        for slot, team, rk, _, scaled in REFS:
            for r, t in scaled.items():
                if r >= min(H, W):
                    continue
                sc, (x, y) = best_loc(cw, t)
                if sc > best[0]:
                    best = (sc, "B", slot, team, rk, x / W, y / H, r / W, r / H, mae(cw, t, x, y), content(t))
    return key, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=0.6)
    ap.add_argument("--since", help="only match dumps written after this local time (YYYY-MM-DD HH:MM) and merge "
                                    "the result into the existing csv")
    ap.add_argument("--families", help="comma separated families: only match those and merge into the csv")
    args = ap.parse_args()
    init()
    keys = sorted(k for k in FILES if family(k) not in SKIP_FAMILIES)
    old_rows = []
    if args.since or args.families:
        if args.since:
            cut = datetime.strptime(args.since, "%Y-%m-%d %H:%M").timestamp()
            keys = [k for k in keys if Path(FILES[k]).stat().st_mtime > cut]
        if args.families:
            fams = set(args.families.split(","))
            keys = [k for k in keys if family(k) in fams]
        done = set(keys)
        if OUT.exists():
            old_rows = [r for r in csv.reader(open(OUT, encoding="utf-8"))][1:]
            old_rows = [r for r in old_rows if r[0] not in done]
    print(len(keys), "candidates,", len(REFS), "references")
    with mp.Pool(max(1, mp.cpu_count() - 1), initializer=init) as pool:
        res = pool.map(match, keys, chunksize=8)
    rows = old_rows
    for key, b in res:
        if b and b[0] >= args.min:
            rows.append([key, b[2], b[3], b[4], b[1], f"{b[0]:.3f}"] + [f"{v:.4f}" for v in b[5:]])
    rows.sort(key=lambda r: (int(r[1]), -float(r[5])))
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "team_slot", "team", "ref_key", "mode", "score", "x", "y", "w", "h", "mae", "content"])
        w.writerows(rows)
    print(len(rows), "matches written to", OUT)


if __name__ == "__main__":
    main()
