"""Translate the verified Europe disc roster to/from the existing save-layout builder."""
import struct
from pathlib import Path
from typing import BinaryIO

from inventory_lettering_iso import asset_hash
from patch_lettering_iso import digest
from player_texture_iso import read_archive, read_asset
from roster_stats import repack

ASSET = "roster.iff"
ISO_OFFSET, DISC_SIZE = 0xBCB800, 0x87340
DISC_SHA256 = "bb87308ff4136a5fc8a1f4b495b9ad5ff5ea531f1ac4f8030422cc26bcb2b5b6"
NAME_SIZE = 0x20
CONTENT_END = DISC_SIZE - NAME_SIZE
CARD_SIZE = 0xB1040
POOL_MIN = 0x675DC
HISTORY_INIT_OFFSET = 0x140934
HISTORY_INIT_CONTEXT = bytes.fromhex(
    "64c3060c00000000a6d7060c00000000e2aa060c00000000aec0060c00000000"
    "98e9050c000000008700023c01000424dce6422409000324"
)


def history_initialization_patch(stream: BinaryIO) -> tuple[int, bytes, bytes]:
    stream.seek(HISTORY_INIT_OFFSET - 0x20)
    if stream.read(len(HISTORY_INIT_CONTEXT)) != HISTORY_INIT_CONTEXT:
        raise ValueError("Unexpected default-roster history initialization code")
    # Skip only the startup call that deletes the current season. The same
    # routine's franchise/season-rollover callers remain unchanged.
    return HISTORY_INIT_OFFSET, struct.pack("<I", 0x0C05E998), bytes(4)


def read_source(stream: BinaryIO) -> bytes:
    entries = read_archive(stream)
    if entries.get(asset_hash(ASSET)) != (ISO_OFFSET, DISC_SIZE):
        raise ValueError("Unexpected Europe roster archive entry")
    _, data = read_asset(stream, entries, ASSET)
    if digest(data) != DISC_SHA256:
        raise ValueError("Pristine disc roster fingerprint differs")
    return data


def baseline(disc: bytes) -> bytes:
    if len(disc) != DISC_SIZE or digest(disc) != DISC_SHA256:
        raise ValueError("Expected the verified pristine Europe roster.iff")
    # Only the named resource's prologue differs. Relative pointers remain valid
    # because every table and string moves together by exactly 32 bytes.
    data = bytearray(disc[:0x40] + disc[0x60:])
    data.extend(bytes(CARD_SIZE - len(data)))
    # The card loader uses +0x0C as the descriptor/data copy length, unlike the
    # generic disc resource header. +0x08 is an optional auxiliary snapshot.
    struct.pack_into("<III", data, 4, CARD_SIZE - 0x20, 0, CONTENT_END - 0x40)
    struct.pack_into("<II", data, 0x30, 0, 0xD)
    validate_payload(data)
    return bytes(data)


def validate_payload(data: bytes | bytearray) -> None:
    if (len(data) != CARD_SIZE or data[:4] != b"ROST" or data[0x2C:0x30] != b"ROST"
            or struct.unpack_from("<I", data, 4)[0] != CARD_SIZE - 0x20
            or struct.unpack_from("<II", data, 8) != (0, CONTENT_END - 0x40)
            or struct.unpack_from("<II", data, 0x30) != (0, 0xD)):
        raise ValueError("Expected a complete, unnamed roster-save payload")
    if any(data[CONTENT_END:]):
        raise ValueError("Roster exceeds the fixed disc resource; no ISO or card was published")

    def target(field: int) -> int:
        value = struct.unpack_from("<i", data, field)[0]
        if not value & 1:
            raise ValueError(f"Untagged roster pointer at {field:#x}")
        return field + value - 1

    for field, count, base in ((0x40, 792, 0x64F4), (0x48, 20, 0x22ED4),
                               (0x50, 86, 0xC8), (0x58, 54, 0x11F0),
                               (0x60, 457, 0x4F88)):
        if struct.unpack_from("<I", data, field)[0] != count or target(field + 4) != base:
            raise ValueError(f"Unsupported roster table descriptor at {field:#x}")

    def string(field: int) -> None:
        start = target(field)
        if start % 2 or not POOL_MIN <= start < CONTENT_END - 1:
            raise ValueError(f"Roster string pointer outside disc storage at {field:#x}")
        end = start
        while end + 2 <= CONTENT_END and data[end:end + 2] != b"\0\0":
            end += 2
        if end + 2 > CONTENT_END:
            raise ValueError(f"Unterminated roster string at {field:#x}")
        bytes(data[start:end]).decode("utf-16le")

    for row in range(0x4F88, 0x64F4, 12):
        string(row)
    for record in range(812):
        row = 0x64F4 + record * 0x94
        college = target(row)
        if not 0x4F88 <= college < 0x64F4 or (college - 0x4F88) % 12:
            raise ValueError(f"Invalid college row for roster record {record}")
        for offset in (0xC, 0x10, 0x24, 0x28):
            string(row + offset)
    for row in range(0x11F0, 0x11F0 + 54 * 0x124, 0x124):
        for offset in (0x48, 0x4C, 0x74, 0x7C):
            string(row + offset)
    for row in range(0xC8, 0xC8 + 86 * 0x30, 0x30):
        for offset in (0, 8, 0xC):
            string(row + offset)
    repack(data, {})


def encode(disc: bytes, payload: bytes) -> bytes:
    if len(disc) != DISC_SIZE or digest(disc) != DISC_SHA256:
        raise ValueError("Expected the verified pristine Europe roster.iff")
    validate_payload(payload)
    result = disc[:0x60] + payload[0x40:CONTENT_END]
    if len(result) != DISC_SIZE:
        raise ValueError("Disc roster size changed")
    return result


def prepare(stream: BinaryIO, payload: Path | None = None) -> tuple[list[tuple[int, bytes, bytes]], dict]:
    original = read_source(stream)
    base = baseline(original)
    initialization = history_initialization_patch(stream)
    report = {
        "asset": ASSET, "iso_offset": ISO_OFFSET, "disc_size": DISC_SIZE,
        "baseline_sha256": digest(base), "original_sha256": DISC_SHA256,
        "card_size": CARD_SIZE, "content_end": CONTENT_END,
        "history_initialization": {
            "iso_offset": initialization[0], "original": initialization[1].hex(),
            "replacement": initialization[2].hex(),
            "scope": "Preserve embedded current-season histories during default-roster startup only",
        },
    }
    if payload is None:
        return [], report
    data = payload.read_bytes()
    replacement = encode(original, data)
    report.update({
        "payload_sha256": digest(data), "patched_sha256": digest(replacement),
        "changed_bytes": sum(a != b for a, b in zip(original, replacement)),
        "elf_crc_delta": int.from_bytes(initialization[1], "little"),
    })
    patches = [(ISO_OFFSET, original, replacement)] if original != replacement else []
    return [*patches, initialization], report
