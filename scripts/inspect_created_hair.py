"""Export experimental created-head vertex point clouds; does not modify the ISO."""
import argparse
import csv
import struct
from pathlib import Path

from PIL import Image, ImageDraw

from player_texture_iso import read_archive, read_asset
from texture_catalogue import object_name, relative, text
from vc_lz import decode


def vif_commands(stream: bytes):
    if len(stream) < 8:
        raise ValueError("Truncated DMA tag")
    tag, address = struct.unpack_from("<II", stream)
    if tag >> 28 != 6 or address:
        raise ValueError("Expected inline DMA CNT tag")
    offset = 8
    while offset + 4 <= len(stream):
        instruction = struct.unpack_from("<I", stream, offset)[0]
        start = offset
        offset += 4
        op = instruction >> 24 & 0x7f
        count = (instruction >> 16 & 0xff) or 256
        immediate = instruction & 0xffff
        if op >= 0x60:
            components, width = (op >> 2) & 3, op & 3
            if width == 3:
                if components != 3:
                    raise ValueError(f"Reserved VIF UNPACK at {start:#x}")
                length = count * 2
            else:
                length = count * (components + 1) * (4 >> width)
        elif op == 0x20:
            length = 4
        elif op in (0x30, 0x31):
            length = 16
        elif op == 0x4a:
            length = count * 8
        elif op in (0x50, 0x51):
            length = (immediate or 65536) * 16
        elif op in (0, 1, 2, 3, 4, 5, 6, 7, 0x10, 0x11, 0x13, 0x14, 0x15, 0x17):
            length = 0
        else:
            raise ValueError(f"Unsupported VIF command {op:#x} at {start:#x}")
        if offset + length > len(stream):
            raise ValueError(f"Truncated VIF command at {start:#x}")
        yield op, count, immediate, stream[offset:offset + length]
        offset = (offset + length + 3) & ~3
    if offset != len(stream):
        raise ValueError("Trailing partial VIF command")


def vertex_points(stream: bytes) -> list[tuple[int, int, int]]:
    group = None
    result = []
    for op, count, immediate, payload in vif_commands(stream):
        if op == 0x6d and immediate in (0x4127, 0x41dd):
            if group is not None:
                raise ValueError("Unfinished vertex batch")
            group = {"normals": None, "uv": None, "vertices": None}
        elif group is not None and op in (0x6a, 0x6e):
            group["normals"] = count
        elif group is not None and op == 0x65:
            group["uv"] = count
        elif group is not None and op == 0x6d:
            if group["normals"] != count or group["uv"] != count or group["vertices"] is not None:
                raise ValueError("Unexpected vertex batch layout")
            group["vertices"] = [row[:3] for row in struct.iter_unpack("<4H", payload)]
        elif group is not None and op in (0x14, 0x17):
            if group["vertices"] is None:
                raise ValueError("Vertex batch has no positions")
            result.extend(group["vertices"])
            group = None
    if group is not None or not result:
        raise ValueError("Unfinished or empty vertex stream")
    return result


def scene_points(package: bytes, chunk: int, expected_name: str, *, extractor=vertex_points) -> dict:
    if chunk < 0 or chunk + 32 > len(package):
        raise ValueError("Scene header outside asset")
    kind, stored, system, video, sentinel, *_ = struct.unpack_from("<4s7I", package, chunk)
    if kind != b"SCNE" or sentinel != 0xfeedbeef or chunk + 32 + stored > len(package):
        raise ValueError("Expected a complete compressed SCNE")
    data = decode(package[chunk + 32:chunk + 32 + stored], system + video,
                  collect_tokens=False)[0]
    if object_name(data, system) != expected_name:
        raise ValueError(f"Expected {expected_name} scene at {chunk:#x}")
    root = relative(data, 20, system)
    if root + 52 > system:
        raise ValueError("Truncated scene header")
    material_count = struct.unpack_from("<I", data, root + 28)[0]
    materials = relative(data, root + 32, system)
    mesh_count = struct.unpack_from("<I", data, root + 44)[0]
    if mesh_count != 1:
        raise ValueError(f"Expected one player mesh, found {mesh_count}")
    mesh = relative(data, root + 48, system)
    if mesh + 112 > system:
        raise ValueError("Truncated player mesh")
    count = struct.unpack_from("<I", data, mesh + 104)[0]
    parts = relative(data, mesh + 108, system)
    if count > (system - parts) // 24:
        raise ValueError("Truncated mesh part table")
    result = {}
    for index in range(count):
        record = parts + index * 24
        size, material = struct.unpack_from("<II", data, record + 4)
        if material >= material_count:
            raise ValueError("Mesh part material is outside the material table")
        name_ptr = materials + material * 96 + 0x58
        if name_ptr + 4 > system:
            raise ValueError("Material name pointer is outside the scene")
        if not struct.unpack_from("<I", data, name_ptr)[0]:
            raise ValueError("Mesh part material has no name")
        name = text(data, relative(data, name_ptr, system), system)
        if name != "face" and not name.startswith("hair"):
            continue
        if name in result:
            raise ValueError(f"Multiple parts use {name}; cannot export unambiguously")
        start = relative(data, record, system)
        if not size or start + size > system:
            raise ValueError(f"Invalid stream for {name}")
        result[name] = (index, extractor(data[start:start + size]))
    if "face" not in result:
        raise ValueError("Scene has no face part for orientation")
    return result


def write_ply(path: Path, face: list, hair: list) -> None:
    with path.open("x", encoding="ascii", newline="\n") as out:
        out.write("ply\nformat ascii 1.0\ncomment Quantized local points only; not a surface\n")
        out.write(f"element vertex {len(face) + len(hair)}\n")
        out.write("property float x\nproperty float y\nproperty float z\n")
        out.write("property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
        for points, colour in ((face, "130 130 130"), (hair, "255 188 72")):
            for x, y, z in points:
                out.write(f"{x} {y} {z} {colour}\n")


def draw_projection(draw, box, face: list, hair: list, axes: tuple[int, int]) -> None:
    x0, y0, x1, y1 = box
    values = face + hair
    a, b = axes
    lo_a, hi_a = min(v[a] for v in values), max(v[a] for v in values)
    lo_b, hi_b = min(v[b] for v in values), max(v[b] for v in values)
    span = max(hi_a - lo_a, hi_b - lo_b)
    if not span:
        raise ValueError("Degenerate point cloud")
    scale = min(x1 - x0, y1 - y0) * 0.88 / span
    cx, cy = (lo_a + hi_a) / 2, (lo_b + hi_b) / 2
    for cloud, colour, radius in ((face, "#858585", 1), (hair, "#ffbc48", 2)):
        for value in cloud:
            x = (x0 + x1) / 2 + (value[a] - cx) * scale
            y = (y0 + y1) / 2 - (value[b] - cy) * scale
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colour)


def inspect(source: Path, output: Path, head: int) -> None:
    if not 0 <= head <= 6:
        raise ValueError("Head must be in 0..6")
    if output.exists():
        raise ValueError("Output directory already exists")
    rows = []
    panels = []
    with source.open("rb") as iso:
        entries = read_archive(iso, verify_hash=False)
        _, low_asset = read_asset(iso, entries, "gamedataextra.iff")
        low = scene_points(low_asset, 0x117700, "locreatehead")
        specs = [(f"low_{i:02}", "gamedataextra.iff", low, f"hair{i:02}_mat")
                 for i in range(1, 4)]
        for style in range(26):
            asset = f"hihead{head:02}{style:02}.iff"
            _, package = read_asset(iso, entries, asset)
            scene = scene_points(package, 0, "hihead")
            hair = None if style == 0 else f"hair{style - 1:02}_mat"
            specs.append((f"high_{head:02}_{style:02}", asset, scene, hair))
        for label, asset, scene, name in specs:
            expected = {key for key in scene if key.startswith("hair")}
            if expected != ({name} if name else set()) and not label.startswith("low_"):
                raise ValueError(f"Unexpected hair materials in {asset}: {sorted(expected)}")
            face = scene["face"][1]
            part, hair = scene[name] if name else ("", [])
            rows.append((label, asset, name or "bald", part, len(face), len(hair)))
            panels.append((label, name or "bald", face, hair))

    output.mkdir(parents=True)
    for label, _, face, hair in panels:
        write_ply(output / f"{label}.ply", face, hair)
    with (output / "inventory.csv").open("x", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(("label", "asset", "material", "mesh_part", "face_points", "hair_points"))
        writer.writerows(rows)
    columns, width, height = 3, 540, 230
    for page_start in range(0, len(panels), 9):
        page = panels[page_start:page_start + 9]
        image = Image.new("RGB", (columns * width, 3 * height), "#1c2028")
        draw = ImageDraw.Draw(image)
        for i, (label, name, face, hair) in enumerate(page):
            x, y = (i % columns) * width, (i // columns) * height
            draw.text((x + 5, y + 5), f"{label}: {name}  (points only)", fill="white")
            draw_projection(draw, (x, y + 24, x + 265, y + height), face, hair, (0, 1))
            draw_projection(draw, (x + 270, y + 24, x + 535, y + height), face, hair, (2, 1))
        image.save(output / f"points_{page_start // 9 + 1:02}.png")
    print(f"Exported {len(rows)} point clouds to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory for review files")
    parser.add_argument("--head", type=int, default=0, help="Created-head selector, 0..6")
    args = parser.parse_args()
    inspect(args.iso_source, args.output, args.head)


if __name__ == "__main__":
    main()
