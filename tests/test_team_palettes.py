import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import team_palettes as palettes


def config():
    settings = {"mode": "outlined", "fill": "#123456", "outline1": "#010203", "outline2": "#ABCDEF"}
    return {"schema": 1, "team": dict.fromkeys(palettes.TEAM_FIELDS, "#123456"),
            "uniforms": {"home": {"names": settings.copy(), "numbers": settings.copy()}},
            "court": {"mode": "original", "primary": "#111111", "secondary": "#222222", "lines": "#FFFFFF"}}


class TeamPaletteTests(unittest.TestCase):
    def test_all_canonical_slots_and_variant_counts(self):
        values = [palettes.load(palettes.DEFAULT_WS, slot) for slot in range(30)]
        self.assertEqual(sum(len(value["uniforms"]) for value in values), 79)
        self.assertFalse((palettes.DEFAULT_WS.parent / "lettering").exists())
        self.assertEqual(len(list(palettes.DEFAULT_WS.rglob("colours.json"))), 30)

    def test_schema_rejects_unknown_missing_invalid_and_alpha_values(self):
        mutations = [
            lambda c: c.update(extra=True),
            lambda c: c["team"].pop("colorui1"),
            lambda c: c["team"].update(colorjersey1="#12345678"),
            lambda c: c["uniforms"]["home"]["names"].update(fill="#GGGGGG"),
            lambda c: c["court"].update(mode="silent"),
            lambda c: c["court"].update(lines=[255, 255, 255]),
            lambda c: c["uniforms"].update(fake=c["uniforms"]["home"]),
        ]
        for mutate in mutations:
            value = config()
            mutate(value)
            with self.assertRaises(ValueError):
                palettes.validate(value)

    def test_migration_preserves_all_uniform_controls_and_binary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, dest = root / "lettering", root / "team_palettes"
            for slot in range(30):
                path = source / f"{slot:03}" / "home"
                path.mkdir(parents=True)
                controls = {"schema": 1, **config()["uniforms"]["home"]}
                (path / "colours.json").write_text(json.dumps(controls))
                (path / "numbers.palette.png").write_bytes(bytes((slot, 123, 255)))
            teams, slots = root / "teams.csv", root / "slots.csv"
            teams.write_text("sheet,colorjersey1,colorjersey2,colorui1,colorui2\nTest,#010203,#040506,#070809,#0A0B0C\n")
            slots.write_text("sheet,nba_slot\nTest,22\n")
            with patch.object(palettes, "defaults", side_effect=lambda slot, uniforms:
                              {**copy.deepcopy(config()), "uniforms": uniforms}):
                palettes.migrate(source, dest, teams, slots)
            for slot in range(30):
                self.assertEqual(palettes.load(dest, slot)["uniforms"], config()["uniforms"])
                self.assertEqual((dest / f"{slot:03}" / "home" / "numbers.palette.png").read_bytes(),
                                 bytes((slot, 123, 255)))
            self.assertEqual(palettes.team_colours(dest, 22)["colorui1"], "#070809")
            self.assertFalse(source.exists())

    def test_error_has_document_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "colours.json"):
                palettes.load(Path(directory), 22)


if __name__ == "__main__":
    unittest.main()
