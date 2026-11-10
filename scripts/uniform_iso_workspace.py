"""Export complete native uniform bundles and migrate verified legacy artwork.

    python scripts\\uniform_iso_workspace.py export --iso-source PRISTINE

Compilation is shared with texture_iso_workspace.py and season_iso.py. No
PCSX2 dumps or legacy workspace are needed after the initial migration.
"""
import argparse
import collections
import json
import re
import shutil
import struct
from contextlib import closing
from pathlib import Path

from PIL import Image

import texture_iso_workspace as native
import texture_workspace as legacy
import uniform_labels
from inventory_lettering_iso import asset_hash
from texlib import dump_files
from texture_catalogue import descriptors, open_catalogue, pixel_digest, resolve_names, texture_images

MANIFEST = "_iso_uniforms.json"
BUNDLE = re.compile(r"(?:(sel)?([wpst])?u|w)([hax])(\d{3})\.iff|cs(crowd|trainer|ch)(\d{3})\.iff")
MIGRATED_GROUPS = {"uniforms", "uniform_parts", "jersey_numbers", "jersey_name_plates",
                   "crowd_and_referee_sprites"}


def owner(asset: str) -> dict:
    match = BUNDLE.fullmatch(asset)
    if match is None:
        raise ValueError(f"{asset}: not a verified uniform bundle filename")
    number = int(match[4] or match[6])
    if match[5]:
        return {"slot": native.team_ids().get(number), "native_team_id": number,
                "variant": "shared", "surface": {"ch": "cheer"}.get(match[5], match[5]), "warmup": False}
    return {"slot": native.team_ids().get(number), "native_team_id": number,
            "variant": {"h": "home", "a": "away", "x": "alternate"}[match[3]],
            "surface": "preview" if match[1] else "game",
            "warmup": bool(match[2] or asset.startswith(("wh", "wa", "wx")))}


def bundle_owner(asset: str, key: str, logos: list[dict]) -> dict:
    if BUNDLE.fullmatch(asset):
        return owner(asset)
    if asset != f"hash:{key}":
        raise ValueError(f"{asset}: unverified uniform package name")
    known = collections.defaultdict(set)
    for row in logos:
        if row["slot"] is not None:
            known[row["original_digest"]].add(row["slot"])
    matches = set().union(*(known[row["original_digest"]] for row in logos if row["asset_hash"] == key))
    return {"slot": next(iter(matches)) if len(matches) == 1 else None, "native_team_id": None,
            "variant": "unresolved", "surface": "unresolved", "warmup": False}


def inventory(stream, catalogue: Path, excluded: set[str],
              logos: list[dict] | None = None) -> tuple[list[dict], dict, list[dict]]:
    entries = native.read_archive(stream)
    names = resolve_names(stream, entries)
    sources, originals, packages, failures = [], {}, [], []
    with closing(open_catalogue(catalogue)) as connection:
        structural = {row[0] for row in connection.execute("SELECT DISTINCT asset_hash FROM resources WHERE name='unif'")}
        query = """
            SELECT a.name AS asset,a.iso_offset,a.size AS asset_size,r.*
            FROM resources r JOIN assets a ON a.hash=r.asset_hash
            ORDER BY a.entry_index,r.ordinal
        """
        seen = set()
        for resource in connection.execute(query):
            row = dict(resource)
            asset = names.get(int(row["asset_hash"], 16), row["asset"])
            if not BUNDLE.fullmatch(asset) and row["asset_hash"] not in structural:
                continue
            if entries.get(int(row["asset_hash"], 16)) != (row["iso_offset"], row["asset_size"]):
                raise ValueError(f"{asset}: catalogue archive location changed")
            ownership = bundle_owner(asset, row["asset_hash"], logos or [])
            if asset not in seen:
                packages.append({"asset": asset, "asset_hash": row["asset_hash"], **ownership})
                seen.add(asset)
            if not row["video"]:
                continue
            body, data = native.source_bytes(stream, {**row, "asset": row["asset"]})
            objects = descriptors(data, row["kind"], row["system"])
            if not objects:
                raise ValueError(f"{asset} resource {row['ordinal']}: video data without decoded descriptors")
            offsets = [location for location, _ in objects]
            aliases = {}
            for descriptor, name in objects:
                identity = f"{native.SOURCE_SHA256}:{row['asset_hash']}:{row['ordinal']}:{descriptor}"
                token = native.digest(identity.encode())[:8]
                if token in excluded:
                    continue
                try:
                    images, layout, start, end = texture_images(
                        data, row["system"], row["video"], descriptor, offsets)
                except ValueError as error:
                    failures.append({"asset": asset, "resource": row["ordinal"], "texture": name,
                                     "descriptor": descriptor, "reason": str(error)})
                    continue
                psm = (struct.unpack_from("<Q", data, descriptor)[0] >> 20) & 63
                if psm not in (19, 20):
                    raise ValueError(f"{asset}/{name}: unsupported native encoder PSM {psm}")
                digests = [pixel_digest(image["width"], image["height"], image["rgba"]) for image in images]
                addresses = tuple(tuple(image.get(key) for key in
                                        ("width", "height", "pixel_offset", "palette_offset", "tbp", "tbw", "cbp"))
                                  for image in images)
                signature = (start, end, layout, addresses, tuple(digests))
                if signature in aliases:
                    aliases[signature]["aliases"].append({"descriptor": descriptor, "texture": name})
                    continue
                source = {
                    "id": token, "asset": asset, "asset_hash": row["asset_hash"],
                    "iso_offset": row["iso_offset"], "asset_size": row["asset_size"],
                    "ordinal": row["ordinal"], "chunk_offset": row["chunk_offset"],
                    "kind": row["kind"], "scene": row["name"], "stored": row["stored"],
                    "system": row["system"], "video": row["video"], "scratch": row["scratch"],
                    "compressed": bool(row["compressed"]), "stored_sha256": native.digest(body),
                    "descriptor": descriptor, "descriptor_offsets": offsets, "texture": name,
                    "group": "uniforms", "editable": True, **ownership,
                    "width": images[0]["width"], "height": images[0]["height"], "layout": layout,
                    "original_digest": digests[0], "mip_digests": digests,
                    "original_display_digest": native.image_digest(native.display(images[0])),
                    "aliases": [{"descriptor": descriptor, "texture": name}],
                }
                aliases[signature] = source
                sources.append(source)
                originals[token] = native.display(images[0])
    if failures:
        raise ValueError("Native uniform decoding blockers: " + json.dumps(failures, indent=2))
    if not sources or len({row["id"] for row in sources}) != len(sources):
        raise ValueError("Native uniform inventory is empty or has duplicate IDs")
    return sources, originals, packages


def legacy_edits(roots: list[Path]) -> tuple[dict, dict, list[str]]:
    manual, effective, warnings = {}, {}, []
    for root in roots:
        if not (root / "_manifest.csv").is_file():
            raise ValueError(f"{root}: legacy migration manifest missing")
        manifest = legacy.read_manifest(root)
        files = legacy.scan(root)
        state_path = root / "_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        mapping, problems = uniform_labels.analyse_groups(root)
        warnings.extend(f"{root}: {problem}" for problem in problems)
        local = {}
        for token, row in manifest.items():
            path = files.get(token)
            if path is None:
                continue
            sha = legacy.sha1(path)
            if sha == row["sha1"] or sha == state.get("_workspace_auto", {}).get(row["key"]):
                continue
            with Image.open(path) as file:
                image = file.copy()
            signature = ("A" in image.getbands() or "transparency" in image.info, native.image_digest(image))
            key = row["key"]
            if key in manual and manual[key]["signature"] != signature:
                raise ValueError(f"Conflicting legacy manual artwork for {key}: {manual[key]['path']}, {path}")
            manual.setdefault(key, {"path": str(path.resolve()), "sha1": sha, "signature": signature,
                                    "group": row["group"], "image": image})
            local[key] = manual[key]
        for key in manifest:
            row = manifest[key]
            dump_key = row["key"]
            group = mapping.get(dump_key)
            source = dump_key
            if group:
                if group["master"] in local:
                    source = group["master"]
                else:
                    copies = [entry for entry, details in mapping.items()
                              if details["master"] == group["master"] and details["role"] == "copy" and entry in local]
                    if copies:
                        source = max(copies, key=lambda entry: Path(local[entry]["path"]).stat().st_mtime)
            if source not in local:
                continue
            if dump_key in local and local[dump_key]["signature"] != local[source]["signature"]:
                raise ValueError(f"{root}: independently edited COPY/LOD conflicts with its MASTER: {dump_key}")
            if dump_key in effective and manual[effective[dump_key]]["signature"] != local[source]["signature"]:
                raise ValueError(f"{root}: legacy workspaces disagree on inherited artwork for {dump_key}")
            effective[dump_key] = source
    return manual, effective, warnings


def legacy_seed_index(roots: list[Path]) -> tuple[dict, dict, list[str]]:
    manual, effective, warnings = legacy_edits(roots)
    dumps = dump_files()
    by_digest = collections.defaultdict(set)
    for key, source in effective.items():
        if key not in dumps:
            raise ValueError(f"Pristine dump missing for legacy migration: {key}")
        with Image.open(dumps[key]) as file:
            image = file.convert("RGBA")
            by_digest[pixel_digest(*image.size, image.tobytes())].add(source)
    return manual, by_digest, warnings


def seed_images(sources: list[dict], originals: dict, roots: list[Path]) -> tuple[dict, dict]:
    manual, by_digest, warnings = legacy_seed_index(roots)
    images, covered = dict(originals), collections.defaultdict(list)
    conflicts = []
    for row in sources:
        candidates = set().union(*(by_digest[value] for value in row["mip_digests"]))
        if not candidates:
            continue
        signatures = {manual[key]["signature"] for key in candidates}
        if len(signatures) != 1:
            conflicts.append({"id": row["id"], "asset": row["asset"], "texture": row["texture"],
                              "sources": [manual[key]["path"] for key in sorted(candidates)]})
            continue
        selected = sorted(candidates)[0]
        images[row["id"]] = manual[selected]["image"]
        row["legacy_seeds"] = [{"key": key, "path": manual[key]["path"], "sha1": manual[key]["sha1"]}
                               for key in sorted(candidates)]
        for key in candidates:
            covered[key].append(row["id"])
    missing = [{"key": key, "path": value["path"]} for key, value in manual.items()
               if value["group"] in ("uniforms", "uniform_parts") and key not in covered]
    if conflicts or missing:
        raise ValueError("Legacy uniform migration requires review: " +
                         json.dumps({"conflicts": conflicts, "unmapped_manual_edits": missing}, indent=2))
    return images, {"manual_sources": [
        {"key": key, "path": manual[key]["path"], "sha1": manual[key]["sha1"], "masters": sorted(ids)}
        for key, ids in sorted(covered.items())], "warnings": sorted(set(warnings)),
        "unmapped_manual_edits": [], "conflicts": []}


def load_manifest(workspace: Path) -> dict:
    manifest = json.loads((workspace / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("source_sha256") != native.SOURCE_SHA256:
        raise ValueError("Native uniform workspace schema/source mismatch")
    if (manifest.get("migration", {}).get("unmapped_manual_edits")
            or manifest.get("migration", {}).get("conflicts") or manifest.get("exceptions")):
        raise ValueError("Native uniform export has unresolved migration/decoding blockers")
    return manifest


def export(source: Path, workspace: Path = native.DEFAULT_WS,
           catalogue: Path = native.ROOT / "cache" / "texture_iso" / "catalogue.sqlite",
           legacy_workspace: Path = legacy.DEFAULT_WS) -> dict:
    native.validate_workspace(workspace)
    logos = json.loads((workspace / native.MANIFEST).read_text(encoding="utf-8"))
    if logos.get("source_sha256") != native.SOURCE_SHA256 or logos.get("schema") != 1:
        raise ValueError("Export the native logo workspace first")
    previous = load_manifest(workspace) if (workspace / MANIFEST).exists() else None
    old = {row["id"]: row for row in previous["sources"]} if previous else {}
    existing = native.scan(workspace, previous["sources"]) if previous else {}
    with source.open("rb") as stream:
        if native.hash_stream(stream) != native.SOURCE_SHA256:
            raise ValueError("Uniform export requires the verified pristine ISO")
        sources, originals, packages = inventory(
            stream, catalogue, {row["id"] for row in logos["sources"]}, logos["sources"])
    if old.keys() - {row["id"] for row in sources}:
        raise ValueError("Uniform inventory lost existing masters; migrate explicitly")
    if previous and {row["id"] for row in sources} == old.keys():
        images, migration = originals, previous["migration"]
    else:
        roots = [legacy_workspace]
        if (workspace / "_manifest.csv").exists() and workspace.resolve() != legacy_workspace.resolve():
            roots.append(workspace)
        images, migration = seed_images(sources, originals, roots)
    for row in sources:
        if row["slot"] is not None:
            team = f"slot_{row['slot']:03}_{uniform_labels.TEAM_NAMES[row['slot']]}"
        elif row["native_team_id"] is not None:
            team = f"native_{row['native_team_id']:03}"
        else:
            team = f"unresolved_{row['asset_hash']}"
        label = native.safe(f"{row['asset'].replace('.iff', '')}_{row['scene']}_{row['texture']}")
        row["path"] = str(Path("uniforms") / team / native.safe(row["asset"].replace(".iff", "")) /
                          f"{label}__{row['width']}x{row['height']}__{row['id']}.png")
        row["seed_digest"] = native.image_digest(images[row["id"]])
        if row["id"] in old:
            if old[row["id"]]["stored_sha256"] != row["stored_sha256"]:
                raise ValueError("Native uniform source changed; migrate explicitly")
            row["path"] = str(existing[row["id"]].relative_to(workspace))
            row["seed_digest"] = old[row["id"]]["seed_digest"]
            row["legacy_seeds"] = old[row["id"]].get("legacy_seeds", [])
    if not previous:
        for group in sorted(MIGRATED_GROUPS):
            directory = workspace / group
            backup = workspace / "_legacy_pcsx2" / group
            if directory.exists() and backup.exists():
                raise ValueError(f"{backup}: backup already exists; refusing to overwrite")
        for group in sorted(MIGRATED_GROUPS):
            directory = workspace / group
            if directory.exists():
                backup = workspace / "_legacy_pcsx2" / group
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(directory), str(backup))
    for row in sources:
        if row["id"] not in old:
            path = workspace / row["path"]
            if path.exists():
                with Image.open(path) as file:
                    if native.image_digest(file) != row["seed_digest"]:
                        raise ValueError(f"{path}: refusing to overwrite an untracked master")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            images[row["id"]].save(path)
    manifest = {"schema": 1, "source_sha256": native.SOURCE_SHA256, "sources": sources, "packages": packages,
                "migration": migration, "exceptions": [],
                "external_masters": [row["id"] for row in logos["sources"]
                                     if row["asset_hash"] in {package["asset_hash"] for package in packages}],
                "scope": "All textures in verified game, preview and warmup uniform bundles; native mips regenerated"}
    (workspace / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"masters": len(sources), "packages": len(packages),
            "seeded_masters": sum(bool(row.get("legacy_seeds")) for row in sources),
            "manual_sources": len(migration["manual_sources"]),
            "external_logo_masters": len(manifest["external_masters"]), "migration": migration}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("export",))
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=native.DEFAULT_WS)
    parser.add_argument("--catalogue", type=Path, default=native.ROOT / "cache" / "texture_iso" / "catalogue.sqlite")
    parser.add_argument("--legacy-workspace", type=Path, default=legacy.DEFAULT_WS)
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.iso_source, args.workspace, args.catalogue, args.legacy_workspace), indent=2))
    except (OSError, ValueError, MemoryError) as error:
        parser.exit(1, f"Native uniform export failed: {error}\n")


if __name__ == "__main__":
    main()
