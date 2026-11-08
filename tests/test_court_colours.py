import copy
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import court_colours as courts
from vc_lz import decode


def arena():
    return {"slot": 22, "nba_team": "Raptors", "asset": "s022.iff",
            "materials": [{"index": i, "rgba_offset": 16 + i * 4, "rgba": [79, 63, 122, 128]}
                          for i in range(4)],
            "untextured_floor_material_indices": [2, 3],
            "shared_floor_paint_material_indices": [2, 3],
            "line_masks": [{"descriptor_offset": 0, "palette_logical_entry_offsets": [64, 68],
                            "material_indices": [0]}],
            "filled_circle_masks": [{"descriptor_offset": 1, "palette_logical_entry_offsets": [72],
                                     "material_indices": [1]}],
            "plain_paint_parts": [
                {"material_index": 2, "colour_streams": [{"format": "V4-8", "data_offset": 80, "count": 2}]},
                {"material_index": 3, "colour_streams": [{"format": "V4-5", "data_offset": 88, "count": 2}]}],
            "indexed_apron": []}


CONTROL = {"mode": "recolour", "primary": "#123456", "secondary": "#987654", "lines": "#ABCDEF"}


def source():
    value = bytearray([33] * 128)
    value[71] = 0
    return bytes(value)


class CourtColourTests(unittest.TestCase):
    def test_raptors_linked_slots_and_exact_neutral_rgba(self):
        before = source()
        after, profile = courts.recolour(before, arena(), CONTROL)
        self.assertEqual(after[24:27], bytes.fromhex("123456"))
        self.assertEqual(after[28:31], bytes.fromhex("987654"))
        self.assertEqual(after[64:67], bytes.fromhex("abcdef"))
        self.assertEqual(after[68:72], before[68:72])  # Transparent palette entry stays untouched.
        self.assertEqual(after[72:75], bytes.fromhex("987654"))
        self.assertEqual(after[80:88], bytes((128, 128, 128, 128)) * 2)
        self.assertEqual(after[88:92], struct.pack("<H", 0xC210) * 2)
        self.assertEqual(profile["linked_regions"], [2, 3])
        allowed = set(range(16, 19)) | set(range(20, 23)) | set(range(24, 27)) | set(range(28, 31))
        allowed |= set(range(64, 67)) | set(range(72, 75)) | set(range(80, 92))
        self.assertTrue(all(a == b or i in allowed for i, (a, b) in enumerate(zip(before, after))))

    def test_original_mode_is_byte_identical(self):
        self.assertEqual(courts.recolour(source(), arena(), {**CONTROL, "mode": "original"})[0], source())

    def test_hawks_reduced_profile_preserves_masks_and_authored_vertices(self):
        value = arena()
        value["slot"] = 9
        value["untextured_floor_material_indices"] = [2]
        after, profile = courts.recolour(source(), value, CONTROL)
        self.assertEqual(profile["line_mode"], "material_tint")
        self.assertFalse(profile["flatten_zone_vertices"])
        self.assertEqual(after[64:72], source()[64:72])
        self.assertEqual(after[80:92], source()[80:92])
        self.assertEqual(after[16:19], bytes.fromhex("abcdef"))
        self.assertEqual(after[24:27], bytes.fromhex("123456"))
        self.assertEqual(after[28:31], bytes.fromhex("987654"))

    def test_hornets_apron_interpolation_keeps_alpha(self):
        value = arena()
        value["indexed_apron"] = [{"palette_offset": 96, "material_index": 0,
                                   "white_border_weights": [0, 0.5, 1, -0.008]}]
        result, _ = courts.recolour(source(), value, CONTROL)
        self.assertEqual(result[96:99], bytes.fromhex("123456"))
        self.assertEqual(result[104:107], bytes.fromhex("abcdef"))
        self.assertEqual(result[99:112:4], source()[99:112:4])
        value["indexed_apron"][0]["white_border_weights"] = [1.1]
        with self.assertRaisesRegex(ValueError, "tolerance"):
            courts.recolour(source(), value, CONTROL)

    def test_conflicting_materials_and_unknown_formats_refused(self):
        value = arena()
        value["line_masks"][0]["material_indices"] = [2]
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            courts.recolour(source(), value, CONTROL)
        value = arena()
        value["plain_paint_parts"][0]["colour_streams"][0]["format"] = "guess"
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            courts.recolour(source(), value, CONTROL)

    def test_source_fingerprints_and_fixed_span_refusal(self):
        value = arena()
        original = source()
        compressed = struct.pack("<II", len(original), 0) + b"\x0c" + b"".join(
            b"\0" + original[i:i + 8] for i in range(0, len(original), 8))
        value.update(asset_offset=0, chunk_offset=0, stored=len(compressed), system=64, video=64,
                     scratch=256, stored_sha256=courts.digest(compressed), decoded_sha256=courts.digest(original))
        header = struct.pack("<4s7I", b"SCNE", len(compressed), 64, 64, 0xFEEDBEEF, 256, 0, 0)
        with patch.object(courts, "source_catalogue", return_value={"arenas": [value]}), \
                patch("team_palettes.load", return_value={"court": CONTROL}):
            patches, reports = courts.prepare(io.BytesIO(header + compressed), Path("unused"))
            self.assertEqual(len(patches), 1)
            self.assertEqual(patches[0][0], 32)
            self.assertEqual(len(patches[0][1]), len(patches[0][2]))
            self.assertEqual(decode(patches[0][2], 128)[0], courts.recolour(original, value, CONTROL)[0])
            self.assertEqual(reports[0]["nba_slot"], 22)
            with patch.object(courts, "rebuild_tail", side_effect=ValueError("fixed span")):
                with self.assertRaisesRegex(ValueError, "Slot 022.*no ISO was published"):
                    courts.prepare(io.BytesIO(header + compressed), Path("unused"))
            damaged = bytearray(compressed)
            damaged[-1] ^= 1
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                courts.prepare(io.BytesIO(header + damaged), Path("unused"))


if __name__ == "__main__":
    unittest.main()
