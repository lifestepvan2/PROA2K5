"""Export every remaining archive texture, starting with arena props/signage.

    python scripts\\remaining_texture_workspace.py export --iso-source PRISTINE
    python scripts\\remaining_texture_workspace.py export --iso-source PRISTINE --scope arenas

The season composer discovers this manifest automatically. Native masters are
independent of PCSX2 filenames; original dumps are only initial-migration evidence.
"""
import argparse
import collections
import json
import re
import struct
from contextlib import closing
from pathlib import Path

from PIL import Image

import texture_iso_workspace as native
import uniform_iso_workspace as uniforms
import uniform_labels
from texture_catalogue import TEXTURE_KINDS, descriptors, open_catalogue, pixel_digest, resolve_names, texture_images

MANIFEST = "_iso_textures.json"
POLICY = "_iso_migration.json"
ARENA = re.compile(r"s(\d{3})(n?)\.iff")
PLAYER = re.compile(r"p(\d+)([ha])(2?)\.iff")


def load_manifest(workspace: Path) -> dict:
    manifest = json.loads((workspace / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("source_sha256") != native.SOURCE_SHA256:
        raise ValueError("Native texture workspace schema/source mismatch")
    if (manifest.get("exceptions") or manifest.get("migration", {}).get("conflicts")
            or manifest.get("migration", {}).get("unmapped_manual_edits")):
        raise ValueError("Native texture workspace has unresolved export blockers")
    return manifest


def arena_slots() -> dict[str, int]:
    rows = native.csv_rows(native.ROOT / "data" / "texture_map" / "court_sources.csv")
    result = {}
    for row in rows:
        asset = row["asset"]
        result[asset] = int(row["nba_slot"])
        result[asset.replace(".iff", "n.iff")] = int(row["nba_slot"])
    return result


def location(asset: str, scene: str, texture: str, kind: str) -> tuple[Path, str, int | None]:
    slot = arena_slots().get(asset)
    if ARENA.fullmatch(asset):
        team = (f"slot_{slot:03}_{uniform_labels.TEAM_NAMES[slot]}" if slot is not None
                else f"special_{ARENA.fullmatch(asset)[1]}")
        words = f"{scene} {texture}".lower()
        if any(word in words for word in ("sponsor", "sign", "logo", "banner", "advert", "billboard", "dorna")):
            category = "sponsors_and_signage"
        elif "floor" in scene.lower():
            category = "court"
        elif any(word in words for word in ("crowd", "seat", "bleacher")):
            category = "stands_and_crowd"
        else:
            category = "props"
        return Path("arenas") / team / category, "arenas", slot
    player = PLAYER.fullmatch(asset)
    if player:
        return (Path("players") / f"pid_{int(player[1]):04}" /
                ({"h": "home", "a": "away"}[player[2]] + ("_alternate" if player[3] else "")),
                "players", None)
    if asset == "hash:35cb8d72":
        return Path("players") / "portraits", "portraits", None
    if kind == "FONT":
        return Path("interface") / "fonts", "fonts", None
    if any(word in asset for word in ("frontend", "global", "title", "menu", "load", "replay", "franchise")):
        return Path("interface"), "interface", None
    if any(word in asset for word in ("tv", "broadcast", "score", "espn", "jukebox")):
        return Path("broadcast"), "broadcast", None
    if kind == "CNSR" or asset.startswith(("cs_", "hl_")):
        return Path("cinematics"), "cinematics", None
    if asset.startswith("hash:"):
        return Path("unresolved"), "unresolved", None
    return Path("objects"), "objects", None


def footprint(images: list[dict], layout: str, start: int, end: int) -> tuple:
    addresses = tuple(tuple(image.get(key) for key in
                            ("width", "height", "pixel_offset", "palette_offset", "tbp", "tbw", "cbp"))
                      for image in images)
    return layout, start, end, addresses


def protected_manifests(workspace: Path) -> list[dict]:
    result = []
    for filename in (native.MANIFEST, uniforms.MANIFEST):
        path = workspace / filename
        if path.exists():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("schema") != 1 or manifest.get("source_sha256") != native.SOURCE_SHA256:
                raise ValueError(f"{path}: existing texture manifest schema/source mismatch")
            native.scan(workspace, manifest["sources"])
            result.append(manifest)
    return result


def migration_choices(workspace: Path) -> dict[str, str | None]:
    path = workspace / POLICY
    if not path.exists():
        return {}
    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError(f"{path}: invalid native migration choices")
    choices = policy.get("choices")
    if (policy.get("schema") != 1 or policy.get("source_sha256") != native.SOURCE_SHA256
            or not isinstance(choices, dict)
            or any(not re.fullmatch(r"[0-9a-f]{8}", key)
                   or (value is not None and not isinstance(value, str))
                   for key, value in choices.items())):
        raise ValueError(f"{path}: invalid native migration choices")
    return choices


def select_seed(token: str, candidates: set[str], manual: dict,
                choices: dict[str, str | None]) -> tuple[str | None, bool]:
    conflict = len({manual[key]["signature"] for key in candidates}) > 1
    if token in choices:
        selected = choices[token]
        if selected is not None and selected not in candidates:
            raise ValueError(f"{token}: approved legacy source no longer matches the pristine texture")
        return selected, False
    return (None, True) if conflict else (next(iter(sorted(candidates)), None), False)


def export(source: Path, workspace: Path = native.DEFAULT_WS,
           catalogue: Path = native.ROOT / "cache" / "texture_iso" / "catalogue.sqlite",
           legacy_workspace: Path = uniforms.legacy.DEFAULT_WS, *, scope: str = "all") -> dict:
    native.validate_workspace(workspace)
    if scope not in ("all", "arenas"):
        raise ValueError("Texture export scope must be all or arenas")
    previous = load_manifest(workspace) if (workspace / MANIFEST).exists() else None
    old = {row["id"]: row for row in previous["sources"]} if previous else {}
    existing = native.scan(workspace, previous["sources"]) if previous else {}
    protected = protected_manifests(workspace)
    external = [row for manifest in protected for row in manifest["sources"]]
    reserved = {row["id"]: row for row in external}
    external_resources = collections.defaultdict(list)
    for row in external:
        external_resources[row["asset_hash"], row["ordinal"]].append(row)
    if previous and previous.get("complete") and scope == "arenas":
        raise ValueError("Cannot narrow a complete texture workspace to arena-only scope")
    manual, seeds, warnings = uniforms.legacy_seed_index([legacy_workspace])
    choices = migration_choices(workspace)
    covered = collections.defaultdict(set)
    for manifest in protected:
        for row in manifest.get("migration", {}).get("manual_sources", []):
            covered[row["key"]].update(row["masters"])
    pending = workspace / "_native_export_pending"
    pending.mkdir(parents=True, exist_ok=True)
    sources, exceptions, aliases, conflicts, packages = [], [], [], [], set()
    no_textures = collections.Counter()
    touched = set()
    with source.open("rb") as stream, closing(open_catalogue(catalogue)) as connection:
        if native.hash_stream(stream) != native.SOURCE_SHA256:
            raise ValueError("Texture export requires the verified pristine ISO")
        entries = native.read_archive(stream)
        names = resolve_names(stream, entries)
        query = f"""
            SELECT a.name AS asset,a.entry_index,a.iso_offset,a.size AS asset_size,r.*
            FROM resources r JOIN assets a ON a.hash=r.asset_hash
            WHERE r.video>0 AND r.kind IN ({','.join('?' for _ in TEXTURE_KINDS)})
            ORDER BY a.entry_index,r.ordinal
        """
        resources = [dict(row) for row in connection.execute(query, TEXTURE_KINDS)]
        for row in resources:
            row["asset"] = names.get(int(row["asset_hash"], 16), row["asset"])
        resources.sort(key=lambda row: (not bool(ARENA.fullmatch(row["asset"])), row["entry_index"], row["ordinal"]))
        for resource in resources:
            asset = resource["asset"]
            if scope == "arenas" and not ARENA.fullmatch(asset):
                continue
            if entries.get(int(resource["asset_hash"], 16)) != (resource["iso_offset"], resource["asset_size"]):
                raise ValueError(f"{asset}: catalogue archive identity changed")
            try:
                body, data = native.source_bytes(stream, resource)
                objects = descriptors(data, resource["kind"], resource["system"])
            except (ValueError, UnicodeError) as error:
                exceptions.append({"asset": asset, "ordinal": resource["ordinal"], "reason": str(error)})
                continue
            if not objects:
                no_textures[resource["kind"]] += 1
                continue
            offsets = [offset for offset, _ in objects]
            physical = {}
            for row in external_resources[resource["asset_hash"], resource["ordinal"]]:
                images, layout, start, end = texture_images(
                    data, resource["system"], resource["video"], row["descriptor"], offsets)
                physical[footprint(images, layout, start, end)] = row["id"]
            packages.add(resource["asset_hash"])
            for descriptor, name in objects:
                identity = f"{native.SOURCE_SHA256}:{resource['asset_hash']}:{resource['ordinal']}:{descriptor}"
                token = native.digest(identity.encode())[:8]
                if token in reserved:
                    row = reserved[token]
                    if (row["asset_hash"], row["ordinal"], row["descriptor"]) != (
                            resource["asset_hash"], resource["ordinal"], descriptor):
                        raise ValueError(f"Native master ID collision: {token}")
                    continue
                if token in touched:
                    raise ValueError(f"Native master ID collision: {token}")
                touched.add(token)
                try:
                    images, layout, start, end = texture_images(
                        data, resource["system"], resource["video"], descriptor, offsets)
                except ValueError as error:
                    exceptions.append({"asset": asset, "ordinal": resource["ordinal"], "texture": name,
                                       "descriptor": descriptor, "reason": str(error)})
                    continue
                signature = footprint(images, layout, start, end)
                if signature in physical:
                    aliases.append({"asset_hash": resource["asset_hash"], "ordinal": resource["ordinal"],
                                    "descriptor": descriptor, "id": token, "master": physical[signature]})
                    continue
                physical[signature] = token
                original = native.display(images[0])
                digests = [pixel_digest(image["width"], image["height"], image["rgba"]) for image in images]
                candidates = set().union(*(seeds[digest] for digest in digests))
                selected, conflict = select_seed(token, candidates, manual, choices)
                if conflict:
                    conflicts.append({"id": token, "asset": asset, "texture": name,
                                      "sources": [manual[key]["path"] for key in sorted(candidates)],
                                      "keys": sorted(candidates)})
                    continue
                image = manual[selected]["image"] if selected is not None else original
                folder, group, slot = location(asset, resource["name"], name, resource["kind"])
                asset_folder = native.safe(asset.replace(".iff", ""))[:40]
                scene_folder = native.safe(resource["name"])[:36] or f"resource_{resource['ordinal']:03}"
                label = native.safe(f"{asset_folder}_{resource['name']}_{name}")[:80]
                relative = folder / asset_folder / scene_folder / (
                    f"{label}__{images[0]['width']}x{images[0]['height']}__{token}.png")
                row = {
                    "id": token, "asset": asset, "asset_hash": resource["asset_hash"],
                    "iso_offset": resource["iso_offset"], "asset_size": resource["asset_size"],
                    "ordinal": resource["ordinal"], "chunk_offset": resource["chunk_offset"],
                    "kind": resource["kind"], "scene": resource["name"], "stored": resource["stored"],
                    "system": resource["system"], "video": resource["video"], "scratch": resource["scratch"],
                    "compressed": bool(resource["compressed"]), "stored_sha256": native.digest(body),
                    "descriptor": descriptor, "descriptor_offsets": offsets, "texture": name,
                    "group": group, "slot": slot, "editable": True,
                    "width": images[0]["width"], "height": images[0]["height"], "layout": layout,
                    "psm": (struct.unpack_from("<Q", data, descriptor)[0] >> 20) & 63,
                    "original_digest": digests[0], "mip_digests": digests,
                    "original_display_digest": native.image_digest(original),
                    "seed_digest": native.image_digest(image), "path": str(relative),
                    "selected_legacy_key": selected,
                    "legacy_seeds": [{"key": key, "path": manual[key]["path"], "sha1": manual[key]["sha1"]}
                                     for key in sorted(candidates)],
                }
                for key in candidates:
                    covered[key].add(token)
                if token in old:
                    before = old[token]
                    if before["stored_sha256"] != row["stored_sha256"]:
                        raise ValueError(f"{asset}: native texture source changed")
                    row["path"] = str(existing[token].relative_to(workspace))
                    row["seed_digest"] = before["seed_digest"]
                    row["legacy_seeds"] = before.get("legacy_seeds", [])
                    row["selected_legacy_key"] = before.get("selected_legacy_key")
                else:
                    image.save(pending / f"{token}.png")
                sources.append(row)
        if old.keys() - {row["id"] for row in sources}:
            raise ValueError("Texture inventory lost existing native masters")
        if scope == "all" and set(choices) - touched:
            raise ValueError("Migration choices reference missing or protected native masters")
    missing = [{"key": key, "path": value["path"], "group": value["group"]}
               for key, value in manual.items() if key not in covered]
    review = {"schema": 1, "scope": scope, "exceptions": exceptions, "conflicts": conflicts,
              "unmapped_manual_edits": missing, "warnings": warnings}
    (workspace / "_iso_texture_review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    if exceptions or conflicts or (scope == "all" and missing):
        raise ValueError(f"Native texture export requires review: {len(exceptions)} format blockers, "
                         f"{len(conflicts)} artwork conflicts, {len(missing)} unmapped manual sources; "
                         "see _iso_texture_review.json")
    for row in sources:
        if row["id"] in old:
            continue
        path = workspace / row["path"]
        if path.exists():
            with Image.open(path) as image:
                if native.image_digest(image) != row["seed_digest"]:
                    raise ValueError(f"{path}: refusing to overwrite an untracked native master")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            (pending / f"{row['id']}.png").rename(path)
    migration = {"manual_sources": [
        {"key": key, "path": manual[key]["path"], "sha1": manual[key]["sha1"], "masters": sorted(ids)}
        for key, ids in sorted(covered.items())], "unmapped_manual_edits": missing,
        "warnings": warnings, "conflicts": [], "approved_choices": choices}
    manifest = {"schema": 1, "source_sha256": native.SOURCE_SHA256, "complete": scope == "all",
                "sources": sources, "migration": migration, "exceptions": [], "aliases": aliases,
                "resources_without_textures": dict(no_textures), "packages": len(packages),
                "scope": "Remaining archive textures; arenas first, existing logo/uniform masters reused"}
    temporary = workspace / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(workspace / MANIFEST)
    for path in pending.glob("*.png"):
        path.unlink()
    pending.rmdir()
    return {"masters": len(sources), "groups": dict(collections.Counter(row["group"] for row in sources)),
            "packages": len(packages), "physical_aliases": len(aliases),
            "seeded_masters": sum(row["selected_legacy_key"] is not None for row in sources),
            "manual_sources_covered": len(covered), "unmapped_manual_edits": missing, "complete": scope == "all"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("export",))
    parser.add_argument("--iso-source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=native.DEFAULT_WS)
    parser.add_argument("--catalogue", type=Path, default=native.ROOT / "cache" / "texture_iso" / "catalogue.sqlite")
    parser.add_argument("--legacy-workspace", type=Path, default=uniforms.legacy.DEFAULT_WS)
    parser.add_argument("--scope", choices=("all", "arenas"), default="all")
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.iso_source, args.workspace, args.catalogue, args.legacy_workspace,
                                scope=args.scope), indent=2))
    except (OSError, ValueError, MemoryError) as error:
        parser.exit(1, f"Native texture export failed: {error}\n")


if __name__ == "__main__":
    main()
