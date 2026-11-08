import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import uniform_labels as labels
import texture_workspace as workspace


class OrganisationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = []
        for token, role, label, size in (
            ("12345678", "MASTER", "PistonsJerseyHome", (8, 8)),
            ("23456789", "COPY", "PistonsJerseyHome", (8, 8)),
            ("34567890", "LOD", "PistonsJerseyHome", (2, 2)),
            ("45678901", "MASTER", "JazzAway1", (8, 8)),
            ("56789012", "MASTER", "Unsorted1", (8, 8)),
        ):
            path = self.root / "uniforms" / labels.role_name(role, label, f"{size[0]}x{size[1]}", token)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", size, (50, 80, 100)).save(path)
            self.rows.append({"token": token, "key": f"key-{token}", "group": "uniforms",
                              "relpath": str(path.relative_to(self.root)),
                              "w": size[0], "h": size[1], "sha1": workspace.sha1(path)})
        self.write_manifest()

    def write_manifest(self):
        with (self.root / "_manifest.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def organise(self, dry=False):
        with contextlib.redirect_stdout(io.StringIO()):
            labels.cmd_organise(self.root, dry)

    def test_team_detection_is_conservative(self):
        for label, expected in (("TimberwolvesShortsAway", "Timberwolves"),
                                ("76ersWUtorso1", "76ers"), ("GrizzliesHome1", "Grizzlies"),
                                ("UnknownJerseyHome", None), ("Legends1", None), ("JazzSomething", None)):
            self.assertEqual(labels.team_folder(label), expected)

    def test_sort_preserves_content_labels_mapping_and_unknown_paths(self):
        mapping = labels.analyse_groups(self.root)
        before = {token: entry["path"].read_bytes() for token, entry in labels.role_files(self.root).items()}
        self.organise()
        entries = labels.role_files(self.root)
        self.assertEqual(before, {token: entry["path"].read_bytes() for token, entry in entries.items()})
        self.assertEqual(mapping, labels.analyse_groups(self.root))
        self.assertEqual(entries["12345678"]["path"].parent.name, "Pistons")
        self.assertEqual(entries["45678901"]["path"].parent.name, "Jazz")
        self.assertEqual(entries["56789012"]["path"].parent.name, "uniforms")
        rows = labels.token_rows(self.root)
        for token, entry in entries.items():
            self.assertEqual(self.root / rows[token]["relpath"], entry["path"])
        manifest = (self.root / "_manifest.csv").read_bytes()
        self.organise()
        self.assertEqual((self.root / "_manifest.csv").read_bytes(), manifest)
        marked = workspace.mark_uniform_roles(
            [{"key": "key-12345678", "group": "old", "sub": "", "label": "old"}], self.root)
        self.assertEqual(marked[0]["sub"], "Pistons")

    def test_dry_run_changes_nothing(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.organise(dry=True)
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes()
                                  for p in self.root.rglob("*") if p.is_file()})

    def test_link_and_relabel_use_team_folders(self):
        with contextlib.redirect_stdout(io.StringIO()):
            labels.cmd_link(self.root, "34567890", "12345678")
        self.assertEqual(labels.role_files(self.root)["34567890"]["path"].parent.name, "Pistons")
        with contextlib.redirect_stdout(io.StringIO()):
            labels.cmd_relabel(self.root, "PistonsJerseyHome", "LakersJerseyHome")
        self.assertTrue(all(entry["path"].parent.name == "Lakers"
                            for entry in labels.role_files(self.root).values() if entry["label"] == "LakersJerseyHome"))


if __name__ == "__main__":
    unittest.main()
