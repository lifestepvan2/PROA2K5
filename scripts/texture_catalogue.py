"""Read-only native texture inventory and exact-pixel cache for the Europe ISO.

    python scripts\\texture_catalogue.py --iso-source PRISTINE --out NEW.sqlite

The database contains provenance, decoded images, and explicit unsupported-layout
records. It is an inspection cache, not a patch plan or an edited ISO.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
import sqlite3
import struct
import zlib
from contextlib import closing
from pathlib import Path
from typing import BinaryIO

import numpy as np

from gs_texture import decode_upload
from inventory_lettering_iso import asset_hash
from iso_copy import hash_stream
from patch_preview_lettering_iso import SOURCE_SHA256
from player_texture_iso import read_archive
from txtr_match import SWZ
from uniform_labels import TEAM_NAMES
from vc_lz import decode

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
MAX_DECODED = 0x2000000
RESOURCE_KIND = re.compile(rb"[A-Za-z0-9]{4}")


def relative(data: bytes, field: int, end: int | None = None) -> int:
    if field < 0 or field + 4 > len(data):
        raise ValueError(f"Pointer field outside resource: {field:#x}")
    value = struct.unpack_from("<i", data, field)[0]
    target = field + value - 1
    if not value & 1 or not 0 <= target < (len(data) if end is None else end):
        raise ValueError(f"Invalid tagged pointer at {field:#x}")
    return target


def text(data: bytes, start: int, end: int) -> str:
    if start % 2 or not 0 <= start < end <= len(data):
        raise ValueError("Invalid UTF-16 string bounds")
    stop = start
    while stop + 2 <= end:
        if data[stop:stop + 2] == b"\0\0":
            return data[start:stop].decode("utf-16le")
        stop += 2
    raise ValueError("Unterminated UTF-16 resource name")


def object_name(data: bytes, system: int, obj: int = 0) -> str:
    return text(data, relative(data, obj + 0x10, system), system)


def resolve_names(stream: BinaryIO, entries: dict) -> dict[int, str]:
    candidates = set()
    stream.seek(0x90000)
    elf = stream.read(8783992)
    for pattern, encoding in ((rb"[A-Za-z0-9_.-]{1,80}\.iff", "ascii"),
                              (rb"(?:[A-Za-z0-9_.-]\x00){1,80}i\x00f\x00f\x00", "utf-16le")):
        candidates.update(m.group().decode(encoding).lower() for m in re.finditer(pattern, elf, re.IGNORECASE))
    for pid in range(65536):
        for side in "ha":
            for suffix in ("", "2"):
                candidates.add(f"p{pid:03}{side}{suffix}.iff")
        candidates.add(f"bh{pid:03}.iff")
        candidates.add(f"p{pid:03}.iff")
    for slot in range(1000):
        candidates.add(f"s{slot:03}.iff")
        candidates.add(f"s{slot:03}n.iff")
        for side in "hax":
            candidates.add(f"w{side}{slot:03}.iff")
            for prefix in ("", "w", "sel", "selw"):
                candidates.add(f"{prefix}u{side}{slot:03}.iff")
    result = {}
    for name in sorted(candidates):
        key = asset_hash(name)
        if key in entries:
            if key in result and result[key] != name:
                raise ValueError(f"Ambiguous filename CRC: {result[key]} and {name}")
            result[key] = name
    return result


def ownership(name: str, courts: dict[str, list[dict]]) -> dict:
    uniform = re.fullmatch(r"(sel)?(w)?u([hax])(\d{3})\.iff", name)
    warmup = re.fullmatch(r"w([hax])(\d{3})\.iff", name)
    model = re.fullmatch(r"p(\d+)([ha])(2?)\.iff", name)
    if uniform or warmup:
        slot = int(warmup[2] if warmup else uniform[4])
        side = warmup[1] if warmup else uniform[3]
        return {
            "kind": "uniform", "slot": slot,
            "team": TEAM_NAMES[slot] if slot < len(TEAM_NAMES) else f"uniform-slot-{slot}",
            "variant": {"h": "home", "a": "away", "x": "alternate"}[side],
            "surface": "preview" if uniform and uniform[1] else "game",
            "warmup": bool(warmup or uniform[2]), "evidence": "verified filename CRC and native bundle",
        }
    if model:
        return {"kind": "player_model", "pid": int(model[1]), "side": model[2],
                "variant": model[3] or "standard", "evidence": "verified filename CRC"}
    if name in courts:
        return {"kind": "arena", "teams": courts[name], "evidence": "court_sources.csv asset mapping"}
    if name == "hash:35cb8d72":
        return {"kind": "portrait_collection", "asset": name,
                "evidence": "822 native TXTRs; numeric descriptor names cross-checked against PID and original portrait pixels"}
    return {"kind": "named_asset" if not name.startswith("hash:") else "unresolved_asset",
            "asset": name, "evidence": "verified filename CRC" if not name.startswith("hash:") else "archive hash only"}


def descriptors(data: bytes, kind: str, system: int) -> list[tuple[int, str]]:
    if kind in ("TXTR", "HITX"):
        if data[0xC:0x10] not in (b"TXTR", b"HITX"):
            raise ValueError("Texture object magic differs")
        return [(relative(data, 0x14, system), object_name(data, system))]
    if kind == "TSET":
        if system < 12:
            raise ValueError("Truncated texture set")
        count = struct.unpack_from("<I", data, 4)[0]
        if count > (system - 12) // 36:
            raise ValueError("Texture-set object array outside system data")
        result = []
        for index in range(count):
            obj = 12 + index * 36
            if data[obj + 12:obj + 16] != b"TXTR":
                raise ValueError("Texture-set object magic differs")
            result.append((relative(data, obj + 20, system), object_name(data, system, obj)))
        return result
    if kind in ("SCNE", "HiSn"):
        if data[12:16] != b"SCNE":
            raise ValueError("Scene object magic differs")
        root = relative(data, 20, system)
        if root + 0x1C > system:
            raise ValueError("Truncated scene table header")
        count = struct.unpack_from("<I", data, root + 0x14)[0]
        if count == 0:
            return []
        table = relative(data, root + 0x18, system)
        if count > (system - table) // 56:
            raise ValueError("Scene descriptor array outside system data")
        names = collections.defaultdict(list)
        if root + 0x24 <= system:
            materials = struct.unpack_from("<I", data, root + 0x1C)[0]
            if materials:
                base = relative(data, root + 0x20, system) - 16
                if base < 0 or materials > (system - base) // 96:
                    raise ValueError("Scene material array outside system data")
                for index in range(materials):
                    material = base + index * 96
                    pointer = struct.unpack_from("<I", data, material + 0x5C)[0]
                    if pointer:
                        descriptor = relative(data, material + 0x5C, system)
                        name = material_name(data, material, index, system)
                        if name:
                            names[descriptor].append(name)
        return [(table + i * 56, ";".join(sorted(set(names[table + i * 56]))) or f"descriptor-{i}")
                for i in range(count)]
    return []


def linear_images(data: bytes, system: int, video: int, descriptor: int) -> tuple[list[dict], str]:
    """Decode only layouts whose complete storage size is accounted for."""
    if descriptor < 0 or descriptor + 48 > system:
        raise ValueError("Texture descriptor outside system data")
    width, height = struct.unpack_from("<HH", data, descriptor + 0x2C)
    tex0 = struct.unpack_from("<Q", data, descriptor)[0]
    psm = (tex0 >> 20) & 63
    if not width or not height or width > 4096 or height > 4096:
        raise ValueError("Unsupported texture geometry")
    bits, palette_size = {19: (8, 1024), 20: (4, 64), 0: (32, 0)}.get(psm, (0, 0))
    if not bits:
        return [], f"unsupported PSM {psm}"
    if len(data) < system + video:
        raise ValueError("Decoded video data is truncated")
    sizes = [((max(1, width >> level) * max(1, height >> level) * bits + 7) // 8 + 15) // 16 * 16
             for level in range(7)]
    levels = next((count for count in range(1, 8) if sum(sizes[:count]) + palette_size == video), None)
    if levels is None:
        return [], "packed/shared video or non-linear mip layout; requires transfer decoder"
    palette = None
    if palette_size:
        palette = np.frombuffer(data[system + video - palette_size:system + video], dtype=np.uint8).reshape(-1, 4)
    result, offset = [], system
    for level in range(levels):
        w, h = max(1, width >> level), max(1, height >> level)
        count = w * h
        if psm == 0:
            rgba = data[offset:offset + count * 4]
        else:
            indices = np.frombuffer(data[offset:offset + (count * bits + 7) // 8], dtype=np.uint8)
            if psm == 20:
                indices = np.stack((indices & 15, indices >> 4), axis=1).ravel()[:count]
            if palette is None:
                raise ValueError("Indexed texture lacks its palette")
            rgba = palette[SWZ[indices] if psm == 19 else indices].tobytes()
        result.append({"level": level, "width": w, "height": h, "rgba": rgba,
                       "pixel_offset": offset, "palette_offset": system + video - palette_size if palette_size else None})
        offset += sizes[level]
    return result, "linear" if levels == 1 else ("linear-seven-mip" if levels == 7 else f"linear-{levels}-mip")


def texture_span(data: bytes, system: int, video: int, descriptor: int,
                 descriptor_offsets: list[int]) -> tuple[int, int]:
    """Locate a shared texture upload, using raw offsets relative to video data."""
    if system < 0 or video <= 0 or system + video > len(data) or descriptor not in descriptor_offsets:
        raise ValueError("Invalid shared texture resource bounds or descriptor identity")
    offsets = []
    for location in descriptor_offsets:
        if location < 0 or location + 48 > system:
            raise ValueError("Shared texture descriptor exceeds system data")
        offset = struct.unpack_from("<I", data, location + 24)[0]
        if offset >= video:
            raise ValueError("Shared texture video offset exceeds resource")
        offsets.append(offset)
    start = struct.unpack_from("<I", data, descriptor + 24)[0]
    return start, min((offset for offset in offsets if offset > start), default=video)


def texture_images(data: bytes, system: int, video: int, descriptor: int,
                   descriptor_offsets: list[int]) -> tuple[list[dict], str, int, int]:
    start, end = texture_span(data, system, video, descriptor, descriptor_offsets)
    isolated = data[:system] + data[system + start:system + end]
    images, layout = linear_images(isolated, system, end - start, descriptor)
    if not images:
        images = decode_upload(isolated, system, end - start, descriptor)
        layout = "gs32-upload-64"
    else:
        for image in images:
            image["pixel_offset"] += start
            if image["palette_offset"] is not None:
                image["palette_offset"] += start
    return images, layout, start, end


def material_name(data: bytes, record: int, index: int, system: int) -> str:
    value = struct.unpack_from("<i", data, record + 8)[0]
    target = record + 8 + value - 1
    # The first material's optional object prefix may be absent.
    if not value or (index == 0 and (not value & 1 or not 0 <= target < system)):
        return ""
    return text(data, relative(data, record + 8, system), system)


def scene_materials(data: bytes, system: int) -> list[dict]:
    root = relative(data, 20, system)
    if root + 36 > system:
        raise ValueError("Truncated scene material header")
    count = struct.unpack_from("<I", data, root + 28)[0]
    if not count:
        return []
    base = relative(data, root + 32, system) - 16
    if base < 0 or count > (system - base) // 96:
        raise ValueError("Scene material array exceeds system data")
    result = []
    for index in range(count):
        record = base + index * 96
        pointer = struct.unpack_from("<I", data, record + 92)[0]
        descriptor = relative(data, record + 92, system) if pointer else None
        if descriptor is not None and descriptor + 48 > system:
            raise ValueError("Scene material references invalid texture descriptor")
        result.append({
            "index": index,
            "name": material_name(data, record, index, system),
            "rgba": list(data[record + 88:record + 92]),
            "descriptor": descriptor, "descriptor_ref": pointer,
        })
    return result


def create_database(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE assets (
            hash TEXT PRIMARY KEY, entry_index INTEGER, name TEXT, iso_offset INTEGER,
            size INTEGER, sha256 TEXT, ownership TEXT, status TEXT, reason TEXT
        );
        CREATE TABLE resources (
            asset_hash TEXT, ordinal INTEGER, kind TEXT, name TEXT, chunk_offset INTEGER,
            stored INTEGER, system INTEGER, video INTEGER, scratch INTEGER, compressed INTEGER,
            stored_sha256 TEXT, decoded_sha256 TEXT, status TEXT, reason TEXT,
            PRIMARY KEY(asset_hash, ordinal)
        );
        CREATE TABLE textures (
            id TEXT PRIMARY KEY, asset_hash TEXT, resource_ordinal INTEGER,
            descriptor INTEGER, name TEXT, width INTEGER, height INTEGER, psm INTEGER,
            tex0 TEXT, status TEXT, reason TEXT
        );
        CREATE TABLE pixels (
            digest TEXT PRIMARY KEY, width INTEGER, height INTEGER, rgba BLOB
        );
        CREATE TABLE images (
            texture_id TEXT, level INTEGER, digest TEXT, pixel_offset INTEGER, palette_offset INTEGER,
            PRIMARY KEY(texture_id, level)
        );
        CREATE INDEX images_digest ON images(digest);
    """)


def add_resource(connection: sqlite3.Connection, key: str, ordinal: int, header: tuple,
                 chunk_offset: int, body: bytes) -> None:
    raw_kind, stored, system, video, sentinel, scratch, _, _ = header
    kind, compressed = raw_kind.decode("ascii"), sentinel == 0xFEEDBEEF
    decoded_hash, name, status, reason = "", "", "metadata-only", ""
    if kind in ("TXTR", "HITX", "TSET", "SCNE", "HiSn"):
        connection.execute("SAVEPOINT resource")
        try:
            if not 0 < system + video <= MAX_DECODED:
                raise ValueError("Decoded resource size outside supported bounds")
            data = decode(body, system + video, collect_tokens=False)[0] if compressed else body
            if len(data) < system + video:
                raise ValueError("Uncompressed resource is shorter than its declared data")
            decoded_hash = hashlib.sha256(data).hexdigest()
            name = object_name(data, system) if kind != "TSET" else ""
            found = descriptors(data, kind, system)
            for index, (descriptor, texture_name) in enumerate(found):
                if descriptor + 48 > system:
                    raise ValueError("Texture descriptor exceeds system storage")
                width, height = struct.unpack_from("<HH", data, descriptor + 44)
                tex0 = struct.unpack_from("<Q", data, descriptor)[0]
                identity = f"{SOURCE_SHA256}:{key}:{ordinal}:{index}:{texture_name}"
                texture_id = hashlib.sha256(identity.encode()).hexdigest()
                # Only a single standalone texture owns the whole video tail.
                images, layout = (linear_images(data, system, video, descriptor)
                                  if kind in ("TXTR", "HITX") else ([], "shared container; requires transfer decoder"))
                connection.execute("INSERT INTO textures VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    texture_id, key, ordinal, descriptor, texture_name, width, height,
                    (tex0 >> 20) & 63, f"{tex0:016x}", "decoded" if images else "blocked", layout))
                for image in images:
                    digest = pixel_digest(image["width"], image["height"], image["rgba"])
                    connection.execute("INSERT OR IGNORE INTO pixels VALUES (?,?,?,?)", (
                        digest, image["width"], image["height"], zlib.compress(image["rgba"], 1)))
                    connection.execute("INSERT INTO images VALUES (?,?,?,?,?)", (
                        texture_id, image["level"], digest, image["pixel_offset"], image["palette_offset"]))
            status = "inventoried"
        except (ValueError, UnicodeError, struct.error) as error:
            # Unsupported data is a visible catalogue row, never a successful mapping.
            connection.execute("ROLLBACK TO resource")
            status, reason = "blocked", str(error)
        finally:
            connection.execute("RELEASE resource")
    connection.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        key, ordinal, kind, name, chunk_offset, stored, system, video, scratch, int(compressed),
        hashlib.sha256(body).hexdigest() if body else None, decoded_hash, status, reason))


def pixel_digest(width: int, height: int, rgba: bytes) -> str:
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("Invalid RGBA dimensions or byte length")
    return hashlib.sha256(struct.pack("<II", width, height) + rgba).hexdigest()


def catalogue(source: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Catalogue already exists; choose a new output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        raise ValueError("Catalogue temporary file already exists")
    courts = collections.defaultdict(list)
    with (ROOT / "data" / "texture_map" / "court_sources.csv").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            courts[row["asset"]].append({"slot": int(row["nba_slot"]), "team": row["nba_team"]})
    try:
        with source.open("rb") as stream, closing(sqlite3.connect(temporary)) as connection, connection:
            entries = read_archive(stream)
            ordered = sorted(entries.values())
            if any(start + size > next_start for (start, size), (next_start, _) in zip(ordered, ordered[1:])):
                raise ValueError("Archive entries overlap")
            names = resolve_names(stream, entries)
            create_database(connection)
            connection.executemany("INSERT INTO metadata VALUES (?,?)", [
                ("schema", str(SCHEMA)), ("source_sha256", SOURCE_SHA256), ("complete", "false")])
            for index, (entry_key, (offset, size)) in enumerate(entries.items()):
                key, pos, ordinal = f"{entry_key:08x}", 0, 0
                name = names.get(entry_key, f"hash:{key}")
                status, reason = "inventoried", ""
                digest = hashlib.sha256()
                stream.seek(offset)
                remaining = size
                while remaining:
                    block = stream.read(min(remaining, 4 * 1024 * 1024))
                    if not block:
                        raise ValueError(f"Truncated asset {name}")
                    digest.update(block)
                    remaining -= len(block)
                while pos < size:
                    stream.seek(offset + pos)
                    raw = stream.read(min(32, size - pos))
                    if len(raw) != 32:
                        status, reason = "opaque-tail", f"Trailing {len(raw)} bytes at {pos:#x}"
                        break
                    header = struct.unpack("<4s7I", raw)
                    kind, stored = header[:2]
                    if not RESOURCE_KIND.fullmatch(kind) or not stored or pos + 32 + stored > size:
                        status, reason = "opaque-tail", f"Non-resource boundary at {pos:#x}: {kind.hex()}"
                        break
                    # Multimedia chunks can be very large; metadata alone is sufficient here.
                    if kind in (b"TXTR", b"HITX", b"TSET", b"SCNE", b"HiSn"):
                        if stored > MAX_DECODED:
                            status, reason = "opaque-tail", f"Resource exceeds inspection bound at {pos:#x}"
                            break
                        body = stream.read(stored)
                    else:
                        body = b""
                    add_resource(connection, key, ordinal, header, pos, body)
                    pos += 32 + stored
                    ordinal += 1
                connection.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)", (
                    key, index, name, offset, size, digest.hexdigest(),
                    json.dumps(ownership(name, courts), sort_keys=True), status, reason))
                if index % 100 == 0:
                    connection.commit()
                    print(f"Inventoried {index + 1}/{len(entries)} assets", flush=True)
            if hash_stream(stream) != SOURCE_SHA256:
                raise ValueError("Source ISO changed during inventory")
            connection.execute("UPDATE metadata SET value='true' WHERE key='complete'")
            summary = database_summary(connection)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return summary


def open_catalogue(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        if metadata != {"schema": str(SCHEMA), "source_sha256": SOURCE_SHA256, "complete": "true"}:
            raise ValueError("Incomplete, incompatible or wrong-source texture catalogue")
    except (ValueError, sqlite3.Error):
        connection.close()
        raise
    return connection


def database_summary(connection: sqlite3.Connection) -> dict:
    return {
        "schema": SCHEMA, "source_sha256": SOURCE_SHA256,
        "assets": connection.execute("SELECT count(*) FROM assets").fetchone()[0],
        "resources": connection.execute("SELECT count(*) FROM resources").fetchone()[0],
        "textures": connection.execute("SELECT count(*) FROM textures").fetchone()[0],
        "images": connection.execute("SELECT count(*) FROM images").fetchone()[0],
        "unique_images": connection.execute("SELECT count(*) FROM pixels").fetchone()[0],
        "asset_status": dict(connection.execute("SELECT status,count(*) FROM assets GROUP BY status")),
        "resource_status": dict(connection.execute("SELECT status,count(*) FROM resources GROUP BY status")),
        "texture_status": dict(connection.execute("SELECT status,count(*) FROM textures GROUP BY status")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(catalogue(args.iso_source, args.out), indent=2))
    except (OSError, ValueError, sqlite3.Error, struct.error) as error:
        parser.exit(1, f"Texture catalogue failed: {error}\n")


if __name__ == "__main__":
    main()
