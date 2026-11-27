"""Verified stock low-detail hairstyle selection for the European executable."""
import struct
from typing import BinaryIO

from roster_stats import ELF_ISO_OFFSET

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
