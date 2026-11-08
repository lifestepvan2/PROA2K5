"""Generic source-relative lettering recolouring; no hand-tuned uniform profiles."""
import itertools
import re

import numpy as np

from txtr_match import SWZ

FIELDS = {"mode", "fill", "outline1", "outline2"}
MODES = ("palette", "monochrome", "outlined")


def parse_hex(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
        raise ValueError(f"Expected a six-digit RGB hex colour, got {value!r}")
    value = value.removeprefix("#")
    return int(value[:2], 16), int(value[2:4], 16), int(value[4:], 16)


def hex_colour(rgb: np.ndarray) -> str:
    return "#" + "".join(f"{int(channel):02X}" for channel in rgb)


def validate_controls(value: object) -> dict:
    if (not isinstance(value, dict) or set(value) != {"schema", "numbers", "names"}
            or type(value["schema"]) is not int or value["schema"] != 1):
        raise ValueError("Colour controls require schema 1 and numbers/names settings")
    for target in ("numbers", "names"):
        settings = value[target]
        if not isinstance(settings, dict) or set(settings) != FIELDS:
            raise ValueError(f"{target}: expected mode, fill, outline1 and outline2")
        if settings["mode"] not in MODES:
            raise ValueError(f"{target}: mode must be palette, monochrome or outlined")
        for field in ("fill", "outline1", "outline2"):
            parse_hex(settings[field])
    return value


def source_colours(decoded: bytes, width: int, height: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgba = np.frombuffer(decoded[-1024:], dtype=np.uint8).reshape(256, 4)[SWZ]
    indices = np.frombuffer(decoded, dtype=np.uint8, count=width * height, offset=0x70)
    counts = np.bincount(indices, minlength=256)
    ranked = [int(index) for index in np.argsort(counts)[::-1] if counts[index] and rgba[index, 3]]
    if not ranked:
        raise ValueError("Lettering atlas has no visible pixels")
    alpha = max(int(rgba[index, 3]) for index in ranked)
    solid = [index for index in ranked if rgba[index, 3] == alpha]
    rgb = rgba[:, :3].astype(float)
    fill = solid[0]
    # Avoid treating small shade/quantisation differences as another paint colour.
    outline = next((index for index in solid if np.linalg.norm(rgb[index] - rgb[fill]) >= 32), fill)
    direction = rgb[outline] - rgb[fill]
    length = float(direction @ direction)
    position = np.clip((rgb - rgb[fill]) @ direction / length, 0, 1) if length else np.zeros(256)
    distance = np.sum((rgb - (rgb[fill] + position[:, None] * direction)) ** 2, axis=1)
    distance[rgba[:, 3] == 0] = -1
    edge = int(np.argmax(distance))
    third = rgb[edge] if distance[edge] > 4 else np.array([255., 255., 255.])
    return rgba, counts, np.array([rgb[fill], rgb[outline], third])


def default_settings(decoded: bytes, width: int, height: int) -> dict[str, str]:
    _, _, bases = source_colours(decoded, width, height)
    return {"mode": "palette", **dict(zip(("fill", "outline1", "outline2"), map(hex_colour, bases)))}


def blend_weights(rgb: np.ndarray, bases: np.ndarray) -> np.ndarray:
    best = np.zeros((len(rgb), 3))
    errors = np.full(len(rgb), np.inf)
    # Closest convex blend, including edges/vertices when the bases are collinear.
    for size in range(1, 4):
        for subset in itertools.combinations(range(3), size):
            anchor = bases[subset[0]]
            directions = (bases[list(subset[1:])] - anchor).T
            if size == 1:
                weights = np.ones((len(rgb), 1))
            else:
                if np.linalg.matrix_rank(directions) != size - 1:
                    continue
                coordinates = np.linalg.lstsq(directions, (rgb - anchor).T, rcond=None)[0].T
                weights = np.column_stack((1 - coordinates.sum(axis=1), coordinates))
            valid = (weights >= -1e-10).all(axis=1)
            error = np.sum((rgb - weights @ bases[list(subset)]) ** 2, axis=1)
            use = valid & (error < errors)
            best[use] = 0
            best[np.ix_(use, subset)] = weights[use]
            errors[use] = error[use]
    return best


def recolour(decoded: bytes, width: int, height: int, settings: dict[str, str]) -> tuple[bytes, dict]:
    if settings["mode"] not in ("monochrome", "outlined"):
        raise ValueError("Recolouring requires monochrome or outlined mode")
    rgba, counts, bases = source_colours(decoded, width, height)
    desired = np.array([parse_hex(settings[field]) for field in ("fill", "outline1", "outline2")], dtype=float)
    visible = rgba[:, 3] != 0
    output = rgba.copy()
    diagnostics = {"mode": settings["mode"], "source_bases": list(map(hex_colour, bases)),
                   "model_rms_rgb": 0.0, "clipped_entries": 0}
    if settings["mode"] == "outlined" and np.array_equal(desired, bases):
        return decoded[-1024:], diagnostics
    if settings["mode"] == "monochrome" or (desired == desired[0]).all():
        output[visible, :3] = desired[0].astype(np.uint8)
    else:
        weights = blend_weights(rgba[:, :3].astype(float), bases)
        # Keep source-specific shading/quantisation residuals; never fit against a previous recolour.
        generated = np.rint(rgba[:, :3].astype(float) + weights @ (desired - bases))
        diagnostics["clipped_entries"] = int(np.count_nonzero(
            visible & ((generated < 0) | (generated > 255)).any(axis=1)))
        output[visible, :3] = np.clip(generated[visible], 0, 255).astype(np.uint8)
        residual = rgba[:, :3] - weights @ bases
        coverage = counts * (rgba[:, 3].astype(float) / 128) ** 2
        diagnostics["model_rms_rgb"] = float(np.sqrt(
            np.sum(residual ** 2 * coverage[:, None]) / (3 * coverage.sum())))
    physical = np.frombuffer(decoded[-1024:], dtype=np.uint8).reshape(256, 4).copy()
    physical[SWZ, :3] = output[:, :3]
    return physical.tobytes(), diagnostics
