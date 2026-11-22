"""Create editable horizontal strips from indexed workspace PNG tiles.

Defaults to arena sts_* tiles. Derived images live under _stitched, outside
native master discovery. Sidecars retain the original filenames for splitting.
"""
import argparse
import json
import os
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "texture_workspace_ISO"
DEFAULT_GROUPS = "arenas/slot_*/props/s[0-9][0-9][0-9]"
DEFAULT_TILES = "sts_*/*.png"
DEFAULT_INDEX = r"^sts_(\d+)[\\/]"


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"Path is outside the workspace: {relative}")
    return path


def name_value(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError("Strip name must contain only letters, digits, underscores or hyphens")
    return value


def groups_in(workspace: Path, pattern: str) -> list[Path]:
    groups = sorted(path for path in workspace.glob(pattern)
                    if path.is_dir() and not any(part.startswith("_")
                                                for part in path.relative_to(workspace).parts))
    if not groups:
        raise ValueError(f"No texture groups match {pattern!r} in {workspace}")
    for group in groups:
        inside(workspace, str(group.relative_to(workspace)))
    return groups


def publish(files: list[tuple[Path, Image.Image | dict]]) -> None:
    """Stage every output before replacing any existing file."""
    staged = []
    try:
        for path, content in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            with temporary.open("xb") as file:
                staged.append((temporary, path))
                if isinstance(content, Image.Image):
                    content.save(file, format="PNG")
                else:
                    file.write((json.dumps(content, indent=2) + "\n").encode("utf-8"))
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def stitch(workspace: Path = DEFAULT_WORKSPACE, groups: str = DEFAULT_GROUPS,
           tiles: str = DEFAULT_TILES, index_regex: str = DEFAULT_INDEX,
           tile_size: tuple[int, int] = (128, 128), name: str = "sts") -> list[dict]:
    workspace = workspace.resolve()
    name_value(name)
    if len(tile_size) != 2 or any(value <= 0 for value in tile_size):
        raise ValueError("Tile dimensions must be positive")
    expression = re.compile(index_regex)
    if not expression.groups:
        raise ValueError("Index regex needs a capture group for the numeric tile index")
    outputs, reports = [], []
    for group in groups_in(workspace, groups):
        indexed = {}
        for path in sorted(group.glob(tiles)):
            if not path.is_file():
                continue
            path = inside(workspace, str(path.relative_to(workspace)))
            if path.suffix.lower() != ".png":
                raise ValueError(f"Only PNG tiles are supported: {path}")
            match = expression.search(str(path.relative_to(group)))
            if match is None:
                raise ValueError(f"Tile has no index matching {index_regex!r}: {path}")
            index = int(match.group(1))
            if index < 0:
                raise ValueError(f"Negative tile index in {path}")
            if index in indexed:
                raise ValueError(f"Duplicate tile index {index} in {group}")
            indexed[index] = path
        if not indexed:
            raise ValueError(f"No tiles matching {tiles!r} in {group}")
        ordered = sorted(indexed.items())
        width, height = tile_size
        canvas = Image.new("RGBA", (width * len(ordered), height))
        for column, (_, path) in enumerate(ordered):
            with Image.open(path) as image:
                if image.format != "PNG" or image.size != tile_size:
                    raise ValueError(f"{path}: expected {width}x{height} PNG, got {image.size}")
                canvas.paste(image.convert("RGBA"), (column * width, 0))
        relative_group = str(group.relative_to(workspace))
        directory = workspace / "_stitched" / relative_group
        metadata = {
            "schema": 1, "group": relative_group, "tile_size": list(tile_size),
            "tiles": [{"index": index, "path": str(path.relative_to(workspace))}
                      for index, path in ordered],
        }
        outputs.extend([(directory / f"{name}.png", canvas),
                        (directory / f"{name}.json", metadata)])
        reports.append({"group": relative_group, "tiles": len(ordered),
                        "size": canvas.size, "image": directory / f"{name}.png"})
    publish(outputs)
    return reports


def split(workspace: Path = DEFAULT_WORKSPACE, groups: str = DEFAULT_GROUPS,
          name: str = "sts") -> list[dict]:
    workspace = workspace.resolve()
    name_value(name)
    outputs, reports, destinations = [], [], set()
    for group in groups_in(workspace, groups):
        relative_group = str(group.relative_to(workspace))
        directory = workspace / "_stitched" / relative_group
        metadata_path = directory / f"{name}.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (metadata.get("schema") != 1 or metadata.get("group") != relative_group
                or not isinstance(metadata.get("tiles"), list) or not metadata["tiles"]):
            raise ValueError(f"Invalid strip sidecar: {metadata_path}")
        size = metadata.get("tile_size")
        if (not isinstance(size, list) or len(size) != 2
                or any(type(value) is not int or value <= 0 for value in size)):
            raise ValueError(f"Invalid tile dimensions: {metadata_path}")
        width, height = size
        indices = [tile["index"] for tile in metadata["tiles"]]
        if (any(type(index) is not int or index < 0 for index in indices)
                or indices != sorted(set(indices))):
            raise ValueError(f"Invalid tile ordering: {metadata_path}")
        image_path = directory / f"{name}.png"
        with Image.open(image_path) as image:
            expected = (width * len(indices), height)
            if image.format != "PNG" or image.size != expected or image.mode not in ("RGB", "RGBA"):
                raise ValueError(f"{image_path}: expected {expected} RGB/RGBA PNG; do not resize the strip")
            for column, tile in enumerate(metadata["tiles"]):
                path = inside(workspace, tile["path"])
                if not path.is_relative_to(group) or path.suffix.lower() != ".png":
                    raise ValueError(f"Tile destination is outside its source group: {path}")
                if path in destinations:
                    raise ValueError(f"Duplicate tile destination: {path}")
                destinations.add(path)
                with Image.open(path) as original:
                    if original.format != "PNG" or original.size != (width, height):
                        raise ValueError(f"Original tile dimensions changed: {path}; restitch first")
                    crop = image.crop((column * width, 0, (column + 1) * width, height)).convert("RGBA")
                    if image.mode == "RGB":
                        crop.putalpha(original.convert("RGBA").getchannel("A"))
                outputs.append((path, crop))
        reports.append({"group": relative_group, "tiles": len(indices)})
    publish(outputs)
    return reports


def parser(description: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    result.add_argument("--groups", default=DEFAULT_GROUPS, help="workspace-relative directory glob")
    result.add_argument("--name", default="sts", help="derived strip/sidecar name")
    return result


def main() -> None:
    arguments = parser(__doc__)
    arguments.add_argument("--tiles", default=DEFAULT_TILES, help="group-relative PNG glob")
    arguments.add_argument("--index-regex", default=DEFAULT_INDEX,
                           help="regex on group-relative tile paths; capture group 1 is the integer index")
    arguments.add_argument("--tile-size", type=int, nargs=2, default=(128, 128), metavar=("WIDTH", "HEIGHT"))
    args = arguments.parse_args()
    try:
        reports = stitch(args.workspace, args.groups, args.tiles, args.index_regex,
                         (args.tile_size[0], args.tile_size[1]), args.name)
    except (ValueError, OSError, re.error) as error:
        arguments.exit(1, f"Stitch failed: {error}\n")
    for report in reports:
        print(f"{report['group']}: {report['tiles']} tiles -> {report['size']} {report['image']}")


if __name__ == "__main__":
    main()
