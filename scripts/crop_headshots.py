"""Crop scraped ProA portraits into the 512x512 head+shoulders headshots in assets/PS_out/<proa_id>.png.

Replaces the former Photoshop batch step. Window geometry was calibrated against 72 existing Photoshop crops:
side = 3.68 x detected face width, horizontally centred on the face, face top at 21% of the window height.
Output is opaque RGBA on white (gen_replacements / face_embed composite on white anyway).

    python scripts/crop_headshots.py [--season 2026_2027] [--force]
"""
import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
OUT = ROOT / "assets" / "PS_out"
K_SIDE, TOP_FRAC = 3.68, 0.21

_app = None


def _faces():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.3)
    return _app


def face_bbox(img):
    fs = _faces().get(np.array(img.convert("RGB"))[:, :, ::-1])
    if not fs:
        return None
    f = max(fs, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return f.bbox


def crop(src_path):
    """Returns (512x512 RGBA image, True if a face was detected)."""
    img = Image.open(src_path).convert("RGB")
    b = face_bbox(img)
    if b is None:
        side = img.height * 0.45
        x0, y0 = img.width / 2 - side / 2, img.height * 0.02
    else:
        side = (b[2] - b[0]) * K_SIDE
        x0, y0 = (b[0] + b[2]) / 2 - side / 2, b[1] - TOP_FRAC * side
    canvas = Image.new("RGB", (int(side) + 2, int(side) + 2), "white")
    canvas.paste(img, (-int(round(x0)), -int(round(y0))))
    out = canvas.resize((512, 512), Image.LANCZOS).convert("RGBA")
    return out, b is not None


def placeholder_hashes(src_dir):
    """Portraits the site serves as the generic silhouette share one byte-identical file."""
    import collections
    c = collections.Counter(hashlib.md5(p.read_bytes()).hexdigest() for p in src_dir.glob("*.*"))
    return {h for h, n in c.items() if n >= 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026_2027")
    ap.add_argument("--force", action="store_true", help="redo crops that already exist")
    a = ap.parse_args()
    src_dir = ROOT / "cache" / f"proa_{a.season}" / "portraits"
    OUT.mkdir(parents=True, exist_ok=True)
    ph = placeholder_hashes(src_dir)
    done = nofaces = 0
    for p in sorted(src_dir.glob("*.*")):
        dst = OUT / f"{p.stem}.png"
        if dst.exists() and not a.force:
            continue
        if hashlib.md5(p.read_bytes()).hexdigest() in ph:
            print(f"  placeholder silhouette, skipped: {p.stem}")
            continue
        img, ok = crop(p)
        img.save(dst)
        done += 1
        if not ok:
            nofaces += 1
            print(f"  no face detected: {p.stem} (fallback crop)")
    print(f"{done} headshot(s) written to {OUT} ({nofaces} without face detection)")


if __name__ == "__main__":
    sys.exit(main())
