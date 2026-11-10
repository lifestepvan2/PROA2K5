"""Editable team palettes and combined lettering/court ISO patches for all 30 NBA slots.

    python scripts\\lettering_workspace.py export --iso-source PRISTINE.iso
    python scripts\\lettering_workspace.py check --iso-source PRISTINE.iso --iso-out NEW.iso
    python scripts\\lettering_workspace.py build --iso-source PRISTINE.iso --iso-out NEW.iso
    python scripts\\lettering_workspace.py reset --iso-source PRISTINE.iso --slot 20

Edit <slot>/colours.json for team, court and uniform colours, or use the legacy 16x16 RGB PNG
palettes in palette mode. Number edits target both game and preview
sources; names are independent. Source alpha, indices, descriptors and archive sizes
are immutable for lettering. Court edits normalize authored paint gradients.
Existing edits survive export. Originals/previews stay out of Git.
"""
import argparse
import csv
import json
import os
from pathlib import Path
from typing import BinaryIO

import numpy as np
from PIL import Image

from inventory_lettering_iso import inventory
from iso_copy import publish_iso_copy
from roster_stats import prepare_year_patch
from lettering_colours import default_settings, recolour
from patch_lettering_iso import ISO_SIZE, digest
from patch_preview_lettering_iso import SOURCE_SHA256
from txtr_match import SWZ
from vc_lz import decode, rebuild_tail
import team_palettes
import court_colours

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WS = team_palettes.DEFAULT_WS
DEFAULT_SLOTS = ROOT / "data" / "team_slots.csv"


def assignments(path: Path) -> dict[str, str | None]:
    result: dict[str, str | None] = {str(slot): None for slot in range(30)}
    sheets = set()
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if not {"sheet", "nba_slot"} <= set(reader.fieldnames or ()):
            raise ValueError("Team slot CSV requires sheet and nba_slot columns")
        for row in reader:
            slot, sheet = int(row["nba_slot"]), row["sheet"].strip()
            if slot not in range(30) or not sheet or result[str(slot)] is not None or sheet in sheets:
                raise ValueError("Team assignments require unique sheets and NBA slots in 0-29")
            result[str(slot)] = sheet
            sheets.add(sheet)
    return result


def workspace_path(workspace: Path, relative: Path) -> Path:
    path = workspace / relative
    if not path.resolve().is_relative_to(workspace.resolve()):
        raise ValueError(f"Workspace path escapes its directory: {path}")
    return path


def palette_relative(row: dict) -> Path:
    return Path(f"{row['nba_slot']:03}") / row["variant"] / f"{row['target']}.palette.png"


def read_palette(path: Path) -> bytes:
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size != (16, 16):
            raise ValueError(f"{path}: expected a 16x16 RGB PNG, without alpha or indexed mode")
        return image.tobytes()


def swatch(palette: bytes) -> bytes:
    if len(palette) != 1024:
        raise ValueError("Expected 256 physical RGBA palette entries")
    return np.frombuffer(palette, dtype=np.uint8).reshape(256, 4)[SWZ, :3].tobytes()


def import_rgb(original: bytes, rgb: bytes) -> bytes:
    if len(original) != 1024 or len(rgb) != 768:
        raise ValueError("Invalid physical palette or logical RGB swatch size")
    rgba = np.frombuffer(original, dtype=np.uint8).reshape(256, 4).copy()
    rgba[SWZ, :3] = np.frombuffer(rgb, dtype=np.uint8).reshape(256, 3)
    return rgba.tobytes()


def read_source(stream: BinaryIO, row: dict) -> tuple[bytes, bytes]:
    stream.seek(row["body_offset"])
    body = stream.read(row["stored_body_size"])
    if digest(body) != row["stored_body_sha256"]:
        raise ValueError(f"{row['asset']}: source chunk fingerprint changed")
    decoded = decode(body, row["decoded_size"])[0] if row["compressed"] else body
    if (len(decoded) != row["decoded_size"]
            or digest(decoded[:-1024]) != row["descriptor_indices_mips_sha256"]
            or digest(decoded[-1024:]) != row["palette_sha256"]):
        raise ValueError(f"{row['asset']}: decoded indices or palette fingerprint changed")
    return body, decoded


def expected_manifest(stream: BinaryIO, slots: Path) -> tuple[dict, dict[Path, bytes]]:
    rows = inventory(stream)
    sources = []
    originals = {}
    for row in rows:
        _, decoded = read_source(stream, row)
        palette = decoded[-1024:]
        sources.append({**row, "original_palette_hex": palette.hex()})
        relative = palette_relative(row)
        rgb = swatch(palette)
        if relative in originals and originals[relative] != rgb:
            raise ValueError(f"{row['asset']}: paired number swatches differ")
        originals[relative] = rgb
    manifest = {
        "schema": 1, "source_iso_sha256": SOURCE_SHA256, "nba_slots": 30,
        "assignments": assignments(slots), "sources": sources,
    }
    return manifest, originals


def validate_manifest(workspace: Path, expected: dict) -> None:
    path = workspace_path(workspace, Path("manifest.json"))
    actual = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(actual, dict) or actual != expected:
        raise ValueError("Workspace manifest/source or team-slot mapping differs; use a new workspace and migrate edits explicitly")


def save_swatch(path: Path, rgb: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGB", (16, 16), rgb).save(path)


def save_preview(workspace: Path, row: dict, decoded: bytes, palette: bytes) -> None:
    width, height = row["width"], row["height"]
    indices = np.frombuffer(decoded, dtype=np.uint8, count=width * height, offset=0x70)
    colors = np.frombuffer(palette, dtype=np.uint8).reshape(256, 4)[SWZ]
    rgba = colors[indices].reshape(height, width, 4).copy()
    rgba[:, :, 3] = np.minimum(rgba[:, :, 3].astype(np.uint16) * 2, 255).astype(np.uint8)
    relative = palette_relative(row).with_name(f"{row['target']}.preview.png")
    path = workspace_path(workspace, relative)
    Image.fromarray(rgba).resize((width * 2, height * 2), Image.Resampling.NEAREST).save(path)


def colour_relative(row: dict) -> Path:
    return team_palettes.relative(row["nba_slot"])


def colour_defaults(stream: BinaryIO, sources: list[dict]) -> dict[Path, dict]:
    result = {}
    for row in sources:
        if row["surface"] == "game":
            _, decoded = read_source(stream, row)
            config = result.setdefault(colour_relative(row), {})
            variant = config.setdefault(row["variant"], {})
            variant[row["target"]] = default_settings(decoded, row["width"], row["height"])
    return {path: team_palettes.defaults(int(path.parts[0]), variants)
            for path, variants in result.items()}


def save_controls(path: Path, config: dict, exclusive: bool = False) -> None:
    with path.open("x" if exclusive else "w", encoding="utf-8") as file:
        file.write(json.dumps(config, indent=2) + "\n")
        file.flush()
        os.fsync(file.fileno())


def load_controls(workspace: Path, defaults: dict[Path, dict], create: bool = False) -> dict[Path, dict]:
    result = {}
    for relative, config in defaults.items():
        path = workspace_path(workspace, relative)
        if path.exists():
            try:
                config = team_palettes.validate(json.loads(path.read_text(encoding="utf-8")))
                if set(config["uniforms"]) != set(defaults[relative]["uniforms"]):
                    raise ValueError("Uniform variants differ from the source inventory")
            except ValueError as error:
                raise ValueError(f"{path}: {error}") from error
        elif create:
            save_controls(path, config, exclusive=True)
        else:
            raise ValueError(f"{path}: missing team colour document; run export")
        result[relative] = config
    return result


def effective_palette(row: dict, decoded: bytes, rgb: bytes, controls: dict[Path, dict]) -> tuple[bytes, dict | None]:
    settings = controls[colour_relative(row)]["uniforms"][row["variant"]][row["target"]]
    if settings["mode"] == "palette":
        return import_rgb(decoded[-1024:], rgb), None
    palette, diagnostics = recolour(decoded, row["width"], row["height"], settings)
    return palette, {"nba_slot": row["nba_slot"], "variant": row["variant"],
                     "target": row["target"], "settings": settings, **diagnostics}


def export(source: Path, workspace: Path = DEFAULT_WS, slots: Path = DEFAULT_SLOTS) -> dict:
    with source.open("rb") as stream:
        manifest, originals = expected_manifest(stream, slots)
        manifest_path = workspace_path(workspace, Path("manifest.json"))
        if manifest_path.exists():
            validate_manifest(workspace, manifest)
        for relative, rgb in originals.items():
            path = workspace_path(workspace, relative)
            backup = workspace_path(workspace, Path("_originals") / relative)
            if backup.exists():
                if read_palette(backup) != rgb:
                    raise ValueError(f"{backup}: original swatch backup changed")
            else:
                save_swatch(backup, rgb)
            if not path.exists():
                save_swatch(path, rgb)
            read_palette(path)
        controls = load_controls(workspace, colour_defaults(stream, manifest["sources"]), create=True)
        for row in manifest["sources"]:
            if row["surface"] == "game":
                _, decoded = read_source(stream, row)
                rgb = read_palette(workspace_path(workspace, palette_relative(row)))
                palette, _ = effective_palette(row, decoded, rgb, controls)
                save_preview(workspace, row, decoded, palette)
        if not manifest_path.exists():
            with manifest_path.open("x", encoding="utf-8") as file:
                file.write(json.dumps(manifest, indent=2) + "\n")
                file.flush()
                os.fsync(file.fileno())
    return manifest


def validate_output(source: Path, output: Path, workspace: Path) -> Path:
    output = output.resolve()
    if source.resolve() == output or output.exists():
        raise ValueError("Output must be a new path, different from the pristine source (mounted outputs are refused)")
    if output.is_relative_to(workspace.resolve()):
        raise ValueError("Keep output ISOs outside the lettering workspace")
    if not output.parent.is_dir():
        raise ValueError("Output parent directory does not exist")
    if output.with_name(output.name + ".lettering.json").exists():
        raise ValueError("Output patch manifest already exists")
    return output


def prepare(stream: BinaryIO, workspace: Path, slots: Path, stats_year: int | None = None,
            skin_plan: Path | None = None, *, include_courts: bool = True,
            repack_archive: bool = False) -> tuple[list[tuple[int, bytes, bytes]], dict]:
    expected, originals = expected_manifest(stream, slots)
    validate_manifest(workspace, expected)
    edited = {}
    for relative, original in originals.items():
        backup = workspace_path(workspace, Path("_originals") / relative)
        if read_palette(backup) != original:
            raise ValueError(f"{backup}: original swatch backup changed")
        edited[relative] = read_palette(workspace_path(workspace, relative))
    controls = load_controls(workspace, colour_defaults(stream, expected["sources"]))
    patches = []
    changes = []
    colour_reports = []
    for row in expected["sources"]:
        body, decoded = read_source(stream, row)
        palette, colour_report = effective_palette(row, decoded, edited[palette_relative(row)], controls)
        if colour_report is not None and row["surface"] == "game":
            colour_reports.append(colour_report)
        if palette == decoded[-1024:]:
            continue
        if row["compressed"]:
            try:
                replacement = rebuild_tail(body, row["decoded_size"], palette, row["scratch_bytes"])
            except ValueError as error:
                raise ValueError(f"Slot {row['nba_slot']} {row['variant']} {row['asset']}: {error}") from error
            changed = decode(replacement, row["decoded_size"])[0]
            offset, before, after = row["body_offset"], body, replacement
        else:
            changed = decoded[:-1024] + palette
            offset = row["body_offset"] + row["palette_offset_in_decoded_body"]
            before, after = decoded[-1024:], palette
        if (changed[:-1024] != decoded[:-1024] or changed[-1021::4] != decoded[-1021::4]
                or len(changed) != len(decoded)):
            raise ValueError(f"{row['asset']}: immutable lettering data changed")
        patches.append((offset, before, after))
        changes.append({
            "nba_slot": row["nba_slot"], "variant": row["variant"],
            "surface": row["surface"], "target": row["target"], "asset": row["asset"],
            "offset": offset, "size": len(before), "original_hex": before.hex(),
            "original_sha256": digest(before), "patched_sha256": digest(after),
            "palette_sha256": digest(palette),
            "descriptor_indices_mips_sha256": row["descriptor_indices_mips_sha256"],
            "palette_alpha_sha256": row["palette_alpha_sha256"],
        })
    report = {
        "schema": 1, "source_sha256": SOURCE_SHA256, "iso_size": ISO_SIZE,
        "workspace": str(workspace.resolve()), "assignments": expected["assignments"],
        "nba_slots": 30, "uniforms": len(originals) // 2, "sources": len(expected["sources"]),
        "colour_controls": colour_reports,
        "changes": changes, "restore": "Boot the untouched pristine source ISO, or rebuild from it.",
    }
    court_patches, court_reports = court_colours.prepare(stream, workspace) if include_courts else ([], [])
    patches.extend(court_patches)
    report["courts"] = court_reports
    if stats_year is not None:
        year_patches, report["stats_year"] = prepare_year_patch(stream, stats_year)
        patches.extend(year_patches)
    if skin_plan is not None:
        from skin_tones import load_patches
        skin_patches, report["skin_tones"] = load_patches(stream, skin_plan, repack_archive=repack_archive)
        patches.extend(skin_patches)
    return patches, report


def check(source: Path, workspace: Path = DEFAULT_WS, slots: Path = DEFAULT_SLOTS,
          output: Path | None = None, stats_year: int | None = None, skin_plan: Path | None = None) -> dict:
    if output is not None:
        validate_output(source, output, workspace)
    with source.open("rb") as stream:
        return prepare(stream, workspace, slots, stats_year, skin_plan)[1]


def build(source: Path, output: Path, workspace: Path = DEFAULT_WS, slots: Path = DEFAULT_SLOTS,
          stats_year: int | None = None, skin_plan: Path | None = None) -> dict:
    output = validate_output(source, output, workspace)
    with source.open("rb") as stream:
        patches, report = prepare(stream, workspace, slots, stats_year, skin_plan)
        report["source"] = str(source.resolve())
        return publish_iso_copy(stream, output, patches, SOURCE_SHA256, ISO_SIZE, report,
                                output.with_name(output.name + ".lettering.json"))


def reset(source: Path, workspace: Path, slots: Path, selected_slots: list[int]) -> None:
    if not selected_slots or any(slot not in range(30) for slot in selected_slots):
        raise ValueError("Reset requires explicitly selected NBA slots in 0-29")
    with source.open("rb") as stream:
        expected, originals = expected_manifest(stream, slots)
        validate_manifest(workspace, expected)
        for relative, rgb in originals.items():
            if int(relative.parts[0]) in selected_slots:
                save_swatch(workspace_path(workspace, relative), rgb)
        for relative, config in colour_defaults(stream, expected["sources"]).items():
            if int(relative.parts[0]) in selected_slots:
                current = team_palettes.load(workspace, int(relative.parts[0]))
                current["uniforms"] = config["uniforms"]
                save_controls(workspace_path(workspace, relative), current)
        for row in expected["sources"]:
            if row["surface"] == "game" and row["nba_slot"] in selected_slots:
                _, decoded = read_source(stream, row)
                save_preview(workspace, row, decoded, decoded[-1024:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("export", "check", "build", "reset"))
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--iso-out", type=Path)
    parser.add_argument("--stats-year", type=int, help="player-card season label anchor (check/build only)")
    parser.add_argument("--skin-plan", type=Path, help="prepared face-match complexion recipe (check/build only)")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WS)
    parser.add_argument("--slots", type=Path, default=DEFAULT_SLOTS)
    parser.add_argument("--slot", type=int, choices=range(30), nargs="+")
    args = parser.parse_args()
    if args.command == "build" and args.iso_out is None:
        parser.error("build requires --iso-out")
    if args.command == "reset" and not args.slot:
        parser.error("reset requires --slot (explicitly selected slots)")
    if args.command != "reset" and args.slot:
        parser.error("--slot is only supported by reset")
    if args.command in ("export", "reset") and args.iso_out is not None:
        parser.error("--iso-out is only supported by check/build")
    if args.command in ("export", "reset") and args.stats_year is not None:
        parser.error("--stats-year is only supported by check/build")
    if args.command in ("export", "reset") and args.skin_plan is not None:
        parser.error("--skin-plan is only supported by check/build")
    try:
        if args.command == "export":
            report = export(args.iso_source, args.workspace, args.slots)
            print(f"Exported 30 slots, {len(report['sources']) // 3} uniforms; existing palettes preserved: {args.workspace}")
        elif args.command == "reset":
            reset(args.iso_source, args.workspace, args.slots, args.slot)
            print(f"Reset original palettes for slots {args.slot}")
        else:
            report = (build(args.iso_source, args.iso_out, args.workspace, args.slots, args.stats_year, args.skin_plan)
                      if args.command == "build" else check(args.iso_source, args.workspace, args.slots, args.iso_out, args.stats_year, args.skin_plan))
            if "skin_tones" in report:
                print(f"Model-local complexion assets: {len(report['skin_tones'])}")
            print(f"Verified 30 slots, {report['uniforms']} uniforms, {report['sources']} sources; "
                  f"{len(report['changes'])} lettering patches, {len(report['courts'])} court patches.")
            if "stats_year" in report:
                print(f"Player-card season labels: {report['stats_year']['label_anchor']} backwards.")
            for court in report["courts"]:
                print(f"Court {court['nba_slot']:03} {court['asset']}: "
                      f"{court['used']}/{court['stored']} bytes, profile {court['profile']}")
            colours = report["colour_controls"]
            if colours:
                modes = {mode: sum(row["mode"] == mode for row in colours) for mode in ("monochrome", "outlined")}
                print(f"Colour controls: {modes['monochrome']} monochrome, {modes['outlined']} outlined.")
                if modes["outlined"]:
                    rms = max(row["model_rms_rgb"] for row in colours)
                    print(f"Generic outlined approximation: maximum source-model RGB RMS {rms:.2f}; inspect refreshed previews.")
                clipped = sum(row["clipped_entries"] for row in colours)
                if clipped:
                    print(f"WARNING: {clipped} palette entries clipped to RGB range; inspect refreshed previews.")
            if args.command == "build":
                print(f"Verified output: {args.iso_out}\nSHA256: {report['output_sha256']}\nISO changes require a fresh boot, not F10.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
