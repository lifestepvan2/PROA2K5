"""Content clustering for the mixed texture families (arena props, courts, signs, skin, numbers...).

fit:    python scripts/texcluster.py fit            -> data/texture_map/cluster_model.json (centroids, names from the JSON's "names")
sheets: python scripts/texcluster.py sheets OUTDIR  -> one contact sheet per family for naming the clusters by eye
Cluster names live in data/texture_map/cluster_names.json ({family: {cluster_idx: name}}); the model stores centroids only,
so new dumps are classified by nearest centroid of their family.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from sklearn.cluster import KMeans

from texlib import ROOT, dump_files, family, load_rgba, over_white

MODEL = ROOT / "data/texture_map/cluster_model.json"
NAMES = ROOT / "data/texture_map/cluster_names.json"
# family -> number of clusters
FAMILIES = {"00002213": 18, "00001993": 18, "000019d3": 8, "00001593": 6, "00000d13": 6,
            "00001153": 6}
T = 12


def feature(path):
    rgba = load_rgba(path)
    im = Image.fromarray(over_white(rgba)).resize((T, T), Image.BILINEAR)
    al = Image.fromarray(rgba[..., 3]).resize((T, T), Image.BILINEAR)
    return np.concatenate([np.asarray(im, np.float32).ravel() / 255, np.asarray(al, np.float32).ravel() / 128])


def classify(vec, fam, model):
    c = np.asarray(model[fam]["centroids"], np.float32)
    return int(np.argmin(((c - vec) ** 2).sum(1)))


def fit():
    files = dump_files()
    model = {}
    for fam, k in FAMILIES.items():
        keys = sorted(x for x in files if family(x) == fam)
        X = np.stack([feature(files[x]) for x in keys])
        km = KMeans(k, n_init=10, random_state=1).fit(X)
        model[fam] = {"centroids": km.cluster_centers_.round(4).tolist()}
        print(fam, len(keys), "->", np.bincount(km.labels_).tolist())
    MODEL.write_text(json.dumps(model))


def sheets(outdir, per=14, cell=96):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    files = dump_files()
    model = json.loads(MODEL.read_text())
    rng = np.random.default_rng(0)
    for fam in FAMILIES:
        keys = sorted(x for x in files if family(x) == fam)
        lab = [classify(feature(files[x]), fam, model) for x in keys]
        k = len(model[fam]["centroids"])
        rows = []
        for c in range(k):
            ks = [x for x, l in zip(keys, lab) if l == c]
            pick = list(rng.permutation(ks)[:per])
            rows.append((c, len(ks), pick))
        sheet = Image.new("RGB", (60 + per * cell, k * (cell + 4)), (200, 200, 200))
        d = ImageDraw.Draw(sheet)
        for r, (c, n, pick) in enumerate(rows):
            d.text((2, r * (cell + 4) + 4), f"c{c}\nn={n}", fill=(0, 0, 0))
            for i, x in enumerate(pick):
                im = Image.fromarray(over_white(load_rgba(files[x]), 140))
                im.thumbnail((cell - 2, cell - 2))
                sheet.paste(im, (60 + i * cell, r * (cell + 4)))
        sheet.save(outdir / f"{fam}.png")


if __name__ == "__main__":
    if sys.argv[1] == "fit":
        fit()
    else:
        sheets(sys.argv[2])
