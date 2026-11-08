"""Bounded VC-LZ decoding and fixed-span tail edits for PS2 TXTR resources.

Match tokens copy backwards, so an overlapping match reads unwritten zero bytes.
Rebuilding retains the original tokens before the edited tail and refuses a stream
that exceeds either its stored span or its existing in-place decoder scratch space.
"""
import struct
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    start: int
    length: int
    match: bool
    encoded: bytes


def decode(stream: bytes, expected_size: int) -> tuple[bytes, list[Token], int]:
    if len(stream) < 10:
        raise ValueError("Truncated VC-LZ header")
    size, _ = struct.unpack_from("<II", stream)
    bits = stream[8]
    if size != expected_size or not 0 < size <= 0x2000000:
        raise ValueError("VC-LZ decoded size differs from the resource header or exceeds 32 MB")
    if not 1 <= bits <= 15:
        raise ValueError("Invalid VC-LZ distance bit count")
    out = bytearray(size)
    tokens = []
    source, destination = 9, 0
    while destination < size:
        if source >= len(stream):
            raise ValueError("Truncated VC-LZ flag byte")
        flags = stream[source]
        source += 1
        for bit in range(8):
            if destination == size:
                break
            match = bool(flags & (1 << bit))
            count = 2 if match else 1
            if source + count > len(stream):
                raise ValueError("Truncated VC-LZ token")
            encoded = stream[source:source + count]
            source += count
            if match:
                code = int.from_bytes(encoded, "little")
                distance = code & ((1 << bits) - 1)
                length = (code >> bits) + 3
                if not 0 < distance <= destination or destination + length > size:
                    raise ValueError("Invalid VC-LZ match distance or length")
                out[destination:destination + length] = out[
                    destination - distance:destination - distance + length]
            else:
                length = 1
                out[destination] = encoded[0]
            tokens.append(Token(destination, length, match, encoded))
            destination += length
    return bytes(out), tokens, source


def rebuild_tail(stream: bytes, expected_size: int, tail: bytes, scratch: int) -> bytes:
    original, tokens, _ = decode(stream, expected_size)
    if not tail or len(tail) > expected_size or scratch < 0:
        raise ValueError("Invalid VC-LZ tail or scratch size")
    target = original[:-len(tail)] + tail
    if target == original:
        return stream
    boundary = expected_size - len(tail)
    kept = [token for token in tokens if token.start + token.length <= boundary]
    position = kept[-1].start + kept[-1].length if kept else 0
    bits = stream[8]
    maximum_distance = (1 << bits) - 1
    maximum_length = (1 << (16 - bits)) + 2
    candidates: dict[bytes, deque[int]] = defaultdict(deque)

    def remember(index: int) -> None:
        if index + 3 <= expected_size:
            queue = candidates[target[index:index + 3]]
            queue.append(index)
            while queue and queue[0] < index - maximum_distance:
                queue.popleft()

    for index in range(max(0, position - maximum_distance), position):
        remember(index)
    rebuilt = list(kept)
    consumed = 9 + (len(kept) + 7) // 8 + sum(len(token.encoded) for token in kept)
    while position < expected_size:
        best_length, best_distance = 0, 0
        match_consumed = consumed + 2 + int(len(rebuilt) % 8 == 0)
        safe_length = scratch - len(stream) + expected_size - position + match_consumed - 1
        for index in reversed(candidates.get(target[position:position + 3], ())):
            distance = position - index
            if distance > maximum_distance:
                break
            remaining = expected_size - position
            limit = min(maximum_length, distance, remaining)
            length = 0
            while length < limit and target[index + length] == target[position + length]:
                length += 1
            if length < remaining:
                length = min(length, safe_length)
            if length >= 3 and length > best_length:
                best_length, best_distance = length, distance
                if length == maximum_length:
                    break
        if best_length:
            code = ((best_length - 3) << bits) | best_distance
            token = Token(position, best_length, True, struct.pack("<H", code))
        else:
            token = Token(position, 1, False, target[position:position + 1])
        consumed += len(token.encoded) + int(len(rebuilt) % 8 == 0)
        rebuilt.append(token)
        for index in range(position, position + token.length):
            remember(index)
        position += token.length
    encoded = bytearray(stream[:9])
    required_scratch = 0
    for first in range(0, len(rebuilt), 8):
        group = rebuilt[first:first + 8]
        encoded.append(sum(int(token.match) << bit for bit, token in enumerate(group)))
        for token in group:
            encoded.extend(token.encoded)
            end = token.start + token.length
            if end < expected_size:
                required_scratch = max(required_scratch,
                                       len(stream) - expected_size + end - len(encoded) + 1)
    if len(encoded) > len(stream):
        raise ValueError(f"Recompressed TXTR needs {len(encoded)} bytes; fixed span has {len(stream)}")
    if required_scratch > scratch:
        raise ValueError(f"Recompressed TXTR needs {required_scratch} scratch bytes; header has {scratch}")
    encoded.extend(bytes(len(stream) - len(encoded)))
    result = bytes(encoded)
    decoded, _, _ = decode(result, expected_size)
    if decoded != target:
        raise ValueError("Recompressed TXTR round-trip verification failed")
    return result
