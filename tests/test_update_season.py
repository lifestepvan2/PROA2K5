import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_season as season


class SeasonIsoTests(unittest.TestCase):
    def invoke(self, arguments, runner):
        with patch.object(sys, "argv", ["update_season.py", *arguments]), \
                patch.object(season, "run", runner), \
                patch.object(season.skin_tones, "workbook_requests", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            season.main()

    def test_default_pipeline_neither_requires_nor_writes_iso(self):
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running") as running:
            self.invoke(["--skip-scrape"], runner)
            self.assertFalse(any(call.args[0] == "lettering_workspace.py" for call in runner.call_args_list))
            self.assertEqual(runner.call_args_list[-1].args, ("gen_logo_replacements.py",))
            self.assertEqual(runner.call_args_list[0].args, ("player_database.py",))
            running.assert_not_called()

    def test_iso_preflight_first_and_generation_last(self):
        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso",
                "--lettering-workspace", "palettes"]
        with patch.object(season, "run") as runner:
            self.invoke(args, runner)
            expected = ("--iso-source", "clean.iso", "--iso-out", "new.iso", "--workspace", "palettes",
                        "--stats-year", "2026")
            self.assertEqual(runner.call_args_list[0].args, ("lettering_workspace.py", "check", *expected))
            self.assertEqual(runner.call_args_list[-1].args, ("lettering_workspace.py", "build", *expected,
                                                            "--skin-plan", str(season.skin_tones.PLAN)))
            self.assertEqual(runner.call_args_list[-2].args, ("gen_logo_replacements.py",))
            casting = next(call.args for call in runner.call_args_list if call.args[0] == "face_match.py")
            self.assertEqual(casting, ("face_match.py", "--iso-source", "clean.iso"))

    def test_partial_iso_options_fail_before_pipeline(self):
        for args in (["--iso-source", "clean.iso"], ["--iso-out", "new.iso"]):
            with patch.object(season, "run") as runner, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.invoke(args, runner)
                runner.assert_not_called()

    def test_shared_workspace_is_used_for_both_roster_builds_without_iso(self):
        with patch.object(season, "run") as runner:
            self.invoke(["--skip-scrape", "--team-palettes", "palettes"], runner)
            roster_calls = [call.args for call in runner.call_args_list if call.args[0] == "build_roster.py"]
            self.assertEqual(roster_calls, [
                ("build_roster.py", "--season", "2026_2027", "--team-palettes", "palettes", "--prepare-faces"),
                ("build_roster.py", "--season", "2026_2027", "--team-palettes", "palettes")])

    def test_card_is_written_only_after_combined_iso_succeeds(self):
        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso", "--card", "copy.ps2"]
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running", return_value=False):
            self.invoke(args, runner)
        calls = [call.args for call in runner.call_args_list]
        self.assertEqual(calls[-1], ("build_roster.py", "--season", "2026_2027", "--card", "copy.ps2"))
        self.assertEqual(calls[-2][0:2], ("lettering_workspace.py", "build"))

    def test_failed_combined_iso_never_writes_card(self):
        def run(*arguments):
            if arguments[:2] == ("lettering_workspace.py", "build"):
                raise subprocess.CalledProcessError(1, "build")

        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso", "--card", "copy.ps2"]
        with patch.object(season, "run", side_effect=run) as runner, \
                patch.object(season, "pcsx2_running", return_value=False):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(args, runner)
        self.assertFalse(any("--card" in call.args for call in runner.call_args_list))

    def test_nonzero_skin_without_iso_stops_before_roster_generation(self):
        with patch.object(sys, "argv", ["update_season.py", "--skip-scrape"]), \
                patch.object(season, "run") as runner, \
                patch.object(season.skin_tones, "workbook_requests", return_value=["123"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "Skin Tone requires"):
                season.main()
        self.assertEqual([call.args for call in runner.call_args_list], [("player_database.py",)])

    def test_invalid_season_is_rejected_before_side_effects(self):
        for value in ("2026", "2026_2028", "abc_def"):
            with patch.object(season, "run") as runner, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.invoke(["--season", value], runner)
                runner.assert_not_called()

    def test_failed_preflight_prevents_roster_and_texture_writes(self):
        with patch.object(season, "run", side_effect=subprocess.CalledProcessError(1, "check")) as runner:
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(["--iso-source", "clean.iso", "--iso-out", "new.iso"], runner)
            self.assertEqual(len(runner.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
