"""Generate PCSX2 texture replacements for lineup faces from data/texture_map/starter_faces.csv.

Each key (<h1>-<h2>-00001dd3) is a 128x128 face; the game displays only the (0,3,102,125) window.
The ProA headshot (assets/PS_out/<proa_id>.png, 512x512 RGBA) is cropped to head + shoulders and
fitted into that window on a white canvas.
Usage: python scripts/gen_replacements.py [--out DIR]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pm = {r["record"]: r for r in csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8"))}
    n = 0
    for r in csv.DictReader(open(ROOT / "data/texture_map/starter_faces.csv", encoding="utf-8")):
        src = ROOT / "assets/PS_out" / f"{pm[r['record']]['proa_id']}.png"
        if not src.exists():
            print("no image for", r["name"])
            continue
        make_face(src).save(args.out / f"{r['key']}.png")
        n += 1
    print(n, "faces written to", args.out)


if __name__ == "__main__":
    main()
