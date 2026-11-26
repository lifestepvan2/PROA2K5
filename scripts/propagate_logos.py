"""Replace native frontend flipchips with cropped ProA logos.

    python scripts\\propagate_logos.py [--workspace DIR] [--dry-run]

This overwrites the matching native masters; review or back up manual edits first.
"""
import argparse
import io
import re
from pathlib import Path

from PIL import Image, ImageOps

import remaining_texture_workspace as remaining
import texture_iso_workspace as native
from texlib import proa_slots

LOGOS = native.ROOT / "nba2k_editor" / "assets"
LOGO_ID0 = 38
FLIPCHIP = re.compile(r"(\d{3})_flipchip_00")


def assignments(indices: list[int], fixed: dict[int, int], teams: list[int]) -> dict[int, int]:
    indices = sorted(indices)
    if len(indices) < 2 or len(set(indices)) != len(indices):
        raise ValueError("Flipchip indices must be unique and contain at least two entries")
    if len(teams) < 2 or len(set(teams)) != len(teams):
        raise ValueError("At least two unique ProA teams are required")
    if set(fixed) - set(indices) or set(fixed.values()) - set(teams):
        raise ValueError("Fixed flipchip assignments must reference existing indices and teams")
    result = {}
    cursor = 0
    for pos, index in enumerate(indices):
        previous = result[indices[pos - 1]] if pos else fixed.get(indices[-1])
        following = fixed.get(indices[pos + 1]) if pos + 1 < len(indices) else None
        first = result[indices[0]] if pos == len(indices) - 1 else None
        if index in fixed:
            choice = fixed[index]
            if choice == previous or choice == first:
                raise ValueError(f"Fixed flipchip {index:03} repeats an adjacent team")
        else:
            for step in range(len(teams)):
                candidate = (cursor + step) % len(teams)
                if teams[candidate] not in (previous, following, first):
                    choice = teams[candidate]
                    cursor = (candidate + 1) % len(teams)
                    break
            else:
                raise ValueError(f"Cannot assign flipchip {index:03} without adjacent repeats")
        result[index] = choice
    return result


def cropped_logo(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        logo = source.convert("RGBA")
    bounds = logo.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if bounds is None:
        raise ValueError(f"Empty ProA logo: {path}")
    logo = ImageOps.fit(logo.crop(bounds), size, method=Image.Resampling.LANCZOS)
    background = Image.new("RGBA", size, (32, 32, 32, 255))
    background.alpha_composite(logo)
    return background


def propagate(workspace: Path, logo_dir: Path = LOGOS, *, dry_run: bool = False) -> dict[int, int]:
    native.validate_workspace(workspace)
    manifest = remaining.load_manifest(workspace)
    rows = []
    for row in manifest["sources"]:
        match = FLIPCHIP.fullmatch(row["texture"])
        if row["asset"] == "frontend.iff" and match:
            if not row["editable"]:
                raise ValueError(f"Flipchip {row['texture']} is not editable")
            rows.append((int(match[1]), row))
    if len({row["id"] for _, row in rows}) != len(rows):
        raise ValueError("Flipchip manifest contains duplicate native master IDs")
    slots = proa_slots()
    teams = sorted(slots.values())
    if teams != list(range(len(teams))):
        raise ValueError("ProA team mapping must contain each logo index exactly once")
    fixed = {team_id: slots[slot] for team_id, slot in native.team_ids().items() if slot in slots}
    if set(fixed.values()) != set(teams):
        raise ValueError("ProA slots do not all have distinct native team IDs")
    plan = assignments([index for index, _ in rows], fixed, teams)
    files = native.scan(workspace, [row for _, row in rows])
    pending = []
    cache = {}
    for index, row in sorted(rows, key=lambda item: item[0]):
        path = files[row["id"]]
        size = (row["width"], row["height"])
        key = (plan[index], size)
        if key not in cache:
            cache[key] = cropped_logo(logo_dir / f"{LOGO_ID0 + plan[index]}.png", size)
        image = cache[key]
        fmt = Image.registered_extensions()[path.suffix.lower()]
        if fmt == "JPEG":
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format=fmt)
        pending.append((path, output.getvalue()))
    if not dry_run:
        for path, data in pending:
            path.write_bytes(data)
    for index, team in plan.items():
        print(f"{index:03}: {LOGO_ID0 + team}.png{' (team slot)' if index in fixed else ''}")
    print(f"{'Would replace' if dry_run else 'Replaced'} {len(pending)} flipchip masters")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=native.DEFAULT_WS)
    parser.add_argument("--dry-run", action="store_true", help="validate and show assignments without writing")
    args = parser.parse_args()
    propagate(args.workspace, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
