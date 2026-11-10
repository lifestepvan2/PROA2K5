"""Read-only decoding of verified GS32-upload / PSMT8 texture resources.

The upload is a sequence of complete 64x32 PSMCT32 pages. Texture and
palette reads use the descriptor's GS block addresses, not file offsets.
Address equations express hardware bit placement; no emulator code is used.
"""
import struct
from functools import lru_cache

import numpy as np

from txtr_match import SWZ

PAGE_BYTES = 8192


def address32(x: np.ndarray, y: np.ndarray, bw: int, base: int = 0) -> np.ndarray:
    page = x // 64 + y // 32 * bw
    block = (((x >> 3) & 1) | (((y >> 3) & 1) << 1) | (((x >> 4) & 1) << 2)
             | (((y >> 4) & 1) << 3) | (((x >> 5) & 1) << 4))
    word = ((x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((x & 4) << 1)
            | ((y & 2) << 3) | ((y & 4) << 3))
    return base * 256 + page * PAGE_BYTES + block * 256 + word * 4


def address8(x: np.ndarray, y: np.ndarray, bw: int, base: int = 0) -> np.ndarray:
    page = x // 128 + y // 64 * (bw // 2)
    block = (((x >> 4) & 1) | (((y >> 4) & 1) << 1) | (((x >> 5) & 1) << 2)
             | (((y >> 5) & 1) << 3) | (((x >> 6) & 1) << 4))
    column = (((y >> 1) & 1) | (((x >> 3) & 1) << 1) | ((x & 1) << 2)
              | ((y & 1) << 3) | ((x & 2) << 3)
              | ((((x >> 2) ^ (y >> 1) ^ (y >> 2)) & 1) << 5)
              | ((y & 4) << 4) | ((y & 8) << 4))
    return base * 256 + page * PAGE_BYTES + block * 256 + column


@lru_cache(maxsize=1)
def upload_inverse() -> np.ndarray:
    y, x = np.indices((32, 64))
    physical = (address32(x, y, 1).ravel()[:, None] + np.arange(4)).ravel()
    inverse = np.argsort(physical)
    inverse.flags.writeable = False
    return inverse


def host_offsets(addresses: np.ndarray, size: int) -> np.ndarray:
    if addresses.size == 0 or np.any(addresses < 0) or np.any(addresses >= size):
        raise ValueError("GS texture/palette reads outside resource upload")
    return addresses // PAGE_BYTES * PAGE_BYTES + upload_inverse()[addresses % PAGE_BYTES]


@lru_cache(maxsize=128)
def texture_addresses(width: int, height: int, bw: int, base: int) -> np.ndarray:
    y, x = np.indices((height, width))
    addresses = address8(x, y, bw, base)
    addresses.flags.writeable = False
    return addresses


def decode_upload(data: bytes, system: int, video: int, descriptor: int) -> list[dict]:
    """Return all explicitly addressed mip levels, retaining native alpha bytes.

    This is not a general GS-transfer interpreter or an encoder. Unsupported
    descriptors fail explicitly; an exact dump match establishes source evidence.
    """
    if system < 0 or descriptor < 0 or descriptor + 48 > system or system + video > len(data):
        raise ValueError("Truncated GS-upload resource or descriptor")
    if video <= 0 or video % PAGE_BYTES:
        raise ValueError("GS32 upload requires complete 8192-byte pages")
    tex0, mip1, mip2 = struct.unpack_from("<3Q", data, descriptor)
    width, height = struct.unpack_from("<HH", data, descriptor + 44)
    if not width or not height or width > 4096 or height > 4096:
        raise ValueError("Unsupported GS-upload geometry")
    if ((tex0 >> 20) & 63) != 19:
        raise ValueError("GS-upload decoder supports PSMT8 only")
    if ((tex0 >> 51) & 15) or ((tex0 >> 55) & 1) or ((tex0 >> 56) & 31):
        raise ValueError("GS-upload decoder requires PSMCT32 CSM1 palette with CSA zero")
    if width != 1 << ((tex0 >> 26) & 15) or height != 1 << ((tex0 >> 30) & 15):
        raise ValueError("GS geometry differs from TEX0 dimensions")
    levels = [(tex0 & 16383, (tex0 >> 14) & 63)]
    ended = False
    for word in (mip1, mip2):
        for shift in (0, 20, 40):
            base, bw = (word >> shift) & 16383, (word >> (shift + 14)) & 63
            if not bw:
                if base:
                    raise ValueError("Mip address lacks buffer width")
                ended = True
            elif ended:
                raise ValueError("Noncontiguous GS mip descriptors")
            else:
                levels.append((base, bw))
    raw = np.frombuffer(data, dtype=np.uint8, count=video, offset=system)
    cbp = (tex0 >> 37) & 16383
    y, x = np.indices((16, 16))
    palette_addresses = address32(x, y, 1, cbp).ravel()[:, None] + np.arange(4)
    palette = raw[host_offsets(palette_addresses, video)][SWZ]
    images = []
    for level, (base, bw) in enumerate(levels):
        w, h = max(1, width >> level), max(1, height >> level)
        if bw < 2 or bw % 2 or bw * 64 < w:
            raise ValueError("Unsupported PSMT8 mip buffer width")
        offsets = host_offsets(texture_addresses(w, h, bw, base), video)
        images.append({"level": level, "width": w, "height": h, "rgba": palette[raw[offsets]].tobytes(),
                       "tbp": base, "tbw": bw, "cbp": cbp, "tfx": (tex0 >> 35) & 3,
                       "tcc": (tex0 >> 34) & 1})
    return images
