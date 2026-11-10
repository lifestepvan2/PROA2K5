import sys
import struct
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_texture as native
from gs_texture import decode_upload
from test_gs_texture import fixture
from test_texture_catalogue import texture
from texture_catalogue import texture_images
import texture_iso_workspace as workspace
import numpy as np
import gs_texture as gs


def shared_fixture():
    system, width, height = 160, 8, 4
    size = width * height
    video = size + 2048
    data = bytearray(system + video)
    for index, descriptor in enumerate((48, 104)):
        struct.pack_into("<3Q", data, descriptor, 19 << 20 | 3 << 26 | 2 << 30, 1 << 63, 0)
        struct.pack_into("<I", data, descriptor + 40, size + index * 1024 if index else 0)
        struct.pack_into("<HH", data, descriptor + 44, width, height)
        palette = np.zeros((256, 4), dtype=np.uint8)
        palette[:, index] = np.arange(256)
        palette[:, 3] = 128
        data[system + size + index * 1024:system + size + (index + 1) * 1024] = palette.tobytes()
    data[system:system + size] = bytes(range(size))
    return bytes(data), system, video, [48, 104]


class NativeTextureTests(unittest.TestCase):
    def test_true_color_mips_preserve_system_and_regenerate_native_alpha(self):
        data, system, video = texture(0, 8, 8, 3)
        target, report, preview = native.encode(
            data, system, video, 48, [48], Image.new("RGBA", (16, 16), (21, 33, 99, 128)))
        images = texture_images(target, system, video, 48, [48])[0]
        self.assertEqual(target[:system], data[:system])
        self.assertEqual(report["mips"], 3)
        self.assertTrue(all(im["rgba"] == bytes((21, 33, 99, 64)) * im["width"] * im["height"]
                            for im in images))
        self.assertEqual(preview.getpixel((0, 0)), (21, 33, 99, 127))

    def test_packed_four_bit_encoding_preserves_the_unused_sibling_nibble(self):
        system, video = 112, 8192
        data = bytearray(bytes(system) + b"\xaa" * video)
        struct.pack_into("<3Q", data, 48, (2 << 14) | (20 << 20) | (1 << 37), 0, 0)
        struct.pack_into("<HH", data, 92, 1, 1)
        before = bytes(data)
        target, report, preview = native.encode(
            before, system, video, 48, [48], Image.new("RGBA", (1, 1), (12, 34, 56, 255)))
        pixel = system + int(gs.host_offsets(np.array([0]), video)[0])
        self.assertEqual(target[pixel] & 0xF0, before[pixel] & 0xF0)
        self.assertEqual(target[:system], before[:system])
        self.assertEqual(preview.getpixel((0, 0)), (12, 34, 56, 255))
        self.assertEqual(report["palette_colors"], 16)

    def test_shared_fan_indices_encode_jointly_without_changing_other_variant(self):
        data, system, video, offsets = shared_fixture()
        original = texture_images(data, system, video, 104, offsets)[0][0]
        master = Image.new("RGBA", (8, 4), (30, 70, 120, 255))
        target, reports, previews = native.encode_shared(data, system, video, offsets, {48: master})
        first, layout, _, _ = texture_images(target, system, video, 48, offsets)
        second = texture_images(target, system, video, 104, offsets)[0][0]
        self.assertEqual(layout, "linear-shared-indices")
        self.assertEqual(second["rgba"], original["rgba"])
        self.assertEqual(first[0]["rgba"], bytes((30, 70, 120, 128)) * 32)
        self.assertEqual(target[:system], data[:system])
        self.assertEqual(previews[48].getpixel((0, 0)), (30, 70, 120, 255))
        self.assertTrue(all(row["shared_index_cohort"] == 2 for row in reports))
        with self.assertRaisesRegex(ValueError, "encoded together"):
            native.encode(data, system, video, 48, offsets, master)

    def test_shared_fan_quantization_respects_joint_palette_budget_and_rejects_bad_offsets(self):
        data, system, video, offsets = shared_fixture()
        master = native.display(texture_images(data, system, video, 48, offsets)[0][0])
        _, reports, _ = native.encode_shared(data, system, video, offsets, {48: master}, palette_colors=16)
        self.assertTrue(all(row["palette_colors"] <= 16 for row in reports))
        bad = bytearray(data)
        struct.pack_into("<I", bad, 104 + 40, 100)
        with self.assertRaisesRegex(ValueError, "invalid palette offsets"):
            texture_images(bytes(bad), system, video, 48, offsets)

    def test_gs_master_updates_all_mips_with_one_palette_and_preserves_system(self):
        data, _ = fixture()
        master = Image.new("RGBA", (1024, 512), (24, 90, 180, 255))
        target, report, preview = native.encode(data, 112, 180224, 48, [48], master)
        images = decode_upload(target, 112, 180224, 48)
        self.assertEqual(len(images), 6)
        self.assertTrue(report["changed"])
        self.assertEqual(target[:112], data[:112])
        self.assertTrue(all(set(image["rgba"][::4]) == {24} for image in images))
        self.assertTrue(all(set(image["rgba"][3::4]) == {128} for image in images))
        self.assertEqual(preview.getpixel((0, 0)), (24, 90, 180, 255))
        self.assertEqual(report["rgb_rmse_visible"], 0)

    def test_exported_original_is_a_byte_identical_noop(self):
        data, _ = fixture()
        original = native.display(decode_upload(data, 112, 180224, 48)[0])
        target, report, _ = native.encode(data, 112, 180224, 48, [48], original)
        self.assertEqual(target, data)
        self.assertFalse(report["changed"])

    def test_linear_seven_mips_encode_and_read_back(self):
        data, system, video = texture(19, 64, 64, 7)
        target, report, _ = native.encode(
            data, system, video, 48, [48], Image.new("RGBA", (64, 64), (60, 140, 50, 128)))
        images, _, _, _ = texture_images(target, system, video, 48, [48])
        self.assertEqual(report["mips"], 7)
        self.assertEqual(target[:system], data[:system])
        self.assertTrue(all(set(image["rgba"][3::4]) == {64} for image in images))

    def test_native_team_ids_are_not_roster_slots(self):
        from inventory_lettering_iso import asset_hash
        self.assertEqual(workspace.current_slot("uh002.iff", f"{asset_hash('uh002.iff'):08x}", "logo", "team_logos"), 29)
        self.assertEqual(workspace.current_slot("uh028.iff", f"{asset_hash('uh028.iff'):08x}", "logo", "team_logos"), 1)
        self.assertEqual(workspace.current_slot("hash:a90f4964", "a90f4964", "logo002", "team_logos"), 29)
        self.assertIsNone(workspace.current_slot("hash:a90f4964", "a90f4964", "logo507", "team_logos"))

    def test_observed_six_mip_linear_layouts_include_four_bit_textures(self):
        for psm in (19, 20):
            data, system, video = texture(psm, 64, 32, 6)
            target, report, _ = native.encode(
                data, system, video, 48, [48], Image.new("RGBA", (64, 32), (80, 120, 40, 255)))
            images, layout, _, _ = texture_images(target, system, video, 48, [48])
            self.assertEqual((len(images), layout), (6, "linear-6-mip"))
            self.assertEqual(images[0]["rgba"][:4], bytes((80, 120, 40, 128)))
            self.assertEqual(report["palette_colors"], 256 if psm == 19 else 16)

    def test_legacy_workspace_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not use"):
            workspace.validate_workspace(workspace.ROOT / "texture_workspace" / "test")


if __name__ == "__main__":
    unittest.main()
