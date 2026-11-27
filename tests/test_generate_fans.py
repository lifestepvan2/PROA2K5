import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import openpyxl
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_fans as fans


class GenerateFansTests(unittest.TestCase):
    def fixture(self, root):
        self.enterContext(patch.object(fans, "scorer", return_value=("Test Player", "6", 17.5)))
        self.enterContext(patch.object(fans, "team_info", return_value=("Test Team", "Testers")))
        workspace, output = root / "workspace", root / "review"
        source = workspace / "moved" / "cscrowd002_tshirt_tshirt__256x128__01234567.png"
        source.parent.mkdir(parents=True)
        Image.new("RGBA", fans.SIZE, (197, 8, 201, 123)).save(source)
        other = source.with_name("sweatshirt__76543210.png")
        Image.new("RGBA", fans.SIZE, "yellow").save(other)
        Image.new("RGBA", fans.SIZE, (197, 8, 201, 111)).save(
            source.with_name("varsity__55555555.png"))
        Image.new("RGBA", (128, 128), (197, 8, 201, 129)).save(
            source.with_name("crowdsign__66666666.png"))
        row = {"id": "01234567", "asset": "cscrowd002.iff", "slot": 29,
               "texture": "tshirt", "surface": "crowd", "editable": True,
               "width": 256, "height": 128, "path": "stale/location.png"}
        jersey = source.with_name("cscrowd002_jersey_jersey__256x128__89abcdef.png")
        Image.new("RGBA", fans.SIZE, (197, 8, 201, 91)).save(jersey)
        uniforms = []
        for token, variant, colour, surface in (
            ("11111111", "away", "red", "game"), ("22222222", "home", "green", "game"),
            ("33333333", "away", "yellow", "preview"),
        ):
            path = source.with_name(f"edited_{variant}_{surface}__{token}.png")
            Image.new("RGBA", (512, 256), colour).save(path)
            uniforms.append({**row, "id": token, "texture": "unif", "variant": variant,
                             "surface": surface, "width": 512, "height": 256})
        generics = []
        for index, name in enumerate(("black", "blue", "purple", "red", "white", "yellow")):
            token = f"{0x44444440 + index:08x}"
            path = source.with_name(f"generic_{name}__{token}.png")
            Image.new("RGBA", fans.SIZE, (10 + index, 20 + index, 30 + index, 100 + index)).save(path)
            generics.append({**row, "id": token, "texture": f"generictshirt_{name}"})
        (workspace / fans.uniforms.MANIFEST).write_text(json.dumps({
            "schema": 1, "source_sha256": fans.native.SOURCE_SHA256,
            "sources": [row, {**row, "id": "76543210", "texture": "sweatshirt"},
                        {**row, "id": "89abcdef", "texture": "jersey"},
                        {**row, "id": "55555555", "texture": "varsity"},
                        {**row, "id": "66666666", "texture": "crowdsign",
                         "width": 128, "height": 128}, *uniforms, *generics],
        }), encoding="utf-8")
        controls = {"mode": "monochrome", "fill": "#FFFFFF",
                    "outline1": "#000000", "outline2": "#000000"}
        palette = workspace / "team_palettes" / "029" / "colours.json"
        palette.parent.mkdir(parents=True)
        palette.write_text(json.dumps({
            "schema": 1, "team": {**dict.fromkeys(fans.team_palettes.TEAM_FIELDS, "#123456"),
                                "colorprimary": "#0f4281", "colorsecondary": "#EEEEEE"},
            "uniforms": {v: {"names": controls, "numbers": {**controls, "fill": fill}}
                         for v, fill in (("home", "#F000F0"), ("away", "#00F0F0"))},
            "court": {"mode": "original", "primary": "#123456",
                      "secondary": "#123456", "lines": "#123456"},
        }), encoding="utf-8")
        template = root / "template.png"
        Image.new("RGBA", fans.SIZE, (86, 86, 86, 255)).save(template)
        logos = root / "logos"
        logos.mkdir()
        Image.new("RGBA", (20, 40), "red").save(logos / "46.png")
        return workspace, output, source, palette, template, logos

    def test_render_preserves_shoes_swatches_alpha_and_logo_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, source, _, template, logos = self.fixture(root)
            with Image.open(source) as image, Image.open(template) as fabric:
                before = np.asarray(image).copy()
                rendered = fans.render(image, fabric, logos / "46.png", (15, 66, 129))
                np.testing.assert_array_equal(np.asarray(image), before)
            pixels = np.asarray(rendered)
            untouched = np.ones((128, 256), dtype=bool)
            for left, top, right, bottom in (*fans.SHIRT_REGIONS, fans.CAP_REGION):
                untouched[top:bottom, left:right] = False
            np.testing.assert_array_equal(pixels[untouched], before[untouched])
            np.testing.assert_array_equal(pixels[:, :, 3], before[:, :, 3])
            self.assertEqual(rendered.getpixel((20, 30))[:3], (15, 66, 129))
            self.assertEqual(rendered.getpixel((200, 20))[:3], (15, 66, 129))
            self.assertEqual(rendered.getpixel((81, 54))[:3], (255, 0, 0))
            self.assertEqual(rendered.getpixel((226, 24))[:3], (255, 0, 0))
            self.assertEqual(rendered.getpixel((57, 54))[:3], (15, 66, 129))

    def test_fabric_wrinkles_shade_dark_and_light_colours(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, source, _, template, logos = self.fixture(root)
            with Image.open(source) as image, Image.open(template) as original:
                fabric = original.copy()
                fabric.putpixel((20, 20), (43, 43, 43, 255))
                fabric.putpixel((21, 20), (129, 129, 129, 255))
                for primary in ((0, 0, 0), (15, 66, 129), (255, 255, 255)):
                    result = fans.render(image, fabric, logos / "46.png", primary)
                    dark = sum(result.getpixel((20, 20))[:3])
                    light = sum(result.getpixel((21, 20))[:3])
                    self.assertLess(dark, light)

    def test_generation_resolves_native_id_and_never_overwrites_live_or_review_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, output, source, _, template, logos = self.fixture(root)
            originals = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
            with patch.object(fans, "proa_slots", return_value={29: 8}), \
                    contextlib.redirect_stdout(io.StringIO()):
                first = fans.generate(29, workspace=workspace, output_root=output,
                                      template_path=template, logo_dir=logos)
                self.assertEqual(first.name, source.name)
                self.assertEqual(len(list(first.parent.rglob("*.png"))), 14)
                with Image.open(first) as image:
                    self.assertEqual(image.size, fans.SIZE)
                    self.assertEqual(image.getpixel((81, 54))[:3], (255, 0, 0))
                jersey_name = "cscrowd002_jersey_jersey__256x128__89abcdef.png"
                normal, alternate = first.parent / jersey_name, first.parent / "_alt" / jersey_name
                with Image.open(normal) as away, Image.open(alternate) as home:
                    self.assertEqual(away.getpixel((96, 80)), (255, 0, 0, 91))
                    self.assertEqual(home.getpixel((96, 80)), (0, 128, 0, 91))
                    self.assertEqual(away.getpixel((220, 80))[:3],
                                     (away.getpixel((220, 80))[0],) * 3)
                    self.assertGreater(home.getpixel((220, 80))[2],
                                       home.getpixel((220, 80))[0])
                with Image.open(first.parent / "varsity__55555555.png") as main, \
                        Image.open(first.parent / "_alt" / "varsity__55555555.png") as alt:
                    self.assertEqual(main.getpixel((79, 45)), (0, 128, 0, 111))
                    self.assertEqual(alt.getpixel((79, 45)), (255, 0, 0, 111))
                    self.assertTrue(np.any(np.all(np.asarray(main)[59:75, 72:86, :3]
                                                  == (240, 0, 240), axis=2)))
                    self.assertTrue(np.any(np.all(np.asarray(alt)[59:75, 72:86, :3]
                                                  == (0, 240, 240), axis=2)))
                first.write_bytes(b"manual review edits")
                alternate.write_bytes(b"manual alternative edits")
                second = fans.generate(29, workspace=workspace, output_root=output,
                                       template_path=template, logo_dir=logos)
            self.assertNotEqual(first.parent, second.parent)
            self.assertEqual(first.read_bytes(), b"manual review edits")
            self.assertEqual(alternate.read_bytes(), b"manual alternative edits")
            self.assertEqual(originals, {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()})

    def test_refuses_missing_primary_and_output_inside_workspace_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, output, _, palette, template, logos = self.fixture(Path(directory))
            value = json.loads(palette.read_text())
            del value["team"]["colorprimary"]
            palette.write_text(json.dumps(value))
            with patch.object(fans, "proa_slots", return_value={29: 8}):
                with self.assertRaisesRegex(ValueError, "Add team.colorprimary"):
                    fans.generate(29, workspace=workspace, output_root=output,
                                  template_path=template, logo_dir=logos)
                with self.assertRaisesRegex(ValueError, "outside the live workspace"):
                    fans.generate(29, workspace=workspace, output_root=workspace / "review")
            self.assertFalse(output.exists())
            self.assertFalse((workspace / "review").exists())

    def test_refuses_missing_or_ambiguous_masters_and_unassigned_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, output, _, _, template, logos = self.fixture(Path(directory))
            manifest_path = workspace / fans.uniforms.MANIFEST
            manifest = json.loads(manifest_path.read_text())
            row = manifest["sources"][0]
            with patch.object(fans, "proa_slots", return_value={29: 8}):
                for sources in ([], [row, row]):
                    manifest_path.write_text(json.dumps({**manifest, "sources": sources}))
                    with self.assertRaisesRegex(ValueError, "exactly one editable"):
                        fans.generate(29, workspace=workspace, output_root=output,
                                      template_path=template, logo_dir=logos)
                with self.assertRaisesRegex(ValueError, "no ProA team assignment"):
                    fans.generate(0, workspace=workspace, output_root=output)
            self.assertFalse(output.exists())

    def test_sweatshirt_replaces_old_art_preserves_fabric_and_alpha_without_a_cap_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, source, _, template, logos = self.fixture(Path(directory))
            with Image.open(source) as image, Image.open(template) as fabric:
                fabric.putpixel((20, 20), (43, 43, 43, 255))
                ImageDraw.Draw(fabric).rectangle((0, 124, 255, 127), fill=(43, 43, 43, 255))
                result = fans.render_sweatshirt(image, fabric, logos / "46.png", (15, 66, 129))
                np.testing.assert_array_equal(np.asarray(result)[:, :, 3],
                                              np.asarray(image)[:, :, 3])
            self.assertEqual(result.getpixel((81, 54))[:3], (255, 0, 0))
            self.assertEqual(result.getpixel((57, 54))[:3], (15, 66, 129))
            self.assertEqual(result.getpixel((226, 24))[:3], (15, 66, 129))
            self.assertLess(sum(result.getpixel((20, 20))[:3]),
                            sum(result.getpixel((21, 20))[:3]))
            self.assertLess(sum(result.getpixel((20, 125))[:3]),
                            sum(result.getpixel((20, 120))[:3]))

    def test_all_generic_shirts_change_only_caps_with_exactly_half_each_colour(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, output, _, _, template, logos = self.fixture(Path(directory))
            with patch.object(fans, "proa_slots", return_value={29: 8}), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = fans.generate(29, workspace=workspace, output_root=output,
                                       template_path=template, logo_dir=logos)
            outside_cap = np.ones((128, 256), dtype=bool)
            outside_cap[:50, 192:] = False
            cap_colours = []
            for path in sorted((workspace / "moved").glob("generic_*.png")):
                with Image.open(path) as source, Image.open(result.parent / path.name) as generated:
                    old, new = np.asarray(source), np.asarray(generated)
                    np.testing.assert_array_equal(new[outside_cap], old[outside_cap])
                    np.testing.assert_array_equal(new[:, :, 3], old[:, :, 3])
                    self.assertEqual(generated.getpixel((226, 24))[:3], (255, 0, 0))
                    cap_colours.append(generated.getpixel((200, 0))[:3])
            self.assertEqual(cap_colours.count((15, 66, 129)), 3)
            self.assertEqual(cap_colours.count((48, 48, 48)), 3)
            sweatshirt = result.parent / "sweatshirt__76543210.png"
            with Image.open(sweatshirt) as image:
                self.assertEqual(image.getpixel((81, 54))[:3], (255, 0, 0))
                self.assertGreater(image.getpixel((226, 24))[2], image.getpixel((226, 24))[0])

    def test_incomplete_or_bad_generic_shirts_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, output, _, _, template, logos = self.fixture(Path(directory))
            path = workspace / fans.uniforms.MANIFEST
            manifest = json.loads(path.read_text())
            filtered = [row for row in manifest["sources"] if row["texture"] != "generictshirt_black"]
            path.write_text(json.dumps({**manifest, "sources": filtered}))
            with patch.object(fans, "proa_slots", return_value={29: 8}):
                with self.assertRaisesRegex(ValueError, "split cap colours equally"):
                    fans.generate(29, workspace=workspace, output_root=output,
                                  template_path=template, logo_dir=logos)
                self.assertFalse(output.exists())
                path.write_text(json.dumps(manifest))
                Image.new("RGBA", (128, 128), "red").save(
                    workspace / "moved" / "generic_black__44444440.png")
                with self.assertRaisesRegex(ValueError, "Crowd cap atlas must be"):
                    fans.generate(29, workspace=workspace, output_root=output,
                                  template_path=template, logo_dir=logos)
            self.assertFalse(output.exists())

    def test_jersey_wrap_registration_keeps_neck_and_armholes_and_art_landmarks(self):
        source = Image.new("RGBA", fans.SIZE, (197, 8, 201, 91))
        jersey = Image.new("RGBA", (512, 256), "red")
        draw = ImageDraw.Draw(jersey)
        draw.rectangle((166, 0, 255, 255), fill="green")
        draw.rectangle((256, 0, 421, 255), fill="blue")
        draw.rectangle((422, 0, 511, 255), fill="yellow")
        draw.rectangle((70, 114, 101, 126), fill="magenta")
        with Image.open(fans.JERSEY_TEMPLATE) as template:
            normal = fans.render_jersey(source, jersey, template, (255, 255, 255))
            alternate = fans.render_jersey(source, jersey, template, (15, 66, 129))
            mask = np.asarray(template.getchannel("A")) == 255
            grey = np.asarray(template.convert("L"))
        np.testing.assert_array_equal(np.asarray(normal)[mask, :3],
                                      np.repeat(grey[mask, None], 3, axis=1))
        np.testing.assert_array_equal(np.asarray(normal)[:, :, 3], 91)
        for point in ((96, 25), (48, 50), (144, 50), (0, 7), (220, 80)):
            self.assertLess(alternate.getpixel(point)[0], alternate.getpixel(point)[2])
        self.assertEqual(normal.getpixel((96, 27))[:3], (255, 0, 0))
        self.assertEqual(normal.getpixel((96, 51))[:3], (255, 0, 255))
        for point, colour in (((16, 100), (0, 0, 255)), ((176, 100), (0, 0, 255)),
                              ((48, 100), (255, 255, 0)), ((144, 100), (0, 128, 0))):
            self.assertEqual(normal.getpixel(point)[:3], colour)

    def test_missing_home_master_or_bad_jersey_is_an_error_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, output, _, _, template, logos = self.fixture(Path(directory))
            path = workspace / fans.uniforms.MANIFEST
            manifest = json.loads(path.read_text())
            filtered = [row for row in manifest["sources"] if row["id"] != "22222222"]
            path.write_text(json.dumps({**manifest, "sources": filtered}))
            with patch.object(fans, "proa_slots", return_value={29: 8}):
                with self.assertRaisesRegex(ValueError, "exactly one editable game home unif"):
                    fans.generate(29, workspace=workspace, output_root=output,
                                  template_path=template, logo_dir=logos)
                self.assertFalse(output.exists())
                path.write_text(json.dumps(manifest))
                away = workspace / "moved" / "edited_away_game__11111111.png"
                Image.new("RGBA", (128, 128), "red").save(away)
                with self.assertRaisesRegex(ValueError, "2:1 aspect ratio"):
                    fans.generate(29, workspace=workspace, output_root=output,
                                  template_path=template, logo_dir=logos)
            self.assertFalse(output.exists())

    def test_new_colour_stats_and_sign_errors_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, output, _, palette, template, logos = self.fixture(Path(directory))
            original = json.loads(palette.read_text())
            with patch.object(fans, "proa_slots", return_value={29: 8}):
                for missing, message in (("colorsecondary", "Add team.colorsecondary"),
                                         ("away", "away numbers.fill controls")):
                    value = json.loads(json.dumps(original))
                    del value["team" if missing == "colorsecondary" else "uniforms"][missing]
                    palette.write_text(json.dumps(value))
                    with self.assertRaisesRegex(ValueError, message):
                        fans.generate(29, workspace=workspace, output_root=output,
                                      template_path=template, logo_dir=logos)
                    self.assertFalse(output.exists())
                palette.write_text(json.dumps(original))
                with patch.object(fans, "scorer", side_effect=ValueError("No valid PPG")):
                    with self.assertRaisesRegex(ValueError, "No valid PPG"):
                        fans.generate(29, workspace=workspace, output_root=output,
                                      template_path=template, logo_dir=logos)
                self.assertFalse(output.exists())
                Image.new("RGBA", (256, 128), "red").save(
                    workspace / "moved" / "crowdsign__66666666.png")
                with self.assertRaisesRegex(ValueError, "Crowd sign atlas must be"):
                    fans.generate(29, workspace=workspace, output_root=output,
                                  template_path=template, logo_dir=logos)
                self.assertFalse(output.exists())


class FanVarsityAndSignTests(unittest.TestCase):
    def test_scorer_uses_pooled_ppg_only_team_members_and_deterministic_ties(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster, stats_path = root / "roster.xlsx", root / "stats.json"
            book = openpyxl.Workbook()
            team = book.active
            team.title = "Example"
            header = ["First Name", "Last Name", "ProA ID", "Jersey Number"]
            team.append(header)
            team.append(["Pooled", "Leader", 201, 0])
            team.append(["Season", "Leader", 202, 12])
            team.append(["Equal", "Scorer", 204, 99])
            other = book.create_sheet("Other")
            other.append(header)
            other.append(["Other", "Team", 203, 33])
            book.save(roster)
            book.close()
            stats = {"schema_version": 2, "season": "2026_2027", "players": {
                "201": {"points_avg": 20,
                        "history": {"seasons": {"2026_2027": {"averages": {"PPG": 1}}}}},
                "202": {"points_avg": 19,
                        "history": {"seasons": {"2026_2027": {"averages": {"PPG": 50}}}}},
                "203": {"points_avg": 90}, "204": {"points_avg": 20},
            }}
            stats_path.write_text(json.dumps(stats))
            self.assertEqual(fans.scorer("Example", roster, stats_path), ("Pooled Leader", "0", 20))
            for value in (None, float("nan"), -1, True):
                stats["players"]["202"]["points_avg"] = value
                stats_path.write_text(json.dumps(stats))
                with self.assertRaisesRegex(ValueError, "missing/invalid pooled"):
                    fans.scorer("Example", roster, stats_path)
            stats["players"]["202"]["points_avg"] = 19
            stats_path.write_text(json.dumps(stats))
            team.cell(2, 4, 1.5)
            book.save(roster)
            with self.assertRaisesRegex(ValueError, "Jersey Number: expected an integer"):
                fans.scorer("Example", roster, stats_path)
            with self.assertRaisesRegex(ValueError, "missing team sheet"):
                fans.scorer("Absent", roster, stats_path)

    def test_varsity_preserves_neck_swatches_alpha_and_separates_materials_and_number(self):
        with tempfile.TemporaryDirectory() as directory:
            logo = Path(directory) / "logo.png"
            Image.new("RGBA", (20, 20), "red").save(logo)
            source = Image.new("RGBA", fans.SIZE, (197, 8, 201, 91))
            template = Image.new("RGBA", fans.SIZE, (128, 128, 128, 255))
            template.putpixel((20, 100), (64, 64, 64, 255))
            alpha = template.getchannel("A")
            draw = ImageDraw.Draw(alpha)
            draw.rectangle((67, 22, 88, 98), fill=0)
            draw.rectangle((69, 0, 86, 20), fill=0)
            draw.rectangle((68, 99, 86, 127), fill=0)
            template.putalpha(alpha)
            accents = Image.new("L", fans.SIZE)
            ImageDraw.Draw(accents).rectangle((180, 0, 255, 10), fill=255)
            jersey = Image.new("RGBA", (512, 256), "green")
            result = fans.render_varsity(source, jersey, template, accents, logo,
                                          (15, 66, 129), (238, 238, 238), "33", (240, 0, 240))
            self.assertEqual(result.getpixel((20, 50)), (15, 66, 129, 91))
            self.assertEqual(result.getpixel((200, 5)), (238, 238, 238, 91))
            self.assertEqual(result.getpixel((79, 45)), (0, 128, 0, 91))
            for point in ((78, 5), (78, 110)):
                self.assertEqual(result.getpixel(point), source.getpixel(point))
            self.assertLess(sum(result.getpixel((20, 100))[:3]),
                            sum(result.getpixel((21, 100))[:3]))
            pixels = np.asarray(result)
            np.testing.assert_array_equal(pixels[:, :, 3], 91)
            number = np.all(pixels[:, :, :3] == (240, 0, 240), axis=2)
            self.assertTrue(number.any())
            ys, xs = np.nonzero(number)
            self.assertTrue(np.all((xs >= 72) & (xs < 86) & (ys >= 59) & (ys < 75)))

    def test_sign_uses_logo_or_two_fitted_lines_with_maximum_contrast_and_original_alpha(self):
        with tempfile.TemporaryDirectory() as directory:
            logo = Path(directory) / "logo.png"
            Image.new("RGBA", (20, 40), "red").save(logo)
            source = Image.new("RGBA", (128, 128), (12, 34, 56, 129))
            main = fans.render_sign(source, logo, (15, 66, 129))
            self.assertEqual(main.getpixel((64, 64)), (255, 0, 0, 129))
            self.assertEqual(main.getpixel((0, 0)), (15, 66, 129, 129))
            for primary, foreground in (((15, 66, 129), (255, 255, 255)),
                                        ((240, 240, 240), (0, 0, 0))):
                self.assertEqual(fans.contrast_colour(primary), foreground)
                result = fans.render_sign(source, logo, primary, "Long nickname with spaces")
                pixels = np.asarray(result)
                np.testing.assert_array_equal(pixels[:, :, 3], 129)
                ink = np.any(pixels[:, :, :3] != primary, axis=2)
                ys, xs = np.nonzero(ink)
                self.assertTrue(np.all((xs >= 6) & (xs < 122) & (ys >= 16) & (ys < 112)))
                self.assertTrue(ink[16:56].any())
                self.assertTrue(ink[68:112].any())
                self.assertFalse(ink[56:68].any())
                self.assertTrue(np.any(np.all(pixels[:, :, :3] == foreground, axis=2)))
            metadata = Path(directory) / "teams.csv"
            metadata.write_text("sheet,nickname\nLong team sheet,ShortNick\n")
            self.assertEqual(fans.team_info(0, metadata), ("Long team sheet", "ShortNick"))


if __name__ == "__main__":
    unittest.main()
