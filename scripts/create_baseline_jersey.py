"""Baseline jersey/shorts/warm-up generator: colourises the blank templates in texture_workspace/uniforms/templates for
every ProA team and writes the result over that team's home + away MASTER 512x256 textures (shorts plain, warm-up =
one plain primary-colour jacket with the club logo, copied to every warm-up master filed under the team). The 256x256
warm-up cloth textures (top with sleeves, trouser legs) filed under <Team>/cloth are generated from the logo-less
templates cloth_top_tmpl / cloth_shorts_tmpl in the primary colour.

    python scripts/create_baseline_jersey.py [--team Falcons ...] [--dry-run] [--overwrite] [--restore]
    then:  python scripts/texture_workspace.py sync        (rebuilds the duplicates + LODs from the new MASTERs)

* colours:  data/proa_teams.csv  columns color1 / color2 (hex).  Home = white body + color1 trim/stripes,
            away = color1 body + color2 trim/stripes (white when color2 is empty).
* fabric:   each template region is divided by its own median luminance -> a 'shade' map (folds, perforations),
            which is re-applied on top of the target colour, so the cloth structure survives the recolouring.
* logos:    jerseys: ProA league patch (data/proa_logo.png) on the player's left breast, team logo
            (nba2k_editor/assets/<38+index>.png) on the right breast. Warm-ups: team logo on the chest. Shorts: none.
* --fabric  exports that shade map as editing layers (overlay-grey and black/white-with-alpha PNGs) to templates/fabric/,
            also for the warm-up sleeves / trouser legs (from cloth_top_tmpl / cloth_shorts_tmpl). Existing files are kept unless --overwrite.
* output is saved RGB-only so texture_workspace.py keeps the game's original per-pixel alpha.
* safety:   originals are copied once to texture_workspace/uniforms/backups/; a MASTER is only overwritten while it still
            equals the exported default (manifest sha1) or the file this script wrote last time - unless --overwrite.
"""
import argparse
import csv
import functools
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
PROA_LOGO = ROOT / "data/barmer_logo.png"
SHEET_OUT = ROOT / "docs/_tmp/baseline_sheet.png"
LOGO_ID0 = 38
SIZE = (512, 256)
CLOTH_SIZE = (256, 256)
CLOTH_TEMPLATES = {"cloth-top": "cloth_top_tmpl.png", "cloth-shorts": "cloth_shorts_tmpl.png"}
# logo placement in 512x256 texture pixels: centre (x, y) and bounding box (w, h)
JERSEY_PROA = ((136, 72), (26, 26))   # player's left breast (viewer's right of the neck V), where the NBA logo sits
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


def shade_of(lum, weight, cap=None):
    """Cloth structure of one region: relative deviation from the region's median brightness (0 = flat, <0 darker)."""
    sel = weight > 0.9
    med = max(float(np.median(lum[sel])) if sel.any() else float(lum.mean()), 1.0)
    shade = lum / med - 1.0
    return np.where(shade > 0, shade * HIGHLIGHT, shade)  # compress highlights so light colours do not clip to flat white


def tint(lum, weight, rgb, add=26.0):
    """Colour a region with `rgb` keeping the template's cloth structure (lum / regional median)."""
    shade = shade_of(lum, weight)[..., None]
    rgb = np.array(rgb, dtype=np.float32)
    dark = 1.0 - rgb.mean() / 255.0  # dark colours get an additive share so their folds stay visible
    return rgb * (1.0 + shade) + shade * add * dark * 2


def luma(arr):
    return arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def body_weight(tmpl, kind):
    """(luma, body weight 0..1) of a template: jersey/warm-up body vs trim, or shorts body vs stripes."""
    a = np.asarray(tmpl.convert("RGB"), dtype=np.float32)
    lum = luma(a)
    if kind == "shorts":
        return lum, smoothstep(85, 115, lum)  # dark panels = stripes
    sat = (a.max(2) - a.min(2)) / np.maximum(a.max(2), 1.0)
    return lum, smoothstep(0.25, 0.55, sat)  # saturated = body, grey/white = trim


def colourise(tmpl, kind, body_rgb, trim_rgb):
    lum, wb = body_weight(tmpl, kind)
    out = wb[..., None] * tint(lum, wb, body_rgb) + (1 - wb)[..., None] * tint(lum, 1 - wb, trim_rgb)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def colourise_jersey(tmpl, body_rgb, trim_rgb):
    return colourise(tmpl, "Jersey", body_rgb, trim_rgb)


def colourise_shorts(tmpl, body_rgb, stripe_rgb):
    return colourise(tmpl, "shorts", body_rgb, stripe_rgb)


def layers_from_shade(shade):
    """overlay: grey, 128 = neutral (Overlay / Soft Light / Linear Light blend over a coloured layer).
    shadow_light: black (darker) and white (lighter) pixels whose alpha is the strength (normal blend over a colour)."""
    grey = np.clip(128 * (1 + shade), 0, 255).astype(np.uint8)
    alpha = np.clip(np.abs(shade) * 1.5, 0, 1) * 255
    rgba = np.dstack([np.where(shade < 0, 0, 255)] * 3 + [alpha]).astype(np.uint8)
    return Image.fromarray(grey, "L"), Image.fromarray(rgba, "RGBA")


def fabric_layers(tmpl, kind):
    """The colour-independent cloth structure of a template as editing layers."""
    lum, wb = body_weight(tmpl, kind)
    return layers_from_shade(wb * shade_of(lum, wb) + (1 - wb) * shade_of(lum, 1 - wb))


@functools.lru_cache(maxsize=None)
def cloth_template(kind):
    return Image.open(TEMPLATES / CLOTH_TEMPLATES[kind]).convert("RGB")


def cloth_kind(relpath):
    return "cloth-top" if "cloth-top" in relpath else "cloth-shorts"


def export_fabric(overwrite=False):
    out = TEMPLATES / "fabric"
    out.mkdir(parents=True, exist_ok=True)

    def write(name, layers):
        for suffix, img in zip(("overlay", "shadow_light"), layers):
            p = out / f"{name}_fabric_{suffix}.png"
            if p.exists() and not overwrite:
                print(f"  kept existing {p.name} (use --overwrite to regenerate)")
            else:
                save_retry(img, p)

    for kind, name in (("Jersey", "jersey"), ("shorts", "short"), ("warmup", "warmup")):
        write(name, fabric_layers(Image.open(TEMPLATES / f"{name}_tmpl.png"), "shorts" if kind == "shorts" else "Jersey"))
    for kind, name in (("cloth-top", "warmup_sleeves"), ("cloth-shorts", "warmup_legs")):
        write(name, fabric_layers(cloth_template(kind), "Jersey"))
    print(f"fabric layers in {out}")


def render_cloth(team, kind):
    """Warm-up top / trouser cloth from the logo-less template: one plain primary colour, folds kept."""
    return colourise(cloth_template(kind), "Jersey", team["c1"], team["c1"])


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


def masters_in(team_dir, man, by_key, size=SIZE):
    """{group folder: [MASTER tokens of that texture size]} inside one visual_sort/<Team>/... folder."""
    groups = {}
    for p in sorted(team_dir.rglob("*.png")):
        if not p.name.upper().startswith("MASTER"):
            continue
        t = token_of(p) or by_key.get(re.sub(r"^MASTER[_-]", "", p.stem.split("__")[0]))
        if t in man and (man[t]["w"], man[t]["h"]) == size:
            groups.setdefault(p.parent, []).append(t)
    return groups


def find_masters(team_dir, man, by_key, every_group=False, size=SIZE):
    """MASTER tokens of a folder: the largest group's master (jersey/shorts), or every group's (warm-ups, cloth)."""
    groups = masters_in(team_dir, man, by_key, size)
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
            ("Away", "shorts", "shorts"), ("warmups", "", "warmup"), ("cloth", "", "cloth")]
    for team in teams:
        print(f"{team['sheet']} -> {team['nba']}")
        row = [None] * len(jobs)
        tiles.append(row)
        for col, (side, sub, kind) in enumerate(jobs):
            folder = SORT / team["nba"] / side / sub if sub else SORT / team["nba"] / side
            label = f"{side}/{sub}" if sub else side
            toks = (find_masters(folder, man, by_key, every_group=kind in ("warmup", "cloth"),
                                 size=CLOTH_SIZE if kind == "cloth" else SIZE) if folder.exists() else [])
            toks = [t for t in toks if t in real]
            if not toks:
                print(f"  {label}: no MASTER found - skipped")
                stats["missing"] += 1
                continue
            img = None if kind == "cloth" else render(team, side, kind, tm[kind])
            if img is not None:
                row[col] = img
            for t in toks:
                if kind == "cloth":
                    img = render_cloth(team, cloth_kind(full[t]["relpath"]))
                    row[col] = row[col] or img
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
    ap.add_argument("--fabric", action="store_true", help="export the cloth structure of the templates as layers (templates/fabric/) and exit")
    args = ap.parse_args()
    if args.fabric:
        export_fabric(args.overwrite)
        return

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
        sheet = Image.new("RGB", (w * 5 + h, h * len(tiles)), (30, 30, 30))
        for r, row in enumerate(tiles):
            for c, im in enumerate(row):
                if im is not None:
                    sheet.paste(im.resize((h, h) if im.width == im.height else (w, h), Image.LANCZOS), (c * w, r * h))
        out = Path(args.sheet)
        out.parent.mkdir(parents=True, exist_ok=True)
        save_retry(sheet, out)
        print(f"contact sheet: {out}")
    print(stats)
    if stats["written"]:
        print("next: python scripts/texture_workspace.py sync   (LODs + duplicates), then F10 in PCSX2")


if __name__ == "__main__":
    main()
