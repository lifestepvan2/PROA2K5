"""Arena-specific, fixed-span court recolouring using verified SCNE source offsets."""
import json
import struct
from pathlib import Path
from typing import BinaryIO

from lettering_colours import parse_hex
from patch_lettering_iso import digest
from patch_preview_lettering_iso import SOURCE_SHA256
from vc_lz import decode, rebuild_tail

CATALOGUE = Path(__file__).resolve().parents[1] / "data" / "texture_map" / "court_sources.json"


def source_catalogue() -> dict:
    value = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    if (value["schema"] != 1 or value["source_iso_sha256"] != SOURCE_SHA256
            or [arena["slot"] for arena in value["arenas"]] != list(range(30))):
        raise ValueError("Court catalogue must match the pristine ISO and all thirty slots")
    return value


def profile(arena: dict) -> dict:
    floor = arena["untextured_floor_material_indices"]
    primary = floor[:1]
    # Additional authored colour bands share primary; neutral wood-overlay materials stay untouched.
    primary += [index for index in floor[1:]
                if max(arena["materials"][index]["rgba"][:3]) -
                min(arena["materials"][index]["rgba"][:3]) > 8]
    secondary = [part["material_index"] for part in arena["plain_paint_parts"]
                 if part["material_index"] not in primary]
    if arena["slot"] == 22:
        primary, secondary = [2], [3]
    return {"primary_materials": sorted(set(primary)), "secondary_materials": sorted(set(secondary)),
            "linked_regions": arena["shared_floor_paint_material_indices"],
            "primary_role": "Apron and linked paint" if arena["slot"] == 22 else "Apron / outer colour bands",
            "secondary_role": "Dark floor/key regions" if arena["slot"] == 22 else "Zone and filled circles",
            "line_mode": "material_tint" if arena["slot"] == 9 else "palette_replace",
            "flatten_zone_vertices": arena["slot"] != 9,
            "compression": "Fixed span; choose another colour combination if refused"}


def default_controls(arena: dict) -> dict:
    roles = profile(arena)
    primary = arena["materials"][roles["primary_materials"][0]]["rgba"][:3] if roles["primary_materials"] else [5, 129, 141]
    secondary = arena["materials"][roles["secondary_materials"][0]]["rgba"][:3] if roles["secondary_materials"] else primary
    return {"mode": "original", "primary": "#" + bytes(primary).hex().upper(),
            "secondary": "#" + bytes(secondary).hex().upper(), "lines": "#FFFFFF"}


def recolour(source: bytes, arena: dict, controls: dict) -> tuple[bytes, dict]:
    roles = profile(arena)
    if controls["mode"] == "original":
        return source, roles
    if controls["mode"] != "recolour":
        raise ValueError("Unsupported court mode")
    colours = {field: bytes(parse_hex(controls[field])) for field in ("primary", "secondary", "lines")}
    target = bytearray(source)
    allowed = set()

    def change(offset: int, value: bytes) -> None:
        if offset < 0 or offset + len(value) > len(source):
            raise ValueError("Court edit offset is outside the decoded scene")
        allowed.update(range(offset, offset + len(value)))
        target[offset:offset + len(value)] = value

    material_colours = {}

    def material(index: int, colour: bytes) -> None:
        if index in material_colours and material_colours[index] != colour:
            raise ValueError(f"Conflicting court roles for material {index}")
        material_colours[index] = colour

    for role in ("primary", "secondary"):
        for index in roles[f"{role}_materials"]:
            material(index, colours[role])
    masks = arena["line_masks"] + arena["filled_circle_masks"]
    if {mask["descriptor_offset"] for mask in arena["line_masks"]} & {
            mask["descriptor_offset"] for mask in arena["filled_circle_masks"]}:
        raise ValueError("Court texture assigned to both lines and filled paint")
    for role, textures in (("lines", arena["line_masks"]), ("secondary", arena["filled_circle_masks"])):
        for texture in textures:
            tint = role == "lines" and roles["line_mode"] == "material_tint"
            if not tint:
                for offset in texture["palette_logical_entry_offsets"]:
                    if source[offset + 3]:
                        change(offset, colours[role])
            for index in texture["material_indices"]:
                material(index, colours[role] if tint else b"\xff\xff\xff")
    for part in arena["plain_paint_parts"]:
        if not roles["flatten_zone_vertices"]:
            continue
        for stream in part["colour_streams"]:
            if stream["format"] == "V4-8":
                neutral = bytes((128, 128, 128, 128))
            elif stream["format"] == "V4-5":
                neutral = struct.pack("<H", 0xC210)
            else:
                raise ValueError(f"Unsupported vertex colour format {stream['format']}")
            change(stream["data_offset"], neutral * stream["count"])
    for apron in arena["indexed_apron"]:
        for index, weight in enumerate(apron["white_border_weights"]):
            if not -0.01 <= weight <= 1.01:
                raise ValueError("Hornets palette interpolation exceeds quantization tolerance")
            weight = min(1.0, max(0.0, weight))
            colour = bytes(round((1 - weight) * a + weight * b)
                           for a, b in zip(colours["primary"], colours["lines"]))
            change(apron["palette_offset"] + index * 4, colour)
        material(apron["material_index"], b"\xff\xff\xff")
    for index, colour in material_colours.items():
        change(arena["materials"][index]["rgba_offset"], colour)
    for entry in arena["materials"]:
        offset = entry["rgba_offset"] + 3
        if source[offset] != target[offset]:
            raise ValueError("Court material alpha changed")
    for texture in masks:
        if any(source[offset + 3] != target[offset + 3] for offset in texture["palette_logical_entry_offsets"]):
            raise ValueError("Court mask alpha changed")
    if any(a != b and offset not in allowed for offset, (a, b) in enumerate(zip(source, target))):
        raise ValueError("Unrequested court bytes changed")
    return bytes(target), roles


def prepare(stream: BinaryIO, workspace: Path) -> tuple[list[tuple[int, bytes, bytes]], list[dict]]:
    from team_palettes import load
    patches, reports = [], []
    for arena in source_catalogue()["arenas"]:
        config = load(workspace, arena["slot"])["court"]
        if config["mode"] == "original":
            continue
        offset = arena["asset_offset"] + arena["chunk_offset"]
        stream.seek(offset)
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError("Truncated court header")
        kind, stored, system, video, sentinel, scratch, _, _ = struct.unpack("<4s7I", header)
        if (kind != b"SCNE" or sentinel != 0xFEEDBEEF or
                (stored, system, video, scratch) != tuple(arena[field] for field in ("stored", "system", "video", "scratch"))):
            raise ValueError(f"{arena['asset']}: court header differs from inventory")
        body = stream.read(stored)
        if digest(body) != arena["stored_sha256"]:
            raise ValueError(f"{arena['asset']}: compressed court fingerprint differs")
        decoded = decode(body, system + video)[0]
        if digest(decoded) != arena["decoded_sha256"]:
            raise ValueError(f"{arena['asset']}: decoded court fingerprint differs")
        target, roles = recolour(decoded, arena, config)
        changed = [i for i, (a, b) in enumerate(zip(decoded, target)) if a != b]
        if not changed:
            continue
        try:
            rebuilt = rebuild_tail(body, len(decoded), target[min(changed):], scratch)
        except ValueError as error:
            raise ValueError(f"Slot {arena['slot']:03} {arena['nba_team']} court: {error}. "
                             "Try different colours or court.mode=original; no ISO was published.") from error
        verified, _, used = decode(rebuilt, len(decoded))
        if verified != target or len(rebuilt) != stored:
            raise ValueError("Court rebuild failed exact fixed-span verification")
        patches.append((offset + 32, body, rebuilt))
        reports.append({"nba_slot": arena["slot"], "asset": arena["asset"], "settings": config,
                        "profile": roles, "changed_bytes": len(changed), "used": used,
                        "stored": stored, "scratch": scratch, "original_sha256": digest(body),
                        "patched_sha256": digest(rebuilt), "offset": offset + 32, "size": stored})
    return patches, reports
