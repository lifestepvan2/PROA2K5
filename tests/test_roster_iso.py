import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import roster_iso as roster
from inventory_lettering_iso import asset_hash
from patch_lettering_iso import digest


def fixture():
    data = bytearray(roster.CARD_SIZE)
    data[:4] = data[0x2C:0x30] = b"ROST"
    struct.pack_into("<III", data, 4, roster.CARD_SIZE - 32, 0, roster.CONTENT_END - 0x40)
    struct.pack_into("<II", data, 0x30, 0, 0xD)

    def pointer(field, target):
        struct.pack_into("<i", data, field, target - field + 1)

    for field, count, base in ((0x40, 792, 0x64F4), (0x48, 20, 0x22ED4),
                               (0x50, 86, 0xC8), (0x58, 54, 0x11F0),
                               (0x60, 457, 0x4F88)):
        struct.pack_into("<I", data, field, count)
        pointer(field + 4, base)
    pointer(0xA4, 0x26174)
    text = "Original\0".encode("utf-16le")
    data[roster.POOL_MIN:roster.POOL_MIN + len(text)] = text
    for row in range(0x4F88, 0x64F4, 12):
        pointer(row, roster.POOL_MIN)
    for record in range(812):
        row = 0x64F4 + record * 0x94
        pointer(row, 0x4F88)
        for offset in (0xC, 0x10, 0x24, 0x28):
            pointer(row + offset, roster.POOL_MIN)
    for row in range(0x11F0, 0x11F0 + 54 * 0x124, 0x124):
        for offset in (0x48, 0x4C, 0x74, 0x7C):
            pointer(row + offset, roster.POOL_MIN)
    for row in range(0xC8, 0xC8 + 86 * 0x30, 0x30):
        for offset in (0, 8, 0xC):
            pointer(row + offset, roster.POOL_MIN)
    disc = bytearray(data[:0x40])
    disc.extend("roster\0".encode("utf-16le").ljust(32, b"\0"))
    disc.extend(data[0x40:roster.CONTENT_END])
    struct.pack_into("<III", disc, 4, roster.DISC_SIZE - 32, roster.DISC_SIZE - 32, 0)
    struct.pack_into("<II", disc, 0x30, 0x11, 0x2D)
    return bytes(disc), bytes(data)


class RosterIsoTests(unittest.TestCase):
    def setUp(self):
        self.disc, self.payload = fixture()
        self.fingerprint = patch.object(roster, "DISC_SHA256", digest(self.disc))
        self.fingerprint.start()
        self.addCleanup(self.fingerprint.stop)

    def test_disc_save_roundtrip_preserves_every_native_byte(self):
        self.assertEqual(roster.baseline(self.disc), self.payload)
        self.assertEqual(roster.encode(self.disc, self.payload), self.disc)
        self.assertEqual(len(self.payload), 0xB1040)
        self.assertEqual(len(self.disc), 0x87340)

    def test_edited_content_maps_exactly_and_keeps_native_prologue(self):
        data = bytearray(self.payload)
        data[roster.POOL_MIN:roster.POOL_MIN + 18] = "Modified\0".encode("utf-16le")
        for offset, value in ((4, 235), (6, 235), (0x16, 9), (0x45, 99), (0x58, 77), (0x75, 7)):
            struct.pack_into("<H" if offset in (4, 6) else "<B", data, 0x64F4 + offset, value)
        data[0x11F0 + 0x62:0x11F0 + 0x65] = b"\x11\x22\x33"
        result = roster.encode(self.disc, bytes(data))
        self.assertEqual(result[:0x60], self.disc[:0x60])
        self.assertEqual(result[0x60:], data[0x40:roster.CONTENT_END])
        self.assertEqual(len(result), len(self.disc))

    def test_bad_fingerprint_or_truncated_source_is_rejected(self):
        for data in (self.disc[:-1], b"FAIL" + self.disc[4:]):
            with self.assertRaises(ValueError):
                roster.baseline(data)
            with self.assertRaises(ValueError):
                roster.encode(data, self.payload)

    def test_bad_layout_pointers_and_history_are_rejected(self):
        cases = ((8, roster.CARD_SIZE - 32), (0xC, 0), (0x30, 0x11), (0x60, 456), (0x6500, 0),
                 (0x64F4, 1), (0x64F4 + 0x90, 2), (roster.CONTENT_END, 1))
        for field, value in cases:
            data = bytearray(self.payload)
            struct.pack_into("<I", data, field, value)
            with self.subTest(field=hex(field)), self.assertRaises(ValueError):
                roster.encode(self.disc, bytes(data))
        with self.assertRaises(ValueError):
            roster.validate_payload(self.payload[:-1])

    def test_out_of_bounds_or_unterminated_strings_are_rejected(self):
        for destination in (0x50, roster.CONTENT_END, roster.CONTENT_END - 2):
            data = bytearray(self.payload)
            struct.pack_into("<i", data, 0x6500, destination - 0x6500 + 1)
            if destination < roster.CONTENT_END:
                data[destination:destination + 2] = b"X\0"
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                roster.validate_payload(data)

    def test_source_checks_archive_identity_and_content(self):
        entries = {asset_hash(roster.ASSET): (roster.ISO_OFFSET, roster.DISC_SIZE)}
        with patch.object(roster, "read_archive", return_value=entries), \
                patch.object(roster, "read_asset", return_value=(roster.ISO_OFFSET, self.disc)):
            self.assertEqual(roster.read_source(io.BytesIO()), self.disc)
        with patch.object(roster, "read_archive", return_value={}):
            with self.assertRaisesRegex(ValueError, "archive entry"):
                roster.read_source(io.BytesIO())
        with patch.object(roster, "read_archive", return_value=entries), \
                patch.object(roster, "read_asset", return_value=(roster.ISO_OFFSET, b"wrong")):
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                roster.read_source(io.BytesIO())

    def test_preflight_needs_no_generated_payload_and_prepare_reports_exact_patch(self):
        data = bytearray(self.payload)
        data[0x64F4 + 0x58] = 77
        initialization = (roster.HISTORY_INIT_OFFSET, bytes.fromhex("98e9050c"), bytes(4))
        with patch.object(roster, "read_source", return_value=self.disc), \
                patch.object(roster, "history_initialization_patch", return_value=initialization):
            patches, report = roster.prepare(io.BytesIO())
            self.assertEqual(patches, [])
            self.assertEqual(report["baseline_sha256"], digest(self.payload))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "payload.bin"
                path.write_bytes(data)
                patches, report = roster.prepare(io.BytesIO(), path)
        self.assertEqual(patches, [(roster.ISO_OFFSET, self.disc, roster.encode(self.disc, bytes(data))), initialization])
        self.assertEqual(report["payload_sha256"], digest(data))
        self.assertEqual(report["changed_bytes"], 1)
        self.assertEqual(report["elf_crc_delta"], 0x0C05E998)

    def test_only_verified_startup_cleanup_call_is_disabled(self):
        data = bytearray(roster.HISTORY_INIT_OFFSET + 0x40)
        start = roster.HISTORY_INIT_OFFSET - 0x20
        data[start:start + len(roster.HISTORY_INIT_CONTEXT)] = roster.HISTORY_INIT_CONTEXT
        self.assertEqual(roster.history_initialization_patch(io.BytesIO(data)),
                         (roster.HISTORY_INIT_OFFSET, bytes.fromhex("98e9050c"), bytes(4)))
        data[start] ^= 1
        with self.assertRaisesRegex(ValueError, "initialization code"):
            roster.history_initialization_patch(io.BytesIO(data))


if __name__ == "__main__":
    unittest.main()
