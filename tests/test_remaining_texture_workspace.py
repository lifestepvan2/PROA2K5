import json
import unittest
from unittest.mock import patch

from PIL import Image

import test_uniform_iso_workspace as fixtures
import remaining_texture_workspace as remaining
import texture_iso_workspace as native
import uniform_iso_workspace as uniforms


class RemainingTextureTests(unittest.TestCase):
    def setUp(self):
        fixtures.UniformWorkspaceTests.setUp(self)
        patch.object(remaining, "resolve_names", return_value={int(self.key, 16): "uh021.iff"}).start()

    def export(self):
        return remaining.export(self.source, self.workspace, self.cache, self.legacy)

    def test_arena_ownership_uses_home_team_mapping_not_asset_number(self):
        path, group, slot = remaining.location("s028.iff", "floor", "sponsor_logo", "SCNE")
        self.assertEqual((group, slot), ("arenas", 1))
        self.assertIn("slot_001_Blazers", str(path))
        self.assertIn("sponsors_and_signage", str(path))
        self.assertEqual(remaining.location("s028n.iff", "", "", "SCNE")[2], 1)
        self.assertIsNone(remaining.location("s711.iff", "", "", "SCNE")[2])
        self.assertEqual(remaining.location("cs_intro.iff", "", "", "CNSR")[1], "cinematics")

    def test_manual_master_compiles_without_legacy_and_survives_rename_and_reexport(self):
        report = self.export()
        self.assertEqual(report["masters"], 1)
        row = remaining.load_manifest(self.workspace)["sources"][0]
        master = self.workspace / row["path"]
        self.assertEqual(master.read_bytes(), self.manual.read_bytes())
        with patch.object(uniforms, "dump_files", side_effect=AssertionError("No dumps during compilation")):
            with self.source.open("rb") as stream:
                patches, report = native.prepare(stream, self.workspace)
        self.assertEqual(len(patches), 1)
        self.assertTrue(report["remaining"]["complete"])
        moved = master.with_name(f"my_art__512x256__{row['id']}.png")
        master.rename(moved)
        Image.new("RGB", (128, 64), (5, 6, 7)).save(moved)
        before = moved.read_bytes()
        self.export()
        self.assertEqual(moved.read_bytes(), before)
        self.assertEqual(remaining.load_manifest(self.workspace)["sources"][0]["path"],
                         str(moved.relative_to(self.workspace)))

    def test_unmatched_edit_blocks_manifest_publication(self):
        self.dump.write_bytes(self.manual.read_bytes())
        with self.assertRaisesRegex(ValueError, "unmapped manual"):
            self.export()
        self.assertFalse((self.workspace / remaining.MANIFEST).exists())
        self.assertTrue((self.workspace / "_iso_texture_review.json").exists())

    def test_conflicts_require_explicit_valid_choice_and_keep_superseded_provenance(self):
        manual = {"a": {"signature": "one"}, "b": {"signature": "two"}}
        self.assertEqual(remaining.select_seed("12345678", {"a", "b"}, manual, {}), (None, True))
        self.assertEqual(remaining.select_seed("12345678", {"a", "b"}, manual, {"12345678": "b"}),
                         ("b", False))
        self.assertEqual(remaining.select_seed("12345678", {"a", "b"}, manual, {"12345678": None}),
                         (None, False))
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            remaining.select_seed("12345678", {"a", "b"}, manual, {"12345678": "missing"})
        (self.workspace / remaining.POLICY).write_text(json.dumps({"schema": 0, "choices": {}}))
        with self.assertRaisesRegex(ValueError, "invalid native migration"):
            remaining.migration_choices(self.workspace)

    def test_physical_aliases_do_not_merge_independent_palettes(self):
        first = [{"width": 1, "height": 1, "pixel_offset": 112, "palette_offset": 1024}]
        second = [dict(first[0], palette_offset=2048)]
        self.assertNotEqual(remaining.footprint(first, "linear", 0, 4096),
                            remaining.footprint(second, "linear", 0, 4096))

    def test_reviewed_conflict_publishes_one_choice_and_accounts_for_superseded_source(self):
        manual, seeds, warnings = uniforms.legacy_seed_index([self.legacy])
        rejected = dict(manual[self.dump_key])
        rejected["image"] = Image.new("RGBA", (16, 16), (90, 4, 5, 255))
        rejected["signature"] = (True, native.image_digest(rejected["image"]))
        manual["second-source"] = rejected
        for keys in seeds.values():
            keys.add("second-source")
        with patch.object(uniforms, "legacy_seed_index", return_value=(manual, seeds, warnings)):
            with self.assertRaisesRegex(ValueError, "1 artwork conflicts"):
                self.export()
            review = json.loads((self.workspace / "_iso_texture_review.json").read_text())
            token = review["conflicts"][0]["id"]
            (self.workspace / remaining.POLICY).write_text(json.dumps({
                "schema": 1, "source_sha256": native.SOURCE_SHA256, "choices": {token: self.dump_key}}))
            self.export()
        manifest = remaining.load_manifest(self.workspace)
        row = manifest["sources"][0]
        self.assertEqual(row["selected_legacy_key"], self.dump_key)
        self.assertEqual(len(row["legacy_seeds"]), 2)
        self.assertEqual(len(manifest["migration"]["manual_sources"]), 2)
        self.assertEqual((self.workspace / row["path"]).read_bytes(), self.manual.read_bytes())
        self.assertFalse((self.workspace / "_native_export_pending").exists())

    def test_pristine_source_is_verified_before_publication(self):
        with patch.object(native, "hash_stream", return_value="wrong"):
            with self.assertRaisesRegex(ValueError, "verified pristine"):
                self.export()
        self.assertFalse((self.workspace / remaining.MANIFEST).exists())


if __name__ == "__main__":
    unittest.main()
