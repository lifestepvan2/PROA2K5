"""Generate PCSX2 texture replacements for lineup faces from data/texture_map/starter_faces.csv.

Each key (<h1>-<h2>-00001dd3) is a 128x128 face; the game displays only the (0,3,102,125) window.
The ProA headshot (assets/PS_out/<proa_id>.png, 512x512 RGBA) is cropped to head + shoulders and
fitted into that window on a white canvas.
Usage: python scripts/gen_replacements.py [--out DIR]   (faces: data/texture_map/record_faces.csv + player_map.csv)
"""
import argparse
import csv
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent.parent
DEFAULT_OUT = Path(r"C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\replacements")
WIN = (0, 3, 102, 125)
CROP = (75, 20, 415, 427)  # head + shoulders of a 512x512 ProA headshot


def make_face(src):
    img = Image.open(src).convert("RGBA")
    bg = Image.new("RGB", img.size, "white")
    bg.paste(img, mask=img.split()[3])
    face = bg.crop(CROP).resize((WIN[2] - WIN[0], WIN[3] - WIN[1]), Image.LANCZOS)
    canvas = Image.new("RGB", (128, 128), "white")
    canvas.paste(face, (WIN[0], WIN[1]))
    return canvas


ICON_WIN = (4, 5, 28, 27)  # visible part of the 32x32 team icon
ICON_DISPLAY = (80, 62)    # on-screen size of that part (non-square pixels)
LOGO_ID0 = 38              # nba2k_editor/assets/<38 + team_slot>.png


def make_icon(src):
    img = Image.open(src).convert("RGBA")
    ww, wh = ICON_WIN[2] - ICON_WIN[0], ICON_WIN[3] - ICON_WIN[1]
    s = min(ICON_DISPLAY[0] / img.width, ICON_DISPLAY[1] / img.height) * 0.92
    w = max(1, round(img.width * s * ww / ICON_DISPLAY[0]))
    h = max(1, round(img.height * s * wh / ICON_DISPLAY[1]))
    logo = img.resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
    canvas.alpha_composite(logo, (ICON_WIN[0] + (ww - w) // 2, ICON_WIN[1] + (wh - h) // 2))
    return canvas.convert("RGB")


def write_icons(out):
    n = 0
    for r in csv.DictReader(open(ROOT / "data/texture_map/team_icons.csv", encoding="utf-8")):
        src = ROOT / "nba2k_editor/assets" / f"{LOGO_ID0 + int(r['team_slot'])}.png"
        make_icon(src).save(out / f"{r['key']}.png")
        n += 1
    print(n, "team icons written")


def managed_keys():
    """Texture keys this generator writes (faces of ProA players, team icons); the workspace never overrides them."""
    pm = csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8"))
    recs = {int(r["record"]) for r in pm}
    keys = {int(r["record"]): r["key"] for r in csv.DictReader(open(ROOT / "data/texture_map/record_faces.csv"))}
    icons = {r["key"] for r in csv.DictReader(open(ROOT / "data/texture_map/team_icons.csv", encoding="utf-8"))}
    return {keys[r] for r in recs if r in keys} | icons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    write_icons(args.out)
    pm = list(csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8")))
    keys = {int(r["record"]): r["key"] for r in csv.DictReader(open(ROOT / "data/texture_map/record_faces.csv"))}
    n = 0
    for r in pm:
        src = ROOT / "assets/PS_out" / f"{r['proa_id']}.png"
        if not src.exists():
            print("no image for", r["first"], r["last"])
            continue
        make_face(src).save(args.out / f"{keys[int(r['record'])]}.png")
        n += 1
    print(n, "faces written to", args.out)


if __name__ == "__main__":
    main()
