"""Fixed-layout native image encoding, regenerating mips and shared palettes."""
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
    if layout == "linear-shared-indices":
        raise ValueError("Shared-index texture sets must be encoded together with encode_shared")
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
    if psm not in (0, 19, 20):
        raise ValueError(f"Native encoding requires PSMCT32/PSMT8/PSMT4, found PSM {psm}")
    if type(palette_colors) is not int or palette_colors not in (16, 32, 64, 128, 256):
        raise ValueError("Choose an explicit palette size: 16, 32, 64, 128 or 256")
    colors = min(256 if psm == 19 else 16, palette_colors)
    desired = []
    for image in images:
        rgba = np.array(master.resize((image["width"], image["height"]), Image.Resampling.LANCZOS))
        rgba[..., 3] = np.rint(rgba[..., 3].astype(np.float32) * 128 / 255).astype(np.uint8)
        rgba[rgba[..., 3] == 0, :3] = 0
        desired.append(rgba.reshape(-1, 4))
    if psm == 0:
        target = bytearray(data)
        if layout == "gs32-upload-64":
            raise ValueError("Packed PSMCT32 encoding is not supported")
        for image, rgba in zip(images, desired):
            position = image["pixel_offset"]
            if position < system + start or position + rgba.size > system + end:
                raise ValueError("True-color texture exceeds its native span")
            target[position:position + rgba.size] = rgba.tobytes()
        target = bytes(target)
        verified = texture_images(target, system, video, descriptor, offsets)[0]
        if [image["rgba"] for image in verified] != [rgba.tobytes() for rgba in desired] or target[:system] != data[:system]:
            raise ValueError("True-color native texture readback failed")
        return target, {"changed": target != data, "layout": layout, "mips": len(images),
                        "rgb_rmse_visible": 0.0, "alpha_max_error_ps2": 0}, display(verified[0])
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
    allowed_nibbles = np.zeros(len(data) * 2, dtype=bool)

    def write(locations: np.ndarray, values: np.ndarray) -> None:
        locations = locations.ravel()
        if (len(locations) != len(np.unique(locations)) or np.any(locations < system + start)
                or np.any(locations >= system + end) or np.any(allowed[locations])):
            raise ValueError("Overlapping or out-of-span texture/mip/palette writes")
        allowed[locations] = True
        allowed_nibbles[locations * 2] = True
        allowed_nibbles[locations * 2 + 1] = True
        view = np.frombuffer(target, dtype=np.uint8)
        view[locations] = values.ravel()

    if layout == "gs32-upload-64":
        y, x = np.indices((16, 16) if psm == 19 else (2, 8))
        positions = gs.host_offsets(gs.address32(x, y, 1, images[0]["cbp"]).ravel()[:, None] + np.arange(4), end - start)
        write(system + start + positions, palette[SWZ] if psm == 19 else palette)
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
            if psm == 20:
                y, x = np.indices((image["height"], image["width"]))
                nibbles = gs.address4(x, y, image["tbw"], image["tbp"]).ravel()
                locations = (system + start + gs.host_offsets(nibbles // 2, end - start)) * 2 + (nibbles & 1)
                if len(np.unique(locations)) != len(locations) or np.any(allowed_nibbles[locations]):
                    raise ValueError("Overlapping packed PSMT4 mip/palette writes")
                allowed_nibbles[locations] = True
                view = np.frombuffer(target, dtype=np.uint8)
                for half in (0, 1):
                    selected = (locations & 1) == half
                    byte_offsets = locations[selected] // 2
                    view[byte_offsets] = (view[byte_offsets] & (0xF0 if half == 0 else 0x0F)) | (values[selected] << (half * 4))
                allowed[locations // 2] = True
                expected.append(palette[values].tobytes())
                continue
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


def encode_shared(data: bytes, system: int, video: int, offsets: list[int],
                  masters: dict[int, Image.Image], *, palette_colors: int = 256) -> tuple[bytes, list[dict], dict]:
    """Quantize palette variants jointly, preserving their one shared index plane."""
    if not masters or set(masters) - set(offsets):
        raise ValueError("Shared-index encoding requires known edited descriptors")
    if type(palette_colors) is not int or palette_colors not in (16, 32, 64, 128, 256):
        raise ValueError("Invalid shared-index palette size")
    desired, locations = [], []
    for descriptor in offsets:
        images, layout, _, _ = texture_images(data, system, video, descriptor, offsets)
        if layout != "linear-shared-indices":
            raise ValueError("Mixed shared-index texture layouts")
        original = display(images[0])
        master = masters.get(descriptor)
        if master is None:
            rgba = np.frombuffer(images[0]["rgba"], dtype=np.uint8).reshape(-1, 4)
        else:
            has_alpha = "A" in master.getbands() or "transparency" in master.info
            image = master.convert("RGBA").resize(original.size, Image.Resampling.LANCZOS)
            if not has_alpha:
                image.putalpha(original.getchannel("A"))
            rgba = np.array(image).reshape(-1, 4)
            rgba[:, 3] = np.rint(rgba[:, 3].astype(np.float32) * 128 / 255).astype(np.uint8)
            rgba[rgba[:, 3] == 0, :3] = 0
        desired.append(rgba)
        locations.append(images[0]["palette_offset"])
    vectors = np.concatenate(desired, axis=1)
    values, inverse, counts = np.unique(vectors, axis=0, return_inverse=True, return_counts=True)
    values = values.astype(np.float64)

    def partition(indices):
        weights = counts[indices]
        mean = np.average(values[indices], axis=0, weights=weights)
        variance = np.sum((values[indices] - mean) ** 2 * weights[:, None], axis=0)
        return (float(variance.sum()), int(variance.argmax()), indices)

    groups = [partition(np.arange(len(values)))]
    while len(groups) < min(palette_colors, len(values)):
        selected = max(range(len(groups)), key=lambda index: groups[index][0])
        error, axis, indices = groups[selected]
        if not error or len(indices) < 2:
            break
        ordered = indices[np.argsort(values[indices, axis], kind="stable")]
        middle = int(np.searchsorted(np.cumsum(counts[ordered]), counts[ordered].sum() / 2)) + 1
        middle = min(max(1, middle), len(ordered) - 1)
        groups[selected] = partition(ordered[:middle])
        groups.append(partition(ordered[middle:]))
    mapping = np.zeros(len(values), dtype=np.uint8)
    palettes = np.zeros((256, len(offsets) * 4), dtype=np.uint8)
    for index, (_, _, entries) in enumerate(groups):
        mapping[entries] = index
        palettes[index] = np.rint(np.average(values[entries], axis=0, weights=counts[entries])).astype(np.uint8)
    indices = mapping[inverse]
    target = bytearray(data)
    target[system:system + len(indices)] = indices.tobytes()
    reports, previews = [], {}
    for index, descriptor in enumerate(offsets):
        palette = palettes[:, index * 4:(index + 1) * 4]
        location = locations[index]
        target[location:location + 1024] = palette[SWZ].tobytes()
    target = bytes(target)
    for index, descriptor in enumerate(offsets):
        images, _, _, _ = texture_images(target, system, video, descriptor, offsets)
        actual = np.frombuffer(images[0]["rgba"], dtype=np.uint8).reshape(-1, 4)
        if not np.array_equal(actual, palettes[indices, index * 4:(index + 1) * 4]):
            raise ValueError("Shared-index native readback failed")
        difference = actual.astype(np.int16) - desired[index].astype(np.int16)
        visible = desired[index][:, 3] > 0
        reports.append({"descriptor": descriptor, "changed": target != data, "layout": "linear-shared-indices",
                        "mips": 1, "palette_colors": len(groups), "shared_index_cohort": len(offsets),
                        "rgb_rmse_visible": float(np.sqrt(np.mean(difference[visible, :3].astype(np.float64) ** 2)))
                        if visible.any() else 0.0, "alpha_max_error_ps2": int(np.abs(difference[:, 3]).max())})
        previews[descriptor] = display(images[0])
    if target[:system] != data[:system] or len(target) != len(data):
        raise ValueError("Shared-index encoding changed resource geometry")
    return target, reports, previews
