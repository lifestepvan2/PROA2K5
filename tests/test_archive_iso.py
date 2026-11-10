import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import archive_iso
from iso_copy import CopySpan, hash_stream, publish_iso_copy


class ArchiveRepackTests(unittest.TestCase):
    def setUp(self):
        self.base = 2048
        header = struct.pack("<39I", 3, 0, 3, 4, 4, 2, *([0] * 33))
        table = b"".join(struct.pack("<III", *entry) for entry in
                         ((30, 4096, 1), (10, 4096, 3), (20, 2048, 5)))
        self.data = (b"P" * self.base + (header + table).ljust(2048, b"\0")
                     + b"A" * 4096 + b"B" * 4096 + b"C" * 2048
                     + b"\0" * (4 * 2048) + b"S" * 2048)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "new.iso"

    def publish(self, patches):
        stream = io.BytesIO(self.data)
        plan, outside, report = archive_iso.plan(stream, patches, archive_base=self.base)
        publish_iso_copy(stream, self.output, outside, hash_stream(stream), len(self.data), report,
                         self.output.with_suffix(".json"), copy_plan=plan)
        return self.output.read_bytes(), report

    def test_noop_preserves_every_byte(self):
        result, report = self.publish([])
        self.assertEqual(result, self.data)
        self.assertEqual(report["relocated_assets"], 0)

    def test_shrink_and_grow_pool_sectors_preserving_ordinals_and_opaque_assets(self):
        changes = [(self.base + 2048, b"A" * 4096, b"a" * 512),
                   (self.base + 3 * 2048, b"B" * 4096, b"b" * 6144),
                   (10, b"P", b"p")]
        result, report = self.publish(changes)
        entries = list(struct.iter_unpack("<III", result[self.base + 156:self.base + 192]))
        self.assertEqual(entries, [(30, 512, 1), (10, 6144, 2), (20, 2048, 5)])
        self.assertEqual(result[self.base + 2048:self.base + 2048 + 512], b"a" * 512)
        self.assertEqual(result[self.base + 4096:self.base + 5 * 2048], b"b" * 6144)
        self.assertEqual(result[self.base + 5 * 2048:self.base + 6 * 2048], b"C" * 2048)
        self.assertEqual((len(result), result[10:11], result[-2048:]),
                         (len(self.data), b"p", b"S" * 2048))
        self.assertEqual(report["sector_savings_bytes"], 0)
        self.assertEqual(report["relocated_assets"], 1)

    def test_all_edits_in_a_moved_asset_follow_it_and_keep_untouched_tail(self):
        result, report = self.publish([
            (self.base + 2048, b"A" * 4096, b"a" * 512),
            (self.base + 3 * 2048, b"BB", b"bb"),
            (self.base + 3 * 2048 + 100, b"BB", b"longer"),
        ])
        start = self.base + 4096
        self.assertEqual(result[start:start + 2], b"bb")
        self.assertEqual(result[start + 100:start + 106], b"longer")
        self.assertEqual(result[start + 106:start + 4100], b"B" * (4100 - 106))
        self.assertEqual(report["entries"][1]["size"], 4100)

    def test_refuses_overflow_bad_source_and_edits_crossing_asset_boundaries(self):
        for patches in (
            [(self.base + 2048, b"A" * 4096, b"x" * 20000)],
            [(self.base + 2048, b"wrong", b"x")],
            [(self.base + 3 * 2048 - 1, b"AB", b"xy")],
            [(self.base + 156, self.data[self.base + 156:self.base + 160], b"xxxx")],
        ):
            with self.subTest(patches=len(patches[0][2])):
                with self.assertRaises(ValueError):
                    archive_iso.plan(io.BytesIO(self.data), patches, archive_base=self.base)
        self.assertFalse(self.output.exists())

    def test_rejects_unsupported_segment_strategy_and_unordered_entries(self):
        for offset, value in ((self.base + 4, 1), (self.base + 16, 5),
                              (self.base + 156 + 12 + 8, 0)):
            data = bytearray(self.data)
            struct.pack_into("<I", data, offset, value)
            with self.assertRaises(ValueError):
                archive_iso.plan(io.BytesIO(data), [], archive_base=self.base)

    def test_copy_plan_relocation_crosses_publisher_block_boundary(self):
        size = 4 * 1024 * 1024 + 128
        data = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
        stream = io.BytesIO(data)
        plan = [CopySpan(0, 64, source_offset=size - 64),
                CopySpan(64, size - 64, source_offset=0)]
        publish_iso_copy(stream, self.output, [], hash_stream(stream), size, {},
                         self.output.with_suffix(".json"), copy_plan=plan)
        self.assertEqual(self.output.read_bytes(), data[-64:] + data[:-64])

    def test_invalid_copy_plan_rejected_without_writing(self):
        for plan in ([CopySpan(1, len(self.data), source_offset=0)],
                     [CopySpan(0, len(self.data) - 1, source_offset=0)],
                     [CopySpan(0, len(self.data), source_offset=1)],
                     [CopySpan(0, len(self.data), data=b"x")]):
            with self.assertRaises(ValueError):
                publish_iso_copy(io.BytesIO(self.data), self.output, [], "", len(self.data), {},
                                 self.output.with_suffix(".json"), copy_plan=plan)
        self.assertEqual(list(self.output.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
