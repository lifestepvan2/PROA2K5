import struct
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from vc_lz import decode, rebuild_tail, recompress, validate_inplace, _longest_match


def literal_stream(data: bytes, capacity: int = 0) -> bytes:
    result = bytearray(struct.pack("<II", len(data), 0x5C) + b"\x0B")
    for start in range(0, len(data), 8):
        result.append(0)
        result.extend(data[start:start + 8])
    return bytes(result).ljust(capacity, b"\0")


class VcLzTests(unittest.TestCase):
    def test_variable_storage_roundtrip_alignment_and_scratch(self):
        rng = random.Random(37)
        for data in (b"A", bytes(1024), b"ABCD" * 100, b"ABC" + bytes(80),
                     rng.randbytes(1024), b"abc" * 1000 + rng.randbytes(1024)):
            source = literal_stream(data)
            for bits in (8, 9, 11, 13):
                with self.subTest(size=len(data), bits=bits):
                    rebuilt, scratch = recompress(source, data, distance_bits=bits)
                    self.assertEqual(rebuilt[:8], source[:8])
                    self.assertEqual((len(rebuilt) % 16, scratch % 16), (0, 0))
                    self.assertGreaterEqual(len(data) + scratch, len(rebuilt))
                    validate_inplace(rebuilt, data, scratch)

    def test_variable_storage_can_grow_beyond_original_span(self):
        data = random.Random(23).randbytes(1024)
        source = literal_stream(bytes(1024))[:16]
        rebuilt, scratch = recompress(source, data)
        self.assertGreater(len(rebuilt), len(source))
        self.assertEqual(decode(rebuilt, len(data))[0], data)
        self.assertGreater(scratch, 0)

    def test_variable_storage_rejects_changed_decoded_size_and_invalid_bits(self):
        for source, target, bits in ((b"bad", b"x", 9),
                                     (literal_stream(b"abc"), b"abcd", 9),
                                     (literal_stream(b"x"), b"x", 0)):
            with self.assertRaises(ValueError):
                recompress(source, target, distance_bits=bits)

    def test_match_search_equals_bruteforce_without_unwritten_memory_reads(self):
        rng = random.Random(21)
        for _ in range(100):
            data = bytes(rng.choice((0, 0, 0, 65, 66, 67)) for _ in range(80))
            position, distance = rng.randrange(1, 70), rng.randrange(1, 32)
            limit = min(20, len(data) - position)
            wanted = 0
            for gap in range(1, min(position, distance) + 1):
                candidate = data[position - gap:position]
                length = 0
                while length < min(limit, gap) and data[position + length] == candidate[length]:
                    length += 1
                wanted = max(wanted, length)
            actual, _ = _longest_match(data, position, distance, limit)
            self.assertEqual(actual, wanted if wanted >= 3 else 0)

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
        with self.assertRaisesRegex(ValueError, "uninitialized"):
            validate_inplace(stream, b"ABAB\0", 128)

    def test_fixed_rebuild_rejects_retained_prefix_that_assumes_zeroed_heap(self):
        stream = struct.pack("<II", 8, 0x5C) + b"\x0B\x04AB" + struct.pack("<H", 2) + b"CDE"
        self.assertEqual(decode(stream, 8)[0], b"ABAB\0CDE")
        with self.assertRaisesRegex(ValueError, "uninitialized"):
            rebuild_tail(stream, 8, b"XYZ", 128)

    def test_inventory_mode_preserves_bytes_and_consumed_span(self):
        streams = (
            (literal_stream(bytes(range(64)), 100), 64),
            (struct.pack("<II", 5, 0x5C) + b"\x0B\x04AB" + struct.pack("<H", 2), 5),
        )
        for stream, size in streams:
            with self.subTest(size=size):
                normal, tokens, consumed = decode(stream, size)
                lightweight, no_tokens, lightweight_consumed = decode(stream, size, collect_tokens=False)
                self.assertEqual((lightweight, lightweight_consumed), (normal, consumed))
                self.assertTrue(tokens)
                self.assertEqual(no_tokens, [])

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

    def test_alternate_distance_bits_roundtrip_and_scratch_validation(self):
        source = b"ABCD" * 40 + b"x" * 512
        stream = literal_stream(source)
        target = b"ABCD" * 40 + b"\0" * 512
        for bits in (8, 9, 10, 12, 13):
            rebuilt = rebuild_tail(stream, len(source), target, 2048, distance_bits=bits)
            self.assertEqual(rebuilt[8], bits)
            self.assertEqual(decode(rebuilt, len(target))[0], target)
            validate_inplace(rebuilt, target, 2048)
        with self.assertRaisesRegex(ValueError, "readback"):
            validate_inplace(rebuilt, source, 2048)

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
