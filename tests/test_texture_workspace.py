import contextlib
import io
import json
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


class PreviewSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "texture_workspace_ISO"
        self.workspace.mkdir()
        self.replacements = self.root / "replacements"
        self.dumps = {}
        self.sources = []
        self.source_files = {}
        self.addCleanup(patch.stopall)
        patch.object(ws, "REPL_DIR", self.replacements).start()
        patch.object(ws, "dump_files", side_effect=lambda: self.dumps).start()
        patch.object(ws, "managed_keys", return_value={}).start()

    def add_source(self, source_id, key, original, mips=None):
        original_path = self.root / f"{key}.png"
        original.save(original_path)
        self.dumps[key] = original_path
        native = original.copy()
        native.putalpha(255)
        source_path = self.workspace / f"MASTER__{source_id}.png"
        native.save(source_path)
        row = {
            "id": source_id,
            "path": f"native/{source_id}.png",
            "original_digest": ws.pixel_digest(*original.size, original.tobytes()),
            "original_display_digest": ws.iso_workspace.image_digest(native),
            "mip_digests": [ws.pixel_digest(*original.size, original.tobytes())],
        }
        for mip_key, mip_image in (mips or {}).items():
            mip_path = self.root / f"{mip_key}.png"
            mip_image.save(mip_path)
            self.dumps[mip_key] = mip_path
            row["mip_digests"].append(
                ws.pixel_digest(*mip_image.size, mip_image.tobytes())
            )
        self.sources.append(row)
        self.source_files[source_id] = (source_path, source_path.read_bytes())
        self.write_manifests()

    def write_manifests(self):
        for filename in ws.NATIVE_MANIFESTS:
            rows = self.sources if filename == "_iso_textures.json" else []
            manifest = {
                "schema": 1,
                "source_sha256": ws.iso_workspace.SOURCE_SHA256,
                "sources": rows,
            }
            (self.workspace / filename).write_text(json.dumps(manifest), encoding="utf-8")

    def edit(self, source_id, color):
        path, _ = self.source_files[source_id]
        with Image.open(path) as original:
            size = original.size
        Image.new("RGBA", size, color).save(path)

    def sync(self, dry=False, force=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return ws.sync(self.workspace, "stretch", dry, force)

    def test_exact_matching_emits_mips_and_reverts_only_owned_files(self):
        original = Image.new("RGBA", (4, 4), (20, 40, 60, 128))
        mip = ws.lod_from(original, (2, 2))
        self.add_source("11111111", "base-key", original, {"mip-key": mip})
        self.edit("11111111", (1, 2, 3, 255))

        result = self.sync()
        self.assertEqual(result["written"], 2)
        for key in ("base-key", "mip-key"):
            with Image.open(self.replacements / f"{key}.png") as image:
                self.assertEqual(image.getpixel((0, 0)), (1, 2, 3, 128))
        state_path = self.workspace / ws.PREVIEW_STATE
        self.assertEqual(set(json.loads(state_path.read_text())["files"]), {"base-key", "mip-key"})
        self.assertEqual(self.sync()["unchanged"], 2)

        source_path, original_bytes = self.source_files["11111111"]
        source_path.write_bytes(original_bytes)
        self.assertEqual(self.sync()["removed"], 2)
        self.assertFalse((self.replacements / "base-key.png").exists())
        self.assertFalse((self.replacements / "mip-key.png").exists())

    def test_dry_run_does_not_create_replacements_or_state(self):
        self.add_source("11111111", "base-key", Image.new("RGBA", (4, 4), (20, 40, 60, 128)))
        self.edit("11111111", (1, 2, 3, 255))

        result = self.sync(dry=True)
        self.assertEqual(result["written"], 1)
        self.assertFalse(self.replacements.exists())
        self.assertFalse((self.workspace / ws.PREVIEW_STATE).exists())

    def test_fit_modes_and_rgb_alpha_preservation(self):
        original_path = self.root / "fit-original.png"
        Image.new("RGBA", (4, 2), (20, 40, 60, 64)).save(original_path)
        source = Image.new("RGBA", (2, 2), (1, 2, 3, 255))

        contain = ws.convert_image(source, original_path, "contain", True)
        self.assertEqual(contain.getpixel((0, 0))[3], 0)
        self.assertEqual(contain.getpixel((1, 0)), (1, 2, 3, 128))
        cover = ws.convert_image(source, original_path, "cover", True)
        self.assertEqual(cover.getpixel((0, 0)), (1, 2, 3, 128))
        rgb = ws.convert_image(Image.new("RGB", (4, 2), (9, 8, 7)), original_path, "stretch", False)
        self.assertEqual(rgb.getpixel((0, 0)), (9, 8, 7, 64))

    def test_conflicting_native_sources_are_not_arbitrarily_selected(self):
        original = Image.new("RGBA", (4, 4), (20, 40, 60, 128))
        self.add_source("11111111", "shared-key", original)
        self.add_source("22222222", "shared-key", original)
        self.edit("11111111", (1, 2, 3, 255))
        self.edit("22222222", (8, 9, 10, 255))

        result = self.sync()
        self.assertEqual(result["mapping_conflicts"], {"shared-key": ["11111111", "22222222"]})
        self.assertFalse((self.replacements / "shared-key.png").exists())

    def test_unowned_replacement_is_never_overwritten_or_claimed(self):
        self.add_source("11111111", "base-key", Image.new("RGBA", (4, 4), (20, 40, 60, 128)))
        self.edit("11111111", (1, 2, 3, 255))
        self.replacements.mkdir()
        target = self.replacements / "base-key.png"
        target.write_bytes(b"manual replacement")

        result = self.sync()
        self.assertEqual(result["replacement_conflicts"], 1)
        self.assertEqual(target.read_bytes(), b"manual replacement")
        self.assertFalse((self.workspace / ws.PREVIEW_STATE).exists())

    def test_pipeline_managed_key_is_skipped(self):
        self.add_source("11111111", "base-key", Image.new("RGBA", (4, 4), (20, 40, 60, 128)))
        self.edit("11111111", (1, 2, 3, 255))
        with patch.object(ws, "managed_keys", return_value={"base-key": "pipeline"}):
            result = self.sync()
        self.assertEqual(result["managed_skipped"], 1)
        self.assertFalse((self.replacements / "base-key.png").exists())

    def test_cli_uses_native_workspace_for_sync_and_legacy_workspace_for_export(self):
        with patch.object(sys, "argv", ["texture_workspace.py", "sync", "--dry-run"]), \
                patch.object(ws, "sync") as sync:
            ws.main()
            sync.assert_called_once_with(ws.NATIVE_DEFAULT_WS, "stretch", True, False)
        with patch.object(sys, "argv", ["texture_workspace.py", "export"]), \
                patch.object(ws, "export") as export:
            ws.main()
            export.assert_called_once_with(ws.DEFAULT_WS)


if __name__ == "__main__":
    unittest.main()
