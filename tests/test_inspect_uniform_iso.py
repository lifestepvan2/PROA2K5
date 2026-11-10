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
import inspect_uniform_iso as inspector
import texture_catalogue as native
from test_gs_texture import fixture


class UniformInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data, expected = fixture()
        self.iso = self.root / "source.iso"
        self.iso.write_bytes(b"\0" * 32 + data)
        self.cache = self.root / "cache.sqlite"
        connection = sqlite3.connect(self.cache)
        native.create_database(connection)
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("schema", str(native.SCHEMA)), ("source_sha256", native.SOURCE_SHA256), ("complete", "true")])
        connection.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)", (
            "00000001", 0, "uh021.iff", 0, len(data) + 32, "test",
            json.dumps(native.ownership("uh021.iff", {})), "inventoried", ""))
        connection.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "00000001", 0, "TXTR", "unif", 0, len(data), 112, 180224, 0, 0, "test", "test", "inventoried", ""))
        connection.execute("INSERT INTO textures VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            "native-id", "00000001", 0, 48, "unif", 512, 256, 19, "", "blocked", "packed layout"))
        connection.commit()
        connection.close()
        self.dump = self.root / "original.png"
        Image.frombytes("RGBA", (512, 256), expected[0]).save(self.dump)
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        row = dict(key="key", original_digest=native.pixel_digest(512, 256, expected[0]),
                   status="unresolved", blocker="uniform-transfer-or-inheritance-unproved",
                   manual_edit="1", generated="0", path="artist-file-not-read",
                   label="PistonsJerseyHome", role="MASTER")
        for name in ("workspace_mapping.csv", "active_targets.csv"):
            inspector.write_csv(self.baseline / name, tuple(row), [row])
        self.addCleanup(patch.stopall)
        patch.object(inspector, "read_archive", return_value={1: (0, len(data) + 32)}).start()
        patch.object(inspector, "resolve_names", return_value={1: "uh021.iff"}).start()
        patch.object(inspector, "hash_stream", return_value=native.SOURCE_SHA256).start()
        patch.object(inspector, "body_materials", return_value=[]).start()
        patch.object(inspector, "dump_files", return_value={"key": self.dump}).start()

    def test_exact_native_mips_are_verified_against_clean_dump_not_artist_file(self):
        output = self.root / "report"
        before = self.iso.read_bytes(), self.dump.read_bytes()
        result = inspector.inspect(self.iso, self.cache, self.baseline, output)
        self.assertEqual(result["images"], 6)
        self.assertEqual(result["previous_blockers_now_matching"], {"uniform-transfer-or-inheritance-unproved": 1})
        self.assertEqual(result["previously_blocked_manual_sources_matching"], 1)
        self.assertEqual(before, (self.iso.read_bytes(), self.dump.read_bytes()))
        row = inspector.read_csv(output / "uniform_coverage.csv")[0]
        self.assertEqual((row["native_assets"], row["native_textures"], row["native_levels"]), ("uh021.iff", "unif", "0"))
        self.assertTrue((output / "native_uniform_mips.png").is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            inspector.inspect(self.iso, self.cache, self.baseline, output)
        self.cache.unlink()

    def test_stale_original_dump_is_rejected_not_reported_as_exact(self):
        Image.new("RGBA", (512, 256)).save(self.dump)
        output = self.root / "report"
        with self.assertRaisesRegex(ValueError, "changed since baseline"):
            inspector.inspect(self.iso, self.cache, self.baseline, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
