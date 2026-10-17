"""map_roster_addresses.py — Find all 76ers and Pistons player name addresses in PS2 RAM."""
import sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fast_scan import read_ps2_ram, scan

ROSTER_RANGE = (0x900000, 0xC00000)

PLAYERS = {
    "76ers": ["Iverson","McKie","Robinson","Dalembert","Skinner","Thomas",
              "Salmons","Green","Williamson","Jackson","Rogers"],
    "Pistons": ["Billups","Hamilton","Prince","Wallace","Hunter","McDyess",
                "Arroyo","Ham","Milicic","Parker","Dupree"],
}

def main():
    print("Reading PS2 RAM...")
    ram = read_ps2_ram()

    results = {}
    for team, names in PLAYERS.items():
        print(f"\n=== {team} ===")
        results[team] = {}
        for name in names:
            needle = name.encode("utf-16-le")
            hits   = scan(ram, needle, context_before=0, context_after=40)
            roster = [h for h in hits if ROSTER_RANGE[0] <= h["ps2_addr"] <= ROSTER_RANGE[1]]
            if roster:
                h = roster[0]
                addr = h["ps2_addr"]
                ctx  = h["printable"][:60]
                print(f"  {name:15s}  {addr:#010x}  {ctx}")
                results[team][name] = {"addr": addr, "context": ctx}
            elif hits:
                addrs = [h["ps2_addr"] for h in hits[:3]]
                print(f"  {name:15s}  out-of-range hits: {[hex(a) for a in addrs]}")
                results[team][name] = {"addr": None, "context": ""}
            else:
                print(f"  {name:15s}  NOT FOUND")
                results[team][name] = {"addr": None, "context": ""}

    out = ROOT / "docs" / "roster_addresses.json"
    json.dump(results, out.open("w"), indent=2)
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
