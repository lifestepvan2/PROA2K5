import struct
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gs_texture as gs
from txtr_match import SWZ


def fixture():
    system, video, descriptor = 112, 180224, 48
    data = bytearray(system + video)
    tex0 = (8 << 14) | (19 << 20) | (9 << 26) | (8 << 30) | (688 << 37)
    levels = [(0, 8), (512, 4), (640, 2), (672, 2), (692, 2), (694, 2)]
    words = [sum(base << shift | bw << (shift + 14) for (base, bw), shift in zip(group, (0, 20, 40)))
             for group in (levels[1:4], levels[4:])]
    struct.pack_into("<3Q", data, descriptor, tex0, *words)
    struct.pack_into("<HH", data, descriptor + 44, 512, 256)
    memory = np.full(video, 255, dtype=np.uint8)
    palette = np.array([(i, 255 - i, i // 2, i % 129) for i in range(256)], dtype=np.uint8)
    expected = []
    for level, (base, bw) in enumerate(levels):
        h, w = max(1, 256 >> level), max(1, 512 >> level)
        y, x = np.indices((h, w))
        indices = ((3 * x + 5 * y + level) % 256).astype(np.uint8)
        memory[gs.address8(x, y, bw, base)] = indices
        expected.append(palette[indices].tobytes())
    y, x = np.indices((16, 16))
    memory[(gs.address32(x, y, 1, 688).ravel()[:, None] + np.arange(4))] = palette[SWZ]
    y, x = np.indices((video // 256, 64))
    upload_addresses = (gs.address32(x, y, 1).ravel()[:, None] + np.arange(4)).ravel()
    data[system:] = memory[upload_addresses].tobytes()
    return bytes(data), expected


class GsTextureTests(unittest.TestCase):
    def test_hardware_address_bit_positions(self):
        for (x, y), address in { (0, 0): 0, (4, 0): 32, (0, 2): 33, (0, 4): 96,
                                (0, 8): 128, (16, 0): 256, (0, 16): 512,
                                (64, 0): 4096, (128, 0): 8192, (0, 64): 32768}.items():
            self.assertEqual(int(gs.address8(np.array(x), np.array(y), 8)), address)
        for (x, y), address in {(0, 0): 0, (8, 0): 256, (0, 8): 512,
                               (32, 0): 4096, (64, 0): 8192, (0, 32): 32768}.items():
            self.assertEqual(int(gs.address32(np.array(x), np.array(y), 4)), address)

    def test_both_formats_address_every_byte_in_a_page_once(self):
        y, x = np.indices((64, 128))
        self.assertEqual(sorted(gs.address8(x, y, 2).ravel()), list(range(8192)))
        y, x = np.indices((32, 64))
        addresses = (gs.address32(x, y, 1).ravel()[:, None] + np.arange(4)).ravel()
        self.assertEqual(sorted(addresses), list(range(8192)))
        self.assertEqual(gs.host_offsets(addresses, 8192).tolist(), list(range(8192)))
        y, x = np.indices((128, 128))
        self.assertEqual(sorted(gs.address4(x, y, 2).ravel()), list(range(16384)))
        self.assertEqual(int(gs.address4(np.array(128), np.array(0), 4)), 16384)
        self.assertEqual(int(gs.address4(np.array(0), np.array(128), 4)), 32768)

    def test_all_six_native_mips_shared_palette_and_alpha(self):
        data, expected = fixture()
        images = gs.decode_upload(data, 112, 180224, 48)
        self.assertEqual(len(images), 6)
        self.assertEqual([image["rgba"] for image in images], expected)
        self.assertEqual([image["tbp"] for image in images], [0, 512, 640, 672, 692, 694])
        self.assertEqual([(i["width"], i["height"]) for i in images],
                         [(512, 256), (256, 128), (128, 64), (64, 32), (32, 16), (16, 8)])

    def test_truncation_unsupported_palette_and_geometry_fail_explicitly(self):
        data, _ = fixture()
        with self.assertRaisesRegex(ValueError, "Truncated"):
            gs.decode_upload(data[:-1], 112, 180224, 48)
        with self.assertRaisesRegex(ValueError, "complete"):
            gs.decode_upload(data, 112, 180223, 48)
        for flag, reason in ((1 << 20, "PSMT8"), (1 << 55, "palette"), (1 << 56, "palette")):
            changed = bytearray(data)
            q = struct.unpack_from("<Q", changed, 48)[0]
            struct.pack_into("<Q", changed, 48, q ^ flag)
            with self.assertRaisesRegex(ValueError, reason):
                gs.decode_upload(changed, 112, 180224, 48)

    def test_out_of_bounds_palette_does_not_read_another_resource(self):
        data, _ = fixture()
        changed = bytearray(data)
        q = struct.unpack_from("<Q", changed, 48)[0]
        struct.pack_into("<Q", changed, 48, (q & ~(16383 << 37)) | (16383 << 37))
        with self.assertRaisesRegex(ValueError, "outside"):
            gs.decode_upload(changed, 112, 180224, 48)


if __name__ == "__main__":
    unittest.main()
