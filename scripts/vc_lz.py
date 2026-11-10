"""VC-LZ decoding, fixed-span tail edits and resized PS2 resource encoding.

Match tokens copy backwards. Emit only nonoverlapping matches: native heap
allocations do not guarantee that unwritten destination bytes contain zeros.
Fixed-span rebuilding preserves original prefix tokens and existing size limits.
"""
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    start: int
    length: int
    match: bool
    encoded: bytes


def _longest_match(data: bytes, position: int, maximum_distance: int, limit: int) -> tuple[int, int]:
    start = max(0, position - maximum_distance)
    best_length, best_index = 0, -1
    low, high = 3, min(limit, position)
    while low <= high:
        length = (low + high) // 2
        index = data.rfind(data[position:position + length], start, position)
        if index < 0:
            high = length - 1
        else:
            best_length, best_index = length, index
            low = length + 1
    return (best_length, position - best_index) if best_length >= 3 else (0, 0)


def decode(stream: bytes, expected_size: int, *, collect_tokens: bool = True) -> tuple[bytes, list[Token], int]:
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
            if collect_tokens:
                tokens.append(Token(destination, length, match, encoded))
            destination += length
    return bytes(out), tokens, source


def validate_inplace(stream: bytes, target: bytes, scratch: int) -> int:
    if type(scratch) is not int or scratch < 0 or len(target) + scratch > 0x2000000:
        raise ValueError("Invalid VC-LZ scratch allocation")
    decoded, tokens, used = decode(stream, len(target))
    if decoded != target:
        raise ValueError("VC-LZ decoded readback differs from requested data")
    consumed, required = 9, 0
    for index, token in enumerate(tokens):
        consumed += len(token.encoded) + int(index % 8 == 0)
        end = token.start + token.length
        if end < len(target):
            required = max(required, len(stream) - len(target) + end - consumed + 1)
    if required > scratch or len(stream) > len(target) + scratch:
        raise ValueError(f"VC-LZ stream needs {required} scratch bytes; header has {scratch}")
    memory = bytearray(b"\xA5") * (len(target) + scratch)
    source_start = len(memory) - len(stream)
    memory[source_start:] = stream
    for token in tokens:
        if token.match:
            distance = int.from_bytes(token.encoded, "little") & ((1 << stream[8]) - 1)
            for position in range(token.start + token.length - 1, token.start - 1, -1):
                memory[position] = memory[position - distance]
        else:
            memory[token.start] = token.encoded[0]
    if memory[:len(target)] != target:
        raise ValueError("VC-LZ in-place readback depends on uninitialized decoded memory")
    return used


def recompress(stream: bytes, target: bytes, *, distance_bits: int | None = None) -> tuple[bytes, int]:
    """Encode a resized resource, returning its aligned body and required scratch."""
    if len(stream) < 9 or not 0 < len(target) <= 0x2000000:
        raise ValueError("Invalid resized VC-LZ source or decoded size")
    if struct.unpack_from("<I", stream)[0] != len(target):
        raise ValueError("Resizing storage must preserve the decoded resource size")
    bits = stream[8] if distance_bits is None else distance_bits
    if type(bits) is not int or not 1 <= bits <= 15:
        raise ValueError("Invalid VC-LZ distance bit count")
    encoded = bytearray(stream[:8]) + bytes([bits])
    position, peak = 0, 0
    while position < len(target):
        flag = len(encoded)
        encoded.append(0)
        for bit in range(8):
            if position == len(target):
                break
            length, distance = _longest_match(
                target, position, (1 << bits) - 1, min((1 << (16 - bits)) + 2, len(target) - position))
            if length >= 3:
                encoded[flag] |= 1 << bit
                encoded.extend(struct.pack("<H", ((length - 3) << bits) | distance))
            else:
                length = 1
                encoded.append(target[position])
            position += length
            if position < len(target):
                peak = max(peak, position - len(encoded) + 1)
    encoded.extend(bytes(-len(encoded) % 16))
    scratch = max(0, len(encoded) - len(target), len(encoded) - len(target) + peak)
    scratch = (scratch + 15) // 16 * 16
    result = bytes(encoded)
    validate_inplace(result, target, scratch)
    return result, scratch


def rebuild_tail(stream: bytes, expected_size: int, tail: bytes, scratch: int,
                 *, distance_bits: int | None = None) -> bytes:
    original, tokens, _ = decode(stream, expected_size)
    if not tail or len(tail) > expected_size or scratch < 0:
        raise ValueError("Invalid VC-LZ tail or scratch size")
    target = original[:-len(tail)] + tail
    if target == original:
        return stream
    boundary = expected_size - len(tail)
    kept = [token for token in tokens if token.start + token.length <= boundary]
    position = kept[-1].start + kept[-1].length if kept else 0
    bits = stream[8] if distance_bits is None else distance_bits
    if type(bits) is not int or not 1 <= bits <= 15:
        raise ValueError("Invalid VC-LZ distance bit count")
    if bits != stream[8]:
        kept, position = [], 0
    maximum_distance = (1 << bits) - 1
    maximum_length = (1 << (16 - bits)) + 2
    rebuilt = list(kept)
    consumed = 9 + (len(kept) + 7) // 8 + sum(len(token.encoded) for token in kept)
    while position < expected_size:
        match_consumed = consumed + 2 + int(len(rebuilt) % 8 == 0)
        safe_length = scratch - len(stream) + expected_size - position + match_consumed - 1
        best_length, best_distance = _longest_match(
            target, position, maximum_distance, min(maximum_length, expected_size - position))
        if best_length < expected_size - position:
            best_length = min(best_length, safe_length)
        if best_length >= 3:
            code = ((best_length - 3) << bits) | best_distance
            token = Token(position, best_length, True, struct.pack("<H", code))
        else:
            token = Token(position, 1, False, target[position:position + 1])
        consumed += len(token.encoded) + int(len(rebuilt) % 8 == 0)
        rebuilt.append(token)
        position += token.length
    encoded = bytearray(stream[:9])
    encoded[8] = bits
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
    validate_inplace(result, target, scratch)
    return result
