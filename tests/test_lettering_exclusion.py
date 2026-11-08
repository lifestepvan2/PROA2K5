import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import uniform_labels
from texture_workspace import scan
from uniform_lods import skipped


class LetteringExclusionTests(unittest.TestCase):
    def test_shared_scan_guard_preserves_existing_exclusions(self):
        self.assertTrue(skipped(("lettering", "020", "home")))
        self.assertTrue(skipped(("uniforms", "lettering")))
        self.assertTrue(skipped(("_retired_1",)))
        self.assertTrue(skipped(("visual_sort",)))
        self.assertFalse(skipped(("uniforms",)))

    def test_ordinary_workspace_and_uniform_scans_ignore_lettering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (Path("lettering") / "020" / "home" / "numbers__12345678.png",
                             Path("uniforms") / "lettering" / "MASTER__Bad__16x16__23456789.png",
                             Path("uniforms") / "MASTER__Good__16x16__34567890.png"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (16, 16)).save(path)
            self.assertEqual(set(scan(root)), {"34567890"})
            entries, _ = uniform_labels.scan(root)
            self.assertEqual(set(entries), {"34567890"})


if __name__ == "__main__":
    unittest.main()
