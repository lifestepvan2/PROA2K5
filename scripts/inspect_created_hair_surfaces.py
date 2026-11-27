"""Export experimental created-head triangle surfaces; does not modify the ISO."""
import argparse
import csv
import struct
from pathlib import Path

from PIL import Image, ImageDraw

from inspect_created_hair import scene_points, vif_commands
from player_texture_iso import read_archive, read_asset


def vertex_surface(stream: bytes) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    memory = {}
    group = None
    vertices = []
    faces = []
    for op, count, immediate, payload in vif_commands(stream):
        if op == 0x6d and immediate in (0x4127, 0x41dd):
            if group is not None:
                raise ValueError("Unfinished surface batch")
            words = struct.unpack("<" + "H" * (len(payload) // 2), payload)
            if len(words) < 12:
                raise ValueError("Short surface batch header")
            copy_start = words[6] - (immediate & 0x3ff)
            if copy_start < 3 or copy_start * 4 > len(words):
                raise ValueError("Invalid surface copy-list pointer")
            group = {"header": words[:12], "references": words[copy_start * 4:],
                     "normal_count": None, "uv_count": None, "positions": None}
        elif group is not None and op in (0x6a, 0x6e):
            if group["normal_count"] is not None:
                raise ValueError("Duplicate surface normals")
            group["normal_count"] = count
        elif group is not None and op == 0x65:
            if group["uv_count"] is not None:
                raise ValueError("Duplicate surface UVs")
            group["uv_count"] = count
        elif group is not None and op == 0x6d:
            if (group["normal_count"] != count or group["uv_count"] != count
                    or group["positions"] is not None):
                raise ValueError("Unexpected surface vertex layout")
            group["positions"] = list(struct.iter_unpack("<4H", payload))
        elif group is not None and op in (0x14, 0x17):
            header, refs = group["header"], group["references"]
            if group["positions"] is None:
                raise ValueError("Surface batch has no positions")
            for x, y, z, address in group["positions"]:
                memory[address] = (x, y, z)
            copies = header[1] + header[2]
            if len(refs) != 4 * (copies + header[3]):
                raise ValueError("Invalid surface batch metadata length")
            try:
                for i in range(copies):
                    a, b, c, d = refs[i * 4:i * 4 + 4]
                    memory[c], memory[d] = memory[a], memory[b]
                start = header[5] + 1
                size = header[4] & 0x7fff
                marks = set(refs[copies * 4:])
                if any(not start <= a < start + size * 3 or (a - start) % 3 for a in marks):
                    raise ValueError("Surface strip marker outside packet")
                packet = [memory[start + 3 * i] for i in range(size)]
            except KeyError as exc:
                raise ValueError(f"Surface references missing VU vertex {exc.args[0]:#x}") from exc
            base = len(vertices)
            vertices.extend(packet)
            for i in range(2, size):
                address = start + i * 3
                if address in marks or address - 3 in marks:
                    continue
                tri = (base + i - 2, base + i - 1, base + i)
                faces.append((tri[1], tri[0], tri[2]) if i & 1 else tri)
            group = None
    if group is not None or not vertices:
        raise ValueError("Unfinished or empty surface stream")
    return vertices, faces


def write_obj(path: Path, face: tuple, hair: tuple) -> None:
    with path.open("x", encoding="ascii", newline="\n") as out:
        out.write("# Experimental untextured, untransformed quantized coordinates\n")
        base = 1
        for label, (vertices, faces) in (("face", face), ("hair", hair)):
            out.write(f"g {label}\n")
            for x, y, z in vertices:
                out.write(f"v {x} {y} {z}\n")
            for a, b, c in faces:
                out.write(f"f {a + base} {b + base} {c + base}\n")
            base += len(vertices)


def draw_surface(draw, box, meshes, axes):
    points = [point for _, (vertices, _) in meshes for point in vertices]
    a, b, depth = axes
    bounds = [(min(p[k] for p in points), max(p[k] for p in points)) for k in range(3)]
    span = max(bounds[a][1] - bounds[a][0], bounds[b][1] - bounds[b][0])
    if not span:
        raise ValueError("Degenerate surface")
    x0, y0, x1, y1 = box
    scale = min(x1 - x0, y1 - y0) * 0.86 / span
    mid = [(low + high) / 2 for low, high in bounds]
    triangles = []
    for color, (vertices, faces) in meshes:
        for face in faces:
            positions = [vertices[i] for i in face]
            polygon = [(x0 + (x1 - x0) / 2 + (p[a] - mid[a]) * scale,
                        y0 + (y1 - y0) / 2 - (p[b] - mid[b]) * scale)
                       for p in positions]
            triangles.append((sum(p[depth] for p in positions), polygon, color))
    for _, polygon, color in sorted(triangles):
        draw.polygon(polygon, fill=color, outline="#44484f")


def inspect(source: Path, output: Path, head: int) -> None:
    if not 0 <= head <= 6:
        raise ValueError("Head must be in 0..6")
    if output.exists():
        raise ValueError("Output directory already exists")
    panels = []
    with source.open("rb") as iso:
        entries = read_archive(iso, verify_hash=False)
        _, package = read_asset(iso, entries, "gamedataextra.iff")
        low = scene_points(package, 0x117700, "locreatehead", extractor=vertex_surface)
        for i in range(1, 4):
            name = f"hair{i:02}_mat"
            panels.append((f"low_{i:02}", "gamedataextra.iff", name,
                           low["face"][1], low[name][1]))
        for style in range(26):
            asset = f"hihead{head:02}{style:02}.iff"
            _, package = read_asset(iso, entries, asset)
            scene = scene_points(package, 0, "hihead", extractor=vertex_surface)
            name = f"hair{style - 1:02d}_mat" if style else None
            expected = {key for key in scene if key.startswith("hair")}
            if expected != ({name} if name else set()):
                raise ValueError(f"Unexpected hair materials in {asset}: {sorted(expected)}")
            panels.append((f"high_{head:02}_{style:02}", asset, name or "bald",
                           scene["face"][1], scene[name][1] if name else ([], [])))
    output.mkdir(parents=True)
    with (output / "inventory.csv").open("x", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(("label", "asset", "material", "face_triangles", "hair_triangles"))
        for label, asset, name, face, hair in panels:
            writer.writerow((label, asset, name, len(face[1]), len(hair[1])))
            write_obj(output / f"{label}.obj", face, hair)
    width, height = 540, 230
    for page_start in range(0, len(panels), 9):
        image = Image.new("RGB", (3 * width, 3 * height), "#1c2028")
        draw = ImageDraw.Draw(image)
        for i, (label, _, name, face, hair) in enumerate(panels[page_start:page_start + 9]):
            x, y = (i % 3) * width, (i // 3) * height
            draw.text((x + 5, y + 5), f"{label}: {name} (untextured, experimental)", fill="white")
            meshes = [("#858585", face), ("#ffbc48", hair)]
            draw_surface(draw, (x, y + 24, x + 265, y + height), meshes, (0, 1, 2))
            draw_surface(draw, (x + 270, y + 24, x + 535, y + height), meshes, (2, 1, 0))
        image.save(output / f"surfaces_{page_start // 9 + 1:02}.png")
    print(f"Exported {len(panels)} experimental surfaces to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory for review files")
    parser.add_argument("--head", type=int, default=0, help="Created-head selector, 0..6")
    args = parser.parse_args()
    inspect(args.iso_source, args.output, args.head)


if __name__ == "__main__":
    main()
