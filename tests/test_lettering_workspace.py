import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lettering_workspace as ws
from inventory_lettering_iso import lettering_chunks
from test_inventory_lettering_iso import resource


class PaletteTests(unittest.TestCase):
    def test_logical_swizzle_round_trip_and_independent_alpha(self):
        original = bytes(value for i in range(256) for value in (i, 255 - i, i ^ 128, i % 129))
        rgb = bytearray(ws.swatch(original))
        self.assertEqual(rgb[8 * 3:9 * 3], original[16 * 4:16 * 4 + 3])
        rgb[8 * 3:9 * 3] = b"\x10\x20\x30"
        result = ws.import_rgb(original, bytes(rgb))
        self.assertEqual(result[16 * 4:16 * 4 + 3], b"\x10\x20\x30")
        self.assertEqual(result[3::4], original[3::4])
        self.assertEqual(ws.import_rgb(original, ws.swatch(original)), original)

    def test_invalid_swatch_dimensions_modes_and_format_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "palette.png"
            for mode, size, fmt in (("RGB", (32, 16), "PNG"), ("RGBA", (16, 16), "PNG"),
                                    ("P", (16, 16), "PNG"), ("RGB", (16, 16), "JPEG")):
                Image.new(mode, size).save(path, format=fmt)
                with self.subTest(mode=mode, size=size, fmt=fmt):
                    with self.assertRaisesRegex(ValueError, "16x16 RGB PNG"):
                        ws.read_palette(path)

    def test_all_30_team_assignments_and_invalid_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slots.csv"
            with path.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("sheet", "nba_slot"))
                writer.writerows((f"Club{slot}", slot) for slot in range(30))
            self.assertEqual(len(ws.assignments(path)), 30)
            self.assertEqual(ws.assignments(path)["29"], "Club29")
            for text in ("sheet,nba_slot\nA,30\n", "sheet,nba_slot\nA,1\nB,1\n",
                         "sheet,nba_slot\nA,1\nA,2\n", "sheet,nba_slot\n,1\n"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    ws.assignments(path)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.iso"
        self.output = self.root / "output.iso"
        self.workspace = self.root / "lettering"
        self.slots = self.root / "slots.csv"
        self.slots.write_text("sheet,nba_slot\nControl,20\n")
        data = bytearray(b"fixture ISO header" + bytes(64))
        rows = []
        for slot in (20, 21):
            for surface, target in (("game", "names"), ("game", "numbers"), ("preview", "numbers")):
                chunk = bytearray(resource(target, compressed=surface == "preview"))
                if surface == "preview":
                    chunk[20:24] = (0x10000).to_bytes(4, "little")
                offset = len(data)
                row = lettering_chunks(bytes(chunk))[0]
                rows.append({**row, "nba_slot": slot, "variant": "home", "surface": surface,
                             "asset": f"{surface}{slot}{target}.iff", "body_offset": offset + 32})
                data.extend(chunk)
        self.initial = bytes(data)
        self.source.write_bytes(self.initial)
        self.rows = rows
        self.addCleanup(patch.stopall)
        patch.object(ws, "inventory", return_value=rows).start()
        patch.object(ws, "SOURCE_SHA256", ws.digest(self.initial)).start()
        patch.object(ws, "ISO_SIZE", len(self.initial)).start()
        patch.object(ws.court_colours, "prepare", return_value=([], [])).start()
        ws.export(self.source, self.workspace, self.slots)

    def edit(self, slot=20, target="numbers"):
        path = self.workspace / f"{slot:03}" / "home" / f"{target}.palette.png"
        rgb = bytearray(ws.read_palette(path))
        rgb[24:27] = bytes((1, 200, 3))
        ws.save_swatch(path, bytes(rgb))
        return path, bytes(rgb)

    def set_colours(self, slot=20, target="numbers", mode="monochrome", fill="#123456"):
        path = self.workspace / f"{slot:03}" / "colours.json"
        config = json.loads(path.read_text())
        config["uniforms"]["home"][target].update(mode=mode, fill=fill)
        path.write_text(json.dumps(config))
        return path

    def test_colour_controls_generate_paired_numbers_and_matching_preview(self):
        config = self.set_colours()
        legacy, _ = self.edit()
        before = config.read_bytes(), legacy.read_bytes()
        ws.export(self.source, self.workspace, self.slots)
        self.assertEqual((config.read_bytes(), legacy.read_bytes()), before)
        preview = self.workspace / "020" / "home" / "numbers.preview.png"
        with Image.open(preview) as image:
            self.assertEqual(image.getpixel((0, 0)), (18, 52, 86, 255))
        report = ws.build(self.source, self.output, self.workspace, self.slots)
        self.assertEqual(len(report["changes"]), 2)
        self.assertEqual(report["colour_controls"][0]["mode"], "monochrome")
        output = self.output.read_bytes()
        for row in self.rows:
            if row["nba_slot"] != 20 or row["target"] != "numbers":
                continue
            body = output[row["body_offset"]:row["body_offset"] + row["stored_body_size"]]
            if row["compressed"]:
                body = ws.decode(body, row["decoded_size"])[0]
            self.assertEqual(body[-1024:], bytes((18, 52, 86, 128)) * 256)
        self.assertEqual(self.source.read_bytes(), self.initial)

    def test_skin_and_existing_patches_publish_in_one_iso_copy(self):
        self.set_colours()
        skin_plan = self.root / "skin.json"
        skin_patch = (0, self.initial[:4], b"skin")
        with patch("skin_tones.load_patches", return_value=([skin_patch], [{"pid": 235}])) as prepare_skin:
            report = ws.build(self.source, self.output, self.workspace, self.slots, skin_plan=skin_plan)
        self.assertEqual(report["skin_tones"], [{"pid": 235}])
        self.assertEqual(len(report["changes"]), 2)
        self.assertEqual(self.output.read_bytes()[:4], b"skin")
        self.assertEqual(self.source.read_bytes(), self.initial)
        self.assertEqual(prepare_skin.call_args.args[1], skin_plan)
        self.assertTrue(self.output.with_name(self.output.name + ".lettering.json").exists())

    def test_failed_skin_plan_never_publishes_iso(self):
        with patch("skin_tones.load_patches", side_effect=ValueError("stale skin recipe")):
            with self.assertRaisesRegex(ValueError, "stale skin recipe"):
                ws.build(self.source, self.output, self.workspace, self.slots, skin_plan=self.root / "skin.json")
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.name + ".lettering.json").exists())

    def test_colour_controls_keep_names_independent_and_check_read_only(self):
        self.set_colours(target="names")
        before = {p: p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        report = ws.check(self.source, self.workspace, self.slots)
        self.assertEqual([(r["surface"], r["target"]) for r in report["changes"]], [("game", "names")])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_reset_restores_only_selected_colour_controls(self):
        selected = self.set_colours()
        other = self.set_colours(slot=21)
        before = other.read_bytes()
        ws.reset(self.source, self.workspace, self.slots, [20])
        self.assertEqual(json.loads(selected.read_text())["uniforms"]["home"]["numbers"]["mode"], "palette")
        self.assertEqual(other.read_bytes(), before)

    def test_invalid_colour_controls_fail_before_iso_publication(self):
        path = self.set_colours(fill="#GGGGGG")
        with self.assertRaisesRegex(ValueError, "colours.json"):
            ws.build(self.source, self.output, self.workspace, self.slots)
        self.assertFalse(self.output.exists())
        path.write_text("{invalid")
        with self.assertRaisesRegex(ValueError, "colours.json"):
            ws.check(self.source, self.workspace, self.slots)
        self.assertEqual(self.source.read_bytes(), self.initial)

    def test_missing_team_documents_require_explicit_export(self):
        for path in self.workspace.rglob("colours.json"):
            path.unlink()
        self.edit()
        with self.assertRaisesRegex(ValueError, "missing team colour document"):
            ws.check(self.source, self.workspace, self.slots)
        self.assertEqual(list(self.workspace.rglob("colours.json")), [])

    def test_export_preserves_edits_backups_and_manifest(self):
        path, rgb = self.edit()
        original_manifest = (self.workspace / "manifest.json").read_bytes()
        ws.export(self.source, self.workspace, self.slots)
        self.assertEqual(ws.read_palette(path), rgb)
        self.assertEqual((self.workspace / "manifest.json").read_bytes(), original_manifest)
        original = self.workspace / "_originals" / "020" / "home" / "numbers.palette.png"
        self.assertNotEqual(ws.read_palette(original), rgb)

    def test_number_edit_patches_both_surfaces_without_names_or_alpha_changes(self):
        _, rgb = self.edit()
        report = ws.build(self.source, self.output, self.workspace, self.slots)
        self.assertEqual(self.source.read_bytes(), self.initial)
        self.assertEqual({r["surface"] for r in report["changes"]}, {"game", "preview"})
        self.assertEqual(len(report["changes"]), 2)
        out = self.output.read_bytes()
        for row in self.rows:
            body = out[row["body_offset"]:row["body_offset"] + row["stored_body_size"]]
            original = self.initial[row["body_offset"]:row["body_offset"] + row["stored_body_size"]]
            if row["compressed"]:
                body = ws.decode(body, row["decoded_size"])[0]
                original = ws.decode(original, row["decoded_size"])[0]
            self.assertEqual(body[:-1024], original[:-1024])
            self.assertEqual(body[-1021::4], original[-1021::4])
            if row["nba_slot"] == 20 and row["target"] == "numbers":
                self.assertEqual(body[-1024:], ws.import_rgb(original[-1024:], rgb))
            else:
                self.assertEqual(body, original)
        manifest = json.loads(self.output.with_name(self.output.name + ".lettering.json").read_text())
        self.assertEqual(manifest["output_sha256"], ws.digest(out))
        for change in manifest["changes"]:
            self.assertEqual(ws.digest(bytes.fromhex(change["original_hex"])), change["original_sha256"])

    def test_names_are_independent(self):
        self.edit(target="names")
        report = ws.check(self.source, self.workspace, self.slots)
        self.assertEqual([(r["surface"], r["target"]) for r in report["changes"]], [("game", "names")])

    def test_no_edit_output_is_pristine_and_check_is_read_only(self):
        before = {p: p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        report = ws.check(self.source, self.workspace, self.slots, self.output)
        self.assertEqual(report["changes"], [])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse(self.output.exists())
        ws.build(self.source, self.output, self.workspace, self.slots)
        self.assertEqual(self.output.read_bytes(), self.initial)

    def test_reset_only_selected_slot(self):
        path, _ = self.edit()
        other, rgb = self.edit(slot=21)
        ws.reset(self.source, self.workspace, self.slots, [20])
        backup = self.workspace / "_originals" / "020" / "home" / "numbers.palette.png"
        self.assertEqual(ws.read_palette(path), ws.read_palette(backup))
        self.assertEqual(ws.read_palette(other), rgb)

    def test_bad_manifest_mapping_and_backups_are_rejected(self):
        self.slots.write_text("sheet,nba_slot\nDifferent,20\n")
        with self.assertRaisesRegex(ValueError, "mapping differs"):
            ws.check(self.source, self.workspace, self.slots)
        self.slots.write_text("sheet,nba_slot\nControl,20\n")
        backup = self.workspace / "_originals" / "020" / "home" / "numbers.palette.png"
        ws.save_swatch(backup, bytes(768))
        with self.assertRaisesRegex(ValueError, "backup changed"):
            ws.check(self.source, self.workspace, self.slots)

    def test_recompression_failure_leaves_source_and_output_untouched(self):
        self.edit()
        with patch.object(ws, "rebuild_tail", side_effect=ValueError("fixed span too small")):
            with self.assertRaisesRegex(ValueError, "Slot 20 home"):
                ws.build(self.source, self.output, self.workspace, self.slots)
        self.assertEqual(self.source.read_bytes(), self.initial)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.name + ".lettering.json").exists())

    def test_rejects_existing_output_source_as_output_and_path_escape(self):
        self.output.write_bytes(b"keep")
        for output in (self.output, self.source):
            with self.assertRaisesRegex(ValueError, "new path"):
                ws.check(self.source, self.workspace, self.slots, output)
        self.assertEqual(self.output.read_bytes(), b"keep")
        with self.assertRaisesRegex(ValueError, "escapes"):
            ws.workspace_path(self.workspace, Path("..") / "outside.png")


if __name__ == "__main__":
    unittest.main()
