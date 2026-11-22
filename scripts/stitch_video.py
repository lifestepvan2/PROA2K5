"""Stitch native jumbotron movie frames into 50 fps animated GIFs."""
import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from PIL import GifImagePlugin, Image

from stitch_textures import groups_in, inside, name_value

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "texture_workspace_ISO"
DEFAULT_GROUPS = "jumbotron_movies/slot_*/hash_*"
FRAME_SIZE = (64, 64)
FRAME_COUNT = 180
FPS = 50
GIF_DURATIONS_MS = [20] * FRAME_COUNT
VIDEO_NAME = "jumbotron_movie"
INDEX = re.compile(r"jumbotron_movie(\d+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def video_paths(workspace: Path, group: Path, name: str) -> tuple[Path, Path]:
    relative_group = group.relative_to(workspace).as_posix()
    directory = inside(workspace, f"_videos/{relative_group}")
    return directory / f"{name}.gif", directory / f"{name}.json"


def frame_sources(workspace: Path, group: Path) -> list[dict]:
    indexed = {}
    for path in group.iterdir():
        if not path.is_file():
            continue
        path = inside(workspace, str(path.relative_to(workspace)))
        if path.suffix.lower() != ".png":
            raise ValueError(f"Only PNG jumbotron frames are supported: {path}")
        match = INDEX.search(path.name)
        if match is None:
            raise ValueError(f"Frame index missing from filename: {path}")
        index = int(match.group(1))
        if index in indexed:
            raise ValueError(f"Duplicate jumbotron frame index {index} in {group}")
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != FRAME_SIZE:
                raise ValueError(f"{path}: expected 64x64 PNG, got {image.size}")
        indexed[index] = {
            "index": index,
            "path": path,
            "sha256": sha256(path),
        }
    if sorted(indexed) != list(range(FRAME_COUNT)):
        raise ValueError(f"{group}: expected exactly 180 frames indexed 000-179")
    return [indexed[index] for index in range(FRAME_COUNT)]


def temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp{path.suffix}")


def inspect_gif(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        if image.format != "GIF" or image.size != FRAME_SIZE:
            raise ValueError(f"{path}: expected 64x64 GIF, got {image.format} {image.size}")
        frame_count = getattr(image, "n_frames", 1)
        if type(frame_count) is not int or frame_count < 1:
            raise ValueError(f"{path}: GIF must contain at least one frame")
        duration = 0
        for index in range(min(frame_count, FRAME_COUNT)):
            image.seek(index)
            if image.size != FRAME_SIZE:
                raise ValueError(f"{path}: frame {index} is not 64x64")
            delay = image.info.get("duration", 0)
            if type(delay) is not int or delay < 0:
                raise ValueError(f"{path}: invalid GIF delay on frame {index}")
            duration += delay
    return frame_count, duration


def write_gif(path: Path, frames: list[Image.Image]) -> None:
    header, _ = GifImagePlugin.getheader(frames[0], info={"loop": 0})
    with path.open("wb") as output:
        for chunk in header:
            output.write(chunk)
        # Write each frame block directly; Pillow's save_all merges identical neighbors.
        for frame, duration in zip(frames, GIF_DURATIONS_MS):
            for chunk in GifImagePlugin.getdata(
                    frame, duration=duration, disposal=2, include_color_table=True):
                output.write(chunk)
        output.write(b";")


def stitch(workspace: Path = DEFAULT_WORKSPACE, groups: str = DEFAULT_GROUPS,
           name: str = VIDEO_NAME, overwrite: bool = False) -> list[dict]:
    workspace = workspace.resolve()
    name_value(name)
    selected = []
    for group in groups_in(workspace, groups):
        frames = frame_sources(workspace, group)
        video, sidecar = video_paths(workspace, group, name)
        selected.append({
            "group": group,
            "relative_group": group.relative_to(workspace).as_posix(),
            "frames": frames,
            "video": video,
            "sidecar": sidecar,
        })

    staged = []
    reports = []
    try:
        for job in selected:
            if job["video"].is_file() and not overwrite:
                frame_count, _ = inspect_gif(job["video"])
                reports.append({
                    "group": job["relative_group"],
                    "frames": frame_count,
                    "video": job["video"],
                    "skipped": True,
                })
                continue
            job["video"].parent.mkdir(parents=True, exist_ok=True)
            temporary_video = temporary_path(job["video"])
            staged.append((temporary_video, job["video"]))
            paletted_frames = []
            for source in job["frames"]:
                if sha256(source["path"]) != source["sha256"]:
                    raise ValueError(f"Frame changed during stitch; retry: {source['path']}")
                with Image.open(source["path"]) as image:
                    rgb = image.convert("RGB")
                    paletted_frames.append(rgb.quantize(
                        colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
                    ))
            write_gif(temporary_video, paletted_frames)
            if not temporary_video.is_file() or temporary_video.stat().st_size == 0:
                raise ValueError(f"GIF encoder produced no output: {job['video']}")
            frame_count, duration_ms = inspect_gif(temporary_video)
            if frame_count != FRAME_COUNT or duration_ms != 3600:
                raise ValueError(
                    f"{temporary_video}: expected 180 frames and 3600 ms, "
                    f"got {frame_count} frames and {duration_ms} ms"
                )

            metadata = {
                "schema": 2,
                "group": job["relative_group"],
                "video": job["video"].relative_to(workspace).as_posix(),
                "format": "GIF",
                "fps": int(FPS),
                "frame_size": list(FRAME_SIZE),
                "duration_ms": duration_ms,
                "frames": [
                    {
                        "index": source["index"],
                        "path": source["path"].relative_to(workspace).as_posix(),
                        "sha256": source["sha256"],
                    }
                    for source in job["frames"]
                ],
            }
            temporary_sidecar = temporary_path(job["sidecar"])
            staged.append((temporary_sidecar, job["sidecar"]))
            temporary_sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            reports.append({
                "group": job["relative_group"],
                "frames": FRAME_COUNT,
                "video": job["video"],
                "skipped": False,
            })
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return reports


def load_metadata(workspace: Path, group: Path, name: str) -> tuple[dict, list[dict], Path]:
    video, sidecar = video_paths(workspace, group, name)
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    relative_group = group.relative_to(workspace).as_posix()
    relative_video = video.relative_to(workspace).as_posix()
    legacy_video = video.with_suffix(".mp4").relative_to(workspace).as_posix()
    if (isinstance(metadata, dict)
            and metadata.get("schema") == 1
            and metadata.get("codec") == "H.264"
            and metadata.get("video") == legacy_video):
        metadata = dict(metadata)
        metadata.pop("codec")
        metadata.update(
            schema=2,
            video=relative_video,
            format="GIF",
            fps=int(FPS),
            duration_ms=inspect_gif(video)[1],
        )
    elif (isinstance(metadata, dict)
            and metadata.get("schema") == 2
            and metadata.get("format") == "GIF"
            and metadata.get("video") == relative_video
            and metadata.get("fps") == 60):
        metadata = dict(metadata)
        metadata["fps"] = int(FPS)
        metadata["duration_ms"] = inspect_gif(video)[1]
    if (not isinstance(metadata, dict)
            or metadata.get("schema") != 2
            or metadata.get("group") != relative_group
            or metadata.get("video") != relative_video
            or metadata.get("format") != "GIF"
            or metadata.get("fps") not in (int(FPS), 60)
            or metadata.get("frame_size") != list(FRAME_SIZE)
            or type(metadata.get("duration_ms")) is not int
            or metadata["duration_ms"] < 0):
        raise ValueError(f"Invalid jumbotron video sidecar: {sidecar}")
    sources = metadata.get("frames")
    if not isinstance(sources, list) or len(sources) != FRAME_COUNT:
        raise ValueError(f"{sidecar}: expected exactly 180 frame mappings")
    if any(not isinstance(source, dict) for source in sources):
        raise ValueError(f"Invalid frame mapping in {sidecar}")
    indices = [source.get("index") for source in sources]
    if (any(type(index) is not int for index in indices)
            or indices != list(range(FRAME_COUNT))):
        raise ValueError(f"{sidecar}: frame indices must be exactly 000-179 in order")

    paths, checked = set(), []
    for source in sources:
        relative = source.get("path")
        expected_hash = source.get("sha256")
        if (not isinstance(relative, str)
                or not isinstance(expected_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)):
            raise ValueError(f"Invalid frame mapping in {sidecar}")
        path = inside(workspace, relative)
        if path.parent != group or path.suffix.lower() != ".png":
            raise ValueError(f"Frame destination is outside its source group: {path}")
        if path in paths:
            raise ValueError(f"Duplicate frame destination: {path}")
        paths.add(path)
        if not path.is_file():
            raise ValueError(f"Missing original frame: {path}")
        if sha256(path) != expected_hash:
            raise ValueError(f"Original frame changed since stitch; restitch first: {path}")
        checked.append({"index": source["index"], "path": path})

    current_frames = {
        inside(workspace, str(path.relative_to(workspace)))
        for path in group.glob("*.png")
        if path.is_file()
    }
    if current_frames != paths:
        raise ValueError(f"{group}: frame set changed since stitch; restitch first")
    return metadata, checked, video


def read_gif(path: Path) -> tuple[list[Image.Image], int]:
    frame_count, duration_ms = inspect_gif(path)
    frames = []
    with Image.open(path) as image:
        for index in range(min(frame_count, FRAME_COUNT)):
            image.seek(index)
            frames.append(image.convert("RGB").copy())
    while len(frames) < FRAME_COUNT:
        frames.append(frames[-1].copy())
    return frames, duration_ms


def split(workspace: Path = DEFAULT_WORKSPACE, groups: str = DEFAULT_GROUPS,
          name: str = VIDEO_NAME) -> list[dict]:
    workspace = workspace.resolve()
    name_value(name)
    staged, reports = [], []
    try:
        for group in groups_in(workspace, groups):
            metadata, sources, video = load_metadata(workspace, group, name)
            frames, duration_ms = read_gif(video)
            metadata["fps"] = int(FPS)
            metadata["duration_ms"] = duration_ms
            updated_sources = []
            for source, frame in zip(sources, frames):
                if sha256(source["path"]) != metadata["frames"][source["index"]]["sha256"]:
                    raise ValueError(f"Frame changed during split; retry: {source['path']}")
                with Image.open(source["path"]) as original:
                    output = frame.convert("RGBA")
                    output.putalpha(original.convert("RGBA").getchannel("A"))
                temporary = temporary_path(source["path"])
                staged.append((temporary, source["path"]))
                output.save(temporary, format="PNG")
                updated_sources.append({
                    "index": source["index"],
                    "path": source["path"].relative_to(workspace).as_posix(),
                    "sha256": sha256(temporary),
                })
            metadata["frames"] = updated_sources
            _, sidecar = video_paths(workspace, group, name)
            temporary_sidecar = temporary_path(sidecar)
            staged.append((temporary_sidecar, sidecar))
            temporary_sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            reports.append({"group": group.relative_to(workspace).as_posix(), "frames": FRAME_COUNT})
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return reports


def parser(description: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    result.add_argument("--groups", default=DEFAULT_GROUPS, help="workspace-relative directory glob")
    result.add_argument("--name", default=VIDEO_NAME, help="derived video/sidecar name")
    return result


def main() -> None:
    arguments = parser(__doc__)
    arguments.add_argument(
        "--overwrite", action="store_true", help="regenerate existing GIFs from the current PNG frames"
    )
    args = arguments.parse_args()
    try:
        reports = stitch(args.workspace, args.groups, args.name, args.overwrite)
    except (ValueError, OSError, KeyError, TypeError, re.error) as error:
        arguments.exit(1, f"GIF stitch failed: {error}\n")
    for report in reports:
        action = "kept" if report["skipped"] else "created"
        print(f"{report['group']}: {action} {report['frames']}-frame GIF -> {report['video']}")


if __name__ == "__main__":
    main()
