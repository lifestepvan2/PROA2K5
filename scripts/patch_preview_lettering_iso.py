"""Read-only inspection or new-output Pacers home preview-number ISO experiment.

    python scripts\\patch_preview_lettering_iso.py PRISTINE.iso
    python scripts\\patch_preview_lettering_iso.py PRISTINE.iso --out NEW_COPY.iso

Only the verified Europe source hash is accepted. The source is never written.
The output retains every archive member's size. By default only the compressed
preview-number body changes; --with-game-test also changes the two verified court
palettes. Stop emulation before booting the new output; do not load a state.
"""
import argparse
import json
import struct
from pathlib import Path

from iso_copy import hash_stream, publish_iso_copy
from patch_lettering_iso import (
    ARCHIVE_BASE, ISO_SIZE, PALETTES, PALETTE_SHA256, check_layout, digest, green_fill,
)
from vc_lz import decode, rebuild_tail

SOURCE_SHA256 = "4cdad2339dbe2828b440ca222f869f234b15c0321c8dcdeac016a30b10678fb7"
ENTRY_INDEX = 178
ENTRY_HASH = 0x0F1821E5
ENTRY_OFFSET = 0x203D800
ENTRY_SIZE = 0x188D0
DECODED_SIZE = 0x159C0


def inspect(stream) -> tuple[int, bytes, bytes, dict]:
    stream.seek(0, 2)
    if stream.tell() != ISO_SIZE:
        raise ValueError("Unexpected Europe ISO size")
    stream.seek(ARCHIVE_BASE + 0x9C + ENTRY_INDEX * 12)
    asset_hash, size, sector = struct.unpack("<III", stream.read(12))
    if (asset_hash, size, ARCHIVE_BASE + sector * 2048) != (ENTRY_HASH, ENTRY_SIZE, ENTRY_OFFSET):
        raise ValueError("Unexpected Pacers home preview archive entry")
    stream.seek(ENTRY_OFFSET)
    header = stream.read(32)
    magic, stored, system, video, sentinel, scratch, _, _ = struct.unpack("<4s7I", header)
    if (magic, system, video, sentinel) != (b"TXTR", 0x70, 0x15950, 0xFEEDBEEF):
        raise ValueError("Unexpected compressed preview-number header")
    if not 10 <= stored <= ENTRY_SIZE - 32:
        raise ValueError("Invalid compressed preview-number span")
    body = stream.read(stored)
    original, _, consumed = decode(body, DECODED_SIZE)
    if (original[12:16] != b"TXTR" or original[32:48] != "numbers\0".encode("utf-16le")
            or digest(original[-1024:]) != PALETTE_SHA256):
        raise ValueError("Unexpected decoded preview-number source")
    replacement_palette = green_fill(original[-1024:])
    replacement = rebuild_tail(body, DECODED_SIZE, replacement_palette, scratch)
    changed = decode(replacement, DECODED_SIZE)[0]
    if changed[:-1024] != original[:-1024] or changed[-1021::4] != original[-1021::4]:
        raise ValueError("Preview indices, descriptor or palette alpha changed")
    manifest = {
        "experiment": "Pacers home preview blue number fill -> green",
        "entry_index": ENTRY_INDEX, "entry_hash": f"{ENTRY_HASH:08x}",
        "body_offset": ENTRY_OFFSET + 32, "body_size": stored,
        "original_body_sha256": digest(body), "patched_body_sha256": digest(replacement),
        "original_palette_sha256": digest(original[-1024:]),
        "patched_palette_sha256": digest(replacement_palette),
        "decoded_size": DECODED_SIZE, "original_consumed_bytes": consumed,
        "scratch_bytes": scratch,
    }
    return ENTRY_OFFSET + 32, body, replacement, manifest


def build(source: Path, output: Path | None = None, with_game_test: bool = False) -> dict:
    source = source.resolve()
    if output is not None:
        output = output.resolve()
        if source == output or output.exists():
            raise ValueError("Output must be a new path, different from the source")
        if not output.parent.is_dir():
            raise ValueError("Output parent directory does not exist")
    with source.open("rb") as stream:
        offset, original, replacement, manifest = inspect(stream)
        patches = [(offset, original, replacement)]
        if with_game_test:
            manifest["game_test"] = {}
            for target, spec in PALETTES.items():
                check_layout(stream, target)
                stream.seek(spec.palette_offset)
                palette = stream.read(1024)
                if digest(palette) != spec.sha256:
                    raise ValueError(f"Unexpected pristine game {target} palette")
                changed = green_fill(palette)
                patches.append((spec.palette_offset, palette, changed))
                manifest["game_test"][target] = {
                    "offset": spec.palette_offset, "original_sha256": digest(palette),
                    "patched_sha256": digest(changed),
                }
        source_hash = hash_stream(stream)
        if source_hash != SOURCE_SHA256:
            raise ValueError("Source is not the verified pristine Europe ISO")
        manifest["source_sha256"] = source_hash
        if output is None:
            return manifest
        manifest_path = output.with_name(output.name + ".preview-lettering-test.json")
        publish_iso_copy(stream, output, patches, source_hash, ISO_SIZE, manifest, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--with-game-test", action="store_true",
                        help="also apply the independently verified court number/name diagnostic palettes")
    args = parser.parse_args()
    try:
        manifest = build(args.source, args.out, args.with_game_test)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(json.dumps(manifest, indent=2))
    print(f"Verified new output: {args.out}" if args.out else "Read-only inspection; no ISO bytes written.")


if __name__ == "__main__":
    main()
