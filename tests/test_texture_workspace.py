import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import texture_workspace as ws


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.dump = self.root / "dump.png"
        Image.new("RGBA", (4, 4), (20, 40, 60, 128)).save(self.dump)
        self.key = "test-dump-key"
        self.token = ws.token(self.key)
        self.row = dict(key=self.key, family="test", w=4, h=4, group="ui_fragments", sub="", label="Original")
        self.addCleanup(patch.stopall)
        patch.object(ws, "dump_files", return_value={self.key: self.dump}).start()
        patch.object(ws, "managed_keys", return_value={}).start()
        patch.object(ws, "catalog", return_value=[self.row]).start()
        patch.object(ws.uniform_labels, "report").start()

    def export(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ws.export(self.workspace)

    def images(self):
        return list(self.workspace.rglob("*.png"))

    def test_repeated_unchanged_exports_are_idempotent(self):
        self.export()
        before = {path: path.read_bytes() for path in self.workspace.rglob("*") if path.is_file()}
        for _ in range(3):
            self.export()
        self.assertEqual(before, {path: path.read_bytes() for path in self.workspace.rglob("*") if path.is_file()})

    def test_repeated_exports_keep_renamed_edited_images_without_duplicates(self):
        self.export()
        original = self.images()[0]
        original_hash = ws.read_manifest(self.workspace)[self.token]["sha1"]
        renamed = self.workspace / f"ArtistPrefix__{self.token}.png"
        original.rename(renamed)
        Image.new("RGB", (4, 4), (200, 1, 2)).save(renamed)
        edited = renamed.read_bytes()
        for _ in range(3):
            self.row["label"] = "NewCatalogPrefix"
            self.export()
            self.assertEqual(self.images(), [renamed])
            self.assertEqual(renamed.read_bytes(), edited)
            self.assertEqual(ws.read_manifest(self.workspace)[self.token]["sha1"], original_hash)

    def test_missing_manifest_adopts_existing_id_and_recovers_original_hash(self):
        self.export()
        original_hash = ws.read_manifest(self.workspace)[self.token]["sha1"]
        existing = self.images()[0]
        renamed = self.workspace / f"MASTER__CustomHome__4x4__{self.token}.png"
        existing.rename(renamed)
        Image.new("RGB", (4, 4), (200, 1, 2)).save(renamed)
        edited = renamed.read_bytes()
        (self.workspace / "_manifest.csv").unlink()
        self.export()
        self.assertEqual(self.images(), [renamed])
        self.assertEqual(renamed.read_bytes(), edited)
        row = ws.read_manifest(self.workspace)[self.token]
        self.assertEqual(row["sha1"], original_hash)
        self.assertEqual(self.workspace / row["relpath"], renamed)
        self.assertNotEqual(ws.sha1(renamed), row["sha1"])

    def test_existing_duplicate_ids_are_reported_not_deleted(self):
        self.export()
        duplicate = self.workspace / f"Duplicate__{self.token}.png"
        duplicate.write_bytes(self.images()[0].read_bytes())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ws.scan(self.workspace)
        self.assertIn("duplicate workspace ID", output.getvalue())
        self.export()
        self.assertEqual(len(self.images()), 2)


class RegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.replacements = self.root / "replacements"
        self.files, self.found, self.manifest, self.mapping = {}, {}, {}, {}
        for key, role, size in (("master", "master", (8, 8)), ("copy", "copy", (8, 8)), ("lod", "lod", (2, 2))):
            dump = self.root / f"{key}.png"
            Image.new("RGBA", size, (120, 50, 30, 128)).save(dump)
            working = self.workspace / f"{role.upper()}__Group__{size[0]}x{size[1]}__{ws.token(key)}.png"
            Image.new("RGBA", size, (120, 50, 30, 255)).save(working)
            self.files[key] = dump
            self.found[ws.token(key)] = working
            self.manifest[ws.token(key)] = {"key": key, "token": ws.token(key), "sha1": ws.sha1(working)}
            self.mapping[key] = {"role": role, "master": "master", "size": f"{size[0]}x{size[1]}"}
        self.addCleanup(patch.stopall)
        patch.object(ws, "REPL_DIR", self.replacements).start()
        patch.object(ws, "dump_files", return_value=self.files).start()
        patch.object(ws, "managed_keys", return_value={}).start()
        patch.object(ws, "read_manifest", return_value=self.manifest).start()
        patch.object(ws, "scan", return_value=self.found).start()
        patch.object(ws.uniform_labels, "analyse_groups", return_value=(self.mapping, [])).start()

    def sync(self, force=False, dry=False):
        with contextlib.redirect_stdout(io.StringIO()):
            ws.sync(self.workspace, "stretch", dry, force)

    def test_force_generates_unchanged_master_children_and_normal_sync_reverts(self):
        self.sync()
        self.assertFalse(self.replacements.exists())
        self.sync(force=True)
        self.assertEqual({p.name for p in self.replacements.iterdir()}, {"copy.png", "lod.png"})
        with Image.open(self.replacements / "lod.png") as image:
            self.assertEqual(image.size, (2, 2))
            self.assertEqual(image.getpixel((0, 0)), (119, 49, 29, 128))
        self.sync()
        self.assertEqual(list(self.replacements.iterdir()), [])

    def test_force_bypasses_cache_refreshes_children_and_preserves_master(self):
        master = self.found[ws.token("master")]
        before = master.read_bytes()
        Image.new("RGB", (2, 2), "blue").save(self.found[ws.token("lod")])
        self.sync(force=True)
        Image.new("RGBA", (2, 2), "blue").save(self.replacements / "lod.png")
        self.sync(force=True)
        with Image.open(self.replacements / "lod.png") as image:
            self.assertEqual(image.getpixel((0, 0)), (119, 49, 29, 128))
        self.assertEqual(before, master.read_bytes())
        with Image.open(self.found[ws.token("lod")]) as image:
            self.assertEqual(image.getpixel((0, 0)), (120, 50, 30, 255))

    def test_generated_workspace_copy_does_not_become_edited_source(self):
        master = self.found[ws.token("master")]
        original = master.read_bytes()
        Image.new("RGB", (8, 8), (1, 200, 3)).save(master)
        self.sync(force=True)
        with Image.open(self.found[ws.token("copy")]) as image:
            self.assertEqual(image.getpixel((0, 0)), (1, 200, 3, 255))
        master.write_bytes(original)
        self.sync()
        self.assertEqual(list(self.replacements.iterdir()), [])
        with Image.open(self.found[ws.token("copy")]) as image:
            self.assertEqual(image.getpixel((0, 0)), (120, 50, 30, 255))

    def test_newly_linked_lod_is_generated_from_an_edited_cached_master(self):
        master = self.found[ws.token("master")]
        Image.new("RGB", (8, 8), (1, 200, 3)).save(master)
        self.sync()
        (self.replacements / "lod.png").unlink()
        self.sync()
        with Image.open(self.replacements / "lod.png") as image:
            self.assertEqual(image.getpixel((0, 0)), (1, 199, 3, 128))

    def test_force_prefers_master_over_edited_copy(self):
        Image.new("RGB", (8, 8), (1, 200, 3)).save(self.found[ws.token("copy")])
        self.sync()
        self.assertTrue((self.replacements / "master.png").exists())
        self.sync(force=True)
        self.assertFalse((self.replacements / "master.png").exists())
        with Image.open(self.replacements / "copy.png") as image:
            self.assertEqual(image.getpixel((0, 0)), (120, 50, 30, 128))

    def test_force_dry_run_has_no_side_effects_and_managed_targets_win(self):
        self.sync(force=True, dry=True)
        self.assertFalse(self.replacements.exists())
        self.assertFalse((self.workspace / "_state.json").exists())
        with patch.object(ws, "managed_keys", return_value={"lod": "pipeline"}):
            self.sync(force=True)
        self.assertFalse((self.replacements / "lod.png").exists())
        self.assertTrue((self.replacements / "copy.png").exists())

    def test_force_missing_master_warns_without_copy_fallback(self):
        self.found.pop(ws.token("master"))
        state = {"lod": "auto:old"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = ws.sync_uniform_lods(self.workspace, self.mapping, self.manifest, self.found,
                                          self.files, {}, state, "stretch", False, True)
        self.assertEqual(result, (0, 0))
        self.assertEqual(state, {"lod": "auto:old"})
        self.assertIn("MASTER is missing", output.getvalue())

    def test_cli_rejects_force_for_export(self):
        with patch.object(sys, "argv", ["texture_workspace.py", "export", "--force-regen"]), \
                contextlib.redirect_stderr(io.StringIO()), patch.object(ws, "export") as export:
            with self.assertRaises(SystemExit):
                ws.main()
            export.assert_not_called()

    def test_cli_forwards_force_and_dry_run(self):
        with patch.object(sys, "argv", ["texture_workspace.py", "sync", "--force-regen", "--dry-run"]), \
                patch.object(ws, "sync") as sync:
            ws.main()
            sync.assert_called_once_with(ws.DEFAULT_WS, "stretch", True, True)


if __name__ == "__main__":
    unittest.main()
