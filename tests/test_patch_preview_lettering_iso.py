import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import patch_preview_lettering_iso as preview


class PreviewOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.iso"
        self.output = Path(self.temp.name) / "out.iso"
        self.original = bytes(range(256)) * 4
        self.source.write_bytes(self.original)
        self.addCleanup(patch.stopall)
        patch.object(preview, "ISO_SIZE", len(self.original)).start()
        patch.object(preview, "SOURCE_SHA256", preview.digest(self.original)).start()
        patch.object(preview, "inspect", return_value=(32, self.original[32:48], b"X" * 16, {})).start()

    def test_read_only_inspection(self):
        result = preview.build(self.source)
        self.assertEqual(result["source_sha256"], preview.digest(self.original))
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])

    def test_new_output_is_exact_and_source_untouched(self):
        result = preview.build(self.source, self.output)
        expected = self.original[:32] + b"X" * 16 + self.original[48:]
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertEqual(result["output_sha256"], preview.digest(expected))
        manifest = self.output.with_name(self.output.name + ".preview-lettering-test.json")
        self.assertEqual(json.loads(manifest.read_text()), result)
        self.assertFalse(list(self.source.parent.glob("*.tmp")))

    def test_rejects_existing_output_and_source_as_output(self):
        with self.assertRaisesRegex(ValueError, "new path"):
            preview.build(self.source, self.source)
        self.output.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "new path"):
            preview.build(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"keep")

    def test_rejects_wrong_source_hash(self):
        self.source.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "pristine"):
            preview.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_source_patch_mismatch_and_cleans_temporary(self):
        patch.object(preview, "inspect", return_value=(32, b"wrong", b"XXXXX", {})).start()
        with self.assertRaisesRegex(ValueError, "changed during copy"):
            preview.build(self.source, self.output)
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])

    def test_game_test_composes_independent_palette_edits(self):
        spec = preview.PALETTES["numbers"]
        palette = bytes((20, 40, 100, 128)) * 256
        self.source.write_bytes(palette)
        patch.object(preview, "SOURCE_SHA256", preview.digest(palette)).start()
        patch.object(preview, "inspect", return_value=(0, palette[:16], b"X" * 16, {})).start()
        patch.object(preview, "check_layout").start()
        fake = type(spec)(0, 0, 0, preview.digest(palette), 1024, 64)
        patch.dict(preview.PALETTES, {"numbers": fake}, clear=True).start()
        # Real spans are disjoint; use a preview edit beyond the game palette here.
        self.source.write_bytes(palette + b"original-preview")
        patch.object(preview, "ISO_SIZE", self.source.stat().st_size).start()
        patch.object(preview, "SOURCE_SHA256", preview.digest(self.source.read_bytes())).start()
        patch.object(preview, "inspect", return_value=(1024, b"original-preview", b"changed--preview", {})).start()
        result = preview.build(self.source, self.output, with_game_test=True)
        self.assertEqual(self.output.read_bytes(), preview.green_fill(palette) + b"changed--preview")
        self.assertEqual(result["game_test"]["numbers"]["patched_sha256"], preview.digest(preview.green_fill(palette)))


if __name__ == "__main__":
    unittest.main()
