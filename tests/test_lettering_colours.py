import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lettering_colours import blend_weights, default_settings, parse_hex, recolour, validate_controls
from test_inventory_lettering_iso import resource
from txtr_match import SWZ


def coloured_atlas(width=1024):
    body = bytearray(resource("numbers", width=width)[32:])
    logical = np.zeros((256, 4), dtype=np.uint8)
    logical[:8] = [(235, 235, 235, 0), (20, 33, 78, 128), (247, 219, 0, 128),
                   (255, 255, 255, 128), (77, 80, 59, 128), (251, 237, 127, 64),
                   (252, 245, 192, 32), (1, 1, 1, 128)]
    logical[200] = (134, 126, 39, 128)
    physical = np.zeros_like(logical)
    physical[SWZ] = logical
    body[-1024:] = physical.tobytes()
    pixels = bytes([1]) * 500 + bytes([2]) * 100 + bytes([3]) * 20 + bytes([4]) * 40 + bytes([5]) * 20
    body[0x70:0x70 + len(pixels)] = pixels
    body[0x70 + width * 64] = 200
    return bytes(body)


class ColourTests(unittest.TestCase):
    def test_defaults_and_unchanged_outlined_controls_are_byte_exact(self):
        body = coloured_atlas()
        controls = default_settings(body, 1024, 64)
        self.assertEqual(controls, {"mode": "palette", "fill": "#14214E",
                                   "outline1": "#F7DB00", "outline2": "#FFFFFF"})
        controls["mode"] = "outlined"
        self.assertEqual(recolour(body, 1024, 64, controls)[0], body[-1024:])

    def test_monochrome_recolours_every_visible_entry_including_lower_mips(self):
        for width in (512, 1024):
            body = coloured_atlas(width)
            controls = {**default_settings(body, width, 64), "mode": "monochrome", "fill": "#123456"}
            palette, diagnostics = recolour(body, width, 64, controls)
            original = np.frombuffer(body[-1024:], dtype=np.uint8).reshape(256, 4)[SWZ]
            result = np.frombuffer(palette, dtype=np.uint8).reshape(256, 4)[SWZ]
            self.assertTrue(np.all(result[original[:, 3] != 0, :3] == (18, 52, 86)))
            np.testing.assert_array_equal(result[original[:, 3] == 0], original[original[:, 3] == 0])
            np.testing.assert_array_equal(result[:, 3], original[:, 3])
            self.assertEqual(result[200, :3].tolist(), [18, 52, 86])
            self.assertEqual(diagnostics["clipped_entries"], 0)

    def test_generic_blends_and_source_alpha_are_preserved(self):
        body = coloured_atlas()
        controls = {"mode": "outlined", "fill": "#0C8C50", "outline1": "#FFFFFF", "outline2": "#000000"}
        palette, _ = recolour(body, 1024, 64, controls)
        result = np.frombuffer(palette, dtype=np.uint8).reshape(256, 4)[SWZ]
        np.testing.assert_allclose(result[4, :3], .75 * np.array([12, 140, 80]) + .25 * 255, atol=2)
        self.assertEqual(palette[3::4], body[-1021::4])

    def test_equal_base_colours_collapse_to_exact_monochrome(self):
        body = coloured_atlas()
        controls = dict(mode="outlined", fill="#ABCDEF", outline1="#ABCDEF", outline2="#ABCDEF")
        actual = recolour(body, 1024, 64, controls)[0]
        controls["mode"] = "monochrome"
        self.assertEqual(actual, recolour(body, 1024, 64, controls)[0])

    def test_collinear_and_identical_reference_colours_remain_finite(self):
        for bases in (np.array([[0., 0., 0.], [255., 255., 255.], [255., 255., 255.]]),
                      np.ones((3, 3)) * 255):
            weights = blend_weights(np.array([[0., 0., 0.], [128., 128., 128.], [255., 255., 255.]]), bases)
            self.assertTrue(np.isfinite(weights).all())
            self.assertTrue((weights >= -1e-10).all())
            np.testing.assert_allclose(weights.sum(axis=1), 1)

    def test_recolouring_uses_pristine_references_not_previous_output(self):
        body = coloured_atlas()
        controls = {**default_settings(body, 1024, 64), "mode": "outlined", "fill": "#0C8C50"}
        recolour(body, 1024, 64, controls)
        controls["fill"] = "#963214"
        expected = recolour(body, 1024, 64, controls)[0]
        fresh = {**default_settings(body, 1024, 64), "mode": "outlined", "fill": "#963214"}
        self.assertEqual(expected, recolour(body, 1024, 64, fresh)[0])

    def test_range_clipping_is_reported(self):
        body = coloured_atlas()
        controls = dict(mode="outlined", fill="#000000", outline1="#000000", outline2="#FFFFFF")
        _, diagnostics = recolour(body, 1024, 64, controls)
        self.assertGreater(diagnostics["clipped_entries"], 0)

    def test_invalid_colour_modes_fields_and_schema_are_rejected(self):
        for value in ("FFFFFFF", "#12", "red", "12345G", 123, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_hex(value)
        settings = default_settings(coloured_atlas(), 1024, 64)
        for config in ({"schema": True, "numbers": settings, "names": settings},
                       {"schema": 1, "numbers": {**settings, "mode": "mono"}, "names": settings},
                       {"schema": 1, "numbers": {**settings, "outline": "#000000"}, "names": settings}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_controls(config)


if __name__ == "__main__":
    unittest.main()
