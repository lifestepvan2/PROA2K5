"""Generate ProA team logo replacements for every matched variant of an NBA team logo.

Matches come from data/texture_map/logo_variants.csv (build_logo_map.py, mode A = the texture is a window of the
reference logo frame). The ProA logo (nba2k_editor/assets/<38+ProA team index>.png) is fitted into the content box of the
reference logo, then the matching window is cut out and resized to the texture's own resolution, so
full logos, small versions and split/cropped logos all get the right piece. The ProA logo of an NBA slot is
chosen by data/team_slots.csv.
Textures keep the PS2 alpha convention (0..128, 128 = opaque).
Usage: python scripts/gen_logo_replacements.py [--out DIR] [--list]
"""
import argparse
import csv

import numpy as np
from PIL import Image

from texlib import REPL_DIR, ROOT, dump_files, load_rgba, proa_slots, prune

SRC = ROOT / "data/texture_map/logo_variants.csv"
LOGO_ID0 = 38
CANON = 512
ACCEPT = dict(score=0.75, mae=27.0, content=0.25, size=0.45)  # tuned on reviews of ~90 + 72 matches; 0.75-0.80 only adds right halves of split logos
_cache = {}


def logo_matches(slots=None):
    """All logo-variant rows that pass the acceptance thresholds (mode A: window of a reference logo frame),
    optionally restricted to a set of NBA team slots."""
    out = []
    files = dump_files()
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    # thin logos (Rockets, Wizards) have little ink even in the full frame: scale the content threshold by it
    ref_content = {r["key"]: float(r["content"]) for r in rows if r["key"] == r["ref_key"]}
    for r in rows:
        if (slots is not None and int(r["team_slot"]) not in slots) or r["mode"] != "A" or r["key"] not in files:
            continue
        w, h = float(r["w"]), float(r["h"])
        min_content = min(ACCEPT["content"], 0.7 * ref_content.get(r["ref_key"], 1.0))
        if (float(r["score"]) < ACCEPT["score"] or float(r["mae"]) > ACCEPT["mae"]
                or float(r["content"]) < min_content or max(w, h) < ACCEPT["size"]):
            continue
        out.append(r)
    return out


def accepted():
    """Matches of NBA slots occupied by ProA teams that can be replaced (the reference frame is not one half of a split logo)."""
    files = dump_files()
    return [r for r in logo_matches(set(proa_slots())) if ref_box(r["ref_key"], files) is not None]


PARTIAL_REFS = ("190a7d68", "31fbe669")  # Cavaliers wordmark halves ("Cav" / "ALIERS"): one logo split over two textures


def ref_box(ref_key, files):
    """Content box of a reference frame (native px), or None for split-logo reference frames."""
    if ref_key not in _cache:
        a = load_rgba(files[ref_key])[..., 3]
        ys, xs = np.where(a > 8)
        h, w = a.shape
        box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        _cache[ref_key] = None if ref_key.startswith(PARTIAL_REFS) else (box, (w, h))
    return _cache[ref_key]


def canonical(slot, ref_key, files):
    """CANON x CANON RGBA frame with the ProA logo fitted into the reference logo's content box."""
    k = ("canon", slot, ref_key)
    if k not in _cache:
        (x0, y0, x1, y1), (w, h) = ref_box(ref_key, files)
        s = CANON / w
        bx0, by0, bx1, by1 = x0 * s, y0 * s, x1 * s, y1 * s
        logo = Image.open(ROOT / "nba2k_editor/assets" / f"{LOGO_ID0 + proa_slots()[slot]}.png").convert("RGBA")
        bb = logo.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
        logo = logo.crop(bb)
        f = min((bx1 - bx0) / logo.width, (by1 - by0) / logo.height)
        logo = logo.resize((max(1, round(logo.width * f)), max(1, round(logo.height * f))), Image.LANCZOS)
        fr = Image.new("RGBA", (CANON, CANON), (0, 0, 0, 0))
        fr.alpha_composite(logo, (round((bx0 + bx1 - logo.width) / 2), round((by0 + by1 - logo.height) / 2)))
        _cache[k] = fr
    return _cache[k]


def make(row, files):
    slot = int(row["team_slot"])
    fr = canonical(slot, row["ref_key"], files)
    orig = load_rgba(files[row["key"]])
    h, w = orig.shape[:2]
    # window of the 128-unit reference frame -> pixels of the CANON frame
    box = tuple(round(float(row[c]) * CANON) for c in ("x", "y"))
    box = (box[0], box[1], box[0] + round(float(row["w"]) * CANON), box[1] + round(float(row["h"]) * CANON))
    win = fr.crop(box)
    arr = np.asarray(win, dtype=np.float32)
    al = arr[..., 3]
    mean = arr[..., :3][al > 128].mean(axis=0) if (al > 128).any() else np.zeros(3)
    arr[..., :3][al < 1] = mean
    rgb = Image.fromarray(arr[..., :3].astype(np.uint8)).resize((w, h), Image.LANCZOS)
    a = Image.fromarray(al.astype(np.uint8)).resize((w, h), Image.LANCZOS)
    out = np.dstack([np.asarray(rgb), np.asarray(a)]).astype(np.float32)
    if (orig[..., 3] >= 120).mean() > 0.99:  # original has no transparency: composite on its border colour
        border = np.concatenate([orig[0, :, :3], orig[-1, :, :3], orig[:, 0, :3], orig[:, -1, :3]])
        bg = np.median(border, axis=0)
        k = out[..., 3:] / 255
        out[..., :3] = out[..., :3] * k + bg * (1 - k)
        out[..., 3] = 255
    out[..., 3] = np.round(out[..., 3] * 128 / 255)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def managed_keys():
    return {r["key"] for r in accepted()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=REPL_DIR)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    files = dump_files()
    rows = accepted()
    if args.list:
        for r in rows:
            print(r["team"], r["mode"], r["score"], r["mae"], r["key"])
    from pathlib import Path
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for r in rows:
        make(r, files).save(out / f"{r['key']}.png")
    print(len(rows), "logo variants written to", out)
    print(prune("logos", out, [r["key"] for r in rows]), "stale files removed")


if __name__ == "__main__":
    main()
