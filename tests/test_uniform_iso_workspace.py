import csv
import json
import struct
import sys
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import uniform_iso_workspace as uniforms
import texture_iso_workspace as native
import texture_workspace as legacy
import test_texture_iso_workspace as fixtures


class UniformWorkspaceTests(unittest.TestCase):
    def setUp(self):
        fixtures.NativeWorkspaceTests.setUp(self)
        self.master.rename(self.master.with_name("_reference.png"))
        self.manifest["sources"] = []
        self.manifest_path.write_text(json.dumps(self.manifest))
        patch.object(uniforms, "resolve_names", return_value={int(self.key, 16): "uh021.iff"}).start()
        self.legacy = self.root / "legacy"
        self.legacy.mkdir()
        self.dump = self.root / "dump.png"
        images = native.texture_images(self.data, 112, 180224, 48, [48])[0]
        Image.frombytes("RGBA", (512, 256), images[0]["rgba"]).save(self.dump)
        self.dump_key = "original-original-00002253"
        token = legacy.token(self.dump_key)
        self.manual = self.legacy / "uniforms" / f"MASTER__ClubJersey__512x256__{token}.png"
        self.manual.parent.mkdir()
        native.display(images[0]).save(self.manual)
        sha = legacy.sha1(self.manual)
        Image.new("RGBA", (1024, 512), (20, 100, 160, 255)).save(self.manual)
        with (self.legacy / "_manifest.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=("token", "key", "group", "relpath", "w", "h", "sha1"))
            writer.writeheader()
            writer.writerow(dict(token=token, key=self.dump_key, group="uniforms",
                                 relpath=str(self.manual.relative_to(self.legacy)), w=512, h=256, sha1=sha))
        (self.legacy / "_state.json").write_text("{}")
        patch.object(uniforms, "dump_files", return_value={self.dump_key: self.dump}).start()

    def export(self):
        return uniforms.export(self.source, self.workspace, self.cache, self.legacy)

    def test_native_ownership_handles_slot_ids_all_warmup_and_crowd_families(self):
        for asset in ("uh002.iff", "wh002.iff", "wuh002.iff", "puh002.iff", "suh002.iff",
                      "tuh002.iff", "cscrowd002.iff", "csch002.iff", "cstrainer002.iff"):
            self.assertEqual(uniforms.owner(asset)["slot"], 29)
        self.assertTrue(uniforms.owner("tua600.iff")["warmup"])
        self.assertIsNone(uniforms.owner("tua600.iff")["slot"])
        self.assertEqual(uniforms.owner("selua028.iff")["surface"], "preview")
        with self.assertRaises(ValueError):
            uniforms.owner("p002h.iff")

    def test_manual_default_and_native_mips_are_compiled_without_legacy_inputs(self):
        before = self.manual.read_bytes()
        report = self.export()
        self.assertEqual((report["masters"], report["manual_sources"], report["seeded_masters"]), (1, 1, 1))
        manifest = uniforms.load_manifest(self.workspace)
        row = manifest["sources"][0]
        self.assertIn(f"slot_{row['slot']:03}", row["path"])
        master = self.workspace / row["path"]
        self.assertEqual(master.read_bytes(), before)
        self.assertEqual(len(list((self.workspace / "uniforms").rglob("*.png"))), 1)
        with patch.object(uniforms, "dump_files", side_effect=AssertionError("Compilation needs no dumps")), \
                patch.object(uniforms, "legacy_edits", side_effect=AssertionError("Compilation needs no legacy")):
            with self.source.open("rb") as stream:
                patches, report = native.prepare(stream, self.workspace)
        self.assertEqual(len(patches), 1)
        self.assertEqual(report["textures"][0]["mips"], 6)
        self.assertEqual(report["uniforms"]["masters"], 1)
        self.assertEqual(self.manual.read_bytes(), before)

    def test_existing_native_art_and_renames_survive_reexport_without_dumps(self):
        self.export()
        row = uniforms.load_manifest(self.workspace)["sources"][0]
        master = self.workspace / row["path"]
        moved = master.with_name(f"my_art__512x256__{row['id']}.png")
        master.rename(moved)
        Image.new("RGB", (256, 128), (2, 4, 6)).save(moved)
        before = moved.read_bytes()
        with patch.object(uniforms, "dump_files", side_effect=AssertionError("Reexport needs no dumps")):
            self.export()
        self.assertEqual(moved.read_bytes(), before)
        self.assertEqual(uniforms.load_manifest(self.workspace)["sources"][0]["path"],
                         str(moved.relative_to(self.workspace)))

    def test_unmapped_manual_or_conflicting_copied_art_blocks_before_backup(self):
        self.dump.write_bytes(self.manual.read_bytes())
        with self.assertRaisesRegex(ValueError, "unmapped_manual_edits"):
            self.export()
        self.assertFalse((self.workspace / uniforms.MANIFEST).exists())
        other = self.root / "other"
        import shutil
        shutil.copytree(self.legacy, other)
        copy = other / self.manual.relative_to(self.legacy)
        Image.new("RGBA", (512, 256), (220, 30, 80, 255)).save(copy)
        with self.assertRaisesRegex(ValueError, "Conflicting legacy"):
            uniforms.legacy_edits([self.legacy, other])

    def test_generated_legacy_children_are_not_manual_sources(self):
        state = {"_workspace_auto": {self.dump_key: legacy.sha1(self.manual)}}
        (self.legacy / "_state.json").write_text(json.dumps(state))
        manual, effective, _ = uniforms.legacy_edits([self.legacy])
        self.assertEqual((manual, effective), ({}, {}))

    def test_structurally_verified_unnamed_bundles_export_with_windows_safe_paths(self):
        import sqlite3
        with closing(sqlite3.connect(self.cache)) as connection:
            connection.execute("UPDATE assets SET name=?", (f"hash:{self.key}",))
            connection.commit()
        with patch.object(uniforms, "resolve_names", return_value={}):
            self.export()
        row = uniforms.load_manifest(self.workspace)["sources"][0]
        self.assertIn("unresolved_", row["path"])
        self.assertNotIn(":", row["path"])
        self.assertTrue((self.workspace / row["path"]).is_file())

    def test_equal_pixels_with_independent_palettes_remain_independent_masters(self):
        data = bytearray(self.data)
        struct.pack_into("<Q", data, 80, 19 << 20)
        for palette, expected in ((1000, 1), (2000, 2)):
            images = [[{"width": 1, "height": 1, "rgba": b"\x10\x20\x30\x80",
                        "pixel_offset": 112, "palette_offset": value}] for value in (1000, palette)]
            with patch.object(native, "source_bytes", return_value=(self.data, bytes(data))), \
                    patch.object(uniforms, "descriptors", return_value=[(48, "fan0"), (80, "fan1")]), \
                    patch.object(uniforms, "texture_images",
                                 side_effect=[(image, "linear-shared-indices", 0, 4096) for image in images]):
                with self.source.open("rb") as stream:
                    sources, _, _ = uniforms.inventory(stream, self.cache, set())
            self.assertEqual(len(sources), expected)

    def test_overlap_conflicts_are_explicit_and_unrelated_writes_compose(self):
        self.assertEqual(native.merge_decoded(b"abc", b"xbc", b"aby", "test"), b"xby")
        self.assertEqual(native.merge_decoded(b"abc", b"xbc", b"xbc", "test"), b"xbc")
        with self.assertRaisesRegex(ValueError, "conflicting writes"):
            native.merge_decoded(b"abc", b"xbc", b"ybc", "test")


if __name__ == "__main__":
    unittest.main()
