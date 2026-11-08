import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inventory_lettering_iso import asset_hash, lettering_chunks
from test_vc_lz import literal_stream


def resource(name: str, compressed: bool = False, width: int = 1024) -> bytes:
    height = 64 if name == "numbers" else 32
    size = (0x159C0 if width == 1024 else 0xAF20) if name == "numbers" else 0xAF10
    body = bytearray(size)
    body[12:16] = b"TXTR"
    body[32:48] = (name + "\0").encode("utf-16le").ljust(16, b"\0")
    struct.pack_into("<HH", body, 0x5C, width, height)
    body[-1024:] = bytes((20, 40, 100, 128)) * 256
    stored = literal_stream(bytes(body)) if compressed else bytes(body)
    return struct.pack("<4s7I", b"TXTR" if compressed else b"HITX", len(stored),
                       0x70, len(body) - 0x70, 0xFEEDBEEF if compressed else 0, 128, 0, 0) + stored


class LetteringInventoryTests(unittest.TestCase):
    def test_hash_matches_runtime_and_archive_identities(self):
        self.assertEqual(asset_hash("seluh020.iff"), 0x0F1821E5)
        self.assertEqual(asset_hash("SELUA015.IFF"), 0x43D4368F)
        self.assertEqual(asset_hash("uh020.iff"), 0xAD6241D2)
        self.assertEqual(asset_hash("ua020.iff"), 0x70194F0C)

    def test_game_and_compressed_preview_palettes_match(self):
        game = lettering_chunks(resource("names") + resource("numbers"))
        preview = lettering_chunks(resource("numbers", compressed=True))
        self.assertEqual([row["target"] for row in game], ["names", "numbers"])
        self.assertEqual(preview[0]["compressed"], 1)
        self.assertEqual(game[1]["palette_sha256"], preview[0]["palette_sha256"])
        self.assertEqual(game[1]["descriptor_indices_mips_sha256"], preview[0]["descriptor_indices_mips_sha256"])

    def test_rejects_bad_boundaries_and_geometry(self):
        for data in (b"bad", resource("numbers")[:-1]):
            with self.assertRaises(ValueError):
                lettering_chunks(data)
        data = bytearray(resource("numbers"))
        struct.pack_into("<HH", data, 32 + 0x5C, 128, 64)
        with self.assertRaisesRegex(ValueError, "geometry"):
            lettering_chunks(bytes(data))

    def test_512_wide_number_sources_are_included(self):
        game = lettering_chunks(resource("numbers", width=512))
        preview = lettering_chunks(resource("numbers", compressed=True, width=512))
        self.assertEqual(preview[0]["width"], 512)
        self.assertEqual(game[0]["palette_sha256"], preview[0]["palette_sha256"])


if __name__ == "__main__":
    unittest.main()
