"""Compose the default roster and existing visual/year/skin patches into one new ISO.

    python scripts\\season_iso.py check --iso-source PRISTINE --iso-out NEW
    python scripts\\season_iso.py build --iso-source PRISTINE --iso-out NEW --roster PAYLOAD

The pristine source is read-only. Check runs without generated roster/skin files;
supplying them also verifies their final content before publication.
"""
import argparse
import archive_iso
from pathlib import Path
from typing import BinaryIO

import lettering_workspace
import roster_iso
import court_colours
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
            repack_archive: bool = False) -> tuple[list[tuple[int, bytes, bytes]], dict]:
    patches, roster_report = roster_iso.prepare(stream, roster)
    if texture_workspace is None:
        visual_patches, visual_report = lettering_workspace.prepare(stream, workspace, slots, None, skin_plan)
        logo_report = None
    else:
        texture_iso_workspace.validate_workspace(workspace)
        visual_patches, visual_report = lettering_workspace.prepare(
            stream, workspace, slots, None, skin_plan, include_courts=False)
        logo_patches, logo_report = texture_iso_workspace.prepare(
            stream, texture_workspace, court_colours.decoded_edits(stream, workspace),
            repack_archive=repack_archive)
        visual_patches.extend(logo_patches)
        visual_report["courts"] = logo_report["courts"]
    patches.extend(visual_patches)
    if stats_year is not None or roster_report.get("elf_crc_delta"):
        year_patches, visual_report["stats_year"] = prepare_year_patch(
            stream, stats_year if stats_year is not None else 2004, roster_report.get("elf_crc_delta", 0))
        patches.extend(year_patches)
    report = {
        "schema": 1, "source_sha256": SOURCE_SHA256, "iso_size": ISO_SIZE,
        "roster": roster_report, "visuals": visual_report, "logos": logo_report,
        "scope": ("Default roster and native logo masters embedded; portraits and legacy skin PNGs remain external"
                  if logo_report is not None else "Default roster embedded; logo migration not selected"),
        "restore": "Boot the untouched pristine ISO; rebuild from it rather than patching a previous output",
    }
    if repack_archive:
        report["archive"] = archive_iso.plan(stream, patches)[2]
    else:
        validate_patches(patches, ISO_SIZE)
    return patches, report


def check(source: Path, output: Path, workspace: Path = lettering_workspace.DEFAULT_WS,
          slots: Path = lettering_workspace.DEFAULT_SLOTS, stats_year: int | None = None,
          roster: Path | None = None, skin_plan: Path | None = None,
          texture_workspace: Path | None = None, *, repack_archive: bool = False) -> dict:
    validate_output(source, output, workspace)
    with source.open("rb") as stream:
        return prepare(stream, workspace, slots, stats_year, roster, skin_plan, texture_workspace,
                       repack_archive=repack_archive)[1]


def build(source: Path, output: Path, roster: Path, workspace: Path = lettering_workspace.DEFAULT_WS,
          slots: Path = lettering_workspace.DEFAULT_SLOTS, stats_year: int | None = None,
          skin_plan: Path | None = None, texture_workspace: Path | None = None, *,
          repack_archive: bool = False) -> dict:
    output = validate_output(source, output, workspace)
    with source.open("rb") as stream:
        patches, report = prepare(stream, workspace, slots, stats_year, roster, skin_plan, texture_workspace,
                                  repack_archive=repack_archive)
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
    parser.add_argument("--repack-archive", action="store_true",
                        help="Experimental: pool package sectors within the existing disc extents")
    args = parser.parse_args()
    if args.workspace is None:
        args.workspace = args.texture_workspace / "team_palettes"
    if args.command == "build" and args.roster is None:
        parser.error("build requires --roster (the final build_roster.py payload)")
    try:
        if args.command == "build":
            report = build(args.iso_source, args.iso_out, args.roster, args.workspace,
                           args.slots, args.stats_year, args.skin_plan, args.texture_workspace,
                           repack_archive=args.repack_archive)
        else:
            report = check(args.iso_source, args.iso_out, args.workspace, args.slots,
                           args.stats_year, args.roster, args.skin_plan, args.texture_workspace,
                           repack_archive=args.repack_archive)
        print(f"Verified default roster and {report['visuals']['sources']} lettering sources; "
              f"roster {'embedded' if args.roster is not None else 'source checked'}.")
    except (OSError, ValueError, MemoryError) as error:
        parser.exit(1, f"Season ISO failed: {error}\n")


if __name__ == "__main__":
    main()
