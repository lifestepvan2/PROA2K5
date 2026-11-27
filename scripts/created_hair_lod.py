"""Approved per-style low-detail hair and stock fallback for the Europe ISO."""
import hashlib
import json
import struct
from pathlib import Path
from typing import BinaryIO

from player_texture_iso import read_archive, read_asset
from roster_stats import ELF_ISO_OFFSET
from texture_catalogue import object_name, relative, text
from vc_lz import decode, recompress, validate_inplace

ASSETS = Path(__file__).resolve().parents[1] / "data" / "created_hair_lod"
CUSTOM_STYLES = (2, 5, 10, 11, 13, 16, 18, 19, 21, 22, 23)
SCENE_ASSETS = ("frontend.iff", "gamedataextra.iff")
SCENE_SHA256 = "3de5f7292652e274160a7072e6e61beb4d94758dd0dd9d2df549fb4c551c3b70"
SELECTOR_OFFSET = 0x11C058
SELECTOR_SIZE = 268
SELECTOR_ORIGINAL_SHA256 = "a70440f124b1cde6c13437653110ac8f738059eb0c5182b3f55a9fec7d1cc3ef"
BINDINGS = (
    (0x3A3F98, 0x75BE0C, 0x18C014),
    (0x3A3FB0, 0x75BE22, 0x18C02E),
    (0x3A3FC8, 0x75BE38, 0x18C048),
)

TABLE_OFFSET = ELF_ISO_OFFSET + 0x3147E0
ORIGINAL_TARGETS = (
    0x18B7F4, 0x18B7F4, 0x18B740, 0x18B748, 0x18B750, 0x18B758,
    0x18B760, 0x18B768, 0x18B770, 0x18B778, 0x18B780, 0x18B788,
    0x18B790, 0x18B798, 0x18B7A0, 0x18B7A8, 0x18B7B0, 0x18B7B8,
    0x18B7C0, 0x18B7C8, 0x18B7D0, 0x18B7D8, 0x18B7E4, 0x18B7B0,
    0x18B7B0, 0x18B7B0, 0x18B7EC,
)
BASIC_MESHES = {
    **dict.fromkeys((1, 2, 5, 13, 18, 22, 23), 0x18B740),
    7: 0x18B7B0,
    **dict.fromkeys((10, 11, 16, 19, 21), 0x18B770),
}


def prepare_basic(stream: BinaryIO) -> tuple[list[tuple[int, bytes, bytes]], int]:
    """Return original-coordinate selector patch and its ELF XOR-CRC delta."""
    fmt = f"<{len(ORIGINAL_TARGETS)}I"
    expected = struct.pack(fmt, *ORIGINAL_TARGETS)
    stream.seek(TABLE_OFFSET)
    before = stream.read(len(expected))
    if before != expected:
        raise ValueError("Unexpected European created-hair selector table")
    targets = list(ORIGINAL_TARGETS)
    for hairstyle, target in BASIC_MESHES.items():
        targets[hairstyle + 1] = target
    after = struct.pack(fmt, *targets)
    delta = 0
    for original, replacement in zip(ORIGINAL_TARGETS, targets):
        delta ^= original ^ replacement
    return [(TABLE_OFFSET, before, after)], delta


def load_assets() -> tuple[dict[int, bytes], bytes, dict]:
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"] != 1 or tuple(row["style"] for row in manifest["meshes"]) != CUSTOM_STYLES:
        raise ValueError("Unexpected approved low-detail hair manifest")
    streams = {}
    for row in manifest["meshes"]:
        style = row["style"]
        data = (ASSETS / f"hair{style:02}.vif").read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"Approved hairstyle {style} stream fingerprint differs")
        streams[style] = data
    selector = (ASSETS / "selector.bin").read_bytes()
    if (len(selector) != SELECTOR_SIZE
            or hashlib.sha256(selector).hexdigest() != manifest["selector_sha256"]):
        raise ValueError("Approved created-hair selector fingerprint differs")
    return streams, selector, manifest


def locate_scene(package: bytes) -> int:
    matches = []
    offset = 0
    while offset < len(package):
        if offset + 32 > len(package):
            raise ValueError("Truncated created-head package header")
        kind, stored, system, video, marker, *_ = struct.unpack_from("<4s7I", package, offset)
        end = offset + 32 + stored
        if not stored or end > len(package):
            raise ValueError("Invalid created-head package resource extent")
        if kind == b"SCNE" and marker == 0xFEEDBEEF:
            data = decode(package[offset + 32:end], system + video, collect_tokens=False)[0]
            if object_name(data, system) == "locreatehead":
                matches.append(offset)
        offset = end
    if len(matches) != 1:
        raise ValueError("Expected exactly one locreatehead scene in the package")
    return matches[0]


def replace_scene(package: bytes, streams: dict[int, bytes]) -> tuple[int, bytes, bytes, dict]:
    if tuple(streams) != CUSTOM_STYLES:
        raise ValueError("Expected the complete approved per-style hair mesh set")
    chunk = locate_scene(package)
    kind, stored, system, video, marker, scratch, x1, x2 = struct.unpack_from("<4s7I", package, chunk)
    if video:
        raise ValueError("Unexpected low-head video allocation")
    body = package[chunk + 32:chunk + 32 + stored]
    original = decode(body, system, collect_tokens=False)[0]
    if hashlib.sha256(original).hexdigest() != SCENE_SHA256:
        raise ValueError("Unexpected pristine low-detail head fingerprint")
    root = relative(original, 20, system)
    mesh = relative(original, root + 48, system)
    mats = relative(original, root + 32, system)
    parts = relative(original, mesh + 108, system)
    if (struct.unpack_from("<I", original, root + 28)[0] != 7
            or struct.unpack_from("<I", original, mesh + 104)[0] != 7):
        raise ValueError("Expected seven original low-head materials and parts")
    donor = parts + 4 * 24
    donor_mat = struct.unpack_from("<I", original, donor + 8)[0]
    if text(original, relative(original, mats + donor_mat * 96 + 88, system), system) != "hair03_mat":
        raise ValueError("Unexpected stock long-hair donor")
    target = bytearray(original)

    def append(data: bytes) -> int:
        target.extend(bytes(-len(target) % 16))
        position = len(target)
        target.extend(data)
        return position

    def pointer(field: int, position: int) -> None:
        struct.pack_into("<i", target, field, position - field + 1)

    count = 7 + len(CUSTOM_STYLES)
    donor_material = original[mats + donor_mat * 96:mats + (donor_mat + 1) * 96]
    new_mats = append(original[mats:mats + 7 * 96] + donor_material * len(CUSTOM_STYLES))
    for index in range(7):
        name_offset = relative(original, mats + index * 96 + 88, system)
        name = text(original, name_offset, system)
        if name in ("hair01_mat", "hair02_mat", "hair03_mat"):
            name_offset = append(("lo" + name + "\0").encode("utf-16le"))
        pointer(new_mats + index * 96 + 88, name_offset)
    for index, style in enumerate(CUSTOM_STYLES):
        name_offset = append((f"hair{style - 1:02}_mat\0").encode("utf-16le"))
        material = new_mats + (7 + index) * 96
        pointer(material + 88, name_offset)
        flags = struct.unpack_from("<Q", target, material + 56)[0]
        struct.pack_into("<Q", target, material + 56, flags | 0x80000000)
    new_parts = append(original[parts:parts + 7 * 24] + original[donor:donor + 24] * len(CUSTOM_STYLES))
    for index in range(7):
        pointer(new_parts + index * 24, relative(original, parts + index * 24, system))
    for index, style in enumerate(CUSTOM_STYLES):
        position = append(streams[style])
        record = new_parts + (7 + index) * 24
        pointer(record, position)
        struct.pack_into("<II", target, record + 4, len(streams[style]), 7 + index)
    pointer(root + 32, new_mats)
    pointer(mesh + 108, new_parts)
    struct.pack_into("<I", target, root + 28, count)
    struct.pack_into("<I", target, mesh + 104, count)
    compressed, required = recompress(struct.pack("<I", len(target)) + body[4:9], bytes(target))
    scratch = max(scratch, required)
    validate_inplace(compressed, bytes(target), scratch)
    replacement = struct.pack("<4s7I", kind, len(compressed), len(target), 0, marker, scratch, x1, x2) + compressed
    return chunk, package[chunk:chunk + 32 + stored], replacement, {
        "old_system_bytes": system, "new_system_bytes": len(target),
        "old_stored_bytes": stored, "new_stored_bytes": len(compressed),
        "scratch_bytes": scratch, "material_count": count, "part_count": count,
        "decoded_sha256": hashlib.sha256(target).hexdigest(),
    }


def prepare_custom(stream: BinaryIO) -> tuple[list[tuple[int, bytes, bytes]], int, dict]:
    """Return original-coordinate scene/ELF patches without changing roster bytes."""
    streams, selector, manifest = load_assets()
    stream.seek(SELECTOR_OFFSET)
    before = stream.read(SELECTOR_SIZE)
    if hashlib.sha256(before).hexdigest() != SELECTOR_ORIGINAL_SHA256:
        raise ValueError("Unexpected European created-hair selector code")
    elf_patches = [(SELECTOR_OFFSET, before, selector)]
    for offset, old_pointer, new_pointer in BINDINGS:
        stream.seek(offset)
        before = stream.read(4)
        if before != struct.pack("<I", old_pointer):
            raise ValueError("Unexpected original stock hair material binding")
        elf_patches.append((offset, before, struct.pack("<I", new_pointer)))
    delta = 0
    for _, before, after in elf_patches:
        for old, new in zip(struct.iter_unpack("<I", before), struct.iter_unpack("<I", after)):
            delta ^= old[0] ^ new[0]
    entries = read_archive(stream, verify_hash=False)
    patches, scenes = [], []
    for asset in SCENE_ASSETS:
        offset, package = read_asset(stream, entries, asset)
        chunk, before, after, detail = replace_scene(package, streams)
        patches.append((offset + chunk, before, after))
        scenes.append({"asset": asset, **detail})
    return patches + elf_patches, delta, {
        "mode": "per-style", "elf_crc_delta": delta,
        "stock_styles": {"1": "short", "7": "afro"},
        "meshes": manifest["meshes"], "source_head": manifest["source_head"],
        "approved_iso_sha256": manifest["approved_iso_sha256"], "scenes": scenes,
        "hardware_status": "Reviewed in PCSX2; original hardware not validated",
    }
