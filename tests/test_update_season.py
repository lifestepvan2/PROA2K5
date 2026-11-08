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
                patch.object(season, "run", runner), contextlib.redirect_stdout(io.StringIO()):
            season.main()

    def test_default_pipeline_neither_requires_nor_writes_iso(self):
        with patch.object(season, "run") as runner, patch.object(season, "pcsx2_running") as running:
            self.invoke(["--skip-scrape"], runner)
            self.assertFalse(any(call.args[0] == "lettering_workspace.py" for call in runner.call_args_list))
            self.assertEqual(runner.call_args_list[-1].args, ("gen_logo_replacements.py",))
            running.assert_not_called()

    def test_iso_preflight_first_and_generation_last(self):
        args = ["--skip-scrape", "--iso-source", "clean.iso", "--iso-out", "new.iso",
                "--lettering-workspace", "palettes"]
        with patch.object(season, "run") as runner:
            self.invoke(args, runner)
            expected = ("--iso-source", "clean.iso", "--iso-out", "new.iso", "--workspace", "palettes")
            self.assertEqual(runner.call_args_list[0].args, ("lettering_workspace.py", "check", *expected))
            self.assertEqual(runner.call_args_list[-1].args, ("lettering_workspace.py", "build", *expected))
            self.assertEqual(runner.call_args_list[-2].args, ("gen_logo_replacements.py",))

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
            self.assertEqual(roster_calls, [("build_roster.py", "--team-palettes", "palettes")] * 2)

    def test_failed_preflight_prevents_roster_and_texture_writes(self):
        with patch.object(season, "run", side_effect=subprocess.CalledProcessError(1, "check")) as runner:
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(["--iso-source", "clean.iso", "--iso-out", "new.iso"], runner)
            self.assertEqual(len(runner.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
