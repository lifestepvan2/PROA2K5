"""ID probe for the head_and_body_skin textures: stamps a unique 3-digit number several times onto every texture of that
group and writes it as a replacement, so that the numbers seen in game reveal which texture a player/body part uses.

    python scripts/texture_id_probe.py stamp   write the stamped replacements + data/texture_map/id_probe.csv (id,key,size)
    python scripts/texture_id_probe.py clear   remove exactly those replacement files again (F10 in PCSX2 afterwards)

The ids follow the sorted (size, key) order of the workspace manifest group `head_and_body_skin`. The original image stays
visible (skin tone / hair), only the digits are drawn over it. PCSX2: press F10 to reload replacements, or load a state.
"""
import argparse
import csv

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from texlib import REPL_DIR, ROOT, dump_files, load_rgba
from texture_workspace import managed_keys

GROUP = "head_and_body_skin"
OUT = ROOT / "data/texture_map/id_probe.csv"
FONT = "C:/Windows/Fonts/arialbd.ttf"


def targets():
    mf = ROOT / "texture_workspace/_manifest.csv"
    rows = [r for r in csv.DictReader(open(mf, encoding="utf-8")) if r["group"] == GROUP]
    return sorted(((int(r["w"]), int(r["h"]), r["key"]) for r in rows))


def stamp(img, text):
    w, h = img.size
    cols, rows = (2, 3) if h >= 128 else (2, 2)
    cw, ch = w / cols, h / rows
    size = int(min(ch * 0.72, cw / 3 / 0.62 * 0.92))
    font = ImageFont.truetype(FONT, size)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for r in range(rows):
        for c in range(cols):
            d.text(((c + 0.5) * cw, (r + 0.5) * ch), text, font=font, anchor="mm", fill=(255, 255, 255, 255),
                   stroke_width=max(2, size // 12), stroke_fill=(0, 0, 0, 255))
    out = img.copy()
    out.alpha_composite(layer)
    a = np.asarray(out).copy()
    a[..., 3] = np.maximum(a[..., 3], np.asarray(layer)[..., 3])  # digits stay visible where the texture is transparent
    return Image.fromarray(a, "RGBA")


def do_stamp():
    files, managed = dump_files(), managed_keys()
    rows, skipped = [], 0
    REPL_DIR.mkdir(parents=True, exist_ok=True)
    for i, (w, h, key) in enumerate(targets()):
        target = REPL_DIR / f"{key}.png"
        if key in managed or key not in files or (target.exists() and not OUT.exists()):
            print(f"skip {key}: pipeline-managed, not dumped or already replaced")
            skipped += 1
            continue
        a = load_rgba(files[key]).copy()
        a[..., 3] = np.minimum(255, np.round(a[..., 3].astype(np.float32) * 255 / 128)).astype(np.uint8)
        stamp(Image.fromarray(a, "RGBA"), f"{i:03d}").save(target)
        rows.append((f"{i:03d}", key, f"{w}x{h}"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["id", "key", "size"])
        wr.writerows(rows)
    print(f"stamped {len(rows)} textures ({skipped} skipped) -> {OUT}. Press F10 in PCSX2.")


def do_clear():
    n = 0
    for r in csv.DictReader(open(OUT, encoding="utf-8")):
        p = REPL_DIR / f"{r['key']}.png"
        if p.exists():
            p.unlink()
            n += 1
    print(f"removed {n} probe replacements. Press F10 in PCSX2.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stamp", "clear"])
    {"stamp": do_stamp, "clear": do_clear}[ap.parse_args().cmd]()
