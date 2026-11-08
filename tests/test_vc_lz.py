import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from vc_lz import decode, rebuild_tail


def literal_stream(data: bytes, capacity: int = 0) -> bytes:
    result = bytearray(struct.pack("<II", len(data), 0x5C) + b"\x0B")
    for start in range(0, len(data), 8):
        result.append(0)
        result.extend(data[start:start + 8])
    return bytes(result).ljust(capacity, b"\0")


class VcLzTests(unittest.TestCase):
    def test_literal_decode_and_consumed_span(self):
        original = bytes(range(64))
        stream = literal_stream(original, 100)
        result, tokens, consumed = decode(stream, len(original))
        self.assertEqual(result, original)
        self.assertEqual(len(tokens), 64)
        self.assertEqual(consumed, 81)

    def test_backwards_overlapping_copy_reads_unwritten_zeros(self):
        stream = struct.pack("<II", 5, 0x5C) + b"\x0B\x04AB" + struct.pack("<H", 2)
        self.assertEqual(decode(stream, 5)[0], b"ABAB\0")

    def test_tail_rebuild_preserves_prefix_and_capacity(self):
        original = bytes(range(64)) * 3
        stream = literal_stream(original, 300)
        replacement = b"\x10\x20\x30\x80" * 16
        result = rebuild_tail(stream, len(original), replacement, 300)
        self.assertEqual(len(result), len(stream))
        self.assertEqual(decode(result, len(original))[0], original[:-64] + replacement)

    def test_identical_tail_preserves_entire_stream(self):
        stream = literal_stream(b"abcdefgh", 32)
        self.assertEqual(rebuild_tail(stream, 8, b"efgh", 0), stream)

    def test_refuses_insufficient_capacity(self):
        original = b"A" * 320
        stream = literal_stream(original)
        packed = rebuild_tail(stream, len(original), b"B" * 312, 4096)
        _, _, consumed = decode(packed, len(original))
        compact = packed[:consumed]
        with self.assertRaisesRegex(ValueError, "fixed span"):
            rebuild_tail(compact, len(original), bytes(range(128)), 4096)

    def test_refuses_insufficient_in_place_scratch(self):
        original = bytes(range(64)) * 3
        stream = literal_stream(original, 500)
        with self.assertRaisesRegex(ValueError, "scratch"):
            rebuild_tail(stream, len(original), b"A" * 64, 0)

    def test_rejects_invalid_streams(self):
        for stream, expected in (
            (b"bad", 1),
            (literal_stream(b"abc"), 4),
            (struct.pack("<II", 1, 0) + b"\0\0A", 1),
            (struct.pack("<II", 3, 0) + b"\x0B\x01\x01\0", 3),
            (literal_stream(b"abcdefgh")[:-1], 8),
        ):
            with self.subTest(stream=stream):
                with self.assertRaises(ValueError):
                    decode(stream, expected)


if __name__ == "__main__":
    unittest.main()
