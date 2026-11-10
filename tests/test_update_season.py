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
                patch("roster_iso.read_source"), patch("roster_iso.baseline"), \
                patch("pathlib.Path.open"), \
                contextlib.redirect_stdout(io.StringIO()):
            season.main()

    def test_build_only_does_not_publish_iso_or_card(self):
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running") as running:
            self.invoke(["--skip-scrape", "--iso-source", "clean.iso", "--build-only"], runner)
            self.assertFalse(any(call.args[0] in ("season_iso.py", "card_patch.py") for call in runner.call_args_list))
            self.assertEqual(runner.call_args_list[-1].args, ("gen_logo_replacements.py",))
            self.assertEqual(runner.call_args_list[0].args, ("player_database.py",))
            running.assert_not_called()

    def test_iso_preflight_first_and_generation_last(self):
        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso",
                "--lettering-workspace", "palettes"]
        with patch.object(season, "run") as runner:
            self.invoke(args, runner)
            expected = ("--iso-source", "clean.iso", "--iso-out", "new.iso", "--workspace", "palettes",
                        "--stats-year", "2026", "--texture-workspace", str(season.texture_iso_workspace.DEFAULT_WS))
            self.assertEqual(runner.call_args_list[0].args, ("season_iso.py", "check", *expected))
            self.assertEqual(runner.call_args_list[-1].args, ("season_iso.py", "build", *expected,
                                                            "--skin-plan", str(season.skin_tones.PLAN),
                                                            "--roster", str(season.ROOT / "data" / "roster_build" / "payload_proa.bin")))
            self.assertEqual(runner.call_args_list[-2].args, ("gen_skin_replacements.py",))
            self.assertFalse(any(call.args[0] == "gen_logo_replacements.py" for call in runner.call_args_list))
            casting = next(call.args for call in runner.call_args_list if call.args[0] == "face_match.py")
            self.assertEqual(casting, ("face_match.py", "--iso-source", "clean.iso"))

    def test_partial_iso_options_fail_before_pipeline(self):
        for args in ([], ["--iso-source", "clean.iso"], ["--iso-out", "new.iso"],
                     ["--iso-source", "clean.iso", "--card-only"],
                     ["--iso-source", "clean.iso", "--card-only", "--card", "copy.ps2", "--iso-out", "new.iso"],
                     ["--iso-source", "clean.iso", "--build-only", "--card", "copy.ps2"]):
            with patch.object(season, "run") as runner, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.invoke(args, runner)
                runner.assert_not_called()

    def test_native_workspace_selects_matching_palettes_without_redirecting_legacy_tools(self):
        self.assertEqual(season.team_palettes.DEFAULT_WS,
                         season.ROOT / "texture_workspace" / "team_palettes")
        for extra, expected in (([], str(Path("native") / "team_palettes")),
                                (["--team-palettes", "custom"], "custom")):
            with patch.object(season, "run") as runner:
                self.invoke(["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso",
                             "--texture-workspace", "native", *extra], runner)
            for call in runner.call_args_list:
                if call.args[0] == "season_iso.py":
                    self.assertEqual(call.args[call.args.index("--workspace") + 1], expected)
                elif call.args[0] == "build_roster.py":
                    self.assertEqual(call.args[call.args.index("--team-palettes") + 1], expected)

    def test_legacy_logo_generation_is_explicit_in_iso_mode(self):
        with patch.object(season, "run") as runner:
            self.invoke(["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso",
                         "--legacy-logo-replacements"], runner)
        self.assertEqual(sum(call.args[0] == "gen_logo_replacements.py"
                             for call in runner.call_args_list), 1)

    def test_archive_repack_is_explicit_and_forwarded_to_check_and_build(self):
        with patch.object(season, "run") as runner:
            self.invoke(["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso",
                         "--repack-archive"], runner)
        calls = [call.args for call in runner.call_args_list if call.args[0] == "season_iso.py"]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--repack-archive" in call for call in calls))
        with patch.object(season, "run") as runner, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.invoke(["--iso-source", "clean.iso", "--build-only", "--repack-archive"], runner)
        runner.assert_not_called()

    def test_shared_workspace_is_used_for_both_roster_builds_without_iso(self):
        with patch.object(season, "run") as runner:
            self.invoke(["--skip-scrape", "--iso-source", "clean.iso", "--build-only",
                         "--team-palettes", "palettes"], runner)
            roster_calls = [call.args for call in runner.call_args_list if call.args[0] == "build_roster.py"]
            self.assertEqual(roster_calls, [
                ("build_roster.py", "--season", "2026_2027", "--iso-source", "clean.iso",
                 "--team-palettes", "palettes", "--prepare-faces"),
                ("build_roster.py", "--season", "2026_2027", "--iso-source", "clean.iso",
                 "--team-palettes", "palettes")])

    def test_card_is_written_only_after_combined_iso_succeeds(self):
        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso", "--card", "copy.ps2"]
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running", return_value=False):
            self.invoke(args, runner)
        calls = [call.args for call in runner.call_args_list]
        self.assertEqual(calls[-1], ("card_patch.py", "--bin",
                                    str(season.ROOT / "data" / "roster_build" / "payload_proa.bin"),
                                    "--card", "copy.ps2"))
        self.assertEqual(calls[-2][0:2], ("season_iso.py", "build"))
        self.assertEqual(sum(call[0] == "build_roster.py" for call in calls), 2)

    def test_failed_combined_iso_never_writes_card(self):
        def run(*arguments):
            if arguments[:2] == ("season_iso.py", "build"):
                raise subprocess.CalledProcessError(1, "build")

        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso", "--card", "copy.ps2"]
        with patch.object(season, "run", side_effect=run) as runner, \
                patch.object(season, "pcsx2_running", return_value=False):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(args, runner)
        self.assertFalse(any("--card" in call.args for call in runner.call_args_list))

    def test_nonzero_skin_without_iso_stops_before_roster_generation(self):
        with patch.object(sys, "argv", ["update_season.py", "--skip-scrape", "--iso-source", "clean.iso", "--build-only"]), \
                patch.object(season, "run") as runner, \
                patch.object(season.skin_tones, "workbook_requests", return_value=["123"]), \
                patch("roster_iso.read_source"), patch("roster_iso.baseline"), patch("pathlib.Path.open"), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "Skin Tone requires"):
                season.main()
        self.assertEqual([call.args for call in runner.call_args_list], [("player_database.py",)])

    def test_invalid_season_is_rejected_before_side_effects(self):
        for value in ("2026", "2026_2028", "abc_def"):
            with patch.object(season, "run") as runner, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.invoke(["--season", value, "--iso-source", "clean.iso", "--build-only"], runner)
                runner.assert_not_called()

    def test_failed_preflight_prevents_roster_and_texture_writes(self):
        with patch.object(season, "run", side_effect=subprocess.CalledProcessError(1, "check")) as runner:
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(["--iso-source", "clean.iso", "--iso-out", "new.iso"], runner)
            self.assertEqual(len(runner.call_args_list), 1)

    def test_card_only_exports_the_same_final_payload_without_rebuilding(self):
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running", return_value=False):
            self.invoke(["--skip-scrape", "--iso-source", "clean.iso", "--card-only", "--card", "copy.ps2"], runner)
        calls = [call.args for call in runner.call_args_list]
        self.assertEqual(calls[-1][0], "card_patch.py")
        self.assertEqual(sum(call[0] == "build_roster.py" for call in calls), 2)
        self.assertFalse(any(call[0] == "season_iso.py" for call in calls))

    def test_running_pcsx2_blocks_card_before_any_pipeline_work(self):
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running", return_value=True):
            with self.assertRaisesRegex(SystemExit, "PCSX2 is running"):
                self.invoke(["--iso-source", "clean.iso", "--card-only", "--card", "copy.ps2"], runner)
        runner.assert_not_called()

    def test_invalid_disc_baseline_blocks_build_only_before_workbook_changes(self):
        with patch.object(sys, "argv", ["update_season.py", "--iso-source", "clean.iso", "--build-only"]), \
                patch("pathlib.Path.open"), patch("roster_iso.read_source", side_effect=ValueError("Invalid ISO")), \
                patch.object(season, "run") as runner:
            with self.assertRaisesRegex(ValueError, "Invalid ISO"):
                season.main()
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
