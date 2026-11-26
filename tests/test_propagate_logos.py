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
import propagate_logos as logos
import texture_iso_workspace as native


class PropagateLogosTests(unittest.TestCase):
    def test_fixed_assignments_and_no_adjacent_repeats_including_wrap(self):
        fixed = {2: 2, 4: 0, 9: 1}
        result = logos.assignments([0, 2, 3, 4, 9], fixed, [0, 1, 2])
        self.assertEqual({index: result[index] for index in fixed}, fixed)
        values = list(result.values())
        self.assertTrue(all(left != right for left, right in zip(values, values[1:] + values[:1])))
        self.assertEqual(result, logos.assignments([9, 4, 3, 2, 0], fixed, [0, 1, 2]))
        with self.assertRaisesRegex(ValueError, "repeats"):
            logos.assignments([0, 1, 2], {0: 1, 1: 1}, [0, 1, 2])

    def test_propagation_resolves_moved_masters_and_stages_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace, source = root / "workspace", root / "logos"
            workspace.mkdir()
            source.mkdir()
            rows, paths = [], []
            for index in range(5):
                token = f"{index:08x}"
                path = workspace / f"renamed_{index}__{token}.png"
                Image.new("RGBA", (32, 32), (1, 2, 3, 255)).save(path)
                paths.append(path)
                rows.append({"id": token, "asset": "frontend.iff",
                             "texture": f"{index:03}_flipchip_00", "editable": True,
                             "width": 32, "height": 32, "path": "outdated.png"})
            (workspace / logos.remaining.MANIFEST).write_text(json.dumps({
                "schema": 1, "source_sha256": native.SOURCE_SHA256, "sources": rows,
            }), encoding="utf-8")
            for team, colour in enumerate(("red", "green", "blue")):
                Image.new("RGBA", (40, 20), colour).save(source / f"{38 + team}.png")
            slots = {10: 0, 11: 1, 12: 2}
            ids = {0: 10, 2: 11, 4: 12}
            original = [path.read_bytes() for path in paths]
            with patch.object(logos, "proa_slots", return_value=slots), \
                    patch.object(native, "team_ids", return_value=ids), \
                    contextlib.redirect_stdout(io.StringIO()):
                plan = logos.propagate(workspace, source, dry_run=True)
                self.assertEqual(original, [path.read_bytes() for path in paths])
                (source / "40.png").unlink()
                with self.assertRaises(FileNotFoundError):
                    logos.propagate(workspace, source)
                self.assertEqual(original, [path.read_bytes() for path in paths])
                Image.new("RGBA", (40, 20), "blue").save(source / "40.png")
                self.assertEqual(plan, logos.propagate(workspace, source))
            for index, path in enumerate(paths):
                with Image.open(path) as image:
                    self.assertEqual(image.size, (32, 32))
                    self.assertEqual(image.getpixel((16, 16))[:3],
                                     [(255, 0, 0), (0, 128, 0), (0, 0, 255)][plan[index]])
            self.assertEqual((plan[0], plan[2], plan[4]), (0, 1, 2))

if __name__ == "__main__":
    unittest.main()
