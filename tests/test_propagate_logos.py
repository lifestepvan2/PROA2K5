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
            for index in range(30):
                token = f"{index:08x}"
                path = workspace / f"renamed_{index}__{token}.png"
                Image.new("RGBA", (32, 32), (1, 2, 3, 255)).save(path)
                paths.append(path)
                rows.append({"id": token, "asset": "frontend.iff",
                             "texture": f"{index:03}_flipchip_00", "editable": True,
                             "width": 32, "height": 32, "path": "outdated.png"})
            atlas_path = workspace / f"moved_collage__{logos.STUDIO_ATLAS_ID}.png"
            Image.new("RGBA", (256, 256), (1, 2, 3, 255)).save(atlas_path)
            rows.append({"id": logos.STUDIO_ATLAS_ID, "asset": "scstudio.iff",
                         "texture": "m_metalnoise", "editable": True,
                         "width": 256, "height": 256})
            sheet_path = workspace / f"moved_sheet__{logos.TITLE_SHEET_ID}.png"
            Image.new("RGBA", (512, 512), (1, 2, 3, 255)).save(sheet_path)
            rows.append({"id": logos.TITLE_SHEET_ID, "asset": "titlepage.iff",
                         "texture": "logosheet", "editable": True,
                         "width": 512, "height": 512})
            team_paths = {}
            for team_id in (0, 1, 2, 4):
                for family, asset, texture, size in (
                    ("loading", f"p{team_id:03}.iff", f"2d{team_id:03}_0", 256),
                    ("franchise", "franchise.iff", f"{team_id:03}_mlogo", 64),
                ):
                    token = f"{0x100 + team_id * 2 + (family == 'franchise'):08x}"
                    path = workspace / f"moved_team_logo__{token}.png"
                    Image.new("RGBA", (size, size), (1, 2, 3, 255)).save(path)
                    rows.append({"id": token, "asset": asset, "texture": texture,
                                 "editable": True, "width": size, "height": size})
                    team_paths[team_id, family] = path
            (workspace / logos.remaining.MANIFEST).write_text(json.dumps({
                "schema": 1, "source_sha256": native.SOURCE_SHA256, "sources": rows,
            }), encoding="utf-8")
            for team, colour in enumerate(("red", "green", "blue")):
                Image.new("RGBA", (40, 20), colour).save(source / f"{38 + team}.png")
            slots = {10: 0, 11: 1, 12: 2}
            ids = {0: 10, 2: 11, 4: 12}
            all_paths = paths + [atlas_path, sheet_path] + list(team_paths.values())
            original = [path.read_bytes() for path in all_paths]
            with patch.object(logos, "proa_slots", return_value=slots), \
                    patch.object(native, "team_ids", return_value=ids), \
                    contextlib.redirect_stdout(io.StringIO()):
                plan = logos.propagate(workspace, source, dry_run=True)
                self.assertEqual(original, [path.read_bytes() for path in all_paths])
                (source / "40.png").unlink()
                with self.assertRaises(FileNotFoundError):
                    logos.propagate(workspace, source)
                self.assertEqual(original, [path.read_bytes() for path in all_paths])
                Image.new("RGBA", (40, 20), "blue").save(source / "40.png")
                self.assertEqual(plan, logos.propagate(workspace, source))
            for index, path in enumerate(paths):
                with Image.open(path) as image:
                    self.assertEqual(image.size, (32, 32))
                    self.assertEqual(image.getpixel((16, 16))[:3],
                                     [(255, 0, 0), (0, 128, 0), (0, 0, 255)][plan[index]])
            self.assertEqual((plan[0], plan[2], plan[4]), (0, 1, 2))
            with Image.open(atlas_path) as atlas:
                self.assertEqual(atlas.size, (256, 256))
                for index in range(30):
                    x, y = index % 6, index // 6
                    center = ((x * 256 // 6 + (x + 1) * 256 // 6) // 2,
                              (y * 256 // 5 + (y + 1) * 256 // 5) // 2)
                    self.assertEqual(atlas.getpixel(center)[:3],
                                     [(255, 0, 0), (0, 128, 0), (0, 0, 255)][plan[index]])
            for team_id, team in ((0, 0), (2, 1), (4, 2)):
                for family in ("loading", "franchise"):
                    with Image.open(team_paths[team_id, family]) as image:
                        self.assertEqual(image.getpixel((0, 0))[3], 0)
                        center = image.width // 2
                        self.assertEqual(image.getpixel((center, center))[:3],
                                         [(255, 0, 0), (0, 128, 0), (0, 0, 255)][team])
            for family in ("loading", "franchise"):
                with Image.open(team_paths[1, family]) as image:
                    self.assertEqual(image.getpixel((0, 0)), (1, 2, 3, 255))
            with Image.open(sheet_path) as sheet:
                self.assertEqual(sheet.getpixel((66, 172))[:3], (255, 0, 0))

    def test_collage_requires_all_thirty_flipchips(self):
        with self.assertRaisesRegex(ValueError, "000 through 029"):
            logos.studio_atlas({0: 0}, Path("unused"))

    def test_missing_team_logo_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "p002.iff/2d002_0"):
            logos.team_logo_rows([], {2: 0})

    def test_title_sheet_has_eighteen_centered_logos_and_shadows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            colours = [(i * 10, 20, 200, 255) for i in range(18)]
            for team, colour in enumerate(colours):
                Image.new("RGBA", (40, 20), colour).save(root / f"{38 + team}.png")
            sheet = logos.title_sheet(list(range(18)), root)
            self.assertEqual(sheet.size, (512, 512))
            for index, colour in enumerate(colours):
                x, y = 66 + index % 6 * 78, 172 + index // 6 * 89
                self.assertEqual(sheet.getpixel((x, y)), colour)
                self.assertEqual(sheet.getpixel((x, 80)), sheet.getpixel((0, 80)))
                self.assertEqual(sheet.getpixel((x, 435)), sheet.getpixel((0, 435)))
            self.assertLess(sheet.getpixel((66, 194))[0], sheet.getpixel((0, 194))[0])
            with self.assertRaisesRegex(ValueError, "18 distinct"):
                logos.title_sheet(list(range(19)), root)

if __name__ == "__main__":
    unittest.main()
