import io
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import roster_stats as stats


def history(*years):
    totals = dict.fromkeys(stats.FIELDS, 0)
    totals.update(GP=10, GS=None, SEC=6030, PTS=30, FGM=12, FGA=20, REB=0)
    return {"seasons": {f"{y}_{y+1}": {"totals": totals.copy()} for y in years}}


def fixture():
    data = bytearray(stats.POOL_END + 20)
    original = struct.pack("<4H", 10, 0x80, 400, 0x8091)
    struct.pack_into("<I", data, stats.POOL_COUNT_FIELD, len(original) // 4)
    struct.pack_into("<i", data, stats.POOL_POINTER_FIELD, stats.POOL_START - stats.POOL_POINTER_FIELD + 1)
    data[stats.POOL_START:stats.POOL_START + len(original)] = original
    field = stats.PLAYER_BASE + stats.HISTORY_POINTER
    struct.pack_into("<i", data, field, stats.POOL_START - field + 1)
    return data, original


class RosterStatsTests(unittest.TestCase):
    def test_known_tayshaun_prince_season_matches_screenshot(self):
        values = (42, 5, 435, 53, 118, 20, 47, 11, 17, 5, 40, 10, 14, 25, 24, 21, 137)
        row = dict(zip(stats.FIELDS, values))
        row["REB"] = row["OREB"] + row["DREB"]
        row["SEC"] = 435 * 60
        encoded, span, warnings = stats.encode_history({"seasons": {"2026_2027": {"totals": row}}}, 2026)
        data = bytearray(stats.POOL_END)
        data[stats.POOL_START:stats.POOL_START + len(encoded)] = encoded
        entries, end = stats.decode_stream(data, stats.POOL_START)
        self.assertEqual([v for v, key in entries], list(values))
        self.assertEqual(entries[-1][1], 0x8090)
        self.assertAlmostEqual(row["PTS"] / row["GP"], 3.3, delta=0.05)
        self.assertEqual((span, warnings), (1, []))

    def test_gap_ordinals_and_unknown_gs(self):
        encoded, span, warnings = stats.encode_history(history(2024, 2026), 2026)
        entries = list(struct.iter_unpack("<HH", encoded))
        self.assertIn((0, 2 << 7), entries)
        self.assertEqual(span, 3)
        self.assertTrue(entries[-1][1] & 0x8000)
        self.assertFalse(any((key & 127) == 1 for value, key in entries))
        self.assertEqual(len(warnings), 2)

    def test_minute_rounding_and_zero_future_slot(self):
        encoded, span, _ = stats.encode_history(history(2025), 2026)
        entries = list(struct.iter_unpack("<HH", encoded))
        self.assertIn((101, 0x82), entries)
        self.assertEqual(entries[-1], (0, 0x8100))
        self.assertEqual(span, 2)

    def test_source_rebound_difference_does_not_change_components(self):
        h = history(2026)
        h["seasons"]["2026_2027"]["totals"].update(OREB=26, DREB=72, REB=99)
        encoded, _, warnings = stats.encode_history(h, 2026)
        entries = dict((key & 127, value) for value, key in struct.iter_unpack("<HH", encoded))
        self.assertEqual((entries[9], entries[10]), (26, 72))
        self.assertTrue(any("game derives REB=98" in w for w in warnings))

    def test_invalid_counts_years_and_span_are_not_clipped(self):
        for key, value in (("PTS", 65536), ("GP", -1), ("FGM", 1.5), ("SEC", None)):
            h = history(2026)
            h["seasons"]["2026_2027"]["totals"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                stats.encode_history(h, 2026)
        for h in (history(2027), history(1800), {"seasons": {"2026_2028": {"totals": {}}}}):
            with self.assertRaises(ValueError):
                stats.encode_history(h, 2026)

    def test_repack_preserves_unknown_original_fields_and_size(self):
        data, original = fixture()
        encoded, span, _ = stats.encode_history(history(2026), 2026)
        result, report = stats.repack(data, {1: (encoded, span)})
        self.assertEqual(result[stats.POOL_START:stats.POOL_START + len(original)], original)
        self.assertEqual(len(result), len(data))
        field = stats.PLAYER_BASE + stats.PLAYER_STRIDE + stats.HISTORY_POINTER
        target = field + struct.unpack_from("<i", result, field)[0] - 1
        self.assertEqual(result[target:target + len(encoded)], encoded)
        self.assertEqual(report["players"], 1)
        self.assertEqual(struct.unpack_from("<I", result, stats.POOL_COUNT_FIELD)[0],
                         (len(original) + len(encoded)) // 4)
        self.assertEqual(data, fixture()[0])
        self.assertEqual(result[stats.POOL_END:], data[stats.POOL_END:])

    def test_repeated_repack_is_identical(self):
        data, _ = fixture()
        encoded, span, _ = stats.encode_history(history(2026), 2026)
        once, _ = stats.repack(data, {1: (encoded, span)})
        twice, _ = stats.repack(once, {1: (encoded, span)})
        self.assertEqual(once, twice)

    def test_no_games_replaces_inherited_stats_with_null_pointer(self):
        data, _ = fixture()
        encoded, span, _ = stats.encode_history({"seasons": {}}, 2026)
        result, _ = stats.repack(data, {0: (encoded, span)})
        field = stats.PLAYER_BASE + stats.HISTORY_POINTER
        self.assertEqual(struct.unpack_from("<I", result, field)[0], 0)

    def test_corruption_overlap_and_capacity_fail_without_mutation(self):
        for mode in ("pointer", "terminator", "unowned", "overlap", "capacity", "count"):
            data, original = fixture()
            replacements = {}
            field = stats.PLAYER_BASE + stats.HISTORY_POINTER
            if mode == "pointer":
                struct.pack_into("<i", data, field, 2)
            elif mode == "terminator":
                data[stats.POOL_START + 7] &= 127
            elif mode == "unowned":
                data[stats.POOL_END - 1] = 1
            elif mode == "overlap":
                field += stats.PLAYER_STRIDE
                struct.pack_into("<i", data, field, stats.POOL_START + 4 - field + 1)
            elif mode == "capacity":
                huge = struct.pack("<HH", 0, 0x80) * ((stats.POOL_END - stats.POOL_START) // 4)
                huge = huge[:-2] + b"\x80\x80"
                replacements = {1: (huge, 1)}
            else:
                struct.pack_into("<I", data, stats.POOL_COUNT_FIELD, 1)
            before = bytes(data)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                stats.repack(data, replacements)
            self.assertEqual(data, before)

    def test_year_patch_only_changes_exact_label_instruction(self):
        data = bytearray(stats.YEAR_ISO_OFFSET + 32)
        base = stats.ELF_ISO_OFFSET
        data[base:base + 7] = b"\x7fELF\x01\x01\x01"
        struct.pack_into("<I", data, base + 28, 0x34)
        struct.pack_into("<HH", data, base + 42, 32, 6)
        for pos in range(0x34, 0xF4, 32):
            struct.pack_into("<8I", data, base + pos, 1, 0x100, 0, 0, 0, 0, 0, 0)
        data[stats.YEAR_ISO_OFFSET - 8:stats.YEAR_ISO_OFFSET + 24] = struct.pack(
            "<8I", 0x0C06C360, 0, 0x2603F822, 0x1220000A,
            0x00431023, 0x3C1000A5, 0x3C050078, 0xAFA20000)
        patches, report = stats.prepare_year_patch(io.BytesIO(data), 2026)
        offset, before, after = patches[0]
        self.assertEqual(offset, stats.YEAR_ISO_OFFSET)
        self.assertEqual(int.from_bytes(after, "little"), 0x2603F80C)
        self.assertEqual(before, data[offset:offset + 4])
        self.assertEqual(report["label_anchor"], 2026)
        original_crc = 0
        for offset, before, after in patches:
            original_crc ^= int.from_bytes(before, "little") ^ int.from_bytes(after, "little")
        self.assertEqual(original_crc, 0)
        self.assertEqual(stats.prepare_year_patch(io.BytesIO(data), 2004)[0], [])
        for year in (2004, 2026):
            additional = 0x0C05E998
            combined, _ = stats.prepare_year_patch(io.BytesIO(data), year, additional)
            delta = additional
            for _, before, after in combined:
                delta ^= int.from_bytes(before, "little") ^ int.from_bytes(after, "little")
            self.assertEqual(delta, 0)
        for invalid in (-1, 0x100000000, True, 1.5):
            with self.assertRaises(ValueError):
                stats.prepare_year_patch(io.BytesIO(data), 2026, invalid)
        for year in (True, 1800, 10000, 2026.5):
            with self.assertRaises(ValueError):
                stats.prepare_year_patch(io.BytesIO(data), year)
        data[stats.YEAR_ISO_OFFSET] ^= 1
        with self.assertRaises(ValueError):
            stats.prepare_year_patch(io.BytesIO(data), 2026)


if __name__ == "__main__":
    unittest.main()
