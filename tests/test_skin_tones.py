import contextlib
import copy
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import skin_tones as skin
import skin_brighten as sb
import gen_skin_replacements as gen
import build_roster
import face_match
import player_database as db
import texlib
from player_texture_iso import texture_resource
from test_player_texture_iso import resource, compact_asset
from test_player_database import workbook


def fixture_asset(red):
    palette = np.zeros((256, 4), dtype=np.uint8)
    palette[:, :3] = (red, round(red * .75), round(red * .6))
    palette[:, 3] = 128
    result = b""
    for part, count in (("face", 256 * 256), ("arm", 128 * 128), ("neck", 128 * 64)):
        result += resource(part, bytes(count) + palette.tobytes())
    return result


class FixtureAssets:
    def __init__(self, stream=None, verify_hash=True):
        self.data = {pid: fixture_asset(value) for pid, value in ((10, 160), (20, 200), (30, 75))}
        self.entries = {skin.asset_hash(f"p{pid}{side}.iff"): (0, len(body))
                        for pid, body in self.data.items() for side in ("h", "a")}

    def asset(self, pid, side):
        return (pid * 1000000 + (500000 if side == "a" else 0), self.data[pid])

    def resource(self, pid, side, part):
        return texture_resource(self.data[pid], part)


class GrowingFixtureAssets(FixtureAssets):
    def __init__(self, stream=None, verify_hash=True):
        super().__init__(stream, verify_hash)
        position, body, decoded, system, _ = self.resource(20, "h", "arm")
        pixels = random.Random(31).randbytes(128 * 128) + decoded[-1024:]
        donor = self.data[20]
        self.data[20] = donor[:position] + resource("arm", pixels) + donor[position + 32 + len(body):]
        self.data = {pid: compact_asset(body) for pid, body in self.data.items()}


class SkinToneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = [{"proa_id": "123", "pid": 10, "skin_tone": 1},
                     {"proa_id": "456", "pid": 30, "skin_tone": 0}]
        patcher = patch.object(skin, "load_candidates", return_value={(5, "arm"): [20], (5, "neck"): [20]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, **kwargs):
        with patch.object(skin, "Assets", FixtureAssets), \
                patch.object(skin, "donor_candidates", return_value={(5, "arm"): [20], (5, "neck"): [20]}):
            return skin.create_plan(None, self.rows, defaults=[], keys={}, **kwargs)

    def test_repack_plan_survives_arm_growth_then_neck_and_face_updates_on_both_sides(self):
        with patch.object(skin, "Assets", GrowingFixtureAssets):
            with self.assertRaisesRegex(ValueError, "no compatible arm donor"):
                skin.create_plan(None, self.rows)
            plan = skin.create_plan(None, self.rows, repack_archive=True)
        self.assertTrue(plan["repack_archive"])
        assets = GrowingFixtureAssets()
        patches, reports = skin.compile_plan(None, plan, self.rows, assets, repack_archive=True)
        self.assertEqual(len(patches), 2)
        for _, before, after in patches:
            self.assertGreater(len(after), len(before))
            for part in ("arm", "neck"):
                _, _, decoded, system, _ = texture_resource(after, part)
                _, _, donor, donor_system, _ = assets.resource(20, "h", part)
                self.assertEqual(decoded[system:], donor[donor_system:])
                self.assertEqual(decoded[:system], texture_resource(before, part)[2][:system])
            _, _, old_face, system, _ = texture_resource(before, "face")
            _, _, new_face, _, _ = texture_resource(after, "face")
            self.assertEqual(old_face[:-1024], new_face[:-1024])
            self.assertEqual(old_face[-1021::4], new_face[-1021::4])
        self.assertTrue(all(row["new_size"] > row["size"] for row in reports))
        self.assertEqual([row["asset"] for row in reports], ["p10h.iff", "p10a.iff"])

    def test_repack_recipe_requires_matching_publisher_mode_and_old_recipes_remain_usable(self):
        plan = self.create(repack_archive=True)
        with self.assertRaisesRegex(ValueError, "requires --repack-archive"):
            skin.compile_plan(None, plan, self.rows, FixtureAssets())
        plan.pop("repack_archive")
        skin.compile_plan(None, plan, self.rows, FixtureAssets())
        skin.compile_plan(None, plan, self.rows, FixtureAssets(), repack_archive=True)
        plan["repack_archive"] = "true"
        with self.assertRaisesRegex(ValueError, "storage mode"):
            skin.compile_plan(None, plan, self.rows, FixtureAssets(), repack_archive=True)

    def test_load_patches_forwards_repack_mode(self):
        plan = self.create(repack_archive=True)
        path = self.root / "plan.json"
        skin.save_plan(path, plan)
        with patch.object(skin, "Assets", FixtureAssets):
            patches, reports = skin.load_patches(None, path, self.rows, repack_archive=True)
        self.assertEqual((len(patches), len(reports)), (2, 2))

    def test_schema_zero_and_bounds(self):
        for value in (0, "0", 1, 6, "6"):
            self.assertEqual(db.field_value("Skin Tone", value), int(value))
        for value in (-1, 7, True, 1.5, "automatic"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                db.field_value("Skin Tone", value)

    def test_old_workbook_migrates_without_scrape_preserving_other_values(self):
        book = workbook()
        sheet = book.active
        columns = {cell.value: cell.column for cell in sheet[1]}
        sheet.delete_cols(columns["Skin Tone"])
        with contextlib.redirect_stdout(io.StringIO()):
            db.apply_overrides(book, {123: {"Skin Tone": 6}})
        columns = {cell.value: cell.column for cell in sheet[1]}
        self.assertEqual(sheet.cell(2, columns["Skin Tone"]).value, 6)
        self.assertEqual(sheet.cell(2, columns["First Name"]).value, "Test")
        self.assertEqual(sheet.cell(2, columns["ProA ID"]).value, 123)
        path = self.root / "book.xlsx"
        book.save(path)
        book.close()
        self.assertEqual(skin.workbook_requests(path), ["123"])

    def test_signature_preserves_manual_pid_and_refuses_shared_pid_when_any_override(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["override_pid"] = "20"
        self.assertEqual(skin.signature(rows)[0]["pid"], 20)
        rows[1]["pid"] = 20
        for order in (rows, list(reversed(rows))):
            with self.assertRaisesRegex(ValueError, "unique PID"):
                skin.signature(order)
        with self.assertRaisesRegex(ValueError, "Duplicate player"):
            skin.signature([self.rows[0], self.rows[0]])

    def test_zero_requests_reset_stale_plan_without_needing_iso(self):
        rows = [{**row, "skin_tone": 0} for row in self.rows]
        plan = skin.create_plan(None, rows)
        self.assertEqual(plan["players"], [])
        self.assertEqual(skin.compile_plan(None, plan, rows), ([], []))
        self.assertEqual(skin.create_plan(None, [{"pid": 10, "proa_id": "123"}])["players"], [])

    def test_plan_recolours_face_preserves_indices_alpha_and_other_models(self):
        plan = self.create()
        self.assertEqual(plan["players"][0]["leg_byte"], 5)
        self.assertEqual(len(plan["players"]), 1)
        assets = FixtureAssets()
        before_control = assets.data[30]
        patches, report = skin.compile_plan(None, plan, self.rows, assets)
        self.assertEqual(len(patches), 2)
        self.assertEqual(len(report), 2)
        for _, before, after in patches:
            self.assertEqual(len(before), len(after))
            for part in ("arm", "neck"):
                actual = texture_resource(after, part)
                expected = assets.resource(20, "h", part)
                self.assertEqual(actual[2][actual[3]:], expected[2][expected[3]:])
            old_face = texture_resource(before, "face")
            new_face = texture_resource(after, "face")
            self.assertEqual(old_face[2][:-1024], new_face[2][:-1024])
            self.assertEqual(old_face[2][-1021::4], new_face[2][-1021::4])
            self.assertNotEqual(old_face[2][-1024:], new_face[2][-1024:])
        self.assertEqual(assets.data[30], before_control)

    def test_stale_roster_pid_tone_or_removed_player_refused(self):
        plan = self.create()
        changed_rows = [
            [{**self.rows[0], "pid": 20}, self.rows[1]],
            [{**self.rows[0], "skin_tone": 2}, self.rows[1]],
            [self.rows[0]],
        ]
        for rows in changed_rows:
            with self.assertRaisesRegex(ValueError, "stale"):
                skin.compile_plan(None, plan, rows, FixtureAssets())
        changed = copy.deepcopy(plan)
        changed["players"] = []
        with self.assertRaisesRegex(ValueError, "every requested player"):
            skin.compile_plan(None, changed, self.rows, FixtureAssets())

    def test_bad_alpha_rgb_source_hash_or_missing_side_rejected(self):
        plan = self.create()
        for mutation, message in (("alpha", "alpha"), ("rgb", "donor-derived"),
                                  ("source", "source changed"), ("side", "both home and away")):
            bad = copy.deepcopy(plan)
            recipe = bad["players"][0]["assets"][0]
            palette = bytearray.fromhex(recipe["face_palette_hex"])
            if mutation in ("alpha", "rgb"):
                palette[3 if mutation == "alpha" else 0] ^= 1
                recipe["face_palette_hex"] = palette.hex()
            elif mutation == "source":
                recipe["source_asset_sha256"] = "changed"
            else:
                bad["players"][0]["assets"].pop()
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, message):
                skin.compile_plan(None, bad, self.rows, FixtureAssets())

    def test_edited_donor_cannot_change_bucket_or_reintroduce_legacy_png_collision(self):
        plan = self.create()
        plan["players"][0]["arm_donor"] = 30
        with self.assertRaisesRegex(ValueError, "outside the requested bucket"):
            skin.compile_plan(None, plan, self.rows, FixtureAssets())

    def test_legacy_replacements_ignore_manual_tone_and_keep_automatic_behavior(self):
        path = self.root / "map.csv"
        path.write_text("proa_id,pid,override_pid,skin_target,skin_tone\n"
                        "123,10,,1.5,1\n456,30,,1.6,0\n", encoding="utf-8")
        with patch.object(gen, "MAP", path), patch.object(sb, "usable_pids", return_value={10, 30}):
            users = gen.used_reserved()
        self.assertEqual([row["proa_id"] for row, _, _ in users], ["456"])

    def test_legacy_generator_prunes_previous_manual_players_managed_pngs(self):
        replacements = self.root / "replacements"
        replacements.mkdir()
        old = replacements / "old-face.png"
        old.write_bytes(b"old managed PNG")
        (self.root / "pipeline_managed.json").write_text(json.dumps({"skin": ["old-face"]}))
        with patch.object(sys, "argv", ["gen_skin_replacements.py", "--out", str(replacements)]), \
                patch.object(gen.sb, "read_keys", return_value={}), \
                patch.object(gen, "dump_files", return_value={}), \
                patch.object(gen, "plan", return_value={}), \
                patch.object(gen, "used_reserved", return_value=[]), \
                patch.object(texlib, "TEX_ROOT", self.root), contextlib.redirect_stdout(io.StringIO()):
            gen.main()
        self.assertFalse(old.exists())
        self.assertEqual(json.loads((self.root / "pipeline_managed.json").read_text())["skin"], [])

    def test_provisional_roster_cannot_write_card(self):
        with patch.object(sys, "argv", ["build_roster.py", "--prepare-faces", "--card", "copy.ps2"]), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                build_roster.main()
        self.assertEqual(error.exception.code, 2)

    def test_donors_exclude_every_legacy_skin_replacement_key(self):
        defaults, keys = [], {}
        for pid, arm_key, neck_key, usable in ((10, "blocked-arm", "blocked-neck", "1"),
                                               (20, "blocked-arm", "safe-neck", "0"),
                                               (30, "safe-arm", "safe-neck", "0")):
            record = bytearray(148)
            record[4:6] = pid.to_bytes(2, "little")
            record[sb.P_SKIN] = 5
            defaults.append({"team_slot": "1", "hex": record.hex()})
            keys[pid] = {"arm_key": arm_key, "neck_key": neck_key, "usable": usable}
        candidates = skin.donor_candidates(FixtureAssets(), defaults, keys)
        self.assertEqual(candidates[5, "arm"], [30])
        self.assertEqual(candidates[5, "neck"], [20])

    def test_donor_fallback_and_explicit_exhaustion(self):
        with patch.object(skin, "replace_texture", side_effect=[ValueError("fixed span"), (b"", {}), (b"", {})]):
            donor = skin._choose_donor(FixtureAssets(), 10, {(5, "arm"): [30, 20]}, "arm", 5)
        self.assertEqual(donor, 20)
        with self.assertRaisesRegex(ValueError, "no compatible arm donor"):
            skin._choose_donor(FixtureAssets(), 10, {}, "arm", 5)

    def test_plan_save_is_atomic_and_does_not_remove_existing_temporary_file(self):
        path = self.root / "plan.json"
        skin.save_plan(path, {"schema": 1})
        self.assertEqual(json.loads(path.read_text()), {"schema": 1})
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(b"other writer")
        with self.assertRaises(FileExistsError):
            skin.save_plan(path, {"schema": 2})
        self.assertEqual(temporary.read_bytes(), b"other writer")
        self.assertEqual(json.loads(path.read_text()), {"schema": 1})

    def test_face_match_creates_plan_with_cached_pid_without_rematching(self):
        rows = [self.rows[0] | {"team_slot": "1", "record": "0", "first": "A", "last": "B",
                               "sheet": "Team", "slot": "0", "ovr": "80"}]
        loaded = ([10, 20], {10: "Original", 20: "Other"}, np.eye(2), np.array([1.5, 1.6]),
                  rows, np.array([[1., 0.]]), np.array([1.5]), {}, np.array([False, False]))
        mapping = self.root / "map.csv"
        plan_path = self.root / "plan.json"
        source = self.root / "source.iso"
        source.write_bytes(b"fixture")
        plan = {"players": []}
        with patch.object(sys, "argv", ["face_match.py", "--iso-source", str(source), "--skin-plan", str(plan_path),
                                       "--repack-archive"]), \
                patch.object(face_match, "load", return_value=loaded), \
                patch.object(face_match, "read_map", return_value={"123": {"pid": "10", "sim": "1", "skin_pen": "0"}}), \
                patch.object(sb, "reserved_pids", return_value=set()), \
                patch.object(sb, "usable_pids", return_value=set()), \
                patch.object(face_match, "SHEETS", self.root / "sheets"), \
                patch.object(face_match, "sheet"), patch.object(face_match, "MAP", mapping), \
                patch.object(skin, "create_plan", return_value=plan) as create, \
                patch.object(skin, "Assets", FixtureAssets), contextlib.redirect_stdout(io.StringIO()):
            face_match.main()
        final_rows = create.call_args.args[1]
        self.assertEqual(final_rows[0]["pid"], 10)
        self.assertEqual(final_rows[0]["skin_tone"], 1)
        self.assertEqual(create.call_args.kwargs, {"repack_archive": True})
        self.assertEqual(json.loads(plan_path.read_text()), plan)
        self.assertIn("skin_tone", mapping.read_text())

    def test_face_map_is_preserved_if_plan_publication_fails(self):
        rows = [self.rows[0] | {"team_slot": "1", "record": "0", "first": "A", "last": "B",
                               "sheet": "Team", "slot": "0", "ovr": "80"}]
        loaded = ([10, 20], {10: "Original", 20: "Other"}, np.eye(2), np.array([1.5, 1.6]),
                  rows, np.array([[1., 0.]]), np.array([1.5]), {}, np.array([False, False]))
        mapping = self.root / "map.csv"
        mapping.write_bytes(b"existing manual choices")
        source = self.root / "source.iso"
        source.write_bytes(b"fixture")
        with patch.object(sys, "argv", ["face_match.py", "--iso-source", str(source)]), \
                patch.object(face_match, "load", return_value=loaded), \
                patch.object(face_match, "read_map", return_value={"123": {"pid": "10", "sim": "1", "skin_pen": "0"}}), \
                patch.object(sb, "reserved_pids", return_value=set()), \
                patch.object(sb, "usable_pids", return_value=set()), \
                patch.object(face_match, "SHEETS", self.root / "sheets"), \
                patch.object(face_match, "sheet"), patch.object(face_match, "MAP", mapping), \
                patch.object(skin, "create_plan", return_value={"players": []}), \
                patch.object(skin, "save_plan", side_effect=OSError("plan is locked")), \
                patch.object(skin, "Assets", FixtureAssets), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, "plan is locked"):
                face_match.main()
        self.assertEqual(mapping.read_bytes(), b"existing manual choices")
        self.assertFalse(mapping.with_name(mapping.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
