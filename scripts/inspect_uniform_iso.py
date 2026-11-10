"""Investigate GS-upload textures against clean original dumps; never patch an ISO.

    python scripts\\inspect_uniform_iso.py --iso-source PRISTINE --out NEW_DIRECTORY

The default traces named uniform bundles. --all-assets also searches other
page-aligned PSMT8 resources for uniform artwork hidden behind unknown asset names.
The milestone-one snapshot is comparison evidence, not an approved patch plan.
"""
import argparse
import collections
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageDraw

from gs_texture import decode_upload
from iso_copy import hash_stream
from patch_preview_lettering_iso import SOURCE_SHA256
from player_texture_iso import read_archive
from texlib import DUMP_DIRS, REPL_DIR, ROOT, dump_files
from texture_catalogue import open_catalogue, ownership, pixel_digest, relative, resolve_names, scene_materials
from vc_lz import decode


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: tuple, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def resource_data(stream, row: sqlite3.Row) -> bytes:
    stream.seek(row["iso_offset"] + row["chunk_offset"] + 32)
    raw = stream.read(row["stored"])
    if len(raw) != row["stored"]:
        raise ValueError("Truncated resource during inspection")
    return decode(raw, row["system"] + row["video"], collect_tokens=False)[0] if row["compressed"] else raw


def body_materials(connection: sqlite3.Connection, stream) -> list[dict]:
    result = []
    query = """
        SELECT a.name AS asset,a.iso_offset,r.*
        FROM assets a JOIN resources r ON r.asset_hash=a.hash
        WHERE a.name IN ('frontend.iff','gamedataextra.iff') AND r.name IN ('hi_body','low_body')
    """
    for row in connection.execute(query):
        data = resource_data(stream, row)
        root = relative(data, 20, row["system"])
        for material in scene_materials(data, row["system"]):
            result.append({
                "asset": row["asset"], "scene": row["name"], "material_index": material["index"], "material": material["name"],
                "embedded_texture_count": int.from_bytes(data[root + 20:root + 24], "little"),
                "texture_ref": material["descriptor_ref"],
                "video": row["video"],
            })
    return result


def inspect(source: Path, catalogue: Path, baseline: Path, output: Path, all_assets: bool = False) -> dict:
    if output.exists():
        raise ValueError("Inspection output already exists; choose a new directory")
    for protected in (ROOT / "texture_workspace", ROOT / "assets", REPL_DIR, *DUMP_DIRS):
        if output.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Inspection output must be outside artist/dump/replacement directories")
    baseline_rows = read_csv(baseline / "workspace_mapping.csv")
    active = read_csv(baseline / "active_targets.csv")
    known = collections.defaultdict(list)
    for row in baseline_rows:
        if row["original_digest"]:
            known[row["original_digest"]].append(row["key"])
    dumps, verified = dump_files(), set()
    images, resources, key_sources = [], [], collections.defaultdict(set)
    samples = []
    key_assets, key_names, key_levels = (collections.defaultdict(set) for _ in range(3))
    with closing(open_catalogue(catalogue)) as connection, source.open("rb") as stream:
        entries = read_archive(stream)
        names = resolve_names(stream, entries)
        materials = body_materials(connection, stream)
        query = """
            SELECT a.name AS asset,a.iso_offset,a.ownership,r.*,t.id,t.descriptor,t.name AS texture_name
            FROM textures t JOIN assets a ON a.hash=t.asset_hash
            JOIN resources r ON r.asset_hash=t.asset_hash AND r.ordinal=t.resource_ordinal
            WHERE t.psm=19 AND r.video>0 AND r.video%8192=0
        """
        query += " ORDER BY a.entry_index,r.ordinal,t.descriptor"
        last_resource, data = None, b""
        for row in connection.execute(query):
            asset = names.get(int(row["asset_hash"], 16), row["asset"])
            if not all_assets and ownership(asset, {})["kind"] != "uniform":
                continue
            resource = (row["asset_hash"], row["ordinal"])
            if resource != last_resource:
                data = resource_data(stream, row)
                last_resource = resource
            record = {"asset": asset, "asset_hash": row["asset_hash"], "ordinal": row["ordinal"],
                      "kind": row["kind"], "texture": row["texture_name"], "texture_id": row["id"],
                      "system": row["system"], "video": row["video"], "status": "", "reason": ""}
            try:
                decoded = decode_upload(data, row["system"], row["video"], row["descriptor"])
            except ValueError as error:
                record.update(status="unsupported", reason=str(error))
                resources.append(record)
                continue
            record["status"] = "decoded"
            for image in decoded:
                digest = pixel_digest(image["width"], image["height"], image["rgba"])
                matches = known.get(digest, [])
                for key in matches:
                    if key not in verified:
                        if key not in dumps:
                            raise ValueError(f"Original dump disappeared since baseline: {key}")
                        with Image.open(dumps[key]) as original:
                            rgba = original.convert("RGBA")
                            if pixel_digest(*rgba.size, rgba.tobytes()) != digest:
                                raise ValueError(f"Original dump changed since baseline: {key}")
                        verified.add(key)
                    key_sources[key].add(f"{row['id']}:{image['level']}")
                    key_assets[key].add(asset)
                    key_names[key].add(row["texture_name"])
                    key_levels[key].add(image["level"])
                images.append({
                    "asset": asset, "kind": row["kind"], "texture": row["texture_name"],
                    "texture_id": row["id"], "descriptor": row["descriptor"], "level": image["level"],
                    "width": image["width"], "height": image["height"], "tbp": image["tbp"],
                    "tbw": image["tbw"], "cbp": image["cbp"], "digest": digest,
                    "tfx": image["tfx"], "tcc": image["tcc"],
                    "dump_keys": ";".join(matches),
                })
                if asset in ("uh021.iff", "wh021.iff") and row["texture_name"] in ("unif", "short", "top", "slv", "pnt"):
                    samples.append((asset, row["texture_name"], image))
            resources.append(record)
        if hash_stream(stream) != SOURCE_SHA256:
            raise ValueError("Pristine ISO changed during inspection")
    coverage = [{"key": row["key"], "old_status": row["status"], "old_blocker": row["blocker"],
                 "manual_edit": row["manual_edit"], "generated": row["generated"],
                 "workspace_path": row["path"], "label": row["label"], "role": row["role"],
                 "native_assets": ";".join(sorted(key_assets[row["key"]])),
                 "native_textures": ";".join(sorted(key_names[row["key"]])),
                 "native_levels": ";".join(str(level) for level in sorted(key_levels[row["key"]])),
                 "native_image_ids": ";".join(sorted(key_sources[row["key"]]))}
                for row in active if row["key"] in key_sources]
    newly_matched = [row for row in coverage if row["old_status"] != "exact"]
    summary = {
        "source_sha256": SOURCE_SHA256, "scope": "all page-aligned PSMT8" if all_assets else "named uniform bundles",
        "descriptors_examined": len(resources),
        "decode_status": dict(collections.Counter(row["status"] for row in resources)),
        "unsupported_reasons": dict(collections.Counter(row["reason"] for row in resources if row["reason"])),
        "images": len(images), "images_matching_original_dumps": sum(bool(row["dump_keys"]) for row in images),
        "unique_original_keys_verified": len(verified), "active_keys_matching": len(coverage),
        "previously_blocked_active_keys_matching": len(newly_matched),
        "previous_blockers_now_matching": dict(collections.Counter(row["old_blocker"] for row in newly_matched)),
        "previously_blocked_manual_sources_matching": sum(row["manual_edit"] == "1" for row in newly_matched),
        "previously_blocked_generated_children_matching": sum(row["generated"] == "1" for row in newly_matched),
        "body_material_rows": len(materials),
        "limitations": "Exact content/location evidence only. No patching, encoding or observed draw-time sampler state. Old audit and artist files remain unchanged.",
    }
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "resources.csv", ("asset", "asset_hash", "ordinal", "kind", "texture", "texture_id",
                                       "system", "video", "status", "reason"), resources)
    write_csv(output / "images.csv", ("asset", "kind", "texture", "texture_id", "descriptor", "level",
                                    "width", "height", "tbp", "tbw", "cbp", "digest", "tfx", "tcc", "dump_keys"), images)
    columns = ("key", "old_status", "old_blocker", "manual_edit", "generated", "workspace_path",
               "label", "role", "native_assets", "native_textures", "native_levels", "native_image_ids")
    write_csv(output / "active_matches.csv", columns, coverage)
    write_csv(output / "uniform_coverage.csv", columns,
              [row for row in coverage if row["old_blocker"] == "uniform-transfer-or-inheritance-unproved"])
    write_csv(output / "body_materials.csv", ("asset", "scene", "material_index", "material",
                                            "embedded_texture_count", "texture_ref", "video"), materials)
    if samples:
        groups = list(dict.fromkeys((asset, name) for asset, name, _ in samples))
        sheet = Image.new("RGB", (1080, 180 * len(groups)), "white")
        draw = ImageDraw.Draw(sheet)
        for asset, name, image in samples:
            x, y = image["level"] * 180, groups.index((asset, name)) * 180
            rgba = Image.frombytes("RGBA", (image["width"], image["height"]), image["rgba"]).convert("RGB")
            rgba.thumbnail((170, 140))
            sheet.paste(rgba, (x + 5, y + 5))
            draw.text((x + 5, y + 148), f"{asset} {name}\nMip {image['level']}: {image['width']}x{image['height']}", fill="black")
        sheet.save(output / "native_uniform_mips.png")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, default=ROOT / "cache" / "texture_iso" / "catalogue.sqlite")
    parser.add_argument("--baseline-audit", type=Path, default=ROOT / "cache" / "texture_iso" / "milestone1")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--all-assets", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.iso_source, args.catalogue, args.baseline_audit, args.out, args.all_assets), indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Uniform inspection failed: {error}\n")


if __name__ == "__main__":
    main()
