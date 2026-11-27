"""Replace native flipchips, logo sheets and team logos with ProA logos.

    python scripts\\propagate_logos.py [--workspace DIR] [--dry-run]

This overwrites the matching native masters; review or back up manual edits first.
"""
import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import remaining_texture_workspace as remaining
import texture_iso_workspace as native
import workspace_images
from texlib import proa_slots

LOGOS = native.ROOT / "nba2k_editor" / "assets"
LOGO_ID0 = 38
FLIPCHIP = re.compile(r"(\d{3})_flipchip_00")
STUDIO_ATLAS_ID = "217648db"
TITLE_SHEET_ID = "ea06148d"


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


def load_logo(path: Path) -> Image.Image:
    with Image.open(path) as source:
        logo = source.convert("RGBA")
    bounds = logo.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if bounds is None:
        raise ValueError(f"Empty ProA logo: {path}")
    return logo.crop(bounds)


def cropped_logo(path: Path, size: tuple[int, int]) -> Image.Image:
    logo = ImageOps.fit(load_logo(path), size, method=Image.Resampling.LANCZOS)
    background = Image.new("RGBA", size, (32, 32, 32, 255))
    background.alpha_composite(logo)
    return background


def full_logo(path: Path, size: tuple[int, int]) -> Image.Image:
    logo = ImageOps.contain(load_logo(path), size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size)
    canvas.alpha_composite(logo, ((size[0] - logo.width) // 2, (size[1] - logo.height) // 2))
    return canvas


def team_logo_rows(sources: list[dict], teams: dict[int, int]) -> list[tuple[int, dict]]:
    result = []
    for team_id in sorted(teams):
        prefix = f"{team_id:03}"
        for asset, texture, size in ((f"p{prefix}.iff", f"2d{prefix}_0", (256, 256)),
                                     ("franchise.iff", f"{prefix}_mlogo", (64, 64))):
            matches = [row for row in sources if row["asset"] == asset and row["texture"] == texture]
            if (len(matches) != 1 or not matches[0]["editable"]
                    or (matches[0]["width"], matches[0]["height"]) != size):
                raise ValueError(f"Missing or invalid native team logo master: {asset}/{texture}")
            result.append((team_id, matches[0]))
    return result


def studio_atlas(plan: dict[int, int], logo_dir: Path) -> Image.Image:
    if not set(range(30)) <= plan.keys():
        raise ValueError("Studio collage requires flipchip indices 000 through 029")
    atlas = Image.new("RGBA", (256, 256))
    cache = {}
    for index in range(30):
        x, y = index % 6, index // 6
        left, right = x * 256 // 6, (x + 1) * 256 // 6
        top, bottom = y * 256 // 5, (y + 1) * 256 // 5
        size = (right - left, bottom - top)
        key = (plan[index], size)
        if key not in cache:
            cache[key] = cropped_logo(logo_dir / f"{LOGO_ID0 + plan[index]}.png", size)
        atlas.paste(cache[key], (left, top))
    return atlas


def title_sheet(teams: list[int], logo_dir: Path) -> Image.Image:
    if not 1 <= len(teams) <= 18 or len(set(teams)) != len(teams):
        raise ValueError("Title logo sheet requires between 1 and 18 distinct teams")
    sheet = Image.new("RGBA", (512, 512))
    draw = ImageDraw.Draw(sheet)
    for y in range(512):
        shade = round(255 - 27 * max(0, abs(y - 255.5) - 48) / 207.5)
        draw.line((0, y, 511, y), fill=(shade, shade, min(255, shade + 1), 255))
    for index, team in enumerate(teams):
        x, y = 30 + index % 6 * 78, 132 + index // 6 * 89
        logo = ImageOps.contain(load_logo(logo_dir / f"{LOGO_ID0 + team}.png"),
                                (72, 80), method=Image.Resampling.LANCZOS)
        left, top = x + (72 - logo.width) // 2, y + (80 - logo.height) // 2
        shadow = Image.new("L", sheet.size)
        shadow.paste(logo.getchannel("A"), (left + 2, top + 3))
        shadow = shadow.filter(ImageFilter.GaussianBlur(2)).point(lambda alpha: alpha * 100 // 255)
        sheet.paste((0, 0, 0, 255), (0, 0, 512, 512), shadow)
        sheet.alpha_composite(logo, (left, top))
    return sheet


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
    atlas_rows = [row for row in manifest["sources"] if row["id"] == STUDIO_ATLAS_ID]
    if (len(atlas_rows) != 1 or atlas_rows[0]["asset"] != "scstudio.iff"
            or atlas_rows[0]["texture"] != "m_metalnoise" or not atlas_rows[0]["editable"]
            or (atlas_rows[0]["width"], atlas_rows[0]["height"]) != (256, 256)):
        raise ValueError("Missing or invalid native studio logo collage master")
    sheet_rows = [row for row in manifest["sources"] if row["id"] == TITLE_SHEET_ID]
    if (len(sheet_rows) != 1 or sheet_rows[0]["asset"] != "titlepage.iff"
            or sheet_rows[0]["texture"] != "logosheet" or not sheet_rows[0]["editable"]
            or (sheet_rows[0]["width"], sheet_rows[0]["height"]) != (512, 512)):
        raise ValueError("Missing or invalid native title logo sheet master")
    slots = proa_slots()
    teams = sorted(slots.values())
    if teams != list(range(len(teams))):
        raise ValueError("ProA team mapping must contain each logo index exactly once")
    fixed = {team_id: slots[slot] for team_id, slot in native.team_ids().items() if slot in slots}
    if set(fixed.values()) != set(teams):
        raise ValueError("ProA slots do not all have distinct native team IDs")
    plan = assignments([index for index, _ in rows], fixed, teams)
    team_rows = team_logo_rows(manifest["sources"], fixed)
    files = native.scan(workspace, [row for _, row in rows] + atlas_rows + sheet_rows
                        + [row for _, row in team_rows])
    pending = []
    cache = {}
    for index, row in sorted(rows, key=lambda item: item[0]):
        path = files[row["id"]]
        size = (row["width"], row["height"])
        key = (plan[index], size)
        if key not in cache:
            cache[key] = cropped_logo(logo_dir / f"{LOGO_ID0 + plan[index]}.png", size)
        pending.append((path, workspace_images.image_bytes(path, cache[key])))
    atlas_path = files[STUDIO_ATLAS_ID]
    pending.append((atlas_path, workspace_images.image_bytes(atlas_path, studio_atlas(plan, logo_dir))))
    sheet_path = files[TITLE_SHEET_ID]
    pending.append((sheet_path, workspace_images.image_bytes(sheet_path, title_sheet(teams, logo_dir))))
    for team_id, row in team_rows:
        path = files[row["id"]]
        image = full_logo(logo_dir / f"{LOGO_ID0 + fixed[team_id]}.png", (row["width"], row["height"]))
        pending.append((path, workspace_images.image_bytes(path, image)))
    if not dry_run:
        for path, data in pending:
            path.write_bytes(data)
    for index, team in plan.items():
        print(f"{index:03}: {LOGO_ID0 + team}.png{' (team slot)' if index in fixed else ''}")
    print(f"{'Would replace' if dry_run else 'Replaced'} {len(rows)} flipchip masters, "
          f"1 studio collage, 1 title logo sheet and {len(team_rows)} team logo masters")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=native.DEFAULT_WS)
    parser.add_argument("--dry-run", action="store_true", help="validate and show assignments without writing")
    args = parser.parse_args()
    propagate(args.workspace, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
