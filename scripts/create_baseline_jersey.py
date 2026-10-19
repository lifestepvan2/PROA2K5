"""Baseline jersey/shorts/warm-up generator: colourises the blank templates in texture_workspace/uniforms/templates for
every ProA team and writes the result over that team's home + away MASTER 512x256 textures (shorts plain, warm-up =
one plain primary-colour jacket with the club logo, copied to every warm-up master filed under the team).

    python scripts/create_baseline_jersey.py [--team Falcons ...] [--dry-run] [--overwrite] [--restore]
    then:  python scripts/texture_workspace.py sync        (rebuilds the duplicates + LODs from the new MASTERs)

* colours:  data/proa_teams.csv  columns color1 / color2 (hex).  Home = white body + color1 trim/stripes,
            away = color1 body + color2 trim/stripes (white when color2 is empty).
* fabric:   each template region is divided by its own median luminance -> a 'shade' map (folds, perforations),
            which is re-applied on top of the target colour, so the cloth structure survives the recolouring.
* logos:    jerseys: ProA league patch (data/proa_logo.png) on the player's left breast, team logo
            (nba2k_editor/assets/<38+index>.png) on the right breast. Warm-ups: team logo on the chest. Shorts: none.
* output is saved RGB-only so texture_workspace.py keeps the game's original per-pixel alpha.
* safety:   originals are copied once to texture_workspace/uniforms/backups/; a MASTER is only overwritten while it still
            equals the exported default (manifest sha1) or the file this script wrote last time - unless --overwrite.
"""
import argparse
import csv
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image

from texlib import ROOT
from texture_workspace import read_manifest
from uniform_lods import TOKEN, WS, tok
from uniform_sort import SORT, manifest, token_of, workspace_files

UNI = WS / "uniforms"
TEMPLATES = UNI / "templates"
BACKUPS = UNI / "backups"
GEN_LOG = BACKUPS / "_generated.json"
PROA_LOGO = ROOT / "data/proa_logo.png"
SHEET_OUT = ROOT / "docs/_tmp/baseline_sheet.png"
LOGO_ID0 = 38
SIZE = (512, 256)

# logo placement in 512x256 texture pixels: centre (x, y) and bounding box (w, h)
JERSEY_PROA = ((131, 70), (24, 15))   # player's left breast (viewer's right of the neck V), where the NBA logo sits
JERSEY_TEAM = ((33, 71), (28, 28))    # player's right breast, mirrored around the front centre line x=82
WARMUP_TEAM = ((128, 76), (38, 36))   # player's left chest (viewer's right of the zipper)

# textures filed under <Team>/warmups that are not warm-up jackets (Hawks jersey inside Jazz/warmups)
NOT_WARMUPS = {"dd07e198"}

WHITE = (240, 240, 240)
HIGHLIGHT = 0.4  # share of the template's above-median brightness that is kept


def sha1(p):
    return hashlib.sha1(p.read_bytes()).hexdigest()


def hex_rgb(s, default):
    s = (s or "").strip().lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) if len(s) == 6 else default


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def load_teams():
    teams = list(csv.DictReader(open(ROOT / "data/proa_teams.csv", encoding="utf-8")))
    slots = {r["sheet"]: r["nba_team"] for r in csv.DictReader(open(ROOT / "data/team_slots.csv", encoding="utf-8"))}
    out = []
    for i, t in enumerate(teams):
        if t["sheet"] not in slots:
            continue
        c1 = hex_rgb(t.get("color1"), None)
        if c1 is None:
            print(f"  {t['sheet']}: no color1 in proa_teams.csv - skipped")
            continue
        out.append(dict(sheet=t["sheet"], nba=slots[t["sheet"]], logo=ROOT / f"nba2k_editor/assets/{LOGO_ID0 + i}.png",
                        c1=c1, c2=hex_rgb(t.get("color2"), WHITE)))
    return out


def fit_logo(path, box):
    """Trimmed logo resized to fit inside box (premultiplied resampling -> no dark fringes)."""
    im = Image.open(path).convert("RGBA")
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    s = min(box[0] / im.width, box[1] / im.height)
    size = (max(1, round(im.width * s)), max(1, round(im.height * s)))
    return im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


def paste(base, logo_path, centre, box):
    logo = fit_logo(logo_path, box)
    base.alpha_composite(logo, (round(centre[0] - logo.width / 2), round(centre[1] - logo.height / 2)))


def tint(lum, weight, rgb, add=26.0):
    """Colour a region with `rgb` keeping the template's cloth structure (lum / regional median)."""
    sel = weight > 0.9
    med = max(float(np.median(lum[sel])) if sel.any() else float(lum.mean()), 1.0)
    shade = (lum / med - 1.0)[..., None]
    shade = np.where(shade > 0, shade * HIGHLIGHT, shade)  # compress highlights so light colours do not clip to flat white
    rgb = np.array(rgb, dtype=np.float32)
    dark = 1.0 - rgb.mean() / 255.0  # dark colours get an additive share so their folds stay visible
    return rgb * (1.0 + shade) + shade * add * dark * 2


def luma(arr):
    return arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def colourise_jersey(tmpl, body_rgb, trim_rgb):
    a = np.asarray(tmpl.convert("RGB"), dtype=np.float32)
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    wb = smoothstep(0.25, 0.55, sat)  # saturated = body, grey/white = trim
    lum = luma(a)
    out = wb[..., None] * tint(lum, wb, body_rgb) + (1 - wb)[..., None] * tint(lum, 1 - wb, trim_rgb)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def colourise_shorts(tmpl, body_rgb, stripe_rgb):
    a = np.asarray(tmpl.convert("RGB"), dtype=np.float32)
    lum = luma(a)
    ws = 1.0 - smoothstep(85, 115, lum)  # dark panels = stripes
    out = (1 - ws)[..., None] * tint(lum, 1 - ws, body_rgb) + ws[..., None] * tint(lum, ws, stripe_rgb)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def render(team, side, kind, tmpl):
    """Jersey: logos on both breasts. Shorts: plain. Warm-up: plain primary colour + club logo on the chest."""
    c1, c2 = team["c1"], team["c2"]
    if kind == "warmup":
        img = colourise_jersey(tmpl, c1, c1).convert("RGBA")
        paste(img, team["logo"], *WARMUP_TEAM)
        return img.convert("RGB")
    body, trim = (WHITE, c1) if side == "Home" else (c1, c2)
    img = (colourise_jersey if kind == "Jersey" else colourise_shorts)(tmpl, body, trim).convert("RGBA")
    if kind == "Jersey":
        paste(img, PROA_LOGO, *JERSEY_PROA)
        paste(img, team["logo"], *JERSEY_TEAM)
    return img.convert("RGB")


def masters_in(team_dir, man, by_key):
    """{group folder: [MASTER 512x256 tokens]} inside one visual_sort/<Team>/... folder."""
    groups = {}
    for p in sorted(team_dir.rglob("*.png")):
        if not p.name.upper().startswith("MASTER"):
            continue
        t = token_of(p) or by_key.get(re.sub(r"^MASTER[_-]", "", p.stem.split("__")[0]))
        if t in man and (man[t]["w"], man[t]["h"]) == SIZE:
            groups.setdefault(p.parent, []).append(t)
    return groups


def find_masters(team_dir, man, by_key, every_group=False):
    """MASTER tokens of a folder: the largest group's master (jersey/shorts), or every group's (warm-ups)."""
    groups = masters_in(team_dir, man, by_key)
    if not groups:
        return []
    if every_group:
        return [t for ts in groups.values() for t in ts if t not in NOT_WARMUPS]
    d, ts = max(groups.items(), key=lambda kv: len(list(kv[0].glob("*.png"))))
    if len(groups) > 1:
        print(f"  note: {team_dir.relative_to(SORT)} has {len(groups)} MASTER groups - using the largest ({d.name})")
    return ts[:1]


def save_retry(img, path, tries=6):
    """Windows scanners occasionally lock a file right after it was read/copied -> retry the write briefly."""
    for i in range(tries):
        try:
            img.save(path)
            return
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(0.5 * (i + 1))


def process(teams, man, full, real, gen, tm, by_key, args, stats, backup_path, tiles):
    jobs = [("Home", "Jersey", "Jersey"), ("Home", "shorts", "shorts"), ("Away", "Jersey", "Jersey"),
            ("Away", "shorts", "shorts"), ("warmups", "", "warmup")]
    for team in teams:
        print(f"{team['sheet']} -> {team['nba']}")
        row = [None] * len(jobs)
        tiles.append(row)
        for col, (side, sub, kind) in enumerate(jobs):
            folder = SORT / team["nba"] / side / sub if sub else SORT / team["nba"] / side
            label = f"{side}/{sub}" if sub else side
            toks = find_masters(folder, man, by_key, every_group=kind == "warmup") if folder.exists() else []
            toks = [t for t in toks if t in real]
            if not toks:
                print(f"  {label}: no MASTER found - skipped")
                stats["missing"] += 1
                continue
            img = render(team, side, kind, tm[kind])
            row[col] = img
            for t in toks:
                p = real[t]
                cur = sha1(p)
                is_default = cur == full[t]["sha1"]
                is_ours = gen.get(t) == cur
                if not (is_default or is_ours or args.overwrite):
                    print(f"  {label}: {p.name} was edited by hand - kept (use --overwrite)")
                    stats["protected"] += 1
                    continue
                print(f"  {label}: {'would write' if args.dry_run else 'writing'} {p.name}"
                      f"{'' if is_default or is_ours else '  [OVERWRITE of hand edit]'}")
                if args.dry_run:
                    continue
                b = backup_path(p)
                if not b.exists():
                    shutil.copy2(p, b)
                save_retry(img, p)
                gen[t] = sha1(p)
                stats["written"] += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", nargs="*", help="only these sheets (e.g. Falcons Ulm); default all")
    ap.add_argument("--dry-run", action="store_true", help="report what would be written, change nothing")
    ap.add_argument("--overwrite", action="store_true", help="also replace MASTERs that were edited by hand")
    ap.add_argument("--restore", action="store_true", help="copy the backups back over the MASTERs and exit")
    ap.add_argument("--sheet", default=str(SHEET_OUT), help="contact sheet of the generated textures ('' = none)")
    args = ap.parse_args()

    man = manifest()
    full = read_manifest(WS)
    real = workspace_files(man)
    gen = json.loads(GEN_LOG.read_text()) if GEN_LOG.exists() else {}

    def backup_path(p):
        return BACKUPS / p.name.replace("__", "~~")

    if args.restore:
        n = 0
        for t, sha in list(gen.items()):
            p = real.get(t)
            b = backup_path(p) if p else None
            if b and b.exists():
                if not args.dry_run:
                    shutil.copy2(b, p)
                    gen.pop(t)
                n += 1
        if not args.dry_run:
            GEN_LOG.write_text(json.dumps(gen, indent=1))
        print(f"restored {n} files from {BACKUPS}")
        return

    tm = {"Jersey": Image.open(TEMPLATES / "jersey_tmpl.png"), "shorts": Image.open(TEMPLATES / "short_tmpl.png"),
          "warmup": Image.open(TEMPLATES / "warmup_tmpl.png")}
    by_key = {m["key"]: t for t, m in man.items()}
    teams = [t for t in load_teams() if not args.team or t["sheet"] in args.team]
    if not teams:
        raise SystemExit("no matching team")
    stats = dict(written=0, protected=0, missing=0, same=0)
    tiles = []
    if not args.dry_run:
        BACKUPS.mkdir(parents=True, exist_ok=True)
    try:
        process(teams, man, full, real, gen, tm, by_key, args, stats, backup_path, tiles)
    finally:
        if not args.dry_run:
            GEN_LOG.write_text(json.dumps(gen, indent=1))
    if args.sheet and tiles:
        w, h = SIZE[0] // 2, SIZE[1] // 2
        sheet = Image.new("RGB", (w * 5, h * len(tiles)), (30, 30, 30))
        for r, row in enumerate(tiles):
            for c, im in enumerate(row):
                if im is not None:
                    sheet.paste(im.resize((w, h), Image.LANCZOS), (c * w, r * h))
        out = Path(args.sheet)
        out.parent.mkdir(parents=True, exist_ok=True)
        save_retry(sheet, out)
        print(f"contact sheet: {out}")
    print(stats)
    if stats["written"]:
        print("next: python scripts/texture_workspace.py sync   (LODs + duplicates), then F10 in PCSX2")


if __name__ == "__main__":
    main()
