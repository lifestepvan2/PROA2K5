import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import texture_catalogue as native
from test_gs_texture import fixture
from test_texture_catalogue import texture


class SharedTextureTests(unittest.TestCase):
    def test_next_distinct_offset_bounds_shared_and_unsorted_descriptors(self):
        data = bytearray(240 + 200)
        for descriptor, start in ((0, 64), (56, 0), (112, 64)):
            struct.pack_into("<I", data, descriptor + 24, start)
        offsets = [112, 0, 56]
        self.assertEqual(native.texture_span(data, 240, 200, 56, offsets), (0, 64))
        for descriptor in (0, 112):
            self.assertEqual(native.texture_span(data, 240, 200, descriptor, offsets), (64, 200))
        with self.assertRaisesRegex(ValueError, "identity"):
            native.texture_span(data, 240, 200, 56, [0])
        with self.assertRaisesRegex(ValueError, "descriptor exceeds"):
            native.texture_span(data, 240, 200, 56, [56, 200])
        struct.pack_into("<I", data, 24, 200)
        with self.assertRaisesRegex(ValueError, "offset exceeds"):
            native.texture_span(data, 240, 200, 56, offsets)
        with self.assertRaisesRegex(ValueError, "bounds"):
            native.texture_span(data[:-1], 240, 200, 56, offsets)

    def test_mixed_gs32_and_linear_uploads_decode_independently(self):
        packed, expected = fixture()
        linear, old_system, linear_size = texture(19, 64, 64, 7)
        system, prefix = 176, 64
        data = bytearray(system) + bytearray(b"\xff" * prefix + packed[112:] + linear[old_system:])
        data[48:96] = packed[48:96]
        data[112:160] = linear[48:96]
        second = prefix + len(packed) - 112
        struct.pack_into("<I", data, 48 + 24, prefix)
        struct.pack_into("<I", data, 112 + 24, second)
        video = len(data) - system
        images, layout, start, end = native.texture_images(bytes(data), system, video, 48, [48, 112])
        self.assertEqual((layout, start, end), ("gs32-upload-64", prefix, second))
        self.assertEqual([image["rgba"] for image in images], expected)
        images, layout, start, end = native.texture_images(bytes(data), system, video, 112, [48, 112])
        wanted, _ = native.linear_images(linear, old_system, linear_size, 48)
        self.assertEqual((layout, start, end), ("linear-seven-mip", second, video))
        self.assertEqual([image["rgba"] for image in images], [image["rgba"] for image in wanted])
        self.assertEqual(images[0]["pixel_offset"], system + second)
        self.assertEqual(images[0]["palette_offset"], system + video - 1024)


if __name__ == "__main__":
    unittest.main()
