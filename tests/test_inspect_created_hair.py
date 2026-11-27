import struct
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_created_hair as hair
import inspect_created_hair_surfaces as surfaces
import created_hair_strips as strips
from test_texture_catalogue import pointer
from test_vc_lz import literal_stream


def command(op, count=0, immediate=0, payload=b""):
    data = struct.pack("<I", op << 24 | count << 16 | immediate) + payload
    return data + b"\0" * (-len(data) % 4)


def stream(normal=0x6a, count=2):
    return (struct.pack("<II", 0x60000000, 0)
            + command(0x6d, 3, 0x4127, bytes(24))
            + command(normal, count, 0x412a, bytes(count * (3 if normal == 0x6a else 4)))
            + command(0x65, count, 0x412a, bytes(count * 4))
            + command(0x6d, count, 0x4131,
                      b"".join(struct.pack("<4H", i + 1, i + 2, i + 3, 0x294 + i * 3)
                               for i in range(count)))
            + command(0x14))


def scene():
    data = bytearray(2048)
    data[12:16] = b"SCNE"
    pointer(data, 16, 1580)
    data[1580:1594] = "hihead\0".encode("utf-16le")
    pointer(data, 20, 64)
    struct.pack_into("<I", data, 64 + 28, 2)
    pointer(data, 64 + 32, 256)
    pointer(data, 256 + 0x58, 1600)
    pointer(data, 256 + 96 + 0x58, 1620)
    data[1600:1610] = "face\0".encode("utf-16le")
    data[1620:1642] = "hair01_mat\0".encode("utf-16le")
    struct.pack_into("<I", data, 64 + 44, 1)
    pointer(data, 64 + 48, 512)
    struct.pack_into("<I", data, 512 + 104, 2)
    pointer(data, 512 + 108, 768)
    for index, offset in enumerate((1024, 1280)):
        payload = stream()
        pointer(data, 768 + index * 24, offset)
        struct.pack_into("<II", data, 768 + index * 24 + 4, len(payload), index)
        data[offset:offset + len(payload)] = payload
    encoded = literal_stream(data)
    return struct.pack("<4s7I", b"SCNE", len(encoded), len(data), 0, 0xfeedbeef, 0, 0, 0) + encoded


def decoded_attribute_faces(stream):
    memory = {}
    group = None
    result = []
    for op, _, immediate, payload in hair.vif_commands(stream):
        if op == 0x6d and immediate in (0x4127, 0x41dd):
            words = struct.unpack("<" + "H" * (len(payload) // 2), payload)
            group = {"header": words[:12], "references": words[(words[6] - (immediate & 0x3ff)) * 4:]}
        elif group is not None and op == 0x6a:
            group["normals"] = list(struct.iter_unpack("<3B", payload))
        elif group is not None and op == 0x65:
            group["uv"] = list(struct.iter_unpack("<2H", payload))
        elif group is not None and op == 0x6d:
            group["positions"] = list(struct.iter_unpack("<4H", payload))
        elif group is not None and op in (0x14, 0x17):
            header, refs = group["header"], group["references"]
            for position, uv, normal in zip(group["positions"], group["uv"], group["normals"]):
                memory[position[3]] = (position[:3], uv, normal)
            copies = header[1] + header[2]
            for index in range(copies):
                a, b, c, d = refs[index * 4:index * 4 + 4]
                memory[c], memory[d] = memory[a], memory[b]
            start = header[5] + 1
            packet = [memory[start + 3 * i] for i in range(header[4] & 0x7fff)]
            markers = set(refs[copies * 4:])
            for i in range(2, len(packet)):
                if start + 3 * i in markers or start + 3 * (i - 1) in markers:
                    continue
                tri = (packet[i - 2], packet[i - 1], packet[i])
                if len({vertex[0] for vertex in tri}) == 3:
                    result.append((tri[1], tri[0], tri[2]) if i & 1 else tri)
            group = None
    return result


class CreatedHairInspectionTests(unittest.TestCase):
    def test_extracts_packed_points_with_both_normal_layouts(self):
        expected = [(1, 2, 3), (2, 3, 4)]
        for normal in (0x6a, 0x6e):
            with self.subTest(normal=normal):
                self.assertEqual(hair.vertex_points(stream(normal)), expected)

    def test_rejects_truncated_and_inconsistent_streams(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            hair.vertex_points(stream()[:-8])
        broken = bytearray(stream())
        normal_word = 8 + len(command(0x6d, 3, 0x4127, bytes(24)))
        broken[normal_word + 2] = 1
        with self.assertRaises(ValueError):
            hair.vertex_points(bytes(broken))

    def test_reads_names_from_runtime_material_array_not_previous_prefix(self):
        result = hair.scene_points(scene(), 0, "hihead")
        self.assertEqual(set(result), {"face", "hair01_mat"})
        self.assertEqual(result["hair01_mat"], (1, [(1, 2, 3), (2, 3, 4)]))
        with self.assertRaisesRegex(ValueError, "Expected locreatehead"):
            hair.scene_points(scene(), 0, "locreatehead")

    def test_surface_reuses_vertices_and_restarts_strips(self):
        def batch(base, output, coordinates, refs=()):
            copies = int(bool(refs))
            marks = (output + 10,) * 4 if copies else ()
            words = [1, copies, 0, int(bool(marks)), 0x8000 | (6 if copies else 2),
                     output, base + 3, 0, 0xa2, base + 3 + copies + int(bool(marks)),
                     len(coordinates), 0, *refs, *marks]
            count = len(coordinates)
            return (command(0x6d, len(words) // 4, 0x4000 | base,
                            struct.pack("<" + "H" * len(words), *words))
                    + command(0x6a, count, 0, bytes(count * 3))
                    + command(0x65, count, 0, bytes(count * 4))
                    + command(0x6d, count, 0, b"".join(
                        struct.pack("<4H", x, 0, 0, address) for x, address in coordinates))
                    + command(0x17))

        payload = (struct.pack("<II", 0x60000000, 0)
                   + batch(0x127, 0x293, [(1, 0x294), (2, 0x297)])
                   + batch(0x1dd, 0x349, [(3, 0x34a), (4, 0x34d),
                                          (5, 0x350), (6, 0x353)],
                           (0x294, 0x297, 0x356, 0x359)))
        vertices, faces = surfaces.vertex_surface(payload)
        self.assertEqual([v[0] for v in vertices], [1, 2, 3, 4, 5, 6, 1, 2])
        self.assertEqual(faces, [(2, 3, 4), (6, 5, 7)])

    def test_surface_rejects_missing_vertex(self):
        words = [1, 0, 0, 0, 0x8002, 0x293, 0x12a, 0, 0xa2, 0x12a, 1, 0]
        payload = (struct.pack("<II", 0x60000000, 0)
                   + command(0x6d, 3, 0x4127, struct.pack("<12H", *words))
                   + command(0x6a, 1, 0, bytes(3))
                   + command(0x65, 1, 0, bytes(4))
                   + command(0x6d, 1, 0, struct.pack("<4H", 1, 2, 3, 0x294))
                   + command(0x14))
        with self.assertRaisesRegex(ValueError, "missing VU vertex"):
            surfaces.vertex_surface(payload)

    def test_strip_encoder_reuses_vertices_across_batches(self):
        vertices = [((i, i * i, i * 7), (0x8000 + i, 0x8100 + i),
                     (i % 256, 64, 128)) for i in range(112)]
        faces = [(i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2)
                 for i in range(110)]
        encoded, detail = strips.encode(vertices, faces)
        decoded, actual_faces = surfaces.vertex_surface(encoded)

        def canonical(triangle):
            return min(triangle, triangle[1:] + triangle[:1], triangle[2:] + triangle[:2])

        expected = sorted(canonical(tuple(vertices[i][0] for i in face)) for face in faces)
        actual = sorted(canonical(tuple(decoded[i] for i in face)) for face in actual_faces
                        if len({decoded[i] for i in face}) == 3)
        self.assertEqual(expected, actual)
        expected_attributes = Counter(canonical(tuple(vertices[i] for i in face)) for face in faces)
        actual_attributes = Counter(canonical(face) for face in decoded_attribute_faces(encoded))
        self.assertEqual(expected_attributes, actual_attributes)
        self.assertLess(detail["transformed_vertices"], len(faces) * 3)
        self.assertGreater(detail["copied_vertices"], 0)
        self.assertEqual(struct.unpack_from("<I", encoded)[0] & 0xffff, len(encoded) // 16 - 1)

    def test_strip_encoder_preserves_uv_seams_and_rejects_invalid_faces(self):
        vertices = [((0, 0, 0), (1, 2), (3, 4, 5)),
                    ((1, 0, 0), (1, 2), (3, 4, 5)),
                    ((0, 1, 0), (1, 2), (3, 4, 5)),
                    ((1, 0, 0), (9, 2), (3, 4, 5)),
                    ((1, 1, 0), (1, 2), (3, 4, 5))]
        encoded, detail = strips.encode(vertices, [(0, 1, 2), (2, 3, 4)])
        self.assertEqual(detail["unique_vertices"], 5)
        uv_arrays = [list(struct.iter_unpack("<2H", payload))
                     for op, _, _, payload in hair.vif_commands(encoded) if op == 0x65]
        self.assertEqual(sorted(uv for array in uv_arrays for uv in array),
                         sorted([vertex[1] for vertex in vertices] + [(1, 2)]))
        with self.assertRaisesRegex(ValueError, "outside mesh"):
            strips.encode(vertices, [(0, 1, 5)])


if __name__ == "__main__":
    unittest.main()
