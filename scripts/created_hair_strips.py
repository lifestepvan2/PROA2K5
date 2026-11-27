"""Experimental native VIF encoder with triangle strips and previous-batch reuse."""
import collections
import random
import struct

Vertex = tuple[tuple[int, int, int], tuple[int, int], tuple[int, int, int]]
Face = tuple[int, int, int]


def triangle_strips(vertices: list[Vertex], faces: list[Face]) -> tuple[list[Vertex], list[list[int]]]:
    if not faces:
        raise ValueError("Cannot encode an empty mesh")
    indices = {}
    unique = []
    indexed = []
    for face in faces:
        if len(face) != 3:
            raise ValueError("Expected triangle faces")
        row = []
        for index in face:
            if not 0 <= index < len(vertices):
                raise ValueError("Triangle vertex outside mesh")
            vertex = vertices[index]
            if vertex not in indices:
                indices[vertex] = len(unique)
                unique.append(vertex)
            row.append(indices[vertex])
        if len(set(row)) != 3:
            raise ValueError("Degenerate input triangle")
        indexed.append(tuple(row))

    directed = collections.defaultdict(list)
    for index, face in enumerate(indexed):
        for i in range(3):
            directed[face[i], face[(i + 1) % 3]].append((index, face[(i + 2) % 3]))

    best = None
    for seed in range(8):
        rng = random.Random(seed)
        unused = set(range(len(indexed)))
        strips = []
        while unused:
            starts = sorted(unused)
            rng.shuffle(starts)
            longest = None
            for start in starts:
                face = indexed[start]
                for rotation in range(3):
                    strip = [face[rotation], face[(rotation + 1) % 3], face[(rotation + 2) % 3]]
                    used = {start}
                    while len(strip) < 56:
                        a, b = strip[-2:]
                        if len(strip) & 1:
                            a, b = b, a
                        choices = [(i, c) for i, c in directed[a, b] if i in unused and i not in used]
                        if not choices:
                            break
                        index, c = min(choices, key=lambda item: (
                            len(directed[b, item[1]]) + len(directed[item[1], b]), rng.random()))
                        strip.append(c)
                        used.add(index)
                    if longest is None or len(strip) > len(longest[0]):
                        longest = strip, used
            if longest is None:
                raise ValueError("Could not build triangle strip")
            strips.append(longest[0])
            unused.difference_update(longest[1])
        if best is None or len(strips) < len(best):
            best = strips
    return unique, best


def _batches(strips: list[list[int]]) -> list[tuple[list[int], list[int]]]:
    remaining = sorted(strips, key=lambda s: -len(s))
    batches = []
    while remaining:
        packet = []
        markers = []
        while remaining:
            available = 56 - len(packet)
            candidates = [i for i, strip in enumerate(remaining)
                          if len(strip) <= available and (not len(packet) % 2 or len(strip) % 2)]
            if not candidates:
                if len(packet) % 2 and available and any(len(strip) < available for strip in remaining):
                    packet.append(packet[-1])
                    continue
                break
            strip = remaining.pop(candidates[0])
            if len(packet) % 2:
                strip = list(reversed(strip))
            markers.append(len(packet))
            packet.extend(strip)
        if not packet:
            raise ValueError("Triangle strip exceeds output buffer")
        batches.append((packet, markers))
    return batches


def _command(op: int, count: int = 0, immediate: int = 0) -> bytes:
    return struct.pack("<I", op << 24 | count << 16 | immediate)


def _unpack(op: int, immediate: int, payload: bytes, count: int) -> bytes:
    if not 1 <= count <= 255:
        raise ValueError("Invalid VIF count")
    return _command(op, count, immediate) + payload + bytes(-len(payload) % 4)


def encode(vertices: list[Vertex], faces: list[Face]) -> tuple[bytes, dict]:
    unique, strips = triangle_strips(vertices, faces)
    for position, uv, normal in unique:
        if (len(position) != 3 or len(uv) != 2 or len(normal) != 3
                or any(not 0 <= v <= 65535 for v in (*position, *uv))
                or any(not 0 <= v <= 255 for v in normal)):
            raise ValueError("Vertex attributes exceed native packed ranges")
    result = bytearray(bytes.fromhex(
        "000000600000000027010003b60000022540016c00ffff41008000c80000000000e00000"))
    previous = {}
    transformed = copied = slots = 0
    batches = _batches(strips)
    for number, (packet, starts) in enumerate(batches):
        input_base, output_tag = ((0x127, 0x293) if number % 2 == 0 else (0x1dd, 0x349))
        destinations = [output_tag + 1 + 3 * i for i in range(len(packet))]
        copies = [(previous[index], dest) for index, dest in zip(packet, destinations)
                  if index in previous]
        fresh = [(index, dest) for index, dest in zip(packet, destinations) if index not in previous]
        if not fresh:
            first = copies.pop(0)
            fresh.append((packet[0], first[1]))
        copy_count = len(copies)
        if len(copies) % 2:
            copies.append(copies[-1])
        copy_words = []
        for i in range(0, len(copies), 2):
            copy_words.extend((copies[i][0], copies[i + 1][0], copies[i][1], copies[i + 1][1]))
        marks = [destinations[i] for i in starts]
        marks.extend([marks[-1]] * (-len(marks) % 4))
        meta_count = 3 + len(copy_words) // 4 + len(marks) // 4
        if meta_count + 3 * len(fresh) > 0xb6:
            raise ValueError("VU input buffer overflow")
        words = [1, 0, len(copy_words) // 4, len(marks) // 4, 0x8000 | len(packet),
                 output_tag, input_base + 3, 0, 0xa2, input_base + meta_count,
                 len(fresh), 0, *copy_words, *marks]
        result += _unpack(0x6d, 0x4000 | input_base, struct.pack("<" + "H" * len(words), *words),
                          meta_count)
        result += _command(1, immediate=0x103) + _command(5, immediate=1)
        result += _unpack(0x6a, 0x4000 | (input_base + meta_count + 1),
                          bytes(x for index, _ in fresh for x in unique[index][2]), len(fresh))
        result += _unpack(0x65, 0x4000 | (input_base + meta_count),
                          b"".join(struct.pack("<2H", *unique[index][1]) for index, _ in fresh), len(fresh))
        result += _unpack(0x6d, 0x4000 | (input_base + meta_count + 2),
                          b"".join(struct.pack("<4H", *unique[index][0], dest)
                                   for index, dest in fresh), len(fresh))
        result += (_command(0x14 if number == 0 else 0x17) + _command(5)
                   + _command(1, immediate=0x101))
        previous = dict(zip(packet, destinations))
        transformed += len(fresh)
        copied += copy_count
        slots += len(packet)
    result += bytes(-len(result) % 16)
    qwc = len(result) // 16 - 1
    if qwc > 0xffff:
        raise ValueError("Encoded mesh exceeds the DMA tag capacity")
    struct.pack_into("<I", result, 0, 0x60000000 | qwc)
    return bytes(result), {"triangles": len(faces), "strips": len(strips), "batches": len(batches),
                           "output_slots": slots, "transformed_vertices": transformed,
                           "copied_vertices": copied, "unique_vertices": len(unique)}
