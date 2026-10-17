"""Minimal PS2 memory card (.ps2, 8 MB with ECC) filesystem reader.

Usage: python scripts/mc_inspect.py <card.ps2> [--extract OUTDIR]
"""
import struct
import sys
from pathlib import Path

PAGE = 512
SPARE = 16
RAW_PAGE = PAGE + SPARE


class Card:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        self.has_ecc = len(raw) % RAW_PAGE == 0 and len(raw) // RAW_PAGE >= 16384
        if self.has_ecc:
            pages = [raw[i:i + PAGE] for i in range(0, len(raw), RAW_PAGE)]
            self.data = b"".join(pages)
        else:
            self.data = raw
        sb = self.data[:PAGE]
        self.magic = sb[:28]
        (self.page_size, self.pages_per_cluster, self.pages_per_block,
         _, self.clusters_per_card, self.alloc_offset, self.alloc_end,
         self.rootdir_cluster, self.backup_block1, self.backup_block2) = struct.unpack_from(
            "<HHHHIIIIII", sb, 0x28)
        self.cluster = self.page_size * self.pages_per_cluster
        (self.ifc_list,) = struct.unpack_from("<32I", sb, 0x50)[:1]
        self.ifc = struct.unpack_from("<32I", sb, 0x50)

    def cl(self, n):
        return self.data[n * self.cluster:(n + 1) * self.cluster]

    def fat_clusters(self):
        entries = []
        for ifc in self.ifc:
            if ifc in (0, 0xFFFFFFFF):
                continue
            ind = struct.unpack("<%dI" % (self.cluster // 4), self.cl(ifc))
            for fc in ind:
                if fc in (0, 0xFFFFFFFF):
                    continue
                entries.extend(struct.unpack("<%dI" % (self.cluster // 4), self.cl(fc)))
        return entries

    def fat(self):
        if not hasattr(self, "_fat"):
            self._fat = self.fat_clusters()
        return self._fat

    def chain(self, start):
        fat = self.fat()
        out = []
        n = start
        seen = set()
        while n != 0xFFFFFFFF and n not in seen:
            seen.add(n)
            out.append(n)
            e = fat[n]
            if not (e & 0x80000000):
                break
            n = e & 0x7FFFFFFF
            if n == 0x7FFFFFFF:
                break
        return out

    def read_chain(self, start, size=None):
        d = b"".join(self.cl(self.alloc_offset + c) for c in self.chain(start))
        return d[:size] if size is not None else d

    def entries(self, start, length=None):
        raw = self.read_chain(start)
        out = []
        limit = len(raw) // 512 if length is None else min(length, len(raw) // 512)
        for i in range(0, limit * 512, 512):
            mode, _, length_, ctime, cluster, dir_entry = struct.unpack_from("<HHI8sII", raw, i)[:6]
            name = raw[i + 0x40:i + 0x60].split(b"\0")[0].decode("ascii", "replace")
            if mode == 0:
                continue
            out.append(dict(mode=mode, length=length_, cluster=cluster, name=name,
                            is_dir=bool(mode & 0x20), exists=bool(mode & 0x8000)))
        return out

    def walk(self, start=None, path="", count=None):
        start = self.rootdir_cluster if start is None else start
        for e in self.entries(start, count):
            if e["name"] in (".", ".."):
                continue
            full = path + "/" + e["name"]
            yield full, e
            if e["is_dir"] and e["exists"]:
                yield from self.walk(e["cluster"], full, e["length"])


if __name__ == "__main__":
    c = Card(sys.argv[1])
    print("magic:", c.magic, "ecc:", c.has_ecc, "cluster:", c.cluster,
          "alloc_offset:", c.alloc_offset, "rootdir:", c.rootdir_cluster)
    out = None
    if "--extract" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--extract") + 1])
        out.mkdir(parents=True, exist_ok=True)
    for path, e in c.walk():
        if not e["exists"]:
            continue
        print(f"{path:60s} {'DIR ' if e['is_dir'] else 'FILE'} {e['length']:>9d} cl={e['cluster']}")
        if out and not e["is_dir"]:
            (out / path.strip("/").replace("/", "__")).write_bytes(c.read_chain(e["cluster"], e["length"]))
