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

    def test_duplicate_and_missing_ids_are_errors(self):
        duplicate = self.master.with_name("another__" + self.row["id"] + ".png")
        shutil.copyfile(self.master, duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.prepare()
        duplicate.unlink()
        self.master.unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            self.prepare()

    def test_reference_edit_is_not_silently_applied_to_unknown_owner(self):
        self.edit()
        self.manifest["sources"][0].update(editable=False, slot=None, asset="hash:" + self.key)
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "outside current-team"):
            self.prepare()

    def test_court_and_logo_edits_share_one_resource_without_overwriting(self):
        self.edit()
        painted = bytearray(self.data)
        painted[4] = 123
        edits = [(32, self.data, self.data, bytes(painted), 0, {"asset": "uh021.iff"})]
        patches, report = self.prepare(court_edits=edits)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0][2][4], 123)
        self.assertEqual(len(report["courts"]), 1)

    def test_lettering_controls_cannot_silently_recolour_reindexed_master_art(self):
        self.edit()
        painted = bytearray(self.data)
        painted[-4:-1] = b"\x20\x40\x60"
        edits = [(32, self.data, self.data, bytes(painted), 0,
                  {"asset": "uh021.iff", "compressed": False})]
        with self.assertRaisesRegex(ValueError, "Lettering master and colour controls"):
            self.prepare(texture_edits=edits)

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
