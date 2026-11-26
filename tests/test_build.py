import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


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
