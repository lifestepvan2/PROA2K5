#!/usr/bin/env python3
"""Summarize the PCSX2 texture dump directory.

This script is intentionally conservative: it groups the same dump set by size and
suffix, which helps us separate likely player-face textures from team/logo assets.
The goal is to identify candidate mapping targets for later memory-based linkage.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image


def summarize_dump_dir(dump_dir: Path) -> dict[str, object]:
    files = sorted(dump_dir.glob("*.png"))
    by_size: dict[tuple[int, int], list[str]] = defaultdict(list)
    by_suffix: dict[str, list[str]] = defaultdict(list)
    by_size_suffix: dict[tuple[int, int, str], list[str]] = defaultdict(list)

    for file in files:
        name = file.name[:-4]
        parts = name.split("-")
        suffix = parts[-1] if parts else name
        with Image.open(file) as img:
            size = img.size
        by_size[size].append(file.name)
        by_suffix[suffix].append(file.name)
        by_size_suffix[(size[0], size[1], suffix)].append(file.name)

    return {
        "file_count": len(files),
        "by_size": {f"{w}x{h}": len(v) for (w, h), v in sorted(by_size.items())},
        "by_suffix": {s: len(v) for s, v in sorted(by_suffix.items())},
        "sample_by_size": {f"{w}x{h}": v[:5] for (w, h), v in sorted(by_size.items())},
        "sample_by_suffix": {s: v[:5] for s, v in sorted(by_suffix.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze dumped PS2 texture files for likely player vs team texture classes.")
    parser.add_argument(
        "dump_dir",
        nargs="?",
        default=r"C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\dumps",
        help="Directory containing the dumped PNG files.",
    )
    args = parser.parse_args()

    dump_dir = Path(args.dump_dir)
    if not dump_dir.exists():
        raise SystemExit(f"Dump directory not found: {dump_dir}")

    summary = summarize_dump_dir(dump_dir)
    print(f"PNG count: {summary['file_count']}")
    print("\nGrouped by image size:")
    for key, count in summary["by_size"].items():
        print(f"  {key}: {count}")

    print("\nGrouped by trailing suffix:")
    for key, count in summary["by_suffix"].items():
        print(f"  {key}: {count}")

    print("\nSample files by size:")
    for key, sample in summary["sample_by_size"].items():
        print(f"  {key}: {sample}")

    print("\nLikely interpretation:")
    print("  - 128x128 textures are strong player-face candidates.")
    print("  - 256x256 / 512x512 textures are strong team-logo candidates.")
    print("  - smaller textures are likely UI fragments, jersey markers, or support assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
