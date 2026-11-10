import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import texture_catalogue as native
from test_vc_lz import literal_stream


def pointer(data, field, target):
    struct.pack_into("<i", data, field, target - field + 1)


def texture(psm=19, width=2, height=2, levels=1, kind=b"TXTR"):
    system = 96
    bits, palette = {19: (8, 1024), 20: (4, 64), 0: (32, 0)}[psm]
    sizes = [((max(1, width >> i) * max(1, height >> i) * bits + 7) // 8 + 15) // 16 * 16
             for i in range(levels)]
    video = sum(sizes) + palette
    data = bytearray(system + video)
    data[12:16] = kind
    pointer(data, 16, 32)
    pointer(data, 20, 48)
    data[32:36] = b"x\0\0\0"
    struct.pack_into("<Q", data, 48, psm << 20)
    struct.pack_into("<HH", data, 92, width, height)
    if palette:
        for index in range(palette // 4):
            struct.pack_into("4B", data, len(data) - palette + index * 4, index, 2, 3, 128)
        data[system:system + 4] = b"\x08\x10\x18\x00" if psm == 19 else b"\x21\x43\0\0"
    else:
        data[system:system + 16] = b"\x01\x02\x03\x80" * 4
    return bytes(data), system, video


def texture_set():
    data = bytearray(256)
    struct.pack_into("<II", data, 0, 13, 2)
    for obj, descriptor, name_at, name in ((12, 128, 88, "arm"), (48, 184, 104, "neck")):
        data[obj + 12:obj + 16] = b"TXTR"
        pointer(data, obj + 16, name_at)
        pointer(data, obj + 20, descriptor)
        encoded = name.encode("utf-16le")
        data[name_at:name_at + len(encoded)] = encoded
        struct.pack_into("<HH", data, descriptor + 44, 2, 2)
    return data


def header(kind, data, system, video, compressed=False):
    return (kind, len(data), system, video, 0xFEEDBEEF if compressed else 0, 0, 0, 0)


class TextureCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        native.create_database(self.connection)
        self.addCleanup(self.connection.close)

    def test_tagged_pointer_and_bounded_utf16(self):
        data = bytearray(16)
        pointer(data, 8, 2)
        self.assertEqual(native.relative(data, 8), 2)
        data[2:6] = "xy".encode("utf-16le")
        self.assertEqual(native.text(data, 2, 8), "xy")
        for field in (-1, 13):
            with self.assertRaises(ValueError):
                native.relative(data, field)
        struct.pack_into("<I", data, 8, 2)
        with self.assertRaises(ValueError):
            native.relative(data, 8)
        with self.assertRaises(ValueError):
            native.text(b"x\0y\0", 0, 4)
        with self.assertRaises(ValueError):
            native.text(data, 1, 8)

    def test_indexed_linear_pixels_and_clut(self):
        for psm, expected in ((19, (16, 8, 24, 0)), (20, (1, 2, 3, 4))):
            data, system, video = texture(psm)
            images, layout = native.linear_images(data, system, video, 48)
            self.assertEqual(layout, "linear")
            self.assertEqual(tuple(images[0]["rgba"][::4]), expected)
            self.assertEqual(images[0]["rgba"][3::4], b"\x80" * 4)

    def test_truecolour_and_seven_mips(self):
        data, system, video = texture(0)
        images, _ = native.linear_images(data, system, video, 48)
        self.assertEqual(images[0]["rgba"], b"\x01\x02\x03\x80" * 4)
        data, system, video = texture(19, 64, 32, 7)
        images, layout = native.linear_images(data, system, video, 48)
        self.assertEqual(layout, "linear-seven-mip")
        self.assertEqual([(i["width"], i["height"]) for i in images],
                         [(64, 32), (32, 16), (16, 8), (8, 4), (4, 2), (2, 1), (1, 1)])

    def test_unsupported_layout_is_not_a_mapping(self):
        data, system, video = texture()
        images, reason = native.linear_images(data + b"\0" * 8, system, video + 8, 48)
        self.assertEqual(images, [])
        self.assertIn("transfer decoder", reason)
        with self.assertRaisesRegex(ValueError, "truncated"):
            native.linear_images(data[:-1], system, video, 48)

    def test_standalone_compression_and_shared_pixel_aliases(self):
        data, system, video = texture()
        packed = literal_stream(data)
        native.add_resource(self.connection, "aa", 0, header(b"TXTR", packed, system, video, True), 0, packed)
        hitx, _, _ = texture(kind=b"HITX")
        native.add_resource(self.connection, "bb", 0, header(b"HITX", hitx, system, video), 0, hitx)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM textures").fetchone()[0], 2)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM images").fetchone()[0], 2)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM pixels").fetchone()[0], 1)

    def test_sets_and_failed_resource_do_not_leave_partial_mappings(self):
        data = texture_set()
        self.assertEqual(native.descriptors(data, "TSET", len(data)), [(128, "arm"), (184, "neck")])
        native.add_resource(self.connection, "aa", 0, header(b"TSET", data, len(data), 0), 0, data)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM textures WHERE status='blocked'").fetchone()[0], 2)
        struct.pack_into("<HH", data, 184 + 44, 0, 0)
        # An invalid second descriptor pointer must reject the entire resource.
        pointer(data, 68, 254)
        native.add_resource(self.connection, "bb", 0, header(b"TSET", data, len(data), 0), 0, data)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM textures WHERE asset_hash='bb'").fetchone()[0], 0)
        status = self.connection.execute("SELECT status,reason FROM resources WHERE asset_hash='bb'").fetchone()
        self.assertEqual(status["status"], "blocked")
        self.assertTrue(status["reason"])

    def test_scene_material_context(self):
        data = bytearray(320)
        data[12:16] = b"SCNE"
        pointer(data, 16, 32)
        pointer(data, 20, 64)
        data[32:44] = "court\0".encode("utf-16le")
        struct.pack_into("<I", data, 84, 1)
        pointer(data, 88, 112)
        struct.pack_into("<I", data, 92, 1)
        pointer(data, 96, 192)
        pointer(data, 176 + 8, 280)
        pointer(data, 176 + 92, 112)
        data[280:290] = "wood\0".encode("utf-16le")
        self.assertEqual(native.descriptors(data, "SCNE", len(data)), [(112, "wood")])
        self.assertEqual(native.descriptors(data, "HiSn", len(data)), [(112, "wood")])

    def test_metadata_only_chunks_do_not_claim_an_empty_body_hash(self):
        native.add_resource(self.connection, "aa", 0, (b"PS2i", 500, 300, 200, 0, 0, 0, 0), 0, b"")
        row = self.connection.execute("SELECT * FROM resources").fetchone()
        self.assertEqual(row["status"], "metadata-only")
        self.assertIsNone(row["stored_sha256"])

    def test_nested_markscene_and_cinematic_descriptors_follow_tagged_scene_pointer(self):
        data = bytearray(256)
        pointer(data, 20, 32)
        pointer(data, 32, 96)
        struct.pack_into("<I", data, 96 + 20, 1)
        pointer(data, 96 + 24, 160)
        for kind, magic in (("MRKS", b"MRKS"), ("MRKH", b"MRKS"), ("CNSR", b"CNSR")):
            data[12:16] = magic
            self.assertEqual(native.descriptors(data, kind, len(data)), [(160, "descriptor-0")])
        pointer(data, 32, 240)
        with self.assertRaisesRegex(ValueError, "Truncated scene"):
            native.descriptors(data, "CNSR", len(data))

    def test_font_inline_descriptor_is_bounded_and_keeps_metrics_outside_pixels(self):
        data = bytearray(160)
        data[12:16] = b"FONT"
        pointer(data, 16, 32)
        data[32:42] = "font\0".encode("utf-16le")
        pointer(data, 20, 64)
        self.assertEqual(native.descriptors(data, "FONT", len(data)), [(96, "font")])
        with self.assertRaisesRegex(ValueError, "exceeds system"):
            native.descriptors(data, "FONT", 140)

    def test_dimensions_are_part_of_image_identity(self):
        rgba = b"\0" * 16
        self.assertNotEqual(native.pixel_digest(2, 2, rgba), native.pixel_digest(1, 4, rgba))
        with self.assertRaises(ValueError):
            native.pixel_digest(2, 2, rgba[:-1])

    def test_ownership_uses_native_arena_mapping_not_roster_slot(self):
        courts = {"s009.iff": [{"slot": 21, "team": "Pistons"}]}
        self.assertEqual(native.ownership("s009.iff", courts)["teams"], courts["s009.iff"])
        self.assertEqual(native.ownership("seluh021.iff", courts)["team"], "Pistons")
        self.assertEqual(native.ownership("p035a2.iff", courts)["pid"], 35)
        self.assertEqual(native.ownership("hash:abcd", courts)["kind"], "unresolved_asset")
        warmup = native.ownership("wh017.iff", courts)
        self.assertEqual((warmup["team"], warmup["variant"], warmup["warmup"]), ("Mavericks", "home", True))

    def test_rejects_incomplete_or_wrong_catalogue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite"
            connection = sqlite3.connect(path)
            native.create_database(connection)
            connection.executemany("INSERT INTO metadata VALUES (?,?)", [
                ("schema", "1"), ("source_sha256", native.SOURCE_SHA256), ("complete", "false")])
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                native.open_catalogue(path)
            connection = sqlite3.connect(path)
            connection.execute("UPDATE metadata SET value='true' WHERE key='complete'")
            connection.commit()
            connection.close()
            checked = native.open_catalogue(path)
            checked.close()
            path.unlink()

    def test_catalogue_closes_database_before_publish_and_refuses_overwrite(self):
        data, system, video = texture()
        raw = struct.pack("<4s7I", *header(b"TXTR", data, system, video)) + data
        with tempfile.TemporaryDirectory() as directory:
            source, out = Path(directory) / "source.iso", Path(directory) / "cache.sqlite"
            source.write_bytes(raw)
            with patch.object(native, "read_archive", return_value={1: (0, len(raw))}), \
                 patch.object(native, "resolve_names", return_value={1: "p035h.iff"}), \
                 patch.object(native, "hash_stream", return_value=native.SOURCE_SHA256):
                result = native.catalogue(source, out)
            self.assertEqual(result["images"], 1)
            self.assertTrue(out.is_file())
            self.assertFalse(out.with_suffix(".sqlite.tmp").exists())
            with self.assertRaisesRegex(ValueError, "already exists"):
                native.catalogue(source, out)
            out.unlink()


if __name__ == "__main__":
    unittest.main()
