import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from iso_copy import hash_stream, publish_iso_copy


class IsoCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "new.iso"
        self.manifest = self.output.with_name("new.iso.json")

    def test_patch_crossing_read_block_boundary(self):
        data = b"A" * (4 * 1024 * 1024 + 128)
        offset = 4 * 1024 * 1024 - 8
        stream = io.BytesIO(data)
        report = publish_iso_copy(stream, self.output, [(offset, b"A" * 32, b"B" * 32)],
                                  hash_stream(stream), len(data), {}, self.manifest)
        expected = data[:offset] + b"B" * 32 + data[offset + 32:]
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertEqual(report["output_sha256"], hash_stream(io.BytesIO(expected)))

    def test_invalid_spans_rejected_before_writes(self):
        for spans in ([(-1, b"A", b"B")], [(0, b"A", b"BB")],
                      [(0, b"AA", b"BB"), (1, b"A", b"C")], [(4, b"A", b"B")]):
            with self.assertRaises(ValueError):
                publish_iso_copy(io.BytesIO(b"AAAA"), self.output, spans, "", 4, {}, self.manifest)
            self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_racing_output_is_not_overwritten_and_temporary_manifest_is_removed(self):
        def race(_, output):
            output.write_bytes(b"other process")
            raise FileExistsError("racing output")
        stream = io.BytesIO(b"AAAA")
        with patch("iso_copy.os.link", side_effect=race):
            with self.assertRaises(FileExistsError):
                publish_iso_copy(stream, self.output, [], hash_stream(stream), 4, {}, self.manifest)
        self.assertEqual(self.output.read_bytes(), b"other process")
        self.assertFalse(self.manifest.exists())
        self.assertFalse(list(self.output.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
