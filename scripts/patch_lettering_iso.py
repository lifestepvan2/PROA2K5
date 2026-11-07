"""Reversible Pacers home lettering-colour experiment on a COPY of the Europe ISO.

    python scripts/patch_lettering_iso.py "C:\\path\\test.iso"
    python scripts/patch_lettering_iso.py "C:\\path\\test.iso" --apply
    python scripts/patch_lettering_iso.py "C:\\path\\test.iso" --restore
    python scripts/patch_lettering_iso.py "C:\\path\\test.iso" --target names --apply

Default is read-only inspection. Patches only the verified 1024-byte source digit
palette, or the alphabet palette with --target names, not assembled player textures,
archive index, or ISO filesystem. The two targets have independent restore manifests.
Close/stop the game before applying or restoring. Boot fresh, not from a savestate.
"""
import argparse
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

ISO_SIZE = 3439427584
ARCHIVE_BASE = 4895 * 2048
ENTRY_INDEX = 2103
ENTRY_HASH = 0xAD6241D2
ENTRY_OFFSET = 0xDF07800
ENTRY_SIZE = 0xB5630
CHUNK_OFFSET = 0xDF36F90
PALETTE_OFFSET = 0xDF4C570
PALETTE_SHA256 = "308eb4ba3724e3599eeb60ac52cb8ffdcc82191c5c83afdfa1cab97f2e0a2397"
PALETTE_SIZE = 1024


@dataclass(frozen=True)
class Palette:
    chunk_offset: int
    chunk_size: int
    palette_offset: int
    sha256: str
    width: int
    height: int


PALETTES = {
    "numbers": Palette(CHUNK_OFFSET, 0x159C0, PALETTE_OFFSET, PALETTE_SHA256, 1024, 64),
    "names": Palette(0xDF2BFA0, 0xAF10, 0xDF36AD0,
                     "36acca4d2c21626095a2a6a03c395ae0aa65cb88c89bb18d21c260ccf88bfe7f", 1024, 32),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def green_fill(palette):
    """Make blue-dominant entries green; retain alpha, yellow and neutral entries."""
    if len(palette) != PALETTE_SIZE:
        raise ValueError("Expected 256 RGBA palette entries")
    result = bytearray(palette)
    for pos in range(0, PALETTE_SIZE, 4):
        red, green, blue, alpha = palette[pos:pos + 4]
        if alpha and blue > red + 12 and blue > green + 8:
            result[pos:pos + 3] = bytes((0, 255, 0))
    if result == palette:
        raise ValueError("No blue-dominant entries found")
    return bytes(result)


def check_layout(stream, target="numbers"):
    palette = PALETTES[target]
    stream.seek(0, 2)
    if stream.tell() != ISO_SIZE:
        raise ValueError(f"Only the verified {ISO_SIZE}-byte Europe image is supported")
    stream.seek(16 * 2048)
    if stream.read(7) != b"\x01CD001\x01":
        raise ValueError("Not the expected ISO9660 image")
    stream.seek(ARCHIVE_BASE)
    if struct.unpack("<I", stream.read(4))[0] != 3728:
        raise ValueError("Unexpected archive entry count")
    stream.seek(ARCHIVE_BASE + 0x9C + ENTRY_INDEX * 12)
    asset_hash, size, sector = struct.unpack("<III", stream.read(12))
    if (asset_hash, size, ARCHIVE_BASE + sector * 2048) != (ENTRY_HASH, ENTRY_SIZE, ENTRY_OFFSET):
        raise ValueError("Unexpected uniform bundle index entry")
    stream.seek(palette.chunk_offset)
    chunk = stream.read(0x90)
    if (chunk[:4], struct.unpack_from("<I", chunk, 4)[0],
            chunk[0x40:0x50], struct.unpack_from("<HH", chunk, 0x7C)) != (
            b"HITX", palette.chunk_size, (target + "\0").encode("utf-16le").ljust(16, b"\0"),
            (palette.width, palette.height)):
        raise ValueError(f"Unexpected source {target} texture chunk")
    if palette.chunk_offset + 0x20 + palette.chunk_size - PALETTE_SIZE != palette.palette_offset:
        raise ValueError("Palette is not at the expected chunk boundary")


def patch(iso, apply=False, restore=False, target="numbers"):
    if apply and restore:
        raise ValueError("Choose apply or restore, not both")
    palette = PALETTES[target]
    suffix = ".lettering-test.json" if target == "numbers" else ".lettering-names-test.json"
    manifest_path = iso.with_name(iso.name + suffix)
    with iso.open("rb") as stream:
        check_layout(stream, target)
        stream.seek(palette.palette_offset)
        current = stream.read(PALETTE_SIZE)
    if restore:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        original = bytes.fromhex(manifest["original_hex"])
        if (manifest["offset"] != palette.palette_offset or digest(original) != palette.sha256
                or manifest["patched_sha256"] != digest(green_fill(original))):
            raise ValueError("Restore manifest does not describe this experiment")
        expected, replacement = green_fill(original), original
        if current == original:
            print("Already restored; no ISO bytes written.")
            return
        if current != expected:
            raise ValueError("Current palette differs from the patch; refusing to overwrite other edits")
    else:
        if digest(current) != palette.sha256:
            raise ValueError("Source palette fingerprint differs; already patched or unsupported ISO")
        original = current
        expected, replacement = original, green_fill(original)
        changed = sum(a != b for a, b in zip(original, replacement))
        entries = sum(original[i:i + 4] != replacement[i:i + 4] for i in range(0, PALETTE_SIZE, 4))
        print(f"Verified Pacers home {target}: ISO 0x{palette.palette_offset:X}, {entries} palette entries / {changed} changed bytes")
        if not apply:
            print("Read-only inspection. Use --apply to patch this ISO copy.")
            return
        manifest = {
            "experiment": f"Pacers home blue {target} fill -> green",
            "iso": str(iso.resolve()), "iso_size": ISO_SIZE,
            "offset": palette.palette_offset, "original_sha256": digest(original),
            "patched_sha256": digest(replacement), "original_hex": original.hex(),
            "restore": f"python scripts\\patch_lettering_iso.py <ISO_COPY> --target {target} --restore",
        }
        if manifest_path.exists():
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            if saved.get("original_hex") != original.hex() or saved.get("patched_sha256") != digest(replacement):
                raise ValueError("Existing manifest conflicts with this experiment")
        else:
            with manifest_path.open("x", encoding="utf-8") as file:
                file.write(json.dumps(manifest, indent=2) + "\n")
                file.flush()
                os.fsync(file.fileno())
    with iso.open("r+b") as stream:
        check_layout(stream, target)
        stream.seek(palette.palette_offset)
        if stream.read(PALETTE_SIZE) != expected:
            raise ValueError("ISO changed since inspection; aborting")
        stream.seek(palette.palette_offset)
        if stream.write(replacement) != PALETTE_SIZE:
            raise OSError("Incomplete palette write; restore from the manifest")
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(palette.palette_offset)
        if stream.read(PALETTE_SIZE) != replacement:
            raise OSError("Palette read-back verification failed")
    print(f"{'Restored' if restore else 'Patched'} and read-back verified: {iso}")
    print(f"Restore manifest: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("iso", type=Path)
    parser.add_argument("--target", choices=PALETTES, default="numbers",
                        help="shared source palette to patch (default: numbers)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    try:
        patch(args.iso, args.apply, args.restore, args.target)
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
