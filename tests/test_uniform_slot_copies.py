import io
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import uniform_slot_copies as copies
from inventory_lettering_iso import asset_hash


def resource(name, value, kind=b"TXTR"):
    body = bytearray(80)
    body[12:16] = kind
    struct.pack_into("<i", body, 16, 17)
    encoded = (name + "\0").encode("utf-16le")
    body[32:32 + len(encoded)] = encoded
    body[64:] = bytes([value]) * 16
    return struct.pack("<4s7I", kind, len(body), 64, 16, 0, 0, 0, 0) + body


def metrics(value):
    return struct.pack("<4s7I", b"NAME", 16, 0, 0, 0, 0, 0, 0) + bytes([value]) * 16


def package(value, preview=False):
    if preview:
        return (resource("numbers", value) + metrics(value)
                + resource("unif", value) + resource("unidata", value, b"UnAD"))
    return (resource("coachhead", value) + resource("logo", value)
            + resource("names", value, b"HITX") + metrics(value)
            + resource("numbers", value, b"HITX") + metrics(value)
            + resource("unif", value) + resource("short", value)
            + resource("unidata", value, b"UnAD") + resource("band0", value))


class UniformSlotCopyTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.donor = package(10)
        self.target = package(20)
        self.preview_donor = package(30, True)
        self.preview_target = package(40, True)
        self.entries = {}
        self.source = io.BytesIO(bytes(32768))
        for index, (name, data) in enumerate((
                ("ua021.iff", self.donor), ("r2h021.iff", self.target),
                ("selua021.iff", self.preview_donor), ("selr2h021.iff", self.preview_target))):
            offset = 2048 * (index + 1)
            self.source.seek(offset)
            self.source.write(data)
            self.entries[asset_hash(name)] = (offset, len(data))
        patch.object(copies, "read_archive", return_value=self.entries).start()
        self.rules = [
            copies.UniformCopy(21, "Falcons", "ua021.iff", "r2h021.iff"),
            copies.UniformCopy(21, "Falcons", "selua021.iff", "selr2h021.iff"),
        ]

    def test_copies_final_donor_art_metrics_and_attributes_but_preserves_siblings(self):
        # A resized donor resource must be copied after its header/body edits are composed.
        original_chunk = resource("unif", 10)
        edited_chunk = original_chunk + bytes(16)
        edited_chunk = bytearray(edited_chunk)
        struct.pack_into("<I", edited_chunk, 4, len(edited_chunk) - 32)
        local = self.donor.index(original_chunk)
        donor_offset = self.entries[asset_hash("ua021.iff")][0]
        target_offset = self.entries[asset_hash("r2h021.iff")][0]
        original_band = resource("band0", 20)
        edited_band = resource("band0", 99)
        band_local = self.target.index(original_band)
        patches = [
            (donor_offset + local, original_chunk, bytes(edited_chunk)),
            (target_offset + band_local, original_band, edited_band),
            (0, b"\0", b"X"),
        ]
        result, reports = copies.compose(self.source, patches, self.rules)
        updated = next(after for offset, _, after in result if offset == target_offset)
        self.assertIn(bytes(edited_chunk), updated)
        self.assertIn(edited_band, updated)
        self.assertIn(resource("coachhead", 20), updated)
        self.assertNotIn(resource("coachhead", 10), updated)
        for name in ("names", "numbers"):
            self.assertIn(resource(name, 10, b"HITX") + metrics(10), updated)
        self.assertIn(resource("unidata", 10, b"UnAD"), updated)
        preview_offset = self.entries[asset_hash("selr2h021.iff")][0]
        self.assertEqual(next(after for offset, _, after in result if offset == preview_offset),
                         self.preview_donor)
        self.assertIn(patches[0], result)
        self.assertIn(patches[2], result)
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0]["destination_hash"], f'{asset_hash("r2h021.iff"):08x}')

    def test_rejects_mismatched_source_bytes_and_missing_glyph_metrics(self):
        offset = self.entries[asset_hash("ua021.iff")][0]
        with self.assertRaisesRegex(ValueError, "source edit bytes"):
            copies.compose(self.source, [(offset, b"wrong", b"other")], self.rules)
        with self.assertRaisesRegex(ValueError, "resource set"):
            copies.chunks(self.target.replace(metrics(20), b"", 1), False)

    def test_inherited_offsets_exclude_coach_and_bands(self):
        offsets = copies.inherited_offsets(self.source, self.rules)
        target_offset = self.entries[asset_hash("r2h021.iff")][0]
        self.assertNotIn(target_offset + 32, offsets)
        self.assertNotIn(target_offset + self.target.index(resource("band0", 20)) + 32, offsets)
        self.assertIn(target_offset + self.target.index(resource("short", 20)) + 32, offsets)
        self.assertEqual(len(offsets), 12)

    def test_rules_use_table_side_for_secondary_and_native_team_ids_for_donors(self):
        rows = [
            copies.UniformSlot(29, False, "uh029"),
            copies.UniformSlot(29, True, "ua029"),
            copies.UniformSlot(29, False, "ux029"),
            copies.UniformSlot(29, True, "r1a029"),
            copies.UniformSlot(1, False, "uh001"),
            copies.UniformSlot(1, True, "ua001"),
            copies.UniformSlot(1, False, "r1h001"),
        ]
        entries = {asset_hash(prefix + name + ".iff"): (0, 1)
                   for prefix in ("", "sel") for name in ("uh029", "ua029", "ux029", "r1a029")}
        with patch.object(copies.roster_iso, "read_source", return_value=b""), \
                patch.object(copies.roster_iso, "baseline", return_value=b""), \
                patch.object(copies, "uniform_slots", return_value=rows), \
                patch.object(copies, "assignments", return_value={"28": "Heidelberg"}), \
                patch.object(copies, "read_archive", return_value=entries):
            result = copies.rules(self.source)
        self.assertEqual([(row.donor, row.destination) for row in result], [
            ("ua029.iff", "ux029.iff"), ("selua029.iff", "selux029.iff"),
            ("uh029.iff", "r1a029.iff"), ("seluh029.iff", "selr1a029.iff"),
        ])
        self.assertTrue(all(row.slot == 28 for row in result))

    def test_missing_preview_fails_instead_of_silently_skipping_an_alternate(self):
        rows = [copies.UniformSlot(21, True, "ua021"), copies.UniformSlot(21, False, "r2h021")]
        self.entries.pop(asset_hash("selr2h021.iff"))
        with patch.object(copies.roster_iso, "read_source", return_value=b""), \
                patch.object(copies.roster_iso, "baseline", return_value=b""), \
                patch.object(copies, "uniform_slots", return_value=rows), \
                patch.object(copies, "assignments", return_value={"21": "Falcons"}):
            with self.assertRaisesRegex(ValueError, "game/preview"):
                copies.rules(self.source)


if __name__ == "__main__":
    unittest.main()
