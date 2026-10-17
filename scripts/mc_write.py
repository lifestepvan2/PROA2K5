"""Write files into a PS2 memory card image (.ps2 with ECC) in place.

Only supports overwriting an existing file with data of the same size (or smaller,
without changing the cluster chain). Updates page ECC bytes.

Usage:
    python scripts/mc_write.py CARD.ps2 /DIR/FILE  new_data.bin [--dry]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mc_inspect import Card, PAGE, RAW_PAGE


def _par(x):
    return bin(x).count("1") & 1


# column parity bit layout derived empirically from real cards
_CP_BITS = [(0, 0x55), (1, 0x33), (2, 0x0F), (4, 0xAA), (5, 0xCC), (6, 0xF0)]
_CP = [sum(_par(i & m) << b for b, m in _CP_BITS) for i in range(256)]


def ecc128(chunk: bytes) -> bytes:
    cp, l0, l1 = 0x77, 0x7F, 0x7F
    for i, c in enumerate(chunk):
        cp ^= _CP[c]
        if _par(c):
            l0 ^= (~i) & 0x7F
            l1 ^= i
    return bytes([cp, l0 & 0x7F, l1])


def page_ecc(page: bytes) -> bytes:
    return b"".join(ecc128(page[i * 128:(i + 1) * 128]) for i in range(4))


def verify_card(path):
    raw = Path(path).read_bytes()
    ok = bad = 0
    for p in range(len(raw) // RAW_PAGE):
        page = raw[p * RAW_PAGE:p * RAW_PAGE + PAGE]
        sp = raw[p * RAW_PAGE + PAGE:(p + 1) * RAW_PAGE]
        if page == b"\xff" * PAGE:
            continue
        if page_ecc(page) == sp[:12]:
            ok += 1
        else:
            bad += 1
    return ok, bad


def find_entry(card: Card, path: str):
    for p, e in card.walk():
        if p == path and e["exists"]:
            return e
    raise FileNotFoundError(path)


def write_file(card_path, file_path, data: bytes, dry=False):
    card = Card(card_path)
    assert card.has_ecc, "expects a card image with ECC"
    e = find_entry(card, file_path)
    if len(data) != e["length"]:
        raise ValueError(f"size mismatch: {len(data)} vs {e['length']} (in-place only)")
    chain = card.chain(e["cluster"])
    raw = bytearray(Path(card_path).read_bytes())
    pos = 0
    for c in chain:
        abs_cluster = card.alloc_offset + c
        for pg in range(card.pages_per_cluster):
            if pos >= len(data):
                break
            off = (abs_cluster * card.pages_per_cluster + pg) * RAW_PAGE
            chunk = data[pos:pos + PAGE]
            if len(chunk) < PAGE:
                chunk = chunk + bytes(raw[off + len(chunk):off + PAGE])
            raw[off:off + PAGE] = chunk
            raw[off + PAGE:off + PAGE + 12] = page_ecc(chunk)
            pos += PAGE
    if not dry:
        Path(card_path).write_bytes(bytes(raw))
    return len(chain)


if __name__ == "__main__":
    if sys.argv[1] == "--verify":
        print(verify_card(sys.argv[2]))
        sys.exit()
    card, fpath, src = sys.argv[1:4]
    n = write_file(card, fpath, Path(src).read_bytes(), "--dry" in sys.argv)
    print("clusters written:", n)
