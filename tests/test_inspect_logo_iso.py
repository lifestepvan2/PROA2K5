import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_logo_iso as inspector
import test_inspect_uniform_iso as uniform_tests
from test_texture_catalogue import pointer


class LogoInspectionTests(uniform_tests.UniformInspectionTests):
    def setUp(self):
        super().setUp()
        data = bytearray(self.iso.read_bytes())
        data[32 + 12:32 + 16] = b"TXTR"
        pointer(data, 32 + 16, 32 + 32)
        pointer(data, 32 + 20, 32 + 48)
        data[32 + 32:32 + 42] = "unif\0".encode("utf-16le")
        self.iso.write_bytes(data)
        for name in ("active_targets.csv", "workspace_mapping.csv"):
            path = self.baseline / name
            rows = inspector.read_csv(path)
            rows[0]["blocker"] = inspector.BLOCKER
            path.unlink()
            inspector.write_csv(path, tuple(rows[0]), rows)
        self.variants = self.root / "variants.csv"
        row = dict(key="key", team_slot="21", team="Pistons", ref_key="key", mode="A",
                   score="1", x="0", y="0", w="1", h="1", mae="0", content="0.5")
        inspector.write_csv(self.variants, tuple(row), [row])
        self.courts = self.root / "courts.csv"
        inspector.write_csv(self.courts, ("asset", "nba_slot", "nba_team"), [])
        patch.object(inspector, "read_archive", return_value={1: (0, self.iso.stat().st_size)}).start()
        patch.object(inspector, "resolve_names", return_value={1: "uh021.iff"}).start()
        patch.object(inspector, "hash_stream", return_value=inspector.SOURCE_SHA256).start()
        patch.object(inspector, "dump_files", return_value={"key": self.dump}).start()

    def test_exact_native_mips_are_verified_against_clean_dump_not_artist_file(self):
        output = self.root / "report"
        before = self.iso.read_bytes(), self.dump.read_bytes()
        result = inspector.inspect(self.iso, self.cache, self.baseline, output, self.variants, self.courts)
        self.assertEqual((result["targets"], result["exact_targets"]), (1, 1))
        self.assertEqual(result["native_layouts"], {"gs32-upload-64": 1})
        row = inspector.read_csv(output / "logo_coverage.csv")[0]
        self.assertEqual(row["native_textures"], "unif")
        self.assertEqual(row["native_levels"], "0")
        self.assertEqual(result["scene_context_failures"], [])
        self.assertEqual(before, (self.iso.read_bytes(), self.dump.read_bytes()))
        with self.assertRaisesRegex(ValueError, "already exists"):
            inspector.inspect(self.iso, self.cache, self.baseline, output, self.variants, self.courts)
        self.cache.unlink()

    def test_stale_original_dump_is_rejected_not_reported_as_exact(self):
        Image.new("RGBA", (512, 256)).save(self.dump)
        output = self.root / "report"
        with self.assertRaisesRegex(ValueError, "changed since baseline"):
            inspector.inspect(self.iso, self.cache, self.baseline, output, self.variants, self.courts)
        self.assertFalse(output.exists())

    def test_scene_material_to_mesh_part_is_structural_not_a_texture_name_guess(self):
        data = bytearray(448)
        pointer(data, 20, 64)
        struct.pack_into("<I", data, 64 + 28, 1)
        pointer(data, 64 + 32, 144)
        pointer(data, 128 + 8, 400)
        data[400:410] = "wood\0".encode("utf-16le")
        data[128 + 88:128 + 92] = b"\xff\xff\xff\x80"
        pointer(data, 128 + 92, 352)
        struct.pack_into("<I", data, 64 + 44, 1)
        pointer(data, 64 + 48, 224)
        struct.pack_into("<I", data, 224 + 104, 1)
        pointer(data, 224 + 108, 336)
        # A zero-byte mesh stream is valid; the material index is still meaningful.
        materials = inspector.material_consumers(bytes(data), len(data))
        self.assertEqual(materials[0]["name"], "wood")
        self.assertEqual(materials[0]["descriptor"], 352)
        self.assertEqual(materials[0]["mesh_parts"][0]["part"], 0)
        struct.pack_into("<I", data, 336 + 8, 1)
        with self.assertRaisesRegex(ValueError, "invalid material"):
            inspector.material_consumers(bytes(data), len(data))

    def test_equal_pixel_keys_are_retained_without_expanding_the_frozen_cohort(self):
        for name in ("active_targets.csv", "workspace_mapping.csv"):
            path = self.baseline / name
            rows = inspector.read_csv(path)
            rows.extend([dict(rows[0], key="alias"), dict(rows[0], key="not-a-logo", blocker="another-blocker")])
            path.unlink()
            inspector.write_csv(path, tuple(rows[0]), rows)
        with patch.object(inspector, "dump_files", return_value={"key": self.dump, "alias": self.dump}):
            output = self.root / "report"
            result = inspector.inspect(self.iso, self.cache, self.baseline, output, self.variants, self.courts)
        self.assertEqual((result["targets"], result["exact_targets"], result["distinct_original_images"]), (2, 2, 1))
        rows = inspector.read_csv(output / "logo_coverage.csv")
        self.assertEqual({row["key"]: row["content_alias_keys"] for row in rows}, {"key": "alias", "alias": "key"})
        self.assertEqual(inspector.read_csv(output / "native_sources.csv")[0]["dump_keys"], "key;alias")

    def test_source_change_and_protected_output_are_rejected(self):
        output = self.root / "report"
        with patch.object(inspector, "hash_stream", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "ISO changed"):
                inspector.inspect(self.iso, self.cache, self.baseline, output, self.variants, self.courts)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, "outside"):
            inspector.inspect(self.iso, self.cache, self.baseline, self.baseline / "new", self.variants, self.courts)


if __name__ == "__main__":
    unittest.main()
