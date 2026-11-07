import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import patch_lettering_iso as iso


class LetteringPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "copy.iso"
        self.original = bytes((20, 40, 100, 128, 250, 230, 0, 128,
                               20, 40, 100, 0, 200, 200, 200, 64)) * 64
        self.targets = {
            "numbers": iso.Palette(0, 0, 64, iso.digest(self.original), 1024, 64),
            "names": iso.Palette(0, 0, 1152, iso.digest(self.original), 1024, 32),
        }
        data = bytearray(2304)
        for spec in self.targets.values():
            data[spec.palette_offset:spec.palette_offset + 1024] = self.original
        self.initial = bytes(data)
        self.path.write_bytes(data)
        self.addCleanup(patch.stopall)
        patch.dict(iso.PALETTES, self.targets, clear=True).start()
        patch.object(iso, "check_layout").start()

    def test_dry_run_changes_nothing(self):
        iso.patch(self.path, target="names")
        self.assertEqual(self.path.read_bytes(), self.initial)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_independent_apply_and_restore(self):
        iso.patch(self.path, apply=True)
        iso.patch(self.path, apply=True, target="names")
        data = self.path.read_bytes()
        expected = iso.green_fill(self.original)
        for spec in self.targets.values():
            result = data[spec.palette_offset:spec.palette_offset + 1024]
            self.assertEqual(result, expected)
            self.assertEqual(result[3::4], self.original[3::4])
        iso.patch(self.path, restore=True, target="names")
        data = self.path.read_bytes()
        self.assertEqual(data[64:1088], expected)
        self.assertEqual(data[1152:2176], self.original)
        iso.patch(self.path, restore=True)
        iso.patch(self.path, restore=True, target="names")
        self.assertEqual(self.path.read_bytes(), self.initial)

    def test_rejects_repeated_apply_and_unrelated_palette_edits(self):
        iso.patch(self.path, apply=True, target="names")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            iso.patch(self.path, apply=True, target="names")
        data = bytearray(self.path.read_bytes())
        data[1152] = 123
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            iso.patch(self.path, restore=True, target="names")
        self.assertEqual(self.path.read_bytes(), data)

    def test_manifest_conflict_prevents_write(self):
        self.path.with_name(self.path.name + ".lettering-names-test.json").write_text(json.dumps({}))
        with self.assertRaisesRegex(ValueError, "manifest conflicts"):
            iso.patch(self.path, apply=True, target="names")
        self.assertEqual(self.path.read_bytes(), self.initial)

    def test_invalid_modes_and_palette_sizes(self):
        with self.assertRaisesRegex(ValueError, "not both"):
            iso.patch(self.path, apply=True, restore=True)
        with self.assertRaises(ValueError):
            iso.green_fill(b"bad")

    def test_layout_rejects_other_image_sizes(self):
        patch.stopall()
        with self.assertRaisesRegex(ValueError, "Europe image"):
            iso.check_layout(io.BytesIO(b"not an ISO"))

    def test_transparent_and_nonblue_entries_are_preserved(self):
        result = iso.green_fill(self.original)
        self.assertEqual(result[:4], bytes((0, 255, 0, 128)))
        self.assertEqual(result[4:16], self.original[4:16])


if __name__ == "__main__":
    unittest.main()
