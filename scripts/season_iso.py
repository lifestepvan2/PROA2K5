"""Compose the default roster and existing visual/year/skin patches into one new ISO.

    python scripts\\season_iso.py check --iso-source PRISTINE --iso-out NEW
    python scripts\\season_iso.py build --iso-source PRISTINE --iso-out NEW --roster PAYLOAD

The pristine source is read-only. Check runs without generated roster/skin files;
supplying them also verifies their final content before publication.
"""
import argparse
import archive_iso
import hashlib
import time
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageDraw
import lettering_workspace
import roster_iso
import court_colours
import created_hair_lod
import texture_iso_workspace
from iso_copy import publish_iso_copy, validate_patches
from patch_lettering_iso import ISO_SIZE
from patch_preview_lettering_iso import SOURCE_SHA256
from roster_stats import prepare_year_patch

MANIFEST_SUFFIX = ".season.json"


def validate_output(source: Path, output: Path, workspace: Path) -> Path:
    output = lettering_workspace.validate_output(source, output, workspace)
    if output.with_name(output.name + MANIFEST_SUFFIX).exists():
        raise ValueError("Output season manifest already exists; choose a new output path")
    return output


def prepare(stream: BinaryIO, workspace: Path, slots: Path, stats_year: int | None = None,
            roster: Path | None = None, skin_plan: Path | None = None,
            texture_workspace: Path | None = None, *,
            repack_archive: bool = False, basic_meshes: bool = False) -> tuple[list[tuple[int, bytes, bytes]], dict]:
    patches, roster_report = roster_iso.prepare(stream, roster)
    if texture_workspace is None:
        visual_patches, visual_report = lettering_workspace.prepare(
            stream, workspace, slots, None, skin_plan, repack_archive=repack_archive)
        logo_report = None
    else:
        texture_iso_workspace.validate_workspace(workspace)
        from uniform_iso_workspace import MANIFEST as UNIFORM_MANIFEST
        from remaining_texture_workspace import MANIFEST as TEXTURE_MANIFEST
        uniform_edits = ([] if any((texture_workspace / filename).is_file()
                                  for filename in (UNIFORM_MANIFEST, TEXTURE_MANIFEST)) else None)
        options = {"texture_edits": uniform_edits} if uniform_edits is not None else {}
        skin_options = {"compose_skin": True} if (texture_workspace / TEXTURE_MANIFEST).is_file() else {}
        visual_patches, visual_report = lettering_workspace.prepare(
            stream, workspace, slots, None, skin_plan, include_courts=False, repack_archive=repack_archive,
            **({"texture_edits": uniform_edits} if uniform_edits is not None else {}), **skin_options)
        logo_patches, logo_report = texture_iso_workspace.prepare(
            stream, texture_workspace, court_colours.decoded_edits(stream, workspace),
            repack_archive=repack_archive, slots=slots, **options)
        visual_patches.extend(logo_patches)
        visual_report["courts"] = logo_report["courts"]
    patches.extend(visual_patches)
    if basic_meshes:
        hair_patches, hair_delta = created_hair_lod.prepare_basic(stream)
        hair_report = {"mode": "basic", "elf_crc_delta": hair_delta}
    else:
        hair_patches, hair_delta, hair_report = created_hair_lod.prepare_custom(stream)
        if not repack_archive and any(len(before) != len(after) for _, before, after in hair_patches):
            raise ValueError("Per-style hair meshes require archive repacking; use repack_archive=True "
                             "or --basic-meshes for the stock fallback")
    patches.extend(hair_patches)
    elf_delta = roster_report.get("elf_crc_delta", 0) ^ hair_delta
    if stats_year is not None or elf_delta:
        year_patches, visual_report["stats_year"] = prepare_year_patch(
            stream, stats_year if stats_year is not None else 2004, elf_delta)
        patches.extend(year_patches)
    report = {
        "schema": 1, "source_sha256": SOURCE_SHA256, "iso_size": ISO_SIZE,
        "roster": roster_report, "visuals": visual_report, "logos": logo_report,
        "scope": "Default roster and native texture workspace embedded",
        "created_hair_lod": hair_report,
        "restore": "Boot the untouched pristine ISO; rebuild from it rather than patching a previous output",
    }
    if repack_archive:
        report["archive"] = archive_iso.plan(stream, patches)[2]
    else:
        validate_patches(patches, ISO_SIZE)
    return patches, report


TITLE_ID = "bb453139"
GLYPHS = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "a": ("000", "110", "001", "111", "111"), "b": ("100", "100", "110", "101", "110"),
    "c": ("000", "011", "100", "100", "011"), "d": ("001", "001", "011", "101", "011"),
    "e": ("000", "110", "111", "100", "011"), "f": ("011", "010", "111", "010", "010"),
    "i": ("010", "000", "010", "010", "010"), "l": ("110", "010", "010", "010", "111"),
    "u": ("000", "101", "101", "101", "111"), "x": ("000", "101", "010", "101", "000"),
    " ": ("000", "000", "000", "000", "000"),
}


def build_id(timestamp_ns: int) -> str:
    """Hash the ISO creation time, not the roster or texture payload."""
    return hashlib.sha256(str(timestamp_ns).encode("ascii")).hexdigest()[:16]


def stamp_title(image: Image.Image, identity: str) -> Image.Image:
    if len(identity) != 16 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("Build ID must be 16 lowercase hexadecimal digits")
    image = image.convert("RGBA")
    label = "build 0x" + identity
    if image.width < len(label) * 4 + 8 or image.height < 13:
        raise ValueError("Title texture is too small for the build ID")
    draw = ImageDraw.Draw(image)
    for index, character in enumerate(label):
        for y, row in enumerate(GLYPHS[character]):
            for x, pixel in enumerate(row):
                if pixel == "1":
                    draw.point((4 + index * 4 + x, image.height - 9 + y), fill=(144, 144, 144, 255))
    return image


def add_title_stamp(stream: BinaryIO, workspace: Path, patches: list[tuple[int, bytes, bytes]],
                    identity: str, report: dict) -> None:
    from remaining_texture_workspace import load_manifest
    from native_texture import display, encode
    from texture_catalogue import texture_images

    rows = [row for row in load_manifest(workspace)["sources"] if row["id"] == TITLE_ID]
    if len(rows) != 1:
        raise ValueError("Workspace must contain exactly one native title texture")
    row = rows[0]
    path = texture_iso_workspace.scan(workspace, rows)[TITLE_ID]
    body, original = texture_iso_workspace.source_bytes(stream, row)
    offset = row["iso_offset"] + row["chunk_offset"] + 32
    matching = [index for index, (pos, _, _) in enumerate(patches) if pos == offset]
    if len(matching) > 1 or row["compressed"]:
        raise ValueError("Unsupported title resource composition")
    current = patches[matching[0]][2] if matching else original
    if matching and patches[matching[0]][1] != body:
        raise ValueError("Title patch does not match pristine source")
    images, _, _, _ = texture_images(current, row["system"], row["video"], row["descriptor"],
                                      row["descriptor_offsets"])
    stamped = stamp_title(display(images[0]), identity)
    target, detail, _ = encode(current, row["system"], row["video"], row["descriptor"],
                               row["descriptor_offsets"], stamped)
    if len(target) != len(body):
        raise ValueError("Title resource changed size")
    replacement = (offset, body, target)
    if matching:
        patches[matching[0]] = replacement
    else:
        patches.append(replacement)
    logos = report.get("logos")
    if logos is not None:
        resources = [item for item in logos["resources"] if item["offset"] == offset]
        if len(resources) > 1:
            raise ValueError("Duplicate title resource report")
        if resources:
            resources[0]["decoded_sha256"] = hashlib.sha256(target).hexdigest()
        else:
            logos["resources"].append({
                "asset": row["asset"], "offset": offset, "stored": len(body), "scratch": row["scratch"],
                "new_stored": len(target), "new_scratch": row["scratch"], "runtime_allocation_delta": 0,
                "distance_bits": None, "decoded_sha256": hashlib.sha256(target).hexdigest(),
            })
        textures = [item for item in logos["textures"] if item["id"] == TITLE_ID]
        if len(textures) > 1:
            raise ValueError("Duplicate title texture report")
        if textures:
            textures[0].update(detail)
        else:
            logos["textures"].append({
                "id": TITLE_ID, "asset": row["asset"], "texture": row["texture"], "resource_offset": offset,
                "group": row["group"], "slot": row["slot"], "path": str(path), **detail,
            })
    report["build_id"] = {
        "value": identity, "title_id": TITLE_ID, "title_encoding": detail,
    }


def build_named(source: Path, output_dir: Path, roster: Path, workspace: Path,
                slots: Path = lettering_workspace.DEFAULT_SLOTS, stats_year: int | None = None,
                skin_plan: Path | None = None, texture_workspace: Path = texture_iso_workspace.DEFAULT_WS,
                *, basic_meshes: bool = False) -> dict:
    with source.open("rb") as stream:
        patches, report = prepare(stream, workspace, slots, stats_year, roster, skin_plan, texture_workspace,
                                  repack_archive=True, basic_meshes=basic_meshes)
        timestamp_ns = time.time_ns()
        identity = build_id(timestamp_ns)
        output = validate_output(source, output_dir / f"proa2k5_{identity}.iso", workspace)
        add_title_stamp(stream, texture_workspace, patches, identity, report)
        report["build_id"].update({
            "algorithm": "first 64 bits of SHA-256",
            "input": "ASCII decimal Unix timestamp in nanoseconds",
            "timestamp_ns": str(timestamp_ns),
        })
        copy_plan, patches, report["archive"] = archive_iso.plan(stream, patches)
        report["source"] = str(source.resolve())
        report["output"] = str(output.resolve())
        return publish_iso_copy(stream, output, patches, SOURCE_SHA256, ISO_SIZE, report,
                                output.with_name(output.name + MANIFEST_SUFFIX), copy_plan=copy_plan)


def check(source: Path, output: Path, workspace: Path = lettering_workspace.DEFAULT_WS,
          slots: Path = lettering_workspace.DEFAULT_SLOTS, stats_year: int | None = None,
          roster: Path | None = None, skin_plan: Path | None = None,
          texture_workspace: Path | None = None, *, repack_archive: bool = True,
          basic_meshes: bool = False) -> dict:
    validate_output(source, output, workspace)
    with source.open("rb") as stream:
        return prepare(stream, workspace, slots, stats_year, roster, skin_plan, texture_workspace,
                       repack_archive=repack_archive, basic_meshes=basic_meshes)[1]


def build(source: Path, output: Path, roster: Path, workspace: Path = lettering_workspace.DEFAULT_WS,
          slots: Path = lettering_workspace.DEFAULT_SLOTS, stats_year: int | None = None,
          skin_plan: Path | None = None, texture_workspace: Path | None = None, *,
          repack_archive: bool = True, basic_meshes: bool = False) -> dict:
    output = validate_output(source, output, workspace)
    with source.open("rb") as stream:
        patches, report = prepare(stream, workspace, slots, stats_year, roster, skin_plan, texture_workspace,
                                  repack_archive=repack_archive, basic_meshes=basic_meshes)
        copy_plan = None
        if repack_archive:
            copy_plan, patches, report["archive"] = archive_iso.plan(stream, patches)
        report["source"] = str(source.resolve())
        return publish_iso_copy(stream, output, patches, SOURCE_SHA256, ISO_SIZE, report,
                                output.with_name(output.name + MANIFEST_SUFFIX), copy_plan=copy_plan)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "build"))
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--iso-out", type=Path, required=True)
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--skin-plan", type=Path)
    parser.add_argument("--stats-year", type=int)
    parser.add_argument("--workspace", type=Path, help="team palettes (default: TEXTURE_WORKSPACE/team_palettes)")
    parser.add_argument("--slots", type=Path, default=lettering_workspace.DEFAULT_SLOTS)
    parser.add_argument("--texture-workspace", type=Path, default=texture_iso_workspace.DEFAULT_WS)
    parser.add_argument("--repack-archive", action="store_true", default=True,
                        help="pool package sectors within the existing disc extents (enabled by default)")
    parser.add_argument("--basic-meshes", action="store_true",
                        help="use the three stock low-detail hair meshes instead of the approved per-style set")
    args = parser.parse_args()
    if args.workspace is None:
        args.workspace = args.texture_workspace / "team_palettes"
    if args.command == "build" and args.roster is None:
        parser.error("build requires --roster (the final build_roster.py payload)")
    try:
        if args.command == "build":
            report = build(args.iso_source, args.iso_out, args.roster, args.workspace,
                           args.slots, args.stats_year, args.skin_plan, args.texture_workspace,
                           repack_archive=args.repack_archive, basic_meshes=args.basic_meshes)
        else:
            report = check(args.iso_source, args.iso_out, args.workspace, args.slots,
                           args.stats_year, args.roster, args.skin_plan, args.texture_workspace,
                           repack_archive=args.repack_archive, basic_meshes=args.basic_meshes)
        print(f"Verified default roster and {report['visuals']['sources']} lettering sources; "
              f"roster {'embedded' if args.roster is not None else 'source checked'}.")
    except (OSError, ValueError, MemoryError) as error:
        parser.exit(1, f"Season ISO failed: {error}\n")


if __name__ == "__main__":
    main()
