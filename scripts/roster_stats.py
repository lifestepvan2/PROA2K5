"""Verified sparse season-history codec and fixed-size roster-pool repacking."""
import re
import struct

PLAYER_BASE, PLAYER_STRIDE, PLAYER_COUNT = 0x64F4, 0x94, 792
HISTORY_POINTER, YEARS_PRO = 0x90, 0x41
POOL_START, POOL_END = 0x26174, 0x50DC4
POOL_COUNT_FIELD, POOL_POINTER_FIELD = 0xA0, 0xA4
FIELDS = ("GP", "GS", "MIN", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA",
          "OREB", "DREB", "STL", "BLK", "FLS", "AST", "TO", "PTS")
YEAR_ISO_OFFSET = 0x284F18
ELF_ISO_OFFSET, CRC_PADDING_OFFSET = 0x90000, 0xFC


def prepare_year_patch(stream, year, elf_delta=0):
    """Only the verified Europe player-card label instruction; never the game calendar."""
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 9999:
        raise ValueError("Stats label year must be an integer in 1900..9999")
    if isinstance(elf_delta, bool) or not isinstance(elf_delta, int) or not 0 <= elf_delta <= 0xFFFFFFFF:
        raise ValueError("Additional ELF CRC delta must be a uint32")
    stream.seek(ELF_ISO_OFFSET)
    header = stream.read(0x100)
    if (header[:7] != b"\x7fELF\x01\x01\x01" or len(header) != 0x100
            or struct.unpack_from("<I", header, 28)[0] != 0x34
            or struct.unpack_from("<HH", header, 42) != (32, 6)
            or any(header[0xF4:0x100])):
        raise ValueError("Unexpected European ELF header/padding")
    for pos in range(0x34, 0xF4, 32):
        kind, offset, _, _, size, _, _, _ = struct.unpack_from("<8I", header, pos)
        if kind != 1 or offset < 0x100:
            raise ValueError("CRC compensation padding may be loaded by the ELF")
    stream.seek(YEAR_ISO_OFFSET - 8)
    expected = struct.pack("<8I", 0x0C06C360, 0, 0x2603F822, 0x1220000A,
                           0x00431023, 0x3C1000A5, 0x3C050078, 0xAFA20000)
    if stream.read(len(expected)) != expected:
        raise ValueError("Unexpected European player-card year-rendering code")
    before = struct.pack("<I", 0x2603F822)
    after = struct.pack("<I", 0x26030000 | (-(year + 10) & 0xFFFF))
    delta = int.from_bytes(before, "little") ^ int.from_bytes(after, "little") ^ elf_delta
    # PCSX2 identifies games by XOR of ELF words. Compensate in the verified
    # nonloaded header padding so existing texture and per-game settings still apply.
    patches = [(YEAR_ISO_OFFSET, before, after)] if before != after else []
    if delta:
        patches.append((ELF_ISO_OFFSET + CRC_PADDING_OFFSET, bytes(4), struct.pack("<I", delta)))
    return patches, {
        "label_anchor": year, "ee_address": "0x2f4e18", "iso_offset": hex(YEAR_ISO_OFFSET),
        "original": before.hex(), "replacement": after.hex(),
        "pcsx2_crc_preserved": True,
        "crc_padding_iso_offset": hex(ELF_ISO_OFFSET + CRC_PADDING_OFFSET),
        "crc_padding_replacement": struct.pack("<I", delta).hex(),
        "additional_elf_crc_delta": elf_delta,
        "scope": "player-card season labels only; calendar and birth dates unchanged",
    }


def decode_stream(data, offset, limit=POOL_END):
    if offset % 4 or not POOL_START <= offset < limit <= len(data):
        raise ValueError(f"Invalid history pointer {offset:#x}")
    entries = []
    for pos in range(offset, limit, 4):
        value, key = struct.unpack_from("<HH", data, pos)
        entries.append((value, key))
        if key & 0x8000:
            return entries, pos + 4
    raise ValueError(f"Unterminated player history at {offset:#x}")


def encode_history(history, anchor):
    """Season names use start years. Omitted seasons retain ordinal gaps; GS may be unknown."""
    seasons = {}
    for label, row in history["seasons"].items():
        match = re.fullmatch(r"(\d{4})_(\d{4})", label)
        if not match or int(match[2]) != int(match[1]) + 1:
            raise ValueError(f"Invalid history season {label!r}")
        year = int(match[1])
        if year > anchor:
            raise ValueError(f"Season {label} is newer than label anchor {anchor}")
        seasons[year] = row["totals"]
    if not seasons:
        return b"", 1, []
    first = min(seasons)
    span = anchor - first + 1
    if span > 127:
        raise ValueError(f"Season span {span} exceeds the supported history-key range")
    entries, unknown = [], []
    for year in range(first, anchor + 1):
        ordinal = year - first + 1
        totals = seasons.get(year)
        if totals is None:
            # GP=0 makes the game skip this row while preserving later ordinals.
            entries.append((0, ordinal << 7))
            continue
        for field, name in enumerate(FIELDS):
            if name == "MIN":
                seconds = totals.get("SEC")
                if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
                    raise ValueError(f"{year}: invalid SEC {seconds!r}")
                value = (seconds + 30) // 60
            else:
                value = totals.get(name)
            if value is None and name in ("GS", "FLS"):
                unknown.append(f"{year}: {name} unavailable (omitted in game)")
                continue
            if (isinstance(value, bool) or not isinstance(value, int)
                    or not 0 <= value <= 65535):
                raise ValueError(f"{year}: {name} cannot fit uint16: {value!r}")
            if value or name == "GP":
                entries.append((value, ordinal << 7 | field))
        rebounds = totals["OREB"] + totals["DREB"]
        if totals.get("REB") != rebounds:
            unknown.append(f"{year}: published REB={totals.get('REB')}; game derives "
                           f"REB={rebounds} from preserved OREB+DREB")
    value, key = entries[-1]
    entries[-1] = value, key | 0x8000
    return b"".join(struct.pack("<HH", *entry) for entry in entries), span, unknown


def repack(data, replacements):
    """{record: (encoded_history, display_span)}. Untouched streams retain every source byte."""
    if len(data) < POOL_END:
        raise ValueError("Roster payload is too small for the verified stats pool")
    count = struct.unpack_from("<I", data, POOL_COUNT_FIELD)[0]
    base_pointer = struct.unpack_from("<i", data, POOL_POINTER_FIELD)[0]
    if not base_pointer & 1 or POOL_POINTER_FIELD + base_pointer - 1 != POOL_START:
        raise ValueError("Unexpected global stats-pool pointer")
    logical_end = POOL_START + count * 4
    if logical_end > POOL_END:
        raise ValueError("Global history entry count exceeds the fixed stats pool")
    streams, extents = {}, {}
    for record in range(PLAYER_COUNT):
        field = PLAYER_BASE + record * PLAYER_STRIDE + HISTORY_POINTER
        pointer = struct.unpack_from("<i", data, field)[0]
        if not pointer:
            streams[record] = b""
            continue
        if not pointer & 1:
            raise ValueError(f"Record {record}: history pointer is not tagged")
        target = field + pointer - 1
        _, end = decode_stream(data, target, logical_end)
        streams[record] = bytes(data[target:end])
        extents[target] = end
    previous = POOL_START
    for start, end in sorted(extents.items()):
        if start < previous or any(data[previous:start]):
            raise ValueError("Stats pool contains overlapping histories or unowned nonzero data")
        previous = end
    if any(data[previous:POOL_END]):
        raise ValueError("Stats pool has unowned trailing nonzero data")
    if sum(end - start for start, end in extents.items()) != count * 4:
        raise ValueError("Global history entry count does not match referenced streams")
    for record, (encoded, span) in replacements.items():
        if not 0 <= record < PLAYER_COUNT or not 1 <= span <= 127:
            raise ValueError(f"Invalid stats replacement record/span: {record}/{span}")
        if encoded:
            if len(encoded) % 4 or not int.from_bytes(encoded[-2:], "little") & 0x8000:
                raise ValueError(f"Record {record}: malformed encoded history")
            if any(struct.unpack_from("<H", encoded, pos)[0] & 0x8000
                   for pos in range(2, len(encoded) - 2, 4)):
                raise ValueError(f"Record {record}: history terminates before its final entry")
        streams[record] = encoded
    required = sum(map(len, streams.values()))
    if required > POOL_END - POOL_START:
        raise ValueError(f"Stats pool exhausted: need {required} B, capacity {POOL_END - POOL_START} B")
    result = bytearray(data)
    result[POOL_START:POOL_END] = bytes(POOL_END - POOL_START)
    struct.pack_into("<I", result, POOL_COUNT_FIELD, required // 4)
    cursor = POOL_START
    for record, encoded in streams.items():
        field = PLAYER_BASE + record * PLAYER_STRIDE + HISTORY_POINTER
        pointer = cursor - field + 1 if encoded else 0
        struct.pack_into("<i", result, field, pointer)
        result[cursor:cursor + len(encoded)] = encoded
        cursor += len(encoded)
        if record in replacements:
            result[field - HISTORY_POINTER + YEARS_PRO] = replacements[record][1]
    return result, {"players": len(replacements), "used_bytes": required,
                    "capacity_bytes": POOL_END - POOL_START, "free_bytes": POOL_END - cursor}
