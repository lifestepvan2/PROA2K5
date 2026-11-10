"""Fixed-layout logo image encoding with one RGBA palette for all native mips."""
import hashlib
import math
import struct

import numpy as np
from PIL import Image

import gs_texture as gs
from texture_catalogue import texture_images
from txtr_match import SWZ


def display(image: dict) -> Image.Image:
    rgba = np.frombuffer(image["rgba"], dtype=np.uint8).reshape(image["height"], image["width"], 4).copy()
    rgba[..., 3] = np.minimum(rgba[..., 3].astype(np.uint16) * 255 // 128, 255)
    return Image.fromarray(rgba)


def encode(data: bytes, system: int, video: int, descriptor: int, offsets: list[int],
           master: Image.Image, *, palette_colors: int = 256) -> tuple[bytes, dict, Image.Image]:
    images, layout, start, end = texture_images(data, system, video, descriptor, offsets)
    original = display(images[0])
    master = master.copy()
    has_alpha = "A" in master.getbands() or "transparency" in master.info
    master = master.convert("RGBA").resize(original.size, Image.Resampling.LANCZOS)
    if not has_alpha:
        master.putalpha(original.getchannel("A"))
    if master.tobytes() == original.tobytes():
        return data, {"changed": False, "layout": layout, "mips": len(images)}, original
    tex0 = struct.unpack_from("<Q", data, descriptor)[0]
    psm = (tex0 >> 20) & 63
    if psm not in (19, 20):
        raise ValueError(f"Logo POC encoding requires PSMT8/PSMT4, found PSM {psm}")
    if type(palette_colors) is not int or palette_colors not in (16, 32, 64, 128, 256):
        raise ValueError("Choose an explicit palette size: 16, 32, 64, 128 or 256")
    colors = min(256 if psm == 19 else 16, palette_colors)
    desired = []
    for image in images:
        rgba = np.array(master.resize((image["width"], image["height"]), Image.Resampling.LANCZOS))
        rgba[..., 3] = np.rint(rgba[..., 3].astype(np.float32) * 128 / 255).astype(np.uint8)
        rgba[rgba[..., 3] == 0, :3] = 0
        desired.append(rgba.reshape(-1, 4))
    pixels = np.concatenate(desired)
    width = images[0]["width"]
    sheet = np.zeros((math.ceil(len(pixels) / width) * width, 4), dtype=np.uint8)
    sheet[:len(pixels)] = pixels
    indexed = Image.fromarray(sheet.reshape(-1, width, 4)).quantize(
        colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    palette = np.asarray(indexed.getpalette("RGBA"), dtype=np.uint8).reshape(-1, 4)[:colors]
    palette = np.pad(palette, ((0, (256 if psm == 19 else 16) - len(palette)), (0, 0)))
    indices = np.asarray(indexed).ravel()[:len(pixels)]
    target, allowed = bytearray(data), np.zeros(len(data), dtype=bool)

    def write(locations: np.ndarray, values: np.ndarray) -> None:
        locations = locations.ravel()
        if (len(locations) != len(np.unique(locations)) or np.any(locations < system + start)
                or np.any(locations >= system + end) or np.any(allowed[locations])):
            raise ValueError("Overlapping or out-of-span texture/mip/palette writes")
        allowed[locations] = True
        view = np.frombuffer(target, dtype=np.uint8)
        view[locations] = values.ravel()

    if layout == "gs32-upload-64":
        y, x = np.indices((16, 16))
        positions = gs.host_offsets(gs.address32(x, y, 1, images[0]["cbp"]).ravel()[:, None] + np.arange(4), end - start)
        write(system + start + positions, palette[SWZ])
    else:
        positions = np.arange(images[0]["palette_offset"], images[0]["palette_offset"] + len(palette) * 4)
        write(positions, palette[SWZ] if psm == 19 else palette)
    position = 0
    expected = []
    for image in images:
        size = image["width"] * image["height"]
        values = indices[position:position + size]
        position += size
        if layout == "gs32-upload-64":
            locations = system + start + gs.host_offsets(gs.texture_addresses(
                image["width"], image["height"], image["tbw"], image["tbp"]), end - start)
        else:
            locations = np.arange(image["pixel_offset"], image["pixel_offset"] + (size if psm == 19 else (size + 1) // 2))
        if psm == 20:
            packed = np.zeros((size + 1) // 2, dtype=np.uint8)
            packed[:] = values[::2]
            packed[:size // 2] |= values[1::2] << 4
            if size % 2:
                packed[-1] |= target[int(locations[-1])] & 0xF0
            write(locations, packed)
        else:
            write(locations, values)
        expected.append(palette[values].tobytes())
    target = bytes(target)
    verified, _, _, _ = texture_images(target, system, video, descriptor, offsets)
    if [image["rgba"] for image in verified] != expected:
        raise ValueError("Native texture encode/decode readback failed")
    if np.any(np.frombuffer(data, dtype=np.uint8)[~allowed] != np.frombuffer(target, dtype=np.uint8)[~allowed]):
        raise ValueError("Native texture encoding changed unrelated bytes")
    actual = np.concatenate([np.frombuffer(image["rgba"], dtype=np.uint8).reshape(-1, 4) for image in verified])
    visible = pixels[:, 3] > 0
    difference = actual.astype(np.int16) - pixels.astype(np.int16)
    report = {
        "changed": target != data, "layout": layout, "mips": len(images), "palette_colors": colors,
        "rgb_rmse_visible": float(np.sqrt(np.mean(difference[visible, :3].astype(np.float64) ** 2))) if visible.any() else 0.0,
        "alpha_max_error_ps2": int(np.max(np.abs(difference[:, 3]))),
        "base_decoded_sha256": hashlib.sha256(verified[0]["rgba"]).hexdigest(),
    }
    return target, report, display(verified[0])
