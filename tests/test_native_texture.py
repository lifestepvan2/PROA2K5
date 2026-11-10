import sys
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


class NativeTextureTests(unittest.TestCase):
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
