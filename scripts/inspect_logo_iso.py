"""Trace the milestone-one blocked logo cohort to pristine native images.

    python scripts\\inspect_logo_iso.py --iso-source PRISTINE --out NEW_DIRECTORY

Read-only research: no generator execution, artist edits, or patch publication.
"""
import argparse
import collections
import json
import re
import struct
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageDraw

from inspect_uniform_iso import read_csv, resource_data, write_csv
from iso_copy import hash_stream
from patch_preview_lettering_iso import SOURCE_SHA256
from player_texture_iso import read_archive
from texlib import DUMP_DIRS, REPL_DIR, ROOT, dump_files
from texture_catalogue import (
    descriptors, open_catalogue, ownership, pixel_digest, relative, resolve_names,
    scene_materials, text, texture_images,
)

BLOCKER = "logo-variant-or-scene-transfer-unproved"


def material_consumers(data: bytes, system: int) -> list[dict]:
    materials = scene_materials(data, system)
    for material in materials:
        material["mesh_parts"] = []
    root = relative(data, 20, system)
    if root + 52 > system:
        raise ValueError("Truncated scene mesh header")
    count = struct.unpack_from("<I", data, root + 44)[0]
    if not count:
        return materials
    base = relative(data, root + 48, system)
    if count > (system - base) // 112:
        raise ValueError("Scene mesh array exceeds system data")
    for index in range(count):
        mesh = base + 112 * index
        name_pointer = struct.unpack_from("<I", data, mesh + 64)[0]
        name = text(data, relative(data, mesh + 64, system), system) if name_pointer else ""
        parts = struct.unpack_from("<I", data, mesh + 104)[0]
        if not parts:
            continue
        table = relative(data, mesh + 108, system)
        if parts > (system - table) // 24:
            raise ValueError("Scene mesh parts exceed system data")
        for part in range(parts):
            record = table + part * 24
            material = struct.unpack_from("<I", data, record + 8)[0]
            if material >= len(materials):
                raise ValueError("Scene mesh part references invalid material")
            size = struct.unpack_from("<I", data, record + 4)[0]
            stream = relative(data, record, system) if size else None
            if stream is not None and stream + size > system:
                raise ValueError("Scene mesh stream exceeds system data")
            materials[material]["mesh_parts"].append({
                "mesh_index": index, "mesh": name, "part": part,
                "stream_offset": stream, "stream_bytes": size,
            })
    return materials


def contact_sheets(output: Path, cohort: list[dict], files: dict, coverage: dict) -> None:
    for batch, start in enumerate(range(0, len(cohort), 30), 1):
        page = Image.new("RGB", (1100, 5 * 220 + 38), "#242933")
        draw = ImageDraw.Draw(page)
        draw.text((12, 10), "Clean original logos: exact native source coverage (display alpha normalized)", fill="white")
        for position, row in enumerate(cohort[start:start + 30]):
            key = row["key"]
            x, y = (position % 5) * 220, (position // 5) * 175 + 38
            with Image.open(files[key]) as original:
                image = original.convert("RGBA")
                image.putalpha(image.getchannel("A").point(lambda value: min(255, round(value * 255 / 128))))
                image.thumbnail((145, 132))
                page.paste(image, (x + (220 - image.width) // 2, y), image)
            info = coverage[key]
            draw.text((x + 5, y + 135), f"{start + position + 1:02} {info['generator_teams'][:21]}", fill="white")
            draw.text((x + 5, y + 149), f"{info['width']}x{info['height']}  {info['status']}  sources:{info['native_sources']}", fill="#c3d6e8")
            draw.text((x + 5, y + 163), key[:26], fill="#c3d6e8")
        page.save(output / f"logo_originals_{batch:03}.png")


def asset_contexts(connection, native_rows: list[dict], courts: dict) -> list[dict]:
    result = []
    assets = {row["asset_hash"]: row["asset"] for row in native_rows}
    for key, asset in sorted(assets.items()):
        resources = [dict(row) for row in connection.execute(
            "SELECT kind,name FROM resources WHERE asset_hash=? ORDER BY ordinal", (key,))]
        resource_names = {row["name"] for row in resources}
        owner = ownership(asset, courts)
        if {"coachmodel", "unif", "short", "logo"} <= resource_names:
            role = "team-bundle"
        elif owner["kind"] == "uniform":
            role = "uniform-bundle"
        elif all(row["kind"] == "TXTR" and re.fullmatch(r"logo\d{3}", row["name"]) for row in resources):
            role = "logo-collection"
        elif "floor" in resource_names:
            role = "arena-bundle"
        else:
            role = "unresolved-structure"
        result.append({
            "asset": asset, "asset_hash": key, "structural_role": role,
            "filename_status": "unresolved" if asset.startswith("hash:") else "verified-crc",
            "owner": json.dumps(owner, sort_keys=True), "resource_count": len(resources),
            "resources": json.dumps(resources, sort_keys=True),
        })
    return result


def inspect(source: Path, catalogue: Path, baseline: Path, output: Path,
            variants: Path = ROOT / "data" / "texture_map" / "logo_variants.csv",
            courts: Path = ROOT / "data" / "texture_map" / "court_sources.csv") -> dict:
    if output.exists():
        raise ValueError("Inspection output already exists; choose a new directory")
    for protected in (ROOT / "texture_workspace", ROOT / "assets", REPL_DIR, *DUMP_DIRS, baseline):
        if output.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Inspection output must be outside artist/dump/replacement/baseline directories")
    cohort = [row for row in read_csv(baseline / "active_targets.csv") if row["blocker"] == BLOCKER]
    if not cohort or len({row["key"] for row in cohort}) != len(cohort):
        raise ValueError("Logo baseline cohort must contain unique, nonempty targets")
    baseline_pixels = {row["key"]: row["original_digest"] for row in read_csv(baseline / "workspace_mapping.csv")}
    files = dump_files()
    known, originals = collections.defaultdict(list), {}
    for row in cohort:
        key = row["key"]
        if key not in files:
            raise ValueError(f"Original dump disappeared since baseline: {key}")
        with Image.open(files[key]) as original:
            rgba = original.convert("RGBA")
            digest = pixel_digest(*rgba.size, rgba.tobytes())
            originals[key] = (rgba.width, rgba.height, digest)
        if digest != baseline_pixels.get(key):
            raise ValueError(f"Original dump changed since baseline: {key}")
        known[digest].append(key)
    generator_rows = [row for row in read_csv(variants) if row["key"] in originals]
    court_map = collections.defaultdict(list)
    for row in read_csv(courts):
        court_map[row["asset"]].append({"nba_slot": int(row["nba_slot"]), "nba_team": row["nba_team"]})
    native_rows, resource_rows, consumers, chains = [], [], [], []
    sources = collections.defaultdict(list)
    with closing(open_catalogue(catalogue)) as connection, source.open("rb") as stream:
        entries = read_archive(stream)
        names = resolve_names(stream, entries)
        shapes = sorted({(width, height) for width, height, _ in originals.values()})
        conditions, parameters = [], []
        for width, height in shapes:
            for level in range(7):
                conditions.append(f"(MAX(1,width >> {level})=? AND MAX(1,height >> {level})=?)")
                parameters.extend((width, height))
        query = """
            SELECT a.name AS asset,a.iso_offset,r.*
            FROM resources r JOIN assets a ON a.hash=r.asset_hash
            JOIN (
                SELECT DISTINCT asset_hash,resource_ordinal FROM textures
                WHERE psm IN (0,19,20) AND (""" + " OR ".join(conditions) + """)
            ) candidates ON candidates.asset_hash=r.asset_hash AND candidates.resource_ordinal=r.ordinal
            WHERE r.video>0 AND r.kind IN ('TXTR','HITX','SCNE','HiSn','TSET')
            ORDER BY a.entry_index,r.ordinal
        """
        for resource in connection.execute(query, parameters):
            asset = names.get(int(resource["asset_hash"], 16), resource["asset"])
            data = resource_data(stream, resource)
            system, video = resource["system"], resource["video"]
            try:
                objects = descriptors(data, resource["kind"], system)
            except ValueError as error:
                resource_rows.append({
                    "asset": asset, "resource_ordinal": resource["ordinal"], "kind": resource["kind"],
                    "descriptor": "", "texture": "", "status": "unsupported", "reason": str(error),
                    "layout": "", "video_start": "", "video_end": "", "matched_keys": "",
                })
                continue
            offsets = [location for location, _ in objects]
            scene_links = None
            context_error = ""
            for descriptor, name in objects:
                record = {
                    "asset": asset, "resource_ordinal": resource["ordinal"], "kind": resource["kind"],
                    "descriptor": descriptor, "texture": name, "status": "", "reason": "",
                    "layout": "", "video_start": "", "video_end": "", "matched_keys": "",
                }
                try:
                    images, layout, start, end = texture_images(data, system, video, descriptor, offsets)
                except ValueError as error:
                    record.update(status="unsupported", reason=str(error))
                    resource_rows.append(record)
                    continue
                record.update(status="decoded", layout=layout, video_start=start, video_end=end)
                matched_keys = set()
                for image in images:
                    digest = pixel_digest(image["width"], image["height"], image["rgba"])
                    matches = known.get(digest, [])
                    if not matches:
                        continue
                    if scene_links is None and resource["kind"] in ("SCNE", "HiSn"):
                        try:
                            scene_links = material_consumers(data, system)
                        except ValueError as error:
                            scene_links, context_error = [], str(error)
                    materials = [material for material in (scene_links or []) if material["descriptor"] == descriptor]
                    tex0 = struct.unpack_from("<Q", data, descriptor)[0]
                    identity = f"{resource['asset_hash']}:{resource['ordinal']}:{descriptor}:{image['level']}"
                    native = {
                        "native_image_id": identity, "asset": asset, "asset_hash": resource["asset_hash"],
                        "resource_ordinal": resource["ordinal"], "kind": resource["kind"],
                        "scene": resource["name"], "texture": name, "descriptor": descriptor,
                        "level": image["level"], "width": image["width"], "height": image["height"],
                        "layout": layout, "video_start": start, "video_end": end,
                        "upload_decoded_offset": system + start, "upload_bytes": end - start,
                        "pixel_decoded_offset": image.get("pixel_offset"),
                        "palette_decoded_offset": image.get("palette_offset"),
                        "gs_tbp": image.get("tbp"), "gs_tbw": image.get("tbw"), "gs_cbp": image.get("cbp"),
                        "tfx": (tex0 >> 35) & 3, "tcc": (tex0 >> 34) & 1,
                        "digest": digest, "dump_keys": ";".join(matches),
                        "owner": json.dumps(ownership(asset, court_map), sort_keys=True),
                        "materials": json.dumps(materials, sort_keys=True),
                        "context_status": "unsupported" if context_error else (
                            "scene-linked" if materials else "no-embedded-material-link"),
                        "context_reason": context_error,
                    }
                    native_rows.append(native)
                    for material in materials:
                        consumers.append({
                            "native_image_id": identity, "asset": asset, "scene": resource["name"],
                            "descriptor": descriptor, "level": image["level"],
                            "material_index": material["index"], "material": material["name"],
                            "rgba": json.dumps(material["rgba"]),
                            "mesh_parts": json.dumps(material["mesh_parts"], sort_keys=True),
                        })
                    for key in matches:
                        sources[key].append(native)
                        matched_keys.add(key)
                record["matched_keys"] = ";".join(sorted(matched_keys))
                if matched_keys:
                    chains.append({
                        "native_group_id": f"{resource['asset_hash']}:{resource['ordinal']}:{descriptor}",
                        "asset": asset, "resource_ordinal": resource["ordinal"], "descriptor": descriptor,
                        "texture": name, "layout": layout, "video_start": start, "video_end": end,
                        "stored_mip_count": len(images), "matched_keys": record["matched_keys"],
                        "mips": json.dumps([{
                            "level": image["level"], "width": image["width"], "height": image["height"],
                            "tbp": image.get("tbp"), "tbw": image.get("tbw"), "cbp": image.get("cbp"),
                            "digest": pixel_digest(image["width"], image["height"], image["rgba"]),
                        } for image in images], sort_keys=True),
                    })
                resource_rows.append(record)
        contexts = asset_contexts(connection, native_rows, court_map)
        if hash_stream(stream) != SOURCE_SHA256:
            raise ValueError("Pristine ISO changed during inspection")
    coverage = {}
    for row in cohort:
        key = row["key"]
        metadata = [variant for variant in generator_rows if variant["key"] == key]
        found = sources[key]
        coverage[key] = {
            "key": key, "status": "exact" if found else "unresolved", "old_blocker": BLOCKER,
            "width": originals[key][0], "height": originals[key][1], "digest": originals[key][2],
            "generator_teams": ";".join(sorted({variant["team"] for variant in metadata})),
            "generator_modes": ";".join(sorted({variant["mode"] for variant in metadata})),
            "reference_keys": ";".join(sorted({variant["ref_key"] for variant in metadata})),
            "native_sources": len(found),
            "native_assets": ";".join(sorted({native["asset"] for native in found})),
            "native_textures": ";".join(sorted({native["texture"] for native in found})),
            "native_levels": ";".join(str(level) for level in sorted({native["level"] for native in found})),
            "native_image_ids": ";".join(sorted({native["native_image_id"] for native in found})),
            "content_alias_keys": ";".join(sorted(set(known[originals[key][2]]) - {key})),
        }
    summary = {
        "source_sha256": SOURCE_SHA256, "baseline": str(baseline.resolve()), "cohort": BLOCKER,
        "targets": len(cohort), "exact_targets": sum(bool(sources[row["key"]]) for row in cohort),
        "unresolved_keys": [row["key"] for row in cohort if not sources[row["key"]]],
        "verified_original_pngs": len(originals), "matched_native_images": len(native_rows),
        "matched_native_texture_groups": len(chains),
        "stored_mip_counts": dict(collections.Counter(row["stored_mip_count"] for row in chains)),
        "native_asset_roles": dict(collections.Counter(row["structural_role"] for row in contexts)),
        "unresolved_native_filenames": sum(row["filename_status"] == "unresolved" for row in contexts),
        "distinct_original_images": len(known),
        "target_dimensions": dict(collections.Counter(f"{w}x{h}" for w, h, _ in originals.values())),
        "native_layouts": dict(collections.Counter(row["layout"] for row in native_rows)),
        "native_kinds": dict(collections.Counter(row["kind"] for row in native_rows)),
        "matched_scene_names": dict(collections.Counter(row["scene"] for row in native_rows if row["kind"] in ("SCNE", "HiSn"))),
        "scene_context_failures": sorted({row["context_reason"] for row in native_rows if row["context_reason"]}),
        "descriptor_status": dict(collections.Counter(row["status"] for row in resource_rows)),
        "unsupported_reasons": dict(collections.Counter(row["reason"] for row in resource_rows if row["status"] == "unsupported")),
        "whole_image_matches_only": True, "modified_artist_files": 0, "iso_written": False,
    }
    if not resource_rows:
        raise ValueError("Catalogue contains no candidate texture resources")
    output.mkdir(parents=True)
    write_csv(output / "logo_coverage.csv", tuple(next(iter(coverage.values()))), list(coverage.values()))
    if native_rows:
        write_csv(output / "native_sources.csv", tuple(native_rows[0]), native_rows)
    if consumers:
        write_csv(output / "material_consumers.csv", tuple(consumers[0]), consumers)
    if chains:
        write_csv(output / "mip_chains.csv", tuple(chains[0]), chains)
    if contexts:
        write_csv(output / "asset_contexts.csv", tuple(contexts[0]), contexts)
    if generator_rows:
        write_csv(output / "generator_reference_windows.csv", tuple(generator_rows[0]), generator_rows)
    write_csv(output / "resource_inspection.csv", tuple(resource_rows[0]), resource_rows)
    contact_sheets(output, cohort, files, coverage)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-source", required=True, type=Path)
    parser.add_argument("--catalogue", type=Path, default=ROOT / "cache" / "texture_iso" / "catalogue.sqlite")
    parser.add_argument("--baseline", type=Path, default=ROOT / "cache" / "texture_iso" / "milestone1")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.iso_source, args.catalogue, args.baseline, args.out)
    print(json.dumps(result, indent=2))
    if result["unresolved_keys"] or result["scene_context_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
