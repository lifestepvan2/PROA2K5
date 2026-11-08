"""Inventory shared lettering sources for all 30 NBA slots, without ISO writes.

    python scripts\\inventory_lettering_iso.py PRISTINE.iso --out data\\texture_map\\lettering_sources.csv

Filename hashes are CRC32 of uppercase UTF-16LE names, with no terminator.
Home/away are required for every slot; matching ux/selux alternate pairs are included.
The CSV contains mapping/fingerprints only, never texture indices or palettes.
"""
import argparse
import csv
import struct
import zlib
from pathlib import Path

from patch_lettering_iso import ARCHIVE_BASE, ISO_SIZE, digest
from iso_copy import hash_stream
from patch_preview_lettering_iso import SOURCE_SHA256
from vc_lz import decode


def asset_hash(name: str) -> int:
    return zlib.crc32(name.upper().encode("utf-16le"))


def lettering_chunks(data: bytes) -> list[dict]:
    rows = []
    position = 0
    while position < len(data):
        if position + 32 > len(data):
            raise ValueError("Truncated uniform resource header")
        kind, stored, system, video, sentinel, scratch, _, _ = struct.unpack_from("<4s7I", data, position)
        end = position + 32 + stored
        if stored == 0 or end > len(data):
            raise ValueError("Invalid uniform resource chunk boundary")
        body = data[position + 32:end]
        compressed = kind == b"TXTR" and sentinel == 0xFEEDBEEF
        decoded = None
        if compressed and system == 0x70 and video in (0x15950, 0xAEB0):
            decoded = decode(body, system + video)[0]
        elif kind == b"HITX":
            decoded = body
        if decoded is not None:
            if len(decoded) < 0x70 + 1024:
                raise ValueError("Truncated lettering descriptor/palette")
            name = decoded[0x20:0x40].decode("utf-16le").split("\0", 1)[0]
            if name in ("names", "numbers"):
                width, height = struct.unpack_from("<HH", decoded, 0x5C)
                supported = {(1024, 32)} if name == "names" else {(1024, 64), (512, 64)}
                if (width, height) not in supported:
                    raise ValueError(f"Unsupported {name} atlas geometry {width}x{height} at chunk 0x{position:X}")
                palette = decoded[-1024:]
                rows.append({
                    "target": name, "resource": kind.decode("ascii"),
                    "chunk_relative_offset": position, "stored_body_size": stored,
                    "decoded_size": len(decoded), "compressed": int(compressed),
                    "scratch_bytes": scratch if compressed else 0,
                    "width": width, "height": height,
                    "palette_offset_in_decoded_body": len(decoded) - 1024,
                    "stored_body_sha256": digest(body),
                    "palette_sha256": digest(palette),
                    "palette_alpha_sha256": digest(palette[3::4]),
                    "descriptor_indices_mips_sha256": digest(decoded[:-1024]),
                })
        position = end
    return rows


def inventory(stream) -> list[dict]:
    stream.seek(0, 2)
    if stream.tell() != ISO_SIZE or hash_stream(stream) != SOURCE_SHA256:
        raise ValueError("Inventory requires the verified pristine Europe ISO")
    stream.seek(ARCHIVE_BASE)
    if struct.unpack("<I", stream.read(4))[0] != 3728:
        raise ValueError("Unexpected archive entry count")
    stream.seek(ARCHIVE_BASE + 0x9C)
    index_data = stream.read(3728 * 12)
    if len(index_data) != 3728 * 12:
        raise ValueError("Truncated archive index")
    entries = {}
    for index in range(3728):
        key, size, sector = struct.unpack_from("<III", index_data, index * 12)
        if key in entries:
            raise ValueError("Duplicate archive filename hash")
        offset = ARCHIVE_BASE + sector * 2048
        if not 0 < size <= ISO_SIZE - offset:
            raise ValueError("Archive entry extends outside the ISO")
        entries[key] = (index, offset, size)
    rows = []
    for slot in range(30):
        for letter, variant in (("h", "home"), ("a", "away"), ("x", "alt")):
            names = [f"u{letter}{slot:03}.iff", f"selu{letter}{slot:03}.iff"]
            present = [asset_hash(name) in entries for name in names]
            if letter == "x" and not any(present):
                continue
            if not all(present):
                raise ValueError(f"Missing paired game/preview source for slot {slot} {variant}")
            pair = []
            for name, surface in zip(names, ("game", "preview")):
                key = asset_hash(name)
                index, offset, size = entries[key]
                stream.seek(offset)
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError(f"Truncated asset {name}")
                chunks = lettering_chunks(data)
                expected = {"names", "numbers"} if surface == "game" else {"numbers"}
                if {chunk["target"] for chunk in chunks} != expected or len(chunks) != len(expected):
                    raise ValueError(f"Unexpected lettering sources in {name}")
                for chunk in chunks:
                    pair.append({
                        "nba_slot": slot, "variant": variant, "surface": surface, "asset": name,
                        "entry_index": index, "entry_hash": f"{key:08x}",
                        "entry_offset": offset, "entry_size": size,
                        "chunk_offset": offset + chunk["chunk_relative_offset"],
                        "body_offset": offset + chunk["chunk_relative_offset"] + 32,
                        **chunk, "source_iso_sha256": SOURCE_SHA256,
                    })
            numbers = [row for row in pair if row["target"] == "numbers"]
            if numbers[0]["palette_sha256"] != numbers[1]["palette_sha256"]:
                raise ValueError(f"Game/preview number palettes differ for slot {slot} {variant}")
            rows.extend(pair)
    if hash_stream(stream) != SOURCE_SHA256:
        raise ValueError("Source ISO changed during inventory")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.source.open("rb") as stream:
            rows = inventory(stream)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")
    variants = {(row["nba_slot"], row["variant"]) for row in rows}
    print(f"Inventoried 30 slots, {len(variants)} uniforms, {len(rows)} lettering sources -> {args.out}")


if __name__ == "__main__":
    main()
