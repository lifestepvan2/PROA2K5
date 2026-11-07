"""Export NBA 2K5 lettering TXTRs from a 32 MB EE RAM snapshot, without live writes.

Usage: python scripts/inspect_lettering.py snapshot.bin --out OUTPUT_DIRECTORY

Decoding covers the seven-level, PSMT8 lettering textures observed in this experiment,
not arbitrary TXTR formats. JSON includes palette hashes for cross-snapshot comparison.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from txtr_inventory import find_txtr, wstr
from txtr_match import SWZ


def palette_offset(width, height):
    return sum(((max(1, width >> level) * max(1, height >> level) + 15) // 16) * 16
               for level in range(7))


def preview_owners(ram):
    owners = []
    pattern = rb"s\x00e\x00l\x00u\x00[ha]\x00(?:[0-9]\x00){3}\.\x00i\x00f\x00f\x00"
    for match in re.finditer(pattern, ram):
        address = match.start()
        if address + 0x70 > len(ram):
            continue
        start, end = struct.unpack_from("<II", ram, address + 0x68)
        if 0 < start < end <= len(ram):
            owners.append((start, end, match.group().decode("utf-16le")))
    return owners


def inspect(ram, out):
    owners = preview_owners(ram)
    rows = []
    out.mkdir(parents=True, exist_ok=True)
    for obj, name_ptr, header in find_txtr(ram):
        if name_ptr + 96 > len(ram) or header + 64 > len(ram):
            continue
        name = wstr(ram, name_ptr)
        if name != "numbers" and not re.fullmatch(r"jersey(?:name|num)\d{2}", name):
            continue
        pixel = struct.unpack_from("<I", ram, header + 0x18)[0]
        width, height = struct.unpack_from("<HH", ram, header + 0x2C)
        psm = (struct.unpack_from("<Q", ram, header)[0] >> 20) & 63
        if psm != 0x13 or (width, height) not in {(1024, 64), (128, 64), (256, 32)}:
            raise ValueError(f"Unsupported lettering texture at 0x{obj:X}: {width}x{height}, PSM {psm:X}")
        palette = pixel + palette_offset(width, height)
        if not 0 < pixel < palette or palette + 1024 > len(ram):
            raise ValueError(f"Invalid lettering pixel/palette addresses at 0x{obj:X}")
        palette_bytes = ram[palette:palette + 1024]
        pal = np.frombuffer(palette_bytes, dtype="<u4")
        indices = np.frombuffer(ram, dtype=np.uint8, count=width * height, offset=pixel).astype(int)
        rgba = pal[SWZ[indices]].view(np.uint8).reshape(height, width, 4).copy()
        rgba[:, :, 3] = np.minimum(rgba[:, :, 3].astype(int) * 2, 255)
        filename = f"{name}_{obj:08x}.png"
        Image.fromarray(rgba).save(out / filename)
        rows.append({
            "name": name, "object": f"{obj:08x}", "header": f"{header:08x}",
            "pixel": f"{pixel:08x}", "palette": f"{palette:08x}",
            "width": width, "height": height, "palette_sha256": hashlib.sha256(palette_bytes).hexdigest(),
            "preview_asset": next((asset for start, end, asset in owners if start <= obj < end), None),
            "image": filename,
        })
    if not rows:
        raise ValueError("No supported lettering textures found")
    (out / "lettering.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ram = args.snapshot.read_bytes()
    if len(ram) != 0x2000000:
        parser.error(f"Expected a 32 MB EE snapshot, got {len(ram)} bytes")
    rows = inspect(ram, args.out)
    print(f"Exported {len(rows)} lettering textures to {args.out}")
    for row in rows:
        print(f"{row['object']} {row['name']:12} {row['preview_asset'] or '-':12} "
              f"CLUT {row['palette']} SHA256 {row['palette_sha256'][:12]}")


if __name__ == "__main__":
    main()
