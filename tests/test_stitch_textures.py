import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stitch_textures import stitch, split


class StripTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.group = self.root / "arenas" / "slot_000_Team" / "props" / "s028"
        self.paths = {}
        for index in (2, 0, 1):
            path = self.group / f"sts_{index}" / f"original__{index:08x}.png"
            path.parent.mkdir(parents=True)
            Image.new("RGBA", (128, 128), (index * 80, 10, 20, 100 + index)).save(path)
            self.paths[index] = path
        self.output = self.root / "_stitched" / self.group.relative_to(self.root) / "sts.png"

    def test_dynamic_width_sorted_order_and_lossless_round_trip(self):
        before = {}
        for index, path in self.paths.items():
            with Image.open(path) as image:
                before[index] = image.tobytes()
        report = stitch(self.root)
        self.assertEqual(report[0]["size"], (384, 128))
        with Image.open(self.output) as image:
            for index in range(3):
                self.assertEqual(image.getpixel((128 * index, 0)), (index * 80, 10, 20, 100 + index))
        split(self.root)
        for index, path in self.paths.items():
            with Image.open(path) as image:
                self.assertEqual(image.tobytes(), before[index])

    def test_edited_pixels_alpha_and_original_filenames(self):
        stitch(self.root)
        with Image.open(self.output) as image:
            image.putpixel((130, 4), (1, 2, 3, 4))
            image.save(self.output)
        split(self.root)
        with Image.open(self.paths[1]) as image:
            self.assertEqual(image.getpixel((2, 4)), (1, 2, 3, 4))
        self.assertEqual(set(self.group.rglob("*.png")), set(self.paths.values()))

    def test_rgb_editor_export_keeps_original_alpha(self):
        stitch(self.root)
        Image.new("RGB", (384, 128), (9, 8, 7)).save(self.output)
        split(self.root)
        for index, path in self.paths.items():
            with Image.open(path) as image:
                self.assertEqual(image.getpixel((0, 0)), (9, 8, 7, 100 + index))

    def test_stitch_overwrites_derived_strip_from_current_tiles(self):
        stitch(self.root)
        Image.new("RGBA", (128, 128), (33, 44, 55, 66)).save(self.paths[0])
        stitch(self.root)
        with Image.open(self.output) as image:
            self.assertEqual(image.getpixel((0, 0)), (33, 44, 55, 66))

    def test_invalid_later_strip_does_not_overwrite_any_tiles(self):
        other = self.root / "arenas" / "slot_001_Team" / "props" / "s000" / "sts_0" / "tile.png"
        other.parent.mkdir(parents=True)
        Image.new("RGBA", (128, 128)).save(other)
        stitch(self.root)
        before = {path: path.read_bytes() for path in self.paths.values()}
        Image.new("RGBA", (384, 128), "red").save(self.output)
        derived = self.root / "_stitched" / other.parent.parent.relative_to(self.root) / "sts.png"
        Image.new("RGBA", (1, 1)).save(derived)
        with self.assertRaisesRegex(ValueError, "do not resize"):
            split(self.root)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_duplicate_indices_and_wrong_source_size_fail_before_publication(self):
        duplicate = self.paths[0].with_name("duplicate.png")
        duplicate.write_bytes(self.paths[0].read_bytes())
        with self.assertRaisesRegex(ValueError, "Duplicate tile"):
            stitch(self.root)
        self.assertFalse(self.output.exists())
        duplicate.unlink()
        Image.new("RGBA", (64, 128)).save(self.paths[0])
        with self.assertRaisesRegex(ValueError, "expected 128x128"):
            stitch(self.root)
        self.assertFalse(self.output.exists())

    def test_sidecar_cannot_target_another_group_or_escape_workspace(self):
        stitch(self.root)
        sidecar = self.output.with_suffix(".json")
        metadata = json.loads(sidecar.read_text())
        for destination in ("..\\outside.png", "another_group\\tile.png"):
            metadata["tiles"][0]["path"] = destination
            sidecar.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "outside"):
                split(self.root)

    def test_custom_group_tile_size_name_and_numeric_filename_indices(self):
        group = self.root / "custom"
        group.mkdir()
        for index in (10, 2):
            Image.new("RGBA", (4, 3), (index, 0, 0, 255)).save(group / f"tile{index}.png")
        stitch(self.root, groups="custom", tiles="*.png", index_regex=r"tile(\d+)",
               tile_size=(4, 3), name="banner")
        output = self.root / "_stitched" / "custom" / "banner.png"
        with Image.open(output) as image:
            self.assertEqual(image.size, (8, 3))
            self.assertEqual(image.getpixel((0, 0)), (2, 0, 0, 255))
            self.assertEqual(image.getpixel((4, 0)), (10, 0, 0, 255))
        split(self.root, groups="custom", name="banner")


if __name__ == "__main__":
    unittest.main()
