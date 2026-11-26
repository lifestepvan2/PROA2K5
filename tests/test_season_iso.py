import io
import json
import csv
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import season_iso as season
import portrait_iso
from iso_copy import CopySpan, hash_stream
from PIL import Image


class SeasonCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.output = self.root / "source.iso", self.root / "new.iso"
        self.source.write_bytes(b"A" * 32)
        self.workspace = self.root / "workspace"
        self.roster, self.plan = self.root / "payload.bin", self.root / "skin.json"
        self.roster_patch = (0, b"AA", b"RR")
        self.visual_patch = (8, b"AA", b"VV")

    def test_composes_all_components_in_one_verified_copy(self):
        with patch.object(season.roster_iso, "prepare", return_value=([self.roster_patch], {"asset": "roster.iff"})) as roster, \
                patch.object(season.lettering_workspace, "prepare",
                             return_value=([self.visual_patch], {"sources": 237})) as visuals, \
                patch.object(season, "prepare_year_patch", return_value=([], {"label_anchor": 2026})) as year, \
                patch.object(season, "ISO_SIZE", 32), \
                patch.object(season, "SOURCE_SHA256", hash_stream(io.BytesIO(b"A" * 32))):
            report = season.build(self.source, self.output, self.roster, self.workspace,
                                  stats_year=2026, skin_plan=self.plan)
        roster.assert_called_once()
        self.assertEqual(roster.call_args.args[1], self.roster)
        self.assertEqual(visuals.call_args.args[3:], (None, self.plan))
        self.assertEqual(year.call_args.args[1:], (2026, 0))
        self.assertEqual(self.source.read_bytes(), b"A" * 32)
        self.assertEqual(self.output.read_bytes(), b"RR" + b"A" * 6 + b"VV" + b"A" * 22)
        self.assertEqual(report["output_sha256"], hash_stream(io.BytesIO(self.output.read_bytes())))
        manifest = self.output.with_name(self.output.name + season.MANIFEST_SUFFIX)
        self.assertEqual(json.loads(manifest.read_text())["roster"]["asset"], "roster.iff")

    def test_check_without_generated_artifacts_is_read_only(self):
        with patch.object(season.roster_iso, "prepare", return_value=([], {})) as roster, \
                patch.object(season.lettering_workspace, "prepare", return_value=([], {})) as visuals, \
                patch.object(season, "prepare_year_patch", return_value=([], {})):
            season.check(self.source, self.output, self.workspace, stats_year=2026)
        self.assertIsNone(roster.call_args.args[1])
        self.assertIsNone(visuals.call_args.args[-1])
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_native_logos_take_over_court_composition_in_the_same_copy(self):
        logo_patch = (16, b"AA", b"LL")
        court_edits = [("decoded-court-edit",)]
        native_workspace = self.root / "native"
        with patch.object(season.roster_iso, "prepare", return_value=([], {})), \
                patch.object(season.lettering_workspace, "prepare", return_value=([self.visual_patch], {"sources": 1})) as visual, \
                patch.object(season.court_colours, "decoded_edits", return_value=court_edits), \
                patch.object(season.texture_iso_workspace, "prepare",
                             return_value=([logo_patch], {"courts": [{"asset": "s021.iff"}]})) as logos, \
                patch.object(season, "ISO_SIZE", 32), \
                patch.object(season, "SOURCE_SHA256", hash_stream(io.BytesIO(b"A" * 32))):
            report = season.build(self.source, self.output, self.roster, self.workspace,
                                  texture_workspace=native_workspace)
        self.assertEqual(visual.call_args.kwargs, {"include_courts": False, "repack_archive": False})
        self.assertEqual(logos.call_args.args[1:], (native_workspace, court_edits))
        self.assertEqual(report["visuals"]["courts"], report["logos"]["courts"])
        self.assertEqual(self.output.read_bytes()[16:18], b"LL")

    def test_overlapping_components_fail_before_publication(self):
        with patch.object(season.roster_iso, "prepare", return_value=([self.roster_patch], {})), \
                patch.object(season.lettering_workspace, "prepare", return_value=([(1, b"AA", b"VV")], {})):
            with self.assertRaisesRegex(ValueError, "disjoint"):
                season.check(self.source, self.output, self.workspace, roster=self.roster)
        self.assertFalse(self.output.exists())

    def test_uniform_workspace_routes_lettering_through_single_resource_composer(self):
        native = self.root / "native"
        native.mkdir()
        (native / "_iso_uniforms.json").write_text("{}")
        with patch.object(season.roster_iso, "prepare", return_value=([], {})), \
                patch.object(season.lettering_workspace, "prepare", return_value=([], {})) as letters, \
                patch.object(season.court_colours, "decoded_edits", return_value=[]), \
                patch.object(season.archive_iso, "plan", return_value=([], [], {})), \
                patch.object(season.texture_iso_workspace, "prepare", return_value=([], {"courts": []})) as textures:
            season.prepare(io.BytesIO(), self.workspace, self.root / "slots.csv",
                           texture_workspace=native, repack_archive=True)
        self.assertIs(letters.call_args.kwargs["texture_edits"], textures.call_args.kwargs["texture_edits"])
        self.assertTrue(textures.call_args.kwargs["repack_archive"])

    def test_generic_workspace_routes_skin_explicitly_even_with_unrelated_palette_path(self):
        native = self.root / "native"
        native.mkdir()
        (native / "_iso_textures.json").write_text("{}")
        with patch.object(season.roster_iso, "prepare", return_value=([], {})), \
                patch.object(season.lettering_workspace, "prepare", return_value=([], {})) as letters, \
                patch.object(season.court_colours, "decoded_edits", return_value=[]), \
                patch.object(season.archive_iso, "plan", return_value=([], [], {})), \
                patch.object(season.texture_iso_workspace, "prepare", return_value=([], {"courts": []})) as textures:
            season.prepare(io.BytesIO(), self.root / "separate-palettes", self.root / "slots.csv",
                           texture_workspace=native, skin_plan=self.plan, repack_archive=True)
        self.assertTrue(letters.call_args.kwargs["compose_skin"])
        self.assertIs(letters.call_args.kwargs["texture_edits"], textures.call_args.kwargs["texture_edits"])

    def test_final_roster_generated_portraits_join_native_composition(self):
        native = self.root / "native"
        native.mkdir()
        (native / "_iso_textures.json").write_text("{}")
        generated = {"portrait-id": object()}
        portrait_report = {"generated": 1}
        with patch.object(season.roster_iso, "prepare", return_value=([], {})), \
                patch.object(season.portrait_iso, "prepare", return_value=(generated, portrait_report)) as portraits, \
                patch.object(season.lettering_workspace, "prepare", return_value=([], {})), \
                patch.object(season.court_colours, "decoded_edits", return_value=[]), \
                patch.object(season.texture_iso_workspace, "prepare", return_value=([], {"courts": []})) as textures, \
                patch.object(season, "ISO_SIZE", 32):
            _, report = season.prepare(io.BytesIO(), self.workspace, self.root / "slots.csv",
                                       roster=self.roster, texture_workspace=native)
        portraits.assert_called_once_with(self.roster, native)
        self.assertIs(textures.call_args.kwargs["generated_masters"], generated)
        self.assertEqual(report["logos"]["portraits"], portrait_report)

    def test_portraits_follow_final_roster_and_report_missing_inputs(self):
        payload = bytearray(0x68000)
        rows = []
        for record, (pid, proa_id, first) in enumerate(((123, 1001, "Alice"), (124, 1002, "Bob"))):
            offset = portrait_iso.PLAYER_BASE + record * portrait_iso.PLAYER_STRIDE
            struct.pack_into("<HH", payload, offset + 4, pid, pid)
            for field, text, target in ((offset + 0x10, first, 0x67000 + record * 0x40),
                                        (offset + 0x0C, "Test", 0x67020 + record * 0x40)):
                encoded = (text + "\0").encode("utf-16le")
                payload[target:target + len(encoded)] = encoded
                struct.pack_into("<i", payload, field, target - field + 1)
            rows.append({"record": record, "pid": pid, "proa_id": proa_id, "first": first, "last": "Test"})
        self.roster.write_bytes(payload)
        mapping = self.root / "players.csv"
        with mapping.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, rows[0])
            writer.writeheader()
            writer.writerows(rows)
        photos = self.root / "photos"
        photos.mkdir()
        Image.new("RGB", (512, 512), "red").save(photos / "1001.png")
        manifest = {"complete": True, "sources": [
            {"asset_hash": portrait_iso.PORTRAIT_ASSET, "texture": "0123", "id": "p1"},
            {"asset_hash": portrait_iso.PORTRAIT_ASSET, "texture": "0124", "id": "p2"},
            {"asset_hash": "other", "asset": "global.iff", "scene": "nophoto", "texture": "nophoto", "id": "missing"},
        ]}
        placeholder = photos / "nophoto.png"
        Image.new("RGBA", (128, 128), "blue").save(placeholder)
        with patch.object(portrait_iso.roster_iso, "validate_payload"), \
                patch.object(portrait_iso.remaining_texture_workspace, "load_manifest", return_value=manifest), \
                patch.object(portrait_iso.texture_iso_workspace, "scan", return_value={"missing": placeholder}):
            generated, report = portrait_iso.prepare(self.roster, self.workspace, mapping, photos)
            self.assertEqual(set(generated), {"p1", "p2"})
            self.assertEqual(generated["p2"].getpixel((0, 0)), (0, 0, 255, 255))
            self.assertEqual(report["placeholders"], 1)
            self.assertEqual(report["missing_headshots"], [1002])
            rows[0]["first"] = "Outdated"
            with mapping.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, rows[0])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "does not match"):
                portrait_iso.prepare(self.roster, self.workspace, mapping, photos)

    def test_portrait_generation_rejects_shared_portrait_owners(self):
        payload = bytearray(0x68000)
        rows = []
        for record, proa_id in enumerate((1001, 1002)):
            offset = portrait_iso.PLAYER_BASE + record * portrait_iso.PLAYER_STRIDE
            struct.pack_into("<HH", payload, offset + 4, 123, 123)
            for field, text, target in ((offset + 0x10, "Test", 0x67000 + record * 0x40),
                                        (offset + 0x0C, "Player", 0x67020 + record * 0x40)):
                encoded = (text + "\0").encode("utf-16le")
                payload[target:target + len(encoded)] = encoded
                struct.pack_into("<i", payload, field, target - field + 1)
            rows.append({"record": record, "pid": 123, "proa_id": proa_id, "first": "Test", "last": "Player"})
        self.roster.write_bytes(payload)
        mapping = self.root / "players.csv"
        with mapping.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, rows[0])
            writer.writeheader()
            writer.writerows(rows)
        photos = self.root / "photos"
        photos.mkdir()
        Image.new("RGB", (512, 512), "red").save(photos / "1001.png")
        manifest = {"complete": True, "sources": [
            {"asset_hash": portrait_iso.PORTRAIT_ASSET, "texture": "0123", "id": "p1"}]}
        with patch.object(portrait_iso.roster_iso, "validate_payload"), \
                patch.object(portrait_iso.remaining_texture_workspace, "load_manifest", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "share native portrait"):
                portrait_iso.prepare(self.roster, self.workspace, mapping, photos)

    def test_repack_absorbs_all_archive_edits_and_preserves_outside_patches(self):
        logo_patch = (16, b"AA", b"LLL")
        rendered = b"A" * 16 + b"LLL" + b"A" * 13
        copy_plan = [CopySpan(0, 32, data=rendered)]
        archive_report = {"changed_assets": 2}
        with patch.object(season.roster_iso, "prepare", return_value=([self.roster_patch], {})), \
                patch.object(season.lettering_workspace, "prepare", return_value=([self.visual_patch], {"sources": 1})) as visuals, \
                patch.object(season.court_colours, "decoded_edits", return_value=[]), \
                patch.object(season.texture_iso_workspace, "prepare",
                             return_value=([logo_patch], {"courts": []})) as logos, \
                patch.object(season.archive_iso, "plan",
                             return_value=(copy_plan, [self.roster_patch, self.visual_patch], archive_report)) as plan, \
                patch.object(season, "ISO_SIZE", 32), \
                patch.object(season, "SOURCE_SHA256", hash_stream(io.BytesIO(b"A" * 32))):
            report = season.build(self.source, self.output, self.roster, self.workspace,
                                  texture_workspace=self.root / "native", repack_archive=True)
        self.assertEqual(logos.call_args.kwargs, {"repack_archive": True, "slots": season.lettering_workspace.DEFAULT_SLOTS})
        self.assertEqual(visuals.call_args.kwargs, {"include_courts": False, "repack_archive": True})
        self.assertEqual(plan.call_args.args[1], [self.roster_patch, self.visual_patch, logo_patch])
        self.assertEqual(report["archive"], archive_report)
        self.assertEqual(self.output.read_bytes(), b"RR" + b"A" * 6 + b"VV" + b"A" * 6 + b"LLL" + b"A" * 13)

    def test_component_failure_does_not_publish(self):
        with patch.object(season.roster_iso, "prepare", side_effect=ValueError("Invalid roster")), \
                patch.object(season.lettering_workspace, "prepare") as visuals:
            with self.assertRaisesRegex(ValueError, "Invalid roster"):
                season.build(self.source, self.output, self.roster, self.workspace)
        visuals.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_existing_output_manifest_or_source_as_output_is_rejected(self):
        with self.assertRaises(ValueError):
            season.validate_output(self.source, self.source, self.workspace)
        self.output.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            season.validate_output(self.source, self.output, self.workspace)
        self.output.unlink()
        self.output.with_name(self.output.name + season.MANIFEST_SUFFIX).write_text("{}")
        with self.assertRaisesRegex(ValueError, "manifest"):
            season.validate_output(self.source, self.output, self.workspace)

    def test_year_and_startup_changes_share_one_crc_compensation(self):
        with patch.object(season.roster_iso, "prepare", return_value=([], {"elf_crc_delta": 0x0C05E998})), \
                patch.object(season.lettering_workspace, "prepare", return_value=([], {})), \
                patch.object(season, "prepare_year_patch", return_value=([], {})) as year:
            season.prepare(io.BytesIO(), self.workspace, self.root / "slots.csv", 2026, self.roster)
            self.assertEqual(year.call_args.args[1:], (2026, 0x0C05E998))
            season.prepare(io.BytesIO(), self.workspace, self.root / "slots.csv", roster=self.roster)
            self.assertEqual(year.call_args.args[1:], (2004, 0x0C05E998))

    def test_cli_derives_palettes_from_native_workspace_and_preserves_override(self):
        for extra, expected in (([], Path("native") / "team_palettes"),
                                (["--workspace", "custom"], Path("custom"))):
            with patch.object(sys, "argv", ["season_iso.py", "check", "--iso-source", "source.iso",
                                            "--iso-out", "new.iso", "--texture-workspace", "native", *extra]), \
                    patch.object(season, "check", return_value={"visuals": {"sources": 0}}) as check, \
                    patch("builtins.print"):
                season.main()
            self.assertEqual(check.call_args.args[2], expected)
            self.assertEqual(check.call_args.args[-1], Path("native"))


if __name__ == "__main__":
    unittest.main()
