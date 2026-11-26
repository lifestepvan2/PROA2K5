"""Model-local light-reserve recolouring from pristine native player textures."""
import collections
import csv
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from skimage import color

from face_embed import TEX_CROP
from inventory_lettering_iso import asset_hash
from player_texture_iso import player_asset_name

ROOT = Path(__file__).resolve().parents[1]
LIGHT_TONE = 5
LIGHT_MIN, LIGHT_MAX = 1.2, 1.75
REFERENCE = 1.45
SIGMA = (22, 10, 10)


def inventory(assets):
    """Find the largest tone-3 arm class and independently recolourable models."""
    tones = {}
    with (ROOT / "data" / "nba_defaults" / "players_unknown.csv").open(encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["team_slot"] and int(row["team_slot"]) < 39:
                record = bytes.fromhex(row["hex"])
                tones.setdefault(int.from_bytes(record[4:6], "little"), record[0x69])
    parts = {}
    for pid in tones:
        if not all(asset_hash(player_asset_name(pid, side)) in assets.entries for side in ("h", "a")):
            continue
        parts[pid] = {}
        for part in ("face", "arm", "neck"):
            _, _, decoded, system, _ = assets.resource(pid, "h", part)
            parts[pid][part] = hashlib.sha256(decoded[system:]).digest()
    arms = collections.Counter(parts[pid]["arm"] for pid, tone in tones.items()
                               if tone == 3 and pid in parts)
    if not arms:
        raise ValueError("No native tone-3 arm textures found")
    reserve_arm = arms.most_common(1)[0][0]
    neck_faces = collections.defaultdict(set)
    for part in parts.values():
        neck_faces[part["neck"]].add(part["face"])
    reserved = {pid for pid, part in parts.items() if part["arm"] == reserve_arm}
    usable = {pid for pid in reserved if len(neck_faces[parts[pid]["neck"]]) == 1}
    return reserved, usable


def _patch(lab, box):
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    sample = lab[y0 + int(.35 * height):y0 + int(.65 * height),
                 x0 + int(.3 * width):x0 + int(.7 * width)]
    return np.median(sample.reshape(-1, 3), axis=0)


def recolour(face_rgb, neck_rgb, target):
    """Apply the original smoothed Lab recolour while preserving non-skin detail."""
    target = float(target)
    if not math.isfinite(target):
        raise ValueError("Light-reserve target must be finite")
    lightness = np.clip(target, LIGHT_MIN, LIGHT_MAX) * 100 * 100 / 255
    target_lab = np.array([lightness, 0.1346 * lightness + 6.277, 0.1746 * lightness + 8.855])
    face = color.rgb2lab(np.asarray(face_rgb, float) / 255)
    source = _patch(face, TEX_CROP)
    delta = target_lab - source

    def shift(lab, reference):
        distance = np.sqrt((((lab - reference) / np.array(SIGMA)) ** 2).sum(-1))
        weight = cv2.GaussianBlur(np.clip(1.8 - distance, 0, 1), (0, 0), 2.5)[..., None]
        result = lab + weight * delta
        result[..., 0] = np.where(result[..., 0] > 88, 88 + (result[..., 0] - 88) * 0.5, result[..., 0])
        return (np.clip(color.lab2rgb(result), 0, 1) * 255 + .5).astype(np.uint8)

    neck = color.rgb2lab(np.asarray(neck_rgb, float) / 255)
    height, width = neck.shape[:2]
    return shift(face, source), shift(neck, _patch(neck, (0, 0, width, height)))


def rgb(assets, pid, side, part):
    from skin_tones import rgb_of
    sizes = {"face": (256, 256), "neck": (128, 64), "arm": (128, 128)}
    _, _, decoded, system, _ = assets.resource(pid, side, part)
    return rgb_of(decoded[system:], *sizes[part])


def reference_embeddings(assets, pids, path):
    """Cache reference-face embeddings only while their native input pixels match."""
    from face_embed import embed
    old = {}
    if path.exists():
        with np.load(path, allow_pickle=False) as archive:
            old = {key: archive[key] for key in archive.files}
    data, missing = {}, []
    for pid in sorted(pids):
        face, _ = recolour(rgb(assets, pid, "h", "face"), rgb(assets, pid, "h", "neck"), REFERENCE)
        cropped = Image.fromarray(face).crop(TEX_CROP)
        fingerprint = hashlib.sha256(cropped.tobytes()).hexdigest()
        key = str(pid)
        if (f"hash:{key}" in old and str(old[f"hash:{key}"]) == fingerprint
                and f"emb:{key}" in old and f"lab:{key}" in old):
            result = old[f"emb:{key}"], old[f"lab:{key}"]
        else:
            result = embed(cropped, 3)
        if result is None:
            missing.append(pid)
            continue
        data[f"hash:{key}"] = np.array(fingerprint)
        data[f"emb:{key}"], data[f"lab:{key}"] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    created = False
    try:
        with temporary.open("xb") as file:
            created = True
            np.savez(file, **data)
        temporary.replace(path)
    finally:
        if created and temporary.exists():
            temporary.unlink()
    if missing:
        print(f"Warning: {len(missing)} native reserve faces could not be embedded: {missing}")
    return {pid: (data[f"emb:{pid}"], data[f"lab:{pid}"])
            for pid in pids if f"emb:{pid}" in data}
