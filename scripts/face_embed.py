"""Face embeddings (ArcFace via insightface) for the ProA headshots and the in-game face textures of every NBA player model.

Writes data/face_match/embeddings.npz + skin_lab.npz (keys 'proa:<proa_id>' and 'tex:<pid>'). Texture entries are kept
between runs (only new faces in data/face_match/faces are embedded); ProA entries are recomputed.
Usage: python scripts/face_embed.py
"""
import csv
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
PS_OUT = ROOT / "assets/PS_out"
OUT = ROOT / "data/face_match"
FACES = OUT / "faces"
TEX_CROP = (0, 100, 136, 256)  # frontal face area of the 256x256 face texture
_app = None


def app():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.15)
    return _app


def embed(rgb, scale=1, pad=0.5):
    """ArcFace embedding (512, L2-normalised) of the largest face in an RGB array, or None."""
    img = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    if scale != 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    p = int(max(img.shape[:2]) * pad)
    img = cv2.copyMakeBorder(img, p, p, p, p, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    faces = app().get(img)
    if not faces:
        return None
    f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return f.normed_embedding, skin_lab(img, f)


def skin_lab(img, f):
    """Median CIELAB colour of the cheek/nose patch (below the eyes, above the mouth) of a detected face."""
    (ex0, ey0), (ex1, ey1), (nx, ny), (mx0, my0), (mx1, my1) = f.kps
    w = f.bbox[2] - f.bbox[0]
    x0, x1 = int(nx - 0.18 * w), int(nx + 0.18 * w)
    y0, y1 = int((ey0 + ey1) / 2 + 0.15 * w), int((my0 + my1) / 2 - 0.08 * w)
    x0, y0 = max(x0, 0), max(y0, 0)
    patch = img[y0:max(y1, y0 + 2), x0:max(x1, x0 + 2)]
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
    return np.median(lab, axis=0)


def tex_face(pid):
    """The frontal face area of a player's 256x256 face texture (saved by face_load_scan.py --faces)."""
    return Image.open(FACES / f"{pid}_face.png").convert("RGB").crop(TEX_CROP)


def proa_portrait(proa_id):
    img = Image.open(PS_OUT / f"{proa_id}.png").convert("RGBA")
    bg = Image.new("RGB", img.size, "white")
    bg.paste(img, mask=img.split()[3])
    return bg


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    emb, skin = {}, {}
    if (OUT / "embeddings.npz").exists():
        old_e, old_s = np.load(OUT / "embeddings.npz"), np.load(OUT / "skin_lab.npz")
        emb, skin = {k: old_e[k] for k in old_e.files if k.startswith("tex:")}, {k: old_s[k] for k in old_s.files if k.startswith("tex:")}
    missing = []

    def add(name, img, scale=1):
        res = embed(img, scale)
        if res is None:
            missing.append(name)
        else:
            emb[name], skin[name] = res

    for r in csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8")):
        add(f"proa:{r['proa_id']}", proa_portrait(r["proa_id"]))
    for p in sorted(FACES.glob("*_face.png")):
        pid = p.name.split("_")[0]
        if f"tex:{pid}" not in emb:
            add(f"tex:{pid}", tex_face(pid), 3)
    np.savez(OUT / "embeddings.npz", **emb)
    np.savez(OUT / "skin_lab.npz", **skin)
    print(len(emb), "embedded;", len(missing), "without a detected face:", missing[:20])
