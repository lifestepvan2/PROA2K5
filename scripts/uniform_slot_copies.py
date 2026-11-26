"""Compose opposite-side default uniforms into selectable ProA alternate slots."""
import bisect
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import roster_iso
from inventory_lettering_iso import asset_hash
from lettering_workspace import assignments
from patch_lettering_iso import digest
from player_texture_iso import read_archive
from texture_catalogue import object_name, relative, text
from vc_lz import decode

DEFAULT_SLOTS = Path(__file__).resolve().parents[1] / "data" / "team_slots.csv"
GAME_PARTS = {"logo", "names", "names.metrics", "numbers", "numbers.metrics", "unif", "short", "unidata"}
PREVIEW_PARTS = {"numbers", "numbers.metrics", "unif", "unidata"}


@dataclass(frozen=True)
class UniformSlot:
    team_id: int
    away: bool
    name: str


@dataclass(frozen=True)
class UniformCopy:
    slot: int
    team: str
    donor: str
    destination: str


def uniform_slots(payload: bytes) -> list[UniformSlot]:
    count = struct.unpack_from("<I", payload, 0xB0)[0]
    start = relative(payload, 0xB4)
    if count != 218 or start != 0x65534:
        raise ValueError("Unsupported Europe uniform selection table")
    result = []
    names = set()
    for index in range(count):
        row = start + index * 20
        team, side, reserved = struct.unpack_from("<3I", payload, row)
        name = text(payload, relative(payload, row + 12), roster_iso.CONTENT_END)
        if (side not in (0, 1) or reserved != 0 or name in names
                or not re.fullmatch(r"(?:u[hax]|r[1-9]\d*[ha])\d{3}", name)):
            raise ValueError(f"Unsupported uniform selection row {index}: {name!r}")
        names.add(name)
        result.append(UniformSlot(team, bool(side), name))
    return result


def rules(stream: BinaryIO, slots: Path = DEFAULT_SLOTS) -> list[UniformCopy]:
    from texture_iso_workspace import team_ids

    selected = assignments(slots)
    owners = team_ids()
    uniforms = uniform_slots(roster_iso.baseline(roster_iso.read_source(stream)))
    entries = read_archive(stream)
    result = []
    for uniform in uniforms:
        slot = owners.get(uniform.team_id)
        team = selected.get(str(slot))
        if team is None:
            continue
        defaults = {f"uh{uniform.team_id:03}", f"ua{uniform.team_id:03}"}
        if uniform.name in defaults:
            continue
        donor = f"u{'h' if uniform.away else 'a'}{uniform.team_id:03}"
        if not any(row.team_id == uniform.team_id and row.name == donor for row in uniforms):
            raise ValueError(f"{uniform.name}: missing default uniform donor {donor}")
        for prefix in ("", "sel"):
            source, destination = f"{prefix}{donor}.iff", f"{prefix}{uniform.name}.iff"
            if any(asset_hash(name) not in entries for name in (source, destination)):
                raise ValueError(f"Missing game/preview uniform copy pair: {source} -> {destination}")
            result.append(UniformCopy(slot, team, source, destination))
    return result


def chunks(data: bytes, preview: bool) -> list[tuple[int, int, str | None]]:
    result = []
    position = 0
    previous_name = None
    found = set()
    expected = PREVIEW_PARTS if preview else GAME_PARTS
    while position < len(data):
        if position + 32 > len(data):
            raise ValueError("Truncated uniform resource header")
        kind, stored, system, video, sentinel, _, _, _ = struct.unpack_from("<4s7I", data, position)
        end = position + 32 + stored
        if stored == 0 or end > len(data):
            raise ValueError("Invalid uniform resource boundary")
        name = None
        if kind in (b"TXTR", b"HITX", b"UnAD"):
            body = data[position + 32:end]
            decoded = decode(body, system + video)[0] if sentinel == 0xFEEDBEEF else body
            candidate = object_name(decoded, system or len(decoded))
            if candidate in expected:
                name = candidate
        elif kind == b"NAME" and previous_name in ("names", "numbers"):
            name = f"{previous_name}.metrics"
        if name is not None:
            if name in found:
                raise ValueError(f"Duplicate uniform resource {name}")
            found.add(name)
        result.append((position, end, name))
        previous_name = name
        position = end
    if found != expected:
        raise ValueError(f"Uniform copy resource set differs: expected {sorted(expected)}, got {sorted(found)}")
    return result


def inherited_offsets(stream: BinaryIO, copies: list[UniformCopy]) -> set[int]:
    entries = read_archive(stream)
    result = set()
    for copy in copies:
        offset, size = entries[asset_hash(copy.destination)]
        stream.seek(offset)
        for start, _, name in chunks(stream.read(size), copy.destination.startswith("sel")):
            if name is not None:
                result.add(offset + start + 32)
    return result


def compose(stream: BinaryIO, patches: list[tuple[int, bytes, bytes]],
            copies: list[UniformCopy]) -> tuple[list[tuple[int, bytes, bytes]], list[dict]]:
    if not copies:
        return patches, []
    entries = read_archive(stream)
    ordered = sorted((offset, key, size) for key, (offset, size) in entries.items())
    starts = [row[0] for row in ordered]
    targets = {asset_hash(copy.destination) for copy in copies}
    relevant = targets | {asset_hash(copy.donor) for copy in copies}
    grouped = {key: [] for key in relevant}
    retained = []
    previous = 0
    for patch in sorted(patches):
        offset, before, _ = patch
        if not before or offset < previous:
            raise ValueError("Uniform copy inputs must be disjoint original-coordinate edits")
        previous = offset + len(before)
        index = bisect.bisect_right(starts, offset) - 1
        if index >= 0:
            start, key, size = ordered[index]
            if key in relevant and start <= offset < start + size:
                if offset + len(before) > start + size:
                    raise ValueError("Uniform edit crosses an archive asset boundary")
                grouped[key].append(patch)
                if key in targets:
                    continue
        retained.append(patch)

    originals, final = {}, {}
    for key in relevant:
        offset, size = entries[key]
        stream.seek(offset)
        original = stream.read(size)
        if len(original) != size:
            raise ValueError("Truncated uniform copy source")
        originals[key] = original
        parts, position = [], 0
        for start, before, after in grouped[key]:
            local = start - offset
            if original[local:local + len(before)] != before:
                raise ValueError("Uniform copy source edit bytes changed")
            parts.extend((original[position:local], after))
            position = local + len(before)
        final[key] = b"".join(parts + [original[position:]])

    reports = []
    for copy in copies:
        donor_key, target_key = asset_hash(copy.donor), asset_hash(copy.destination)
        preview = copy.destination.startswith("sel")
        donor = final[donor_key]
        replacements = {name: donor[start:end] for start, end, name in chunks(donor, preview)
                        if name is not None}
        original_chunks = chunks(originals[target_key], preview)
        manual_names = {
            name for start, end, name in original_chunks if name is not None
            and any(offset < entries[target_key][0] + end
                    and offset + len(before) > entries[target_key][0] + start
                    for offset, before, _ in grouped[target_key])
        }
        target = final[target_key]
        updated = b"".join(replacements[name] if name is not None and name not in manual_names else target[start:end]
                           for start, end, name in chunks(target, preview))
        verified = {name: updated[start:end] for start, end, name in chunks(updated, preview)
                    if name is not None}
        target_parts = {name: target[start:end] for start, end, name in chunks(target, preview)
                        if name is not None}
        expected = {name: target_parts[name] if name in manual_names else part
                    for name, part in replacements.items()}
        if verified != expected:
            raise ValueError(f"Uniform donor readback failed: {copy.destination}")
        original = originals[target_key]
        if updated != original:
            retained.append((entries[target_key][0], original, updated))
        reports.append({
            "slot": copy.slot, "team": copy.team, "donor": copy.donor, "destination": copy.destination,
            "destination_hash": f"{target_key:08x}", "resources": sorted(replacements),
            "manual_resources": sorted(manual_names),
            "original_size": len(original), "size": len(updated),
            "sha256": digest(updated), "donor_resources_sha256": digest(b"".join(
                replacements[name] for name in sorted(replacements))),
        })
    return sorted(retained), reports
