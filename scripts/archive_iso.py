"""Repack the native archive inside its existing ISO9660/UDF file extents."""
import bisect
import struct
from typing import BinaryIO

from iso_copy import CopySpan, validate_copy_plan, validate_patches
from patch_lettering_iso import ARCHIVE_BASE

SECTOR = 2048
HEADER_SIZE = 0x9C


def aligned(size: int) -> int:
    return (size + SECTOR - 1) // SECTOR * SECTOR


def plan(stream: BinaryIO, patches: list[tuple[int, bytes, bytes]],
         *, archive_base: int = ARCHIVE_BASE) -> tuple[list[CopySpan], list[tuple[int, bytes, bytes]], dict]:
    """Absorb original-coordinate archive edits, preserving directory ordinals."""
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(archive_base)
    header = stream.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE:
        raise ValueError("Truncated native archive header")
    words = struct.unpack("<39I", header)
    count, strategy, segments = words[:3]
    if (not 0 < count <= 65536 or strategy != 0 or not 1 <= segments <= 32
            or not words[3] or any(words[3 + segments:])
            or any(length != words[3] for length in words[3:2 + segments])
            or not 0 < words[2 + segments] <= words[3]):
        raise ValueError("Unsupported native archive segment layout")
    capacity = sum(words[3:3 + segments]) * SECTOR
    if archive_base < 0 or archive_base + capacity > size:
        raise ValueError("Archive extents exceed the ISO")
    table = stream.read(count * 12)
    if len(table) != count * 12:
        raise ValueError("Truncated native archive directory")
    entries = list(struct.iter_unpack("<III", table))
    minimum = aligned(HEADER_SIZE + len(table))
    previous, hashes = minimum, set()
    for key, length, sector in entries:
        start = sector * SECTOR
        if (key in hashes or length <= 0 or start < previous
                or start + aligned(length) > capacity or length > words[3] * SECTOR):
            raise ValueError("Archive entries must be unique, ordered, bounded sector extents")
        previous = start + aligned(length)
        hashes.add(key)
    starts = [archive_base + sector * SECTOR for _, _, sector in entries]
    grouped, outside = {}, []
    previous = 0
    for offset, before, after in sorted(patches):
        end = offset + len(before)
        if not before or offset < previous or end > size:
            raise ValueError("Original-coordinate edits must be disjoint spans within the ISO")
        previous = end
        if end <= archive_base or offset >= archive_base + capacity:
            outside.append((offset, before, after))
            continue
        ordinal = bisect.bisect_right(starts, offset) - 1
        if ordinal < 0 or end > starts[ordinal] + entries[ordinal][1]:
            raise ValueError("Archive edits must lie entirely inside one indexed asset")
        grouped.setdefault(ordinal, []).append((offset - starts[ordinal], before, after))
    validate_patches(outside, size)
    cursor = entries[0][2] * SECTOR
    old_used = cursor + sum(aligned(entry[1]) for entry in entries)
    writes, records, new_table = [], [], bytearray()
    for ordinal, (key, old_size, old_sector) in enumerate(entries):
        source = starts[ordinal]
        changed = ordinal in grouped
        if changed:
            stream.seek(source)
            original = stream.read(old_size)
            if len(original) != old_size:
                raise ValueError("Truncated archive asset")
            parts, position = [], 0
            for offset, before, after in grouped[ordinal]:
                if original[offset:offset + len(before)] != before:
                    raise ValueError(f"Archive source edit bytes changed in {key:08x}")
                parts.extend((original[position:offset], after))
                position = offset + len(before)
            parts.append(original[position:])
            data = b"".join(parts)
            length = len(data)
        else:
            data, length = None, old_size
        allocated = aligned(length)
        if not length or length > words[3] * SECTOR or cursor + allocated > capacity:
            raise ValueError(f"Archive capacity exceeded by asset {key:08x}; need more sector savings")
        new_table.extend(struct.pack("<III", key, length, cursor // SECTOR))
        target = archive_base + cursor
        if changed:
            writes.append(CopySpan(target, length, data=data))
            if allocated > length:
                writes.append(CopySpan(target + length, allocated - length))
        else:
            writes.append(CopySpan(target, allocated, source_offset=source))
        records.append({
            "asset_hash": f"{key:08x}", "old_size": old_size, "size": length,
            "old_sector": old_sector, "sector": cursor // SECTOR, "changed": changed,
        })
        cursor += allocated
    prefix_end = archive_base + HEADER_SIZE
    table_end = prefix_end + len(table)
    copy_plan = [CopySpan(0, prefix_end, source_offset=0),
                 CopySpan(prefix_end, len(new_table), data=bytes(new_table))]
    if table_end < archive_base + entries[0][2] * SECTOR:
        copy_plan.append(CopySpan(table_end, archive_base + entries[0][2] * SECTOR - table_end,
                                  source_offset=table_end))
    copy_plan.extend(writes)
    if cursor < capacity:
        copy_plan.append(CopySpan(archive_base + cursor, capacity - cursor,
                                  source_offset=archive_base + cursor))
    if archive_base + capacity < size:
        copy_plan.append(CopySpan(archive_base + capacity, size - archive_base - capacity,
                                  source_offset=archive_base + capacity))
    validate_copy_plan(copy_plan, size)
    return copy_plan, outside, {
        "capacity_bytes": capacity, "used_bytes": cursor, "free_bytes": capacity - cursor,
        "previous_used_bytes": old_used, "sector_savings_bytes": old_used - cursor,
        "changed_assets": len(grouped),
        "relocated_assets": sum(row["sector"] != row["old_sector"] for row in records),
        "directory_order_preserved": True, "filesystem_extents_preserved": True,
        "entries": records,
    }
