import io
import random
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import player_texture_iso as iso
from player_texture_iso import inspect, replace_texture, texture_resource
from inventory_lettering_iso import asset_hash
from patch_lettering_iso import digest
from vc_lz import decode, rebuild_tail


def resource(part, value, capacity=None):
    width, height = {"arm": (128, 128), "neck": (128, 64), "face": (256, 256)}[part]
    system = 0x60 if part == "arm" else 0x70
    data_offset = 0x28 if part == "arm" else 0x30
    descriptor = bytearray(system)
    descriptor[12:16] = b"TXTR"
    struct.pack_into("<ii", descriptor, 16, 0x20 - 0x10 + 1, data_offset - 0x14 + 1)
    name = (part + "\0").encode("utf-16le")
    descriptor[32:32 + len(name)] = name
    struct.pack_into("<HH", descriptor, data_offset + 0x2C, width, height)
    pixels = bytes([value]) * (width * height + 1024) if isinstance(value, int) else value
    decoded = bytes(descriptor) + pixels
    encoded = bytearray(struct.pack("<II", len(decoded), 0x5C) + b"\x0B")
    for start in range(0, len(decoded), 8):
        encoded.append(0)
        encoded.extend(decoded[start:start + 8])
    if capacity:
        encoded.extend(bytes(max(0, capacity - len(encoded))))
    header = struct.pack("<4s7I", b"TXTR", len(encoded), system,
                         len(decoded) - system, 0xFEEDBEEF, len(encoded), 0, 0)
    return header + encoded


def asset(value):
    scene_body = b"geometry-stays!!\0"
    scene = struct.pack("<4s7I", b"SCNE", len(scene_body), len(scene_body), 0, 0, 0, 0, 0) + scene_body
    return resource("face", 42) + resource("arm", value) + resource("neck", value) + scene


class PlayerTextureIsoTests(unittest.TestCase):
    def test_planner_changes_only_both_target_assets(self):
        archive_base = 0x100
        image = bytearray(0xC100)
        struct.pack_into("<I", image, archive_base, 3728)
        for i in range(3728):
            struct.pack_into("<III", image, archive_base + 0x9C + i * 12, 0x100000 + i, 1, 0)
        assets = {}
        for i, (name, value) in enumerate((("p235h.iff", 20), ("p922h.iff", 90),
                                          ("p235a.iff", 30), ("p922a.iff", 100))):
            offset = len(image)
            body = asset(value)
            assets[name] = body
            image.extend(body)
            image.extend(bytes((-(len(image) - archive_base)) % 2048))
            struct.pack_into("<III", image, archive_base + 0x9C + i * 12,
                             asset_hash(name), len(body), (offset - archive_base) // 2048)
        stream = io.BytesIO(image)
        with patch.object(iso, "ARCHIVE_BASE", archive_base), patch.object(iso, "ISO_SIZE", len(image)), \
                patch.object(iso, "hash_stream", return_value=iso.SOURCE_SHA256):
            patches, report = inspect(stream, 235, 922, ["arm", "neck"])
        self.assertEqual(len(patches), 2)
        self.assertEqual([row["asset"] for row in report["assets"]], ["p235h.iff", "p235a.iff"])
        self.assertEqual(stream.getvalue(), image)
        for side, (_, original, modified) in zip(("h", "a"), patches):
            self.assertEqual(original, assets[f"p235{side}.iff"])
            for part in ("arm", "neck"):
                result = texture_resource(modified, part)
                donor = texture_resource(assets[f"p922{side}.iff"], part)
                self.assertEqual(result[2][result[3]:], donor[2][donor[3]:])

    def test_only_selected_arm_pixels_change_face_neck_scene_and_descriptor_preserved(self):
        original, donor = asset(20), asset(90)
        patched, report = replace_texture(original, donor, "arm")
        pos, body, decoded, system, _ = texture_resource(original, "arm")
        _, new_body, new_decoded, new_system, _ = texture_resource(patched, "arm")
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched[:pos + 32], original[:pos + 32])
        self.assertEqual(patched[pos + 32 + len(body):], original[pos + 32 + len(body):])
        self.assertEqual(new_system, system)
        self.assertEqual(decoded[:system], new_decoded[:system])
        self.assertEqual(new_decoded[system:], bytes([90]) * (len(decoded) - system))
        self.assertEqual(report["donor_pixels_sha256"], digest(bytes([90]) * (len(decoded) - system)))
        self.assertNotEqual(report["original_pixels_sha256"], report["donor_pixels_sha256"])
        self.assertEqual(decode(new_body, len(decoded))[0], new_decoded)
        self.assertGreater(report["changed_bytes"], 0)

    def test_neck_can_be_copied_independently(self):
        original, donor = asset(20), asset(90)
        patched, _ = replace_texture(original, donor, "neck")
        self.assertEqual(texture_resource(original, "arm")[2], texture_resource(patched, "arm")[2])
        self.assertEqual(texture_resource(patched, "neck")[2][0x70:],
                         texture_resource(donor, "neck")[2][0x70:])

    def test_identical_pixels_are_byte_identical(self):
        original = asset(20)
        patched, report = replace_texture(original, original, "arm")
        self.assertEqual(patched, original)
        self.assertEqual(report["changed_bytes"], 0)

    def test_capacity_failure_does_not_modify_source(self):
        source = resource("arm", 20)
        pos, body, decoded, system, scratch = texture_resource(source, "arm")
        packed = rebuild_tail(body, len(decoded), bytes([30]) * (len(decoded) - system), scratch)
        _, _, consumed = decode(packed, len(decoded))
        header = bytearray(source[:32])
        struct.pack_into("<I", header, 4, consumed)
        compact = bytes(header) + packed[:consumed]
        before = bytes(compact)
        donor = resource("arm", random.Random(0).randbytes(128 * 128 + 1024))
        with self.assertRaisesRegex(ValueError, "fixed span"):
            replace_texture(compact, donor, "arm")
        self.assertEqual(compact, before)

    def test_corrupt_missing_duplicate_and_unsupported_resources_fail(self):
        good = resource("arm", 20)
        for bad in (b"TXTR", good[:-1], good + good, resource("neck", 20)):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                texture_resource(bad, "arm")
        bad = bytearray(good)
        struct.pack_into("<I", bad, 16, 0)
        with self.assertRaisesRegex(ValueError, "uncompressed"):
            texture_resource(bytes(bad), "arm")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            texture_resource(good, "hair")

    def test_unsupported_iso_pid_or_parts_refused(self):
        for pid, donor in ((1, 1), (-1, 2), (1, 65536), (True, 2)):
            with self.assertRaisesRegex(ValueError, "PIDs"):
                inspect(io.BytesIO(), pid, donor, ["arm"])
        for parts in ([], ["hair"], ["arm", "arm"]):
            with self.assertRaisesRegex(ValueError, "arm and/or neck"):
                inspect(io.BytesIO(), 1, 2, parts)
        with self.assertRaisesRegex(ValueError, "pristine"):
            inspect(io.BytesIO(b"not an ISO"), 1, 2, ["arm"])


if __name__ == "__main__":
    unittest.main()
