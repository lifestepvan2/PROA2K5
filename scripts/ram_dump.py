import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fast_scan import read_ps2_ram  # noqa: E402

ram = read_ps2_ram()
a, n = int(sys.argv[1], 16), int(sys.argv[2], 16)
for o in range(a, a + n, 16):
    b = ram[o:o + 16]
    print(f"{o:08x}: " + " ".join(f"{x:02x}" for x in b) + "  " + "".join(chr(x) if 32 <= x < 127 else "." for x in b))
