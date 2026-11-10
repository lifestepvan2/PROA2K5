"""Copy a donor's arm/neck texture into one player's home AND away ISO assets.

    python scripts\\player_texture_iso.py SOURCE.iso --pid 235 --donor 922
    python scripts\\player_texture_iso.py SOURCE.iso --pid 235 --donor 922 --out NEW.iso

Read-only without --out. Requires the pristine Europe ISO; never changes it.
Keeps the target's face, geometry, texture descriptors, archive layout and size.
Uses the existing bounded VC-LZ encoder; fails if the donor cannot fit safely.
Boot/load the patched assets afresh: a state containing loaded models bypasses them.
"""
import argparse
import struct
from pathlib import Path

from inventory_lettering_iso import asset_hash
from iso_copy import hash_stream, publish_iso_copy
from patch_lettering_iso import ARCHIVE_BASE, ISO_SIZE, digest
from patch_preview_lettering_iso import SOURCE_SHA256
from vc_lz import decode, rebuild_tail, recompress, validate_inplace

PARTS = {"arm": (128, 128), "neck": (128, 64)}
TEXTURE_SIZES = {**PARTS, "face": (256, 256)}


def texture_resource(asset: bytes, part: str) -> tuple[int, bytes, bytes, int, int]:
    """Return chunk offset, compressed body, decoded body, system size and scratch."""
    if part not in TEXTURE_SIZES:
        raise ValueError(f"Unsupported player texture {part!r}")
    found = []
    position = 0
    while position < len(asset):
        if position + 32 > len(asset):
            raise ValueError("Truncated player resource header")
        kind, stored, system, video, sentinel, scratch, _, _ = struct.unpack_from(
            "<4s7I", asset, position)
        end = position + 32 + stored
        if not stored or end > len(asset):
            raise ValueError("Invalid player resource boundary")
        if kind == b"TXTR":
            if sentinel != 0xFEEDBEEF:
                raise ValueError("Unsupported uncompressed player TXTR")
            body = asset[position + 32:end]
            decoded, _, _ = decode(body, system + video)
            if len(decoded) < 0x20 or decoded[0xC:0x10] != b"TXTR":
                raise ValueError("Invalid decoded player texture object")
            name_pointer, data_pointer = struct.unpack_from("<ii", decoded, 0x10)
            name_offset = 0x10 + name_pointer - 1
            data_offset = 0x14 + data_pointer - 1
            if (not name_pointer & 1 or not data_pointer & 1 or name_offset != 0x20
                    or not name_offset + 8 <= data_offset <= system - 0x30):
                raise ValueError("Unsupported player texture descriptor")
            name_end = name_offset
            while name_end + 2 <= data_offset and decoded[name_end:name_end + 2] != b"\0\0":
                name_end += 2
            if name_end + 2 > data_offset:
                raise ValueError("Unterminated player texture name")
            name = decoded[name_offset:name_end].decode("utf-16le")
            if name == part:
                width, height = struct.unpack_from("<HH", decoded, data_offset + 0x2C)
                if (width, height) != TEXTURE_SIZES[part] or video != width * height + 1024:
                    raise ValueError(f"Unsupported {part} geometry or indexed-palette size")
                found.append((position, body, decoded, system, scratch))
        position = end
    if len(found) != 1:
        raise ValueError(f"Expected exactly one {part} resource, found {len(found)}")
    return found[0]


def replace_texture(asset: bytes, donor: bytes, part: str, *, repack_archive: bool = False) -> tuple[bytes, dict]:
    if part not in PARTS:
        raise ValueError(f"Only arm/neck donor substitution is supported, not {part!r}")
    _, _, donor_decoded, donor_system, _ = texture_resource(donor, part)
    pixels = donor_decoded[donor_system:]
    return replace_video(asset, part, pixels, repack_archive=repack_archive)


def replace_video(asset: bytes, part: str, pixels: bytes, *, repack_archive: bool = False) -> tuple[bytes, dict]:
    offset, body, original, system, scratch = texture_resource(asset, part)
    if len(pixels) != len(original) - system:
        raise ValueError(f"Incompatible {part} texture storage")
    target = original[:system] + pixels
    new_scratch = scratch
    header = asset[offset:offset + 32]
    if repack_archive and target != original:
        rebuilt, required_scratch = min(
            (recompress(body, target, distance_bits=bits) for bits in dict.fromkeys((body[8], 9))),
            key=lambda result: (len(result[0]), result[1]))
        new_scratch = max(scratch, required_scratch)
        validate_inplace(rebuilt, target, new_scratch)
        updated = bytearray(header)
        struct.pack_into("<I", updated, 4, len(rebuilt))
        struct.pack_into("<I", updated, 20, new_scratch)
        header = bytes(updated)
    else:
        rebuilt = rebuild_tail(body, len(original), pixels, scratch)
    verified, _, _ = decode(rebuilt, len(original))
    if verified != original[:system] + pixels:
        raise ValueError("Player texture replacement failed decoded readback")
    start, end = offset + 32, offset + 32 + len(body)
    result = asset[:offset] + header + rebuilt + asset[end:]
    if (result[:offset] != asset[:offset]
            or result[offset + 32 + len(rebuilt):] != asset[end:]
            or (not repack_archive and (len(result) != len(asset) or result[:start] != asset[:start]))):
        raise ValueError("Player texture replacement modified another resource")
    return result, {
        "part": part, "chunk_offset": offset, "body_offset": start,
        "stored_body_size": len(body), "system_size": system,
        "video_size": len(pixels), "scratch_bytes": scratch,
        "new_stored_body_size": len(rebuilt), "new_scratch_bytes": new_scratch,
        "asset_size_delta": len(result) - len(asset),
        "original_body_sha256": digest(body), "patched_body_sha256": digest(rebuilt),
        "descriptor_sha256": digest(original[:system]),
        "original_pixels_sha256": digest(original[system:]),
        "donor_pixels_sha256": digest(pixels),
        "changed_bytes": sum(a != b for a, b in zip(body, rebuilt)) + abs(len(body) - len(rebuilt)),
    }


def read_archive(stream, verify_hash=True):
    stream.seek(0, 2)
    if stream.tell() != ISO_SIZE or (verify_hash and hash_stream(stream) != SOURCE_SHA256):
        raise ValueError("Player texture patch requires the verified pristine Europe ISO")
    stream.seek(ARCHIVE_BASE)
    if stream.read(4) != struct.pack("<I", 3728):
        raise ValueError("Unexpected player archive entry count")
    stream.seek(ARCHIVE_BASE + 0x9C)
    table = stream.read(3728 * 12)
    if len(table) != 3728 * 12:
        raise ValueError("Truncated player archive index")
    entries = {}
    for key, size, sector in struct.iter_unpack("<III", table):
        offset = ARCHIVE_BASE + sector * 2048
        if key in entries or not 0 < size <= ISO_SIZE - offset:
            raise ValueError("Invalid or duplicate player archive entry")
        entries[key] = (offset, size)
    return entries


def read_asset(stream, entries, name):
    entry = entries.get(asset_hash(name))
    if entry is None:
        raise ValueError(f"Player archive has no {name}")
    offset, size = entry
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"Truncated {name}")
    return offset, data


def inspect(stream, pid: int, donor_pid: int, parts: list[str]) -> tuple[list, dict]:
    if (isinstance(pid, bool) or isinstance(donor_pid, bool)
            or not isinstance(pid, int) or not isinstance(donor_pid, int)
            or not 0 <= pid <= 65535 or not 0 <= donor_pid <= 65535 or pid == donor_pid):
        raise ValueError("Choose different target/donor PIDs in 0..65535")
    if not parts or len(set(parts)) != len(parts) or set(parts) - PARTS.keys():
        raise ValueError("Choose arm and/or neck once each")
    entries = read_archive(stream)

    patches, assets = [], []
    for side in ("h", "a"):
        name, donor_name = f"p{pid}{side}.iff", f"p{donor_pid}{side}.iff"
        offset, original = read_asset(stream, entries, name)
        _, donor = read_asset(stream, entries, donor_name)
        patched, resources = original, []
        for part in parts:
            patched, report = replace_texture(patched, donor, part)
            resources.append(report)
        if original != patched:
            patches.append((offset, original, patched))
        assets.append({
            "asset": name, "donor_asset": donor_name, "iso_offset": offset,
            "size": len(original), "original_sha256": digest(original),
            "patched_sha256": digest(patched), "resources": resources,
        })
    if not patches:
        raise ValueError("Donor textures already match the target; no change to test")
    return patches, {
        "experiment": "model-local arm/neck donor substitution; face and scene unchanged",
        "target_pid": pid, "donor_pid": donor_pid, "parts": parts, "assets": assets,
        "iso_size": ISO_SIZE, "pcsx2_crc_preserved": True,
        "scope": "all uses of this target PID; other PIDs' ISO assets unchanged",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--donor", type=int, required=True)
    parser.add_argument("--part", action="append", choices=sorted(PARTS),
                        help="repeat to copy both arm and neck; default arm")
    parser.add_argument("--out", type=Path, help="publish a verified new ISO; source is read-only")
    args = parser.parse_args()
    try:
        with args.source.open("rb") as stream:
            patches, report = inspect(stream, args.pid, args.donor, args.part or ["arm"])
            for asset in report["assets"]:
                for resource in asset["resources"]:
                    print(f"{asset['asset']} <- {asset['donor_asset']} {resource['part']}: "
                          f"{resource['changed_bytes']} changed bytes; face/scene/descriptors unchanged")
            if args.out:
                publish_iso_copy(stream, args.out, patches, SOURCE_SHA256, ISO_SIZE, report,
                                 args.out.with_name(args.out.name + ".player-textures.json"))
                print(f"Verified ISO copy: {args.out}")
            else:
                print("Read-only verification; use --out NEW.iso to publish a copy.")
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
