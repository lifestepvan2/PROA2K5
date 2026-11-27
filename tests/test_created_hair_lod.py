import hashlib
import io
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import created_hair_lod as hair
from created_hair_strips import encode
from texture_catalogue import relative, text
from vc_lz import decode
from test_texture_catalogue import pointer
from test_vc_lz import literal_stream


def fixture():
    data = bytearray(4800)
    data[2000:2026] = "locreatehead\0".encode("utf-16le")
    pointer(data, 16, 2000)
    pointer(data, 20, 64)
    struct.pack_into("<I", data, 64 + 28, 7)
    pointer(data, 64 + 32, 768)
    pointer(data, 64 + 48, 512)
    struct.pack_into("<I", data, 512 + 104, 7)
    pointer(data, 512 + 108, 1664)
    stream, _ = encode([((1, 1, 1), (0, 0), (0, 1, 0)),
                        ((2, 1, 1), (1, 0), (0, 1, 0)),
                        ((1, 2, 1), (0, 1), (0, 1, 0))], [(0, 1, 2)])
    names = ("face", "eyes", "hair01_mat", "hair02_mat", "hair03_mat", "mouth", "other")
    for index, name in enumerate(names):
        start = 2048 + index * 32
        encoded = (name + "\0").encode("utf-16le")
        data[start:start + len(encoded)] = encoded
        pointer(data, 768 + index * 96 + 88, start)
        record = 1664 + index * 24
        start = 2560 + index * 256
        pointer(data, record, start)
        struct.pack_into("<II", data, record + 4, len(stream), index)
        data[start:start + len(stream)] = stream
    encoded = literal_stream(data)
    scene = struct.pack("<4s7I", b"SCNE", len(encoded), len(data), 0, 0xFEEDBEEF, 16, 0, 0) + encoded
    prefix = struct.pack("<4s7I", b"TXTR", 4, 4, 0, 0, 0, 0, 0) + b"test"
    return prefix + scene, bytes(data), stream


def unpack_scene(package):
    chunk = hair.locate_scene(package)
    _, size, system, _, *_ = struct.unpack_from("<4s7I", package, chunk)
    return decode(package[chunk + 32:chunk + 32 + size], system, collect_tokens=False)[0]


class CreatedHairLodTests(unittest.TestCase):
    def test_adds_per_style_parts_preserving_stock_geometry_and_hiding_custom_materials(self):
        package, original, stream = fixture()
        streams = dict.fromkeys(hair.CUSTOM_STYLES, stream)
        with patch.object(hair, "SCENE_SHA256", hashlib.sha256(original).hexdigest()):
            chunk, before, after, report = hair.replace_scene(package, streams)
        self.assertEqual(chunk, 36)
        self.assertEqual(before, package[chunk:])
        updated = unpack_scene(package[:chunk] + after)
        root = relative(updated, 20)
        mats = relative(updated, root + 32)
        mesh = relative(updated, root + 48)
        parts = relative(updated, mesh + 108)
        self.assertEqual(struct.unpack_from("<I", updated, root + 28)[0], 18)
        self.assertEqual(struct.unpack_from("<I", updated, mesh + 104)[0], 18)
        expected_names = ["face", "eyes", "lohair01_mat", "lohair02_mat", "lohair03_mat", "mouth", "other"]
        expected_names.extend(f"hair{style - 1:02}_mat" for style in hair.CUSTOM_STYLES)
        for index, name in enumerate(expected_names):
            material = mats + index * 96
            self.assertEqual(text(updated, relative(updated, material + 88), len(updated)), name)
            record = parts + index * 24
            start = relative(updated, record)
            size, material_index = struct.unpack_from("<II", updated, record + 4)
            self.assertEqual(updated[start:start + size], stream)
            self.assertEqual(material_index, index)
            if index < 7:
                self.assertEqual(updated[record + 4:record + 24],
                                 original[1664 + index * 24 + 4:1664 + (index + 1) * 24])
            else:
                self.assertTrue(struct.unpack_from("<Q", updated, material + 56)[0] & 0x80000000)
        self.assertEqual(report["decoded_sha256"], hashlib.sha256(updated).hexdigest())

    def test_rejects_wrong_scene_incomplete_mesh_set_and_duplicate_low_heads(self):
        package, _, stream = fixture()
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            hair.replace_scene(package, dict.fromkeys(hair.CUSTOM_STYLES, stream))
        with self.assertRaisesRegex(ValueError, "complete approved"):
            hair.replace_scene(package, {2: stream})
        with self.assertRaisesRegex(ValueError, "exactly one"):
            hair.locate_scene(package + package)
        with self.assertRaisesRegex(ValueError, "Truncated"):
            hair.locate_scene(package + b"X")

    def test_approved_asset_tampering_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / "hair"
            shutil.copytree(hair.ASSETS, assets)
            with patch.object(hair, "ASSETS", assets):
                hair.load_assets()
                path = assets / "hair10.vif"
                path.write_bytes(path.read_bytes()[:-1])
                with self.assertRaisesRegex(ValueError, "hairstyle 10 stream fingerprint"):
                    hair.load_assets()

    def test_prepares_both_scene_copies_and_all_selector_bindings_with_one_crc_delta(self):
        package, original, _ = fixture()
        data = bytearray(0x3A4000)
        data[hair.SELECTOR_OFFSET:hair.SELECTOR_OFFSET + hair.SELECTOR_SIZE] = b"A" * hair.SELECTOR_SIZE
        for offset, old, _ in hair.BINDINGS:
            struct.pack_into("<I", data, offset, old)
        with patch.object(hair, "SCENE_SHA256", hashlib.sha256(original).hexdigest()), \
                patch.object(hair, "SELECTOR_ORIGINAL_SHA256",
                             hashlib.sha256(b"A" * hair.SELECTOR_SIZE).hexdigest()), \
                patch.object(hair, "read_archive", return_value={}), \
                patch.object(hair, "read_asset", side_effect=[(100, package), (20000, package)]) as read:
            patches, delta, report = hair.prepare_custom(io.BytesIO(data))
        self.assertEqual([call.args[2] for call in read.call_args_list], list(hair.SCENE_ASSETS))
        self.assertEqual(len(patches), 6)
        expected_delta = 0
        for _, before, after in patches[2:]:
            for old, new in zip(struct.iter_unpack("<I", before), struct.iter_unpack("<I", after)):
                expected_delta ^= old[0] ^ new[0]
        self.assertEqual(delta, expected_delta)
        self.assertEqual(report["mode"], "per-style")
        self.assertEqual(report["stock_styles"], {"1": "short", "7": "afro"})
        self.assertEqual(len(report["scenes"]), 2)
        data[hair.BINDINGS[0][0]] ^= 1
        with patch.object(hair, "SELECTOR_ORIGINAL_SHA256",
                          hashlib.sha256(b"A" * hair.SELECTOR_SIZE).hexdigest()):
            with self.assertRaisesRegex(ValueError, "stock hair material binding"):
                hair.prepare_custom(io.BytesIO(data))


if __name__ == "__main__":
    unittest.main()
