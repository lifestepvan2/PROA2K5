import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build
from build_roster import PLAYER_BASE, PLAYER_COUNT, PLAYER_STORAGE_COUNT, PLAYER_STRIDE, set_non_proa_ratings
from rating_map_2k5 import ATTR_OFFSETS


class BuildTests(unittest.TestCase):
    def test_build_uses_current_workspace_and_never_scrapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clean.iso"
            source.touch()
            workspace = root / "native"
            workspace.mkdir()
            for name in ("_iso_logos.json", "_iso_uniforms.json", "_iso_textures.json"):
                (workspace / name).touch()
            report = {"output": "built.iso", "build_id": {"value": "0123456789abcdef"}, "logos": {}}
            portraits = {"generated": 1, "placeholders": 0, "missing_headshots": [], "suppressed_portraits": []}
            with patch.object(sys, "argv", ["build.py", "--season", "2027_2028"]), \
                    patch.object(build, "SOURCE", source), \
                    patch.object(build.texture_iso_workspace, "DEFAULT_WS", workspace), \
                    patch.object(build, "run") as run, \
                    patch.object(build.skin_tones, "populate_workspace",
                                 return_value={"masters": 0, "players": 0}), \
                    patch.object(build.portrait_iso, "populate", return_value=portraits) as populate, \
                    patch.object(build.season_iso, "build_named", return_value=report) as publish, \
                    contextlib.redirect_stdout(io.StringIO()):
                build.main()
            scripts = [call.args[0] for call in run.call_args_list]
            self.assertEqual(scripts, ["player_database.py", "crop_headshots.py", "build_roster.py",
                                       "face_embed.py", "face_match.py", "build_roster.py"])
            populate.assert_called_once_with(build.ROSTER, workspace)
            self.assertEqual(publish.call_args.args[0:4], (source, build.OUTPUT_DIR, build.ROSTER,
                                                          workspace / "team_palettes"))
            self.assertEqual(publish.call_args.kwargs["stats_year"], 2027)
            self.assertEqual(run.call_args_list[1].args, ("crop_headshots.py", "--season", "2027_2028"))
            self.assertTrue(all("--suppress-non-proa" in call.args for call in run.call_args_list
                                if call.args[0] == "build_roster.py"))

    def test_keep_non_proa_flag_disables_both_roster_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clean.iso"
            source.touch()
            workspace = root / "native"
            workspace.mkdir()
            for name in ("_iso_logos.json", "_iso_uniforms.json", "_iso_textures.json"):
                (workspace / name).touch()
            with patch.object(sys, "argv", ["build.py", "--keep-non-proa-ratings"]), \
                    patch.object(build, "SOURCE", source), \
                    patch.object(build.texture_iso_workspace, "DEFAULT_WS", workspace), \
                    patch.object(build, "run") as run, \
                    patch.object(build.skin_tones, "populate_workspace", return_value={"masters": 0, "players": 0}), \
                    patch.object(build.portrait_iso, "populate", return_value={"generated": 0, "placeholders": 0,
                                                                            "missing_headshots": [], "suppressed_portraits": []}), \
                    patch.object(build.season_iso, "build_named",
                                 return_value={"output": "built.iso", "build_id": {"value": "0"}}), \
                    contextlib.redirect_stdout(io.StringIO()):
                build.main()
            calls = [call for call in run.call_args_list if call.args[0] == "build_roster.py"]
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("--suppress-non-proa" not in call.args for call in calls))

    def test_non_proa_reset_protects_allocated_records_hidden_bytes_and_templates(self):
        data = bytearray([123]) * (PLAYER_BASE + PLAYER_STORAGE_COUNT * PLAYER_STRIDE)
        before = bytes(data)
        protected = {5, 395, PLAYER_COUNT - 1}
        self.assertEqual(set_non_proa_ratings(data, protected), PLAYER_COUNT - len(protected))
        untouched = [offset for offset in range(PLAYER_STRIDE) if offset not in ATTR_OFFSETS.values()]
        for record in range(PLAYER_STORAGE_COUNT):
            base = PLAYER_BASE + record * PLAYER_STRIDE
            if record in protected or record >= PLAYER_COUNT:
                self.assertEqual(data[base:base + PLAYER_STRIDE], before[base:base + PLAYER_STRIDE])
            else:
                self.assertEqual([data[base + offset] for offset in ATTR_OFFSETS.values()], [50] * 19)
                self.assertEqual([data[base + offset] for offset in untouched],
                                 [before[base + offset] for offset in untouched])
        with self.assertRaisesRegex(ValueError, "outside the main player table"):
            set_non_proa_ratings(data, {PLAYER_COUNT})
        with self.assertRaisesRegex(ValueError, "complete player table"):
            set_non_proa_ratings(bytearray(100), {0})

    def test_missing_source_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", ["build.py"]), \
                patch.object(build, "SOURCE", Path(directory) / "missing.iso"), \
                patch.object(build, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build.main()
            run.assert_not_called()

    def test_invalid_season_stops_before_writing(self):
        with patch.object(sys, "argv", ["build.py", "--season", "2027_2029"]), \
                patch.object(build, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build.main()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
