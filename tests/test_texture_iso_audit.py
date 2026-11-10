import csv
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import texture_catalogue as native
import texture_iso_audit as audit
import texture_workspace as workspace
from test_texture_catalogue import header, texture


class TextureIsoAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ws = self.root / "workspace"
        self.ws.mkdir()
        self.key = "original-dump-key"
        self.token = workspace.token(self.key)
        self.artist = self.ws / f"MASTER__PistonsJerseyHome__2x2__{self.token}.png"
        self.original = self.root / "dump.png"
        data, system, video = texture()
        pixels = native.linear_images(data, system, video, 48)[0][0]["rgba"]
        Image.frombytes("RGBA", (2, 2), pixels).save(self.original)
        Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(self.artist)
        self.manifest = {self.key: {
            "token": self.token, "key": self.key, "group": "uniforms",
            "relpath": self.artist.name, "w": 2, "h": 2, "sha1": "unedited-baseline-hash"}}
        with (self.ws / "_manifest.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(self.manifest[self.key]))
            writer.writeheader()
            writer.writerow(self.manifest[self.key])
        (self.ws / "_state.json").write_text(json.dumps({self.key: "prior-sync-hash"}))
        self.cache = self.root / "cache.sqlite"
        connection = sqlite3.connect(self.cache)
        native.create_database(connection)
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("schema", str(native.SCHEMA)), ("source_sha256", native.SOURCE_SHA256), ("complete", "true")])
        for key, name in (("aa", "seluh021.iff"), ("bb", "uh004.iff")):
            connection.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)", (
                key, 0, name, 0, len(data), "test-hash",
                json.dumps(native.ownership(name, {})), "inventoried", ""))
            native.add_resource(connection, key, 0, header(b"TXTR", data, system, video), 0, data)
        connection.commit()
        connection.close()

    def run_audit(self, **kwargs):
        return audit.audit(self.cache, self.ws, self.root / "report",
                           files={self.key: self.original}, replacements={self.key: self.artist},
                           managed={}, **kwargs)

    def test_exact_original_match_retains_aliases_and_preserves_every_artist_byte(self):
        before = audit.snapshot(self.ws)
        summary = self.run_audit()
        self.assertEqual(summary["manual_sources"], 1)
        self.assertEqual(summary["workspace_entries"], 1)
        self.assertEqual(summary["active_mapping_status"], {"exact": 1})
        self.assertTrue(summary["workspace_unchanged"])
        self.assertEqual(before, audit.snapshot(self.ws))
        with (self.root / "report" / "workspace_mapping.csv").open(encoding="utf-8") as file:
            row = next(csv.DictReader(file))
        self.assertEqual(row["native_count"], "2")
        self.assertEqual(set(row["native_assets"].split(";")), {"seluh021.iff", "uh004.iff"})
        self.assertEqual(len(json.loads(row["native_context"])), 2)
        self.assertIn("multiple native team owners", row["label_review"])
        self.assertTrue((self.root / "report" / "review_batch_001.png").is_file())
        self.assertTrue((self.root / "report" / "review_questions.csv").is_file())
        # A caller may delete/move the cache immediately on Windows: no connection leaked.
        self.cache.unlink()

    def test_missing_original_never_uses_artist_or_replacement_pixels_as_evidence(self):
        rows = audit.build_rows(self.manifest, {self.token: [self.artist]}, {}, {},
                                {self.key: self.artist}, {}, {})
        self.assertEqual(rows[0]["status"], "unresolved")
        self.assertEqual(rows[0]["blocker"], "missing-original-dump")
        self.assertEqual(rows[0]["native_count"], 0)

    def test_duplicate_ids_are_visible_and_never_chosen_by_timestamp(self):
        duplicate = self.ws / f"other__{self.token}.png"
        duplicate.write_bytes(self.artist.read_bytes())
        _, found, warnings = audit.read_workspace(self.ws)
        self.assertEqual(len(found[self.token]), 2)
        self.assertTrue(warnings)
        rows = audit.build_rows(self.manifest, found, {}, {self.key: self.original}, {}, {}, {})
        self.assertEqual(rows[0]["blocker"], "duplicate-workspace-id")

    def test_generated_children_are_not_manual_source_edits(self):
        state = {"_workspace_auto": {self.key: workspace.sha1(self.artist)}}
        rows = audit.build_rows(self.manifest, {self.token: [self.artist]}, state,
                                {self.key: self.original}, {}, {}, {})
        self.assertEqual((rows[0]["manual_edit"], rows[0]["generated"]), (0, 1))

    def test_missing_managed_and_unknown_replacement_are_accounted_for(self):
        rows = audit.build_rows({}, {}, {}, {}, {"unknown": self.artist},
                                {"missing-00001dd3": "faces/icons"}, {})
        self.assertEqual({row["key"] for row in rows}, {"unknown", "missing-00001dd3"})
        missing = next(row for row in rows if row["managed"])
        self.assertFalse(missing["replacement_present"])
        self.assertTrue(missing["reason"])
        with patch.object(workspace.faces, "face_keys", return_value=(
            [({"proa_id": "no-such-input"}, ["missing-00001dd3"])], [])):
            report = audit.missing_inputs({"missing-00001dd3": "faces/icons"}, {})
        self.assertEqual(report[0]["reason"], "headshot input missing")

    def test_role_link_is_only_candidate_not_confirmed_native_mapping(self):
        master = self.manifest[self.key]
        child_key = "child"
        child = self.ws / f"LOD__PistonsJerseyHome__1x1__{workspace.token(child_key)}.png"
        Image.new("RGBA", (1, 1)).save(child)
        manifest = {**self.manifest, child_key: {**master, "key": child_key,
                    "token": workspace.token(child_key), "relpath": child.name}}
        rows = audit.build_rows(manifest, {self.token: [self.artist], workspace.token(child_key): [child]},
                                {}, {self.key: self.original}, {}, {}, {})
        row = next(row for row in rows if row["key"] == child_key)
        self.assertEqual(row["inherited_from"], self.key)
        self.assertEqual(row["status"], "unresolved")
        self.assertEqual(row["native_count"], 0)
        self.assertEqual(row["label_review"], "")

    def test_portrait_pid_conflict_is_not_promoted_to_an_exact_mapping(self):
        row = dict(key=self.key, status="unresolved", blocker="portrait-source-unproved",
                   reason="", native_ids="", native_names="", candidate_native_ids="", label_review="")
        sources = {"candidate": dict(id="candidate", name="0005", asset_hash="35cb8d72")}
        with patch.object(workspace.faces, "face_keys", return_value=(
            [({"pid": "5", "proa_id": "test"}, [self.key])], [])):
            result = audit.portrait_rows([row], sources)
        self.assertEqual(row["blocker"], "portrait-pid-dump-conflict")
        self.assertEqual(row["status"], "unresolved")
        self.assertEqual(row["candidate_native_ids"], "candidate")
        self.assertFalse(result[0]["pid_descriptor_matches"])

    def test_bounded_review_and_existing_output_protection(self):
        summary = self.run_audit(review_limit=0)
        self.assertEqual(summary["review"]["pictured"], 0)
        self.assertGreater(summary["review"]["questions"], 0)
        self.assertFalse(list((self.root / "report").glob("*.png")))
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.run_audit()
        with self.assertRaisesRegex(ValueError, "outside"):
            audit.audit(self.cache, self.ws, self.ws / "report", files={}, replacements={}, managed={})

    def test_wrong_source_cache_is_rejected_before_output(self):
        connection = sqlite3.connect(self.cache)
        connection.execute("UPDATE metadata SET value='wrong' WHERE key='source_sha256'")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(ValueError, "wrong-source"):
            self.run_audit()
        self.assertFalse((self.root / "report").exists())


if __name__ == "__main__":
    unittest.main()
