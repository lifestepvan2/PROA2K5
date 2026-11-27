import json
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import texture_iso_workspace as native
import texture_catalogue as catalogue
from inventory_lettering_iso import asset_hash
from test_gs_texture import fixture
from test_texture_catalogue import pointer
from test_vc_lz import literal_stream
from vc_lz import decode, validate_inplace


class NativeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "source.iso"
        data, _ = fixture()
        data = bytearray(data)
        data[12:16] = b"TXTR"
        pointer(data, 16, 32)
        pointer(data, 20, 48)
        data[32:42] = "logo\0".encode("utf-16le")
        self.data = bytes(data)
        self.source.write_bytes(struct.pack("<4s7I", b"TXTR", len(data), 112, 180224, 0, 0, 0, 0) + data)
        self.key = f"{asset_hash('uh021.iff'):08x}"
        self.cache = self.root / "catalogue.sqlite"
        connection = sqlite3.connect(self.cache)
        catalogue.create_database(connection)
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("schema", str(catalogue.SCHEMA)), ("source_sha256", native.SOURCE_SHA256), ("complete", "true")])
        connection.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)", (
            self.key, 0, "uh021.iff", 0, self.source.stat().st_size, "test", "{}", "inventoried", ""))
        for ordinal, name in enumerate(("logo", "coachmodel", "unif", "short")):
            connection.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                self.key, ordinal, "TXTR" if ordinal == 0 else "SHAP", name, 0,
                len(data) if ordinal == 0 else 0, 112, 180224 if ordinal == 0 else 0,
                0, 0, native.digest(data), native.digest(data), "inventoried", ""))
        connection.commit()
        connection.close()
        self.seeds = self.root / "seeds.json"
        self.seeds.write_text(json.dumps({"schema": 1, "source_sha256": native.SOURCE_SHA256, "images": {}}))
        self.addCleanup(patch.stopall)
        patch.object(native, "SEEDS", self.seeds).start()
        patch.object(native, "read_archive", return_value={int(self.key, 16): (0, self.source.stat().st_size)}).start()
        patch.object(native, "hash_stream", return_value=native.SOURCE_SHA256).start()
        patch.object(native, "proa_slots", return_value={}).start()
        patch("texlib.dump_files", side_effect=AssertionError("Must not use PCSX2 dumps")).start()
        native.export(self.source, self.workspace, self.cache)
        self.manifest_path = self.workspace / native.MANIFEST
        self.manifest = json.loads(self.manifest_path.read_text())
        self.row = self.manifest["sources"][0]
        self.master = self.workspace / self.row["path"]

    def edit(self):
        Image.new("RGBA", (256, 128), (30, 70, 120, 255)).save(self.master)

    def prepare(self, **kwargs):
        with self.source.open("rb") as stream:
            return native.prepare(stream, self.workspace, **kwargs)

    def test_native_export_and_noop_need_no_dumps_and_preserve_source(self):
        before = self.source.read_bytes()
        patches, report = self.prepare()
        self.assertEqual(patches, [])
        self.assertEqual(report["masters"], 1)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertIn("__512x256__", self.master.name)

    def test_alternate_copy_receives_manual_master_edits(self):
        import uniform_iso_workspace

        self.edit()
        (self.workspace / "_iso_uniforms.json").write_text("{}")
        uniforms = {"sources": [], "packages": [], "migration": {}}
        copies = [native.uniform_slot_copies.UniformCopy(21, "Falcons", "ua021.iff", "r2h021.iff")]
        offset = self.row["iso_offset"] + self.row["chunk_offset"] + 32
        copied_patch = (0, b"before", b"after")
        with patch.object(uniform_iso_workspace, "load_manifest", return_value=uniforms), \
                patch.object(native.uniform_slot_copies, "rules", return_value=copies), \
                patch.object(native.uniform_slot_copies, "inherited_offsets", return_value={offset}), \
                patch.object(native.uniform_slot_copies, "compose",
                             return_value=([copied_patch], [{"destination": "r2h021.iff"}])) as compose:
            with self.assertRaisesRegex(ValueError, "require archive repacking"):
                self.prepare()
            patches, report = self.prepare(repack_archive=True)
        self.assertEqual(patches, [copied_patch])
        self.assertEqual(report["uniform_copies"], [{"destination": "r2h021.iff"}])
        self.assertEqual(len(compose.call_args.args[1]), 1)
        self.assertEqual(compose.call_args.args[2], copies)

    def test_moved_renamed_master_survives_reexport_and_updates_all_mips(self):
        self.edit()
        moved = self.workspace / "my_folder" / f"my_label__512x256__{self.row['id']}.png"
        moved.parent.mkdir()
        self.master.rename(moved)
        before = moved.read_bytes()
        native.export(self.source, self.workspace, self.cache)
        self.assertEqual(moved.read_bytes(), before)
        patches, report = self.prepare()
        self.assertEqual(len(patches), 1)
        self.assertEqual(report["textures"][0]["mips"], 6)
        self.assertEqual(patches[0][2][:112], self.data[:112])

    def test_duplicate_ids_are_errors_and_missing_files_are_ignored(self):
        duplicate = self.master.with_name("another__" + self.row["id"] + ".png")
        shutil.copyfile(self.master, duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.prepare()
        duplicate.unlink()
        self.master.unlink()
        patches, report = self.prepare()
        self.assertEqual(patches, [])
        self.assertEqual(report["masters"], 0)

    def test_valid_id_in_user_underscore_directory_is_included(self):
        self.edit()
        target = self.workspace / "_my_art" / self.master.name.upper()
        target.parent.mkdir()
        self.master.rename(target)
        patches, report = self.prepare()
        self.assertEqual(len(patches), 1)
        self.assertEqual(report["textures"][0]["id"], self.row["id"])

    def test_edited_reference_master_is_patched_by_native_identity(self):
        self.edit()
        self.manifest["sources"][0].update(editable=False, slot=None, asset="hash:" + self.key)
        self.manifest_path.write_text(json.dumps(self.manifest))
        patches, report = self.prepare()
        self.assertEqual(len(patches), 1)
        self.assertEqual(report["textures"][0]["id"], self.row["id"])

    def test_court_and_logo_edits_share_one_resource_without_overwriting(self):
        self.edit()
        painted = bytearray(self.data)
        painted[4] = 123
        edits = [(32, self.data, self.data, bytes(painted), 0, {"asset": "uh021.iff", "compressed": False})]
        patches, report = self.prepare(court_edits=edits)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0][2][4], 123)
        self.assertEqual(len(report["courts"]), 1)

    def test_skin_automation_takes_precedence_only_at_controlled_pixels(self):
        self.edit()
        self.manifest["sources"][0]["group"] = "players"
        self.manifest_path.write_text(json.dumps(self.manifest))
        painted = bytearray(self.data)
        position = 112
        painted[position:position + 3] = b"\x20\x40\x60"
        edits = [(32, self.data, self.data, bytes(painted), 0,
                  {"asset": "uh021.iff", "compressed": False, "modifier": "skin_tones"})]
        patches, report = self.prepare(texture_edits=edits)
        self.assertIn(self.row["id"], report["masters_with_automated_controls"])
        def pixels(data):
            image = catalogue.texture_images(data, 112, 180224, self.row["descriptor"],
                                             self.row["descriptor_offsets"])[0][0]
            return native.np.asarray(native.display(image)).astype(int)
        before, control, result = pixels(self.data), pixels(bytes(painted)), pixels(patches[0][2])
        mask = native.np.any(before != control, axis=2)
        self.assertTrue(mask.any())
        self.assertLessEqual(native.np.abs(result[mask] - control[mask]).max(), 3)
        self.assertLessEqual(native.np.abs(result[~mask] - [30, 70, 120, 255]).max(), 3)

    def test_player_master_preserves_zero_alpha_rgb(self):
        self.manifest["sources"][0]["group"] = "players"
        self.manifest["sources"][0]["texture"] = "face"
        self.manifest_path.write_text(json.dumps(self.manifest))
        Image.new("RGBA", (512, 256), (80, 120, 160, 0)).save(self.master)
        patches, report = self.prepare()
        image = catalogue.texture_images(patches[0][2], 112, 180224, self.row["descriptor"],
                                         self.row["descriptor_offsets"])[0][0]
        self.assertEqual(image["rgba"][:4], bytes((80, 120, 160, 0)))
        self.assertEqual(report["textures"][0]["rgb_rmse_all"], 0)

    def test_manual_jersey_master_wins_over_overlapping_controls(self):
        self.edit()
        self.manifest["sources"][0]["group"] = "uniforms"
        self.manifest_path.write_text(json.dumps(self.manifest))
        painted = bytearray(self.data)
        painted[112:115] = b"\x20\x40\x60"
        edits = [(32, self.data, self.data, bytes(painted), 0,
                  {"asset": "uh021.iff", "compressed": False})]
        patches, report = self.prepare(texture_edits=edits)
        expected = self.prepare()[0]
        self.assertEqual(patches, expected)
        self.assertEqual(report["masters_with_automated_controls"], [])

    def test_automation_applies_when_master_is_unmodified(self):
        painted = bytearray(self.data)
        position = 112
        painted[position:position + 3] = b"\x20\x40\x60"
        edits = [(32, self.data, self.data, bytes(painted), 0,
                  {"asset": "uh021.iff", "compressed": False})]
        patches, _ = self.prepare(texture_edits=edits)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0][2], bytes(painted))

    def test_explicit_palette_policy_and_invalid_policy(self):
        self.edit()
        path = self.workspace / "_iso_encoding.json"
        path.write_text(json.dumps({"schema": 1, "palette_colors": {self.row["id"]: 32}}))
        _, report = self.prepare()
        self.assertEqual(report["textures"][0]["palette_colors"], 32)
        for invalid in ([], None, {"schema": True, "palette_colors": {}},
                        {"schema": 1, "palette_colors": {self.row["id"]: 33}},
                        {"schema": 1, "palette_colors": {"ffffffff": 32}}):
            with self.subTest(policy=invalid):
                path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, "palette policy"):
                    self.prepare()

    def test_all_capacity_failures_are_reported_but_block_publication(self):
        self.edit()
        self.manifest["sources"][0]["compressed"] = True
        self.manifest_path.write_text(json.dumps(self.manifest))
        with patch.object(native, "source_bytes", return_value=(literal_stream(self.data), self.data)), \
                patch.object(native, "rebuild_tail", side_effect=ValueError("test capacity")):
            patches, report = self.prepare(collect_failures=True)
            self.assertEqual(patches, [])
            self.assertEqual(len(report["capacity_failures"]), 1)
            with self.assertRaisesRegex(ValueError, "exceed fixed capacity"):
                self.prepare()

    def test_resized_compressed_resource_updates_header_and_uses_verified_cache(self):
        body = literal_stream(self.data)
        header = struct.pack("<4s7I", b"TXTR", len(body), 112, 180224, 0xFEEDBEEF, 16, 0, 0)
        self.source.write_bytes(header + body)
        row = self.manifest["sources"][0]
        row.update(stored=len(body), compressed=True, scratch=16, stored_sha256=native.digest(body),
                   asset_size=32 + len(body))
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.edit()
        with patch.object(native, "read_archive", return_value={int(self.key, 16): (0, 32 + len(body))}):
            patches, report = self.prepare(repack_archive=True)
            cached_patches, _ = self.prepare(repack_archive=True)
        self.assertEqual(patches, cached_patches)
        fields = struct.unpack("<4s7I", patches[0][2])
        self.assertEqual((patches[0][0], fields[0], fields[2:5]), (0, b"TXTR", (112, 180224, 0xFEEDBEEF)))
        self.assertEqual(fields[1], len(patches[1][2]))
        self.assertLess(fields[1], len(body))
        validate_inplace(patches[1][2], decode(patches[1][2], len(self.data))[0], fields[5])
        self.assertEqual(report["resources"][0]["new_stored"], fields[1])

    def test_default_palette_is_explicit_and_per_master_policy_takes_precedence(self):
        self.edit()
        _, report = self.prepare(palette_colors=64)
        self.assertEqual(report["textures"][0]["palette_colors"], 64)
        (self.workspace / "_iso_encoding.json").write_text(json.dumps(
            {"schema": 1, "palette_colors": {self.row["id"]: 32}}))
        _, report = self.prepare(palette_colors=64)
        self.assertEqual(report["textures"][0]["palette_colors"], 32)
        with self.assertRaisesRegex(ValueError, "default native palette"):
            self.prepare(palette_colors=33)


if __name__ == "__main__":
    unittest.main()
