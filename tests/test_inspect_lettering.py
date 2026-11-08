import contextlib
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inspect_lettering import inspect


class InspectLetteringTests(unittest.TestCase):
    def test_reports_preallocated_buffers_and_keeps_initialized_preview(self):
        ram = bytearray(0x5000)
        for header, pixel in ((0x200, 0x1000), (0x300, 0)):
            struct.pack_into("<Q", ram, header, 0x13 << 20)
            struct.pack_into("<I", ram, header + 0x18, pixel)
            struct.pack_into("<HH", ram, header + 0x2C, 128, 64)
        with tempfile.TemporaryDirectory() as directory, \
                patch("inspect_lettering.find_txtr", return_value=[(0x180, 0x100, 0x200), (0x280, 0x100, 0x300)]), \
                patch("inspect_lettering.wstr", return_value="jerseynum00"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rows = inspect(bytes(ram), Path(directory))
            self.assertEqual(len(rows), 1)
            self.assertIn("Skipping uninitialized", output.getvalue())
            self.assertEqual(rows[0]["pixel"], "00001000")

    def test_nonzero_invalid_pixel_pointer_remains_an_error(self):
        ram = bytearray(0x1000)
        struct.pack_into("<I", ram, 0x218, 0xFFFF)
        struct.pack_into("<Q", ram, 0x200, 0x13 << 20)
        struct.pack_into("<HH", ram, 0x22C, 128, 64)
        with tempfile.TemporaryDirectory() as directory, \
                patch("inspect_lettering.find_txtr", return_value=[(0x180, 0x100, 0x200)]), \
                patch("inspect_lettering.wstr", return_value="jerseynum00"):
            with self.assertRaisesRegex(ValueError, "Invalid lettering pixel"):
                inspect(bytes(ram), Path(directory))


if __name__ == "__main__":
    unittest.main()
