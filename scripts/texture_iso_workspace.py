"""Native texture masters, independent of PCSX2 dumps and replacement keys.

Export discovers team logos and centerlogo mesh textures directly from the ISO.
Logo owners outside confirmed current teams remain stock references. Complete
uniform bundles are included after uniform_iso_workspace.py export.
Folder names never control rendering.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
import shutil
import struct
from contextlib import closing
from pathlib import Path

import numpy as np
from PIL import Image

import archive_iso
from inventory_lettering_iso import asset_hash
from iso_copy import hash_stream, publish_iso_copy
from native_texture import display, encode, encode_shared
from patch_lettering_iso import ISO_SIZE
from patch_preview_lettering_iso import SOURCE_SHA256
from player_texture_iso import read_archive
from texture_catalogue import descriptors, open_catalogue, pixel_digest, texture_images
from inspect_logo_iso import material_consumers
from texlib import proa_slots
from vc_lz import decode, rebuild_tail, recompress, validate_inplace

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WS = ROOT / "texture_workspace_ISO"
MANIFEST = "_iso_logos.json"
SEEDS = ROOT / "data" / "texture_map" / "logo_iso_defaults.json"
EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
TOKEN = re.compile(r"__([0-9a-f]{8})$")


def csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def image_digest(image: Image.Image) -> str:
    rgba = image.convert("RGBA")
    return pixel_digest(*rgba.size, rgba.tobytes())


def validate_workspace(workspace: Path) -> None:
    if workspace.resolve().is_relative_to((ROOT / "texture_workspace").resolve()):
        raise ValueError("ISO texture work must not use the legacy texture_workspace; use texture_workspace_ISO")


def team_ids() -> dict[int, int]:
    rows = csv_rows(ROOT / "data" / "nba_defaults" / "teams_unknown.csv")
    return {int(row["id"]): int(row["slot"]) for row in rows if int(row["slot"]) < 30}


def current_slot(asset: str, key: str, texture: str, group: str) -> int | None:
    ids = team_ids()
    if key == "a90f4964":
        match = re.fullmatch(r"logo(\d{3})", texture)
        return ids.get(int(match[1])) if match else None
    if asset.startswith("hash:") or asset_hash(asset) != int(key, 16):
        return None
    if group == "centerlogo":
        courts = {row["asset"]: int(row["nba_slot"])
                  for row in csv_rows(ROOT / "data" / "texture_map" / "court_sources.csv")}
        return courts.get(asset)
    match = re.fullmatch(r"(?:sel)?(?:w)?u[hax](\d{3})\.iff", asset)
    return ids.get(int(match[1])) if match else None


def source_bytes(stream, row: dict) -> tuple[bytes, bytes]:
    stream.seek(row["iso_offset"] + row["chunk_offset"])
    header = stream.read(32)
    if len(header) != 32:
        raise ValueError("Truncated native logo resource header")
    kind, stored, system, video, sentinel, scratch, _, _ = struct.unpack("<4s7I", header)
    if (kind.decode("ascii"), stored, system, video, scratch, sentinel == 0xFEEDBEEF) != (
            row["kind"], row["stored"], row["system"], row["video"], row["scratch"], bool(row["compressed"])):
        raise ValueError(f"{row['asset']}: native logo resource header changed")
    body = stream.read(stored)
    if len(body) != stored or (row.get("stored_sha256") and digest(body) != row["stored_sha256"]):
        raise ValueError(f"{row['asset']}: native logo source fingerprint changed")
    data = decode(body, system + video, collect_tokens=False)[0] if row["compressed"] else body
    return body, data


def inventory(stream, catalogue: Path) -> tuple[list[dict], list[dict]]:
    entries = read_archive(stream)
    result, exceptions = [], []
    with closing(open_catalogue(catalogue)) as connection:
        team_assets = {row[0] for row in connection.execute(
            "SELECT asset_hash FROM resources WHERE name IN ('coachmodel','unif','short') "
            "GROUP BY asset_hash HAVING count(DISTINCT name)=3")}
        query = """
            SELECT a.name AS asset,a.iso_offset,a.size AS asset_size,r.*
            FROM resources r JOIN assets a ON a.hash=r.asset_hash
            WHERE (r.kind='TXTR' AND (r.name IN ('logo','smlogo') OR r.name GLOB 'logo[0-9][0-9][0-9]'))
               OR (r.kind IN ('SCNE','HiSn') AND r.name='floor')
            ORDER BY a.entry_index,r.ordinal
        """
        for resource in connection.execute(query):
            row = dict(resource)
            if row["kind"] == "TXTR" and row["name"] in ("logo", "smlogo") and row["asset_hash"] not in team_assets:
                continue
            if entries.get(int(row["asset_hash"], 16)) != (row["iso_offset"], row["asset_size"]):
                raise ValueError("Native catalogue archive location differs from pristine source")
            body, data = source_bytes(stream, row)
            try:
                objects = descriptors(data, row["kind"], row["system"])
                contexts = material_consumers(data, row["system"]) if row["name"] == "floor" else []
                selected = {material["descriptor"] for material in contexts
                            if any(part["mesh"] == "centerlogo" for part in material["mesh_parts"])}
                for descriptor, name in objects:
                    if row["name"] == "floor" and descriptor not in selected:
                        continue
                    try:
                        images, layout, start, end = texture_images(
                            data, row["system"], row["video"], descriptor, [location for location, _ in objects])
                    except ValueError as error:
                        exceptions.append({"asset": row["asset"], "ordinal": row["ordinal"],
                                           "descriptor": descriptor, "reason": str(error)})
                        continue
                    identity = f"{SOURCE_SHA256}:{row['asset_hash']}:{row['ordinal']}:{descriptor}"
                    group = "centerlogo" if row["name"] == "floor" else "team_logos"
                    # The common collection's filename is unknown, but its numbered objects are verified.
                    asset = row["asset"]
                    slot = current_slot(asset, row["asset_hash"], name, group)
                    result.append({
                        "id": digest(identity.encode())[:8], "asset": asset, "asset_hash": row["asset_hash"],
                        "iso_offset": row["iso_offset"], "asset_size": row["asset_size"],
                        "ordinal": row["ordinal"], "chunk_offset": row["chunk_offset"],
                        "kind": row["kind"], "scene": row["name"], "stored": row["stored"],
                        "system": row["system"], "video": row["video"], "scratch": row["scratch"],
                        "compressed": bool(row["compressed"]), "stored_sha256": digest(body),
                        "descriptor": descriptor, "descriptor_offsets": [location for location, _ in objects],
                        "texture": name, "group": group, "slot": slot, "editable": slot is not None,
                        "width": images[0]["width"], "height": images[0]["height"], "layout": layout,
                        "original_digest": pixel_digest(images[0]["width"], images[0]["height"], images[0]["rgba"]),
                        "original_display_digest": image_digest(display(images[0])),
                        "materials": [material for material in contexts if material["descriptor"] == descriptor],
                    })
            except ValueError as error:
                exceptions.append({"asset": row["asset"], "ordinal": row["ordinal"], "reason": str(error)})
    if not result or len({row["id"] for row in result}) != len(result):
        raise ValueError("Native logo inventory is empty or has duplicate IDs")
    return result, exceptions


def default_image(original: Image.Image, slot: int, recipe: dict | None) -> Image.Image:
    assignments = proa_slots()
    if slot not in assignments:
        return original
    with Image.open(ROOT / "nba2k_editor" / "assets" / f"{38 + assignments[slot]}.png") as file:
        logo = file.convert("RGBA")
    box = logo.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if box is None:
        raise ValueError(f"Team slot {slot}: club logo is empty")
    logo = logo.crop(box)
    if recipe:
        frame_width, frame_height = recipe["reference_size"]
        x0, y0, x1, y1 = recipe["reference_box"]
        scale = 512 / frame_width
        x0, y0, x1, y1 = (value * scale for value in (x0, y0, x1, y1))
        canvas = Image.new("RGBA", (512, 512))
    else:
        frame_width, frame_height = original.size
        bounds = original.getchannel("A").point(lambda value: 255 if value > 16 else 0).getbbox()
        if bounds is None:
            raise ValueError("Native logo is empty; cannot seed a club default")
        x0, y0, x1, y1 = bounds
        canvas = Image.new("RGBA", original.size)
    factor = min((x1 - x0) / logo.width, (y1 - y0) / logo.height)
    logo = logo.resize((max(1, round(logo.width * factor)), max(1, round(logo.height * factor))), Image.Resampling.LANCZOS)
    canvas.alpha_composite(logo, (round((x0 + x1 - logo.width) / 2), round((y0 + y1 - logo.height) / 2)))
    if recipe:
        x, y, width, height = recipe["window"]
        left, top = round(x * 512), round(y * 512)
        canvas = canvas.crop((left, top, left + round(width * 512), top + round(height * 512)))
    if np.mean(np.asarray(original)[..., 3] >= 239) > .99:
        pixels = np.asarray(original)
        border = np.concatenate((pixels[0, :, :3], pixels[-1, :, :3], pixels[:, 0, :3], pixels[:, -1, :3]))
        background = Image.new("RGBA", original.size, tuple(np.median(border, axis=0).astype(int)) + (255,))
        background.alpha_composite(canvas.resize(original.size, Image.Resampling.LANCZOS))
        return background
    return canvas.resize(original.size, Image.Resampling.LANCZOS)


def scan(workspace: Path, sources: list[dict]) -> dict[str, Path]:
    known, found = {row["id"] for row in sources}, {}
    for path in workspace.rglob("*"):
        if (not path.is_file() or path.suffix.lower() not in EXTENSIONS
                or any(part.startswith("_") for part in path.relative_to(workspace).parts)):
            continue
        match = TOKEN.search(path.stem)
        if match and match[1] in known:
            if match[1] in found:
                raise ValueError(f"Duplicate native master ID {match[1]}: {found[match[1]]}, {path}")
            found[match[1]] = path
    missing = known - found.keys()
    if missing:
        raise ValueError(f"Missing native logo masters: {', '.join(sorted(missing))}")
    return found


def export(source: Path, workspace: Path = DEFAULT_WS,
           catalogue: Path = ROOT / "cache" / "texture_iso" / "catalogue.sqlite") -> dict:
    validate_workspace(workspace)
    manifest_path = workspace / MANIFEST
    previous = {}
    existing_files = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != 1 or manifest.get("source_sha256") != SOURCE_SHA256:
            raise ValueError("Existing native workspace schema/source mismatch")
        previous = {row["id"]: row for row in manifest["sources"]}
        existing_files = scan(workspace, manifest["sources"])
    recipes = json.loads(SEEDS.read_text(encoding="utf-8"))
    if recipes["source_sha256"] != SOURCE_SHA256:
        raise ValueError("Native logo default recipes use a different pristine source")
    with source.open("rb") as stream:
        sources, exceptions = inventory(stream, catalogue)
        pending = []
        unseeded = []
        for row in sources:
            _, data = source_bytes(stream, row)
            images, _, _, _ = texture_images(data, row["system"], row["video"], row["descriptor"], row["descriptor_offsets"])
            original = display(images[0])
            recipe = recipes["images"].get(row["original_digest"])
            if recipe and row["editable"] and recipe["slot"] != row["slot"]:
                raise ValueError("Native logo seed recipe disagrees with confirmed current-team ownership")
            image = original
            if row["editable"]:
                if row["group"] == "centerlogo" and row["slot"] in {
                        int(value["nba_slot"]) for value in csv_rows(ROOT / "data" / "team_slots.csv")} and recipe is None:
                    unseeded.append(row["id"])
                else:
                    image = default_image(original, row["slot"], recipe)
            label = safe(f"{row['asset'].replace('.iff', '')}_{row['scene']}_{row['texture']}")
            folder = row["group"]
            row["path"] = str(Path(folder) / f"{label}__{row['width']}x{row['height']}__{row['id']}.png")
            row["seed_digest"] = image_digest(image)
            if row["id"] in previous:
                old = previous[row["id"]]
                if old["stored_sha256"] != row["stored_sha256"]:
                    raise ValueError("Native export source changed; migrate edits explicitly")
                row["path"] = str(existing_files[row["id"]].relative_to(workspace))
                row["seed_digest"] = old["seed_digest"]
            pending.append((row, image))
        if hash_stream(stream) != SOURCE_SHA256:
            raise ValueError("Pristine ISO changed during native export")
    workspace.mkdir(parents=True, exist_ok=True)
    legacy = workspace / "team_logos"
    if legacy.exists() and not previous:
        backup = workspace / "_legacy_pcsx2" / "team_logos"
        if backup.exists():
            raise ValueError("Legacy logo backup already exists; refusing to replace it")
        backup.parent.mkdir(exist_ok=True)
        shutil.move(str(legacy), str(backup))
    for row, image in pending:
        if row["id"] in previous:
            continue
        path = workspace / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    manifest = {
        "schema": 1, "source_sha256": SOURCE_SHA256, "sources": sources,
        "exceptions": exceptions, "unseeded_centerlogo": unseeded,
        "scope": "Only confirmed current-team sources; historical and unresolved owners remain stock references",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"masters": len(sources), "groups": dict(collections.Counter(row["group"] for row in sources)),
            "editable": sum(row["editable"] for row in sources),
            "exceptions": exceptions, "unseeded_centerlogo": unseeded}


def prepare(stream, workspace: Path = DEFAULT_WS, court_edits: list | None = None,
            *, collect_failures: bool = False, repack_archive: bool = False,
            palette_colors: int = 256, texture_edits: list | None = None) -> tuple[list, dict]:
    validate_workspace(workspace)
    if type(palette_colors) is not int or palette_colors not in (16, 32, 64, 128, 256):
        raise ValueError("Invalid default native palette color count")
    if not (workspace / MANIFEST).is_file():
        raise ValueError("Native logo workspace is not exported; run texture_iso_workspace.py export first")
    manifest = json.loads((workspace / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("Native logo workspace schema/source mismatch")
    entries = read_archive(stream)
    from uniform_iso_workspace import MANIFEST as UNIFORM_MANIFEST, load_manifest, bundle_owner
    uniforms = load_manifest(workspace) if (workspace / UNIFORM_MANIFEST).is_file() else None
    from remaining_texture_workspace import MANIFEST as TEXTURE_MANIFEST, load_manifest as load_textures, location
    remaining = load_textures(workspace) if (workspace / TEXTURE_MANIFEST).is_file() else None
    generic_ids = {row["id"] for row in remaining["sources"]} if remaining else set()
    sources = manifest["sources"] + (uniforms["sources"] if uniforms else []) + (remaining["sources"] if remaining else [])
    if (not sources or len({row["id"] for row in sources}) != len(sources)
            or any(not re.fullmatch(r"[0-9a-f]{8}", row["id"]) for row in sources)):
        raise ValueError("Native logo manifest requires unique valid master IDs")
    files = scan(workspace, sources)
    policy_path = workspace / "_iso_encoding.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {"schema": 1, "palette_colors": {}}
    if (not isinstance(policy, dict) or type(policy.get("schema")) is not int
            or policy["schema"] != 1 or set(policy) != {"schema", "palette_colors"}
            or not isinstance(policy["palette_colors"], dict)
            or set(policy["palette_colors"]) - files.keys()
            or any(type(value) is not int or value not in (16, 32, 64, 128, 256)
                   for value in policy["palette_colors"].values())):
        raise ValueError("Invalid explicit native palette policy")
    resources = {}
    shared_edits = collections.defaultdict(list)
    reports = []
    for row in sources:
        path = files[row["id"]]
        with Image.open(path) as file:
            master = file.copy()
        if image_digest(master) == row["original_display_digest"]:
            continue
        if not row["editable"]:
            if image_digest(master) != row["seed_digest"]:
                raise ValueError(f"{path}: historical/unconfirmed-owner reference is outside current-team POC scope")
            continue
        if row["id"] in generic_ids:
            identity = f"{SOURCE_SHA256}:{row['asset_hash']}:{row['ordinal']}:{row['descriptor']}"
            if (digest(identity.encode())[:8] != row["id"]
                    or location(row["asset"], row["scene"], row["texture"], row["kind"])[2] != row["slot"]
                    or (row["asset"] != f"hash:{row['asset_hash']}"
                        and asset_hash(row["asset"]) != int(row["asset_hash"], 16))):
                raise ValueError(f"{path}: native texture ownership/identity changed")
        elif row["group"] == "uniforms":
            actual = bundle_owner(row["asset"], row["asset_hash"], manifest["sources"])
            if ((not row["asset"].startswith("hash:") and asset_hash(row["asset"]) != int(row["asset_hash"], 16))
                    or any(row[key] != value for key, value in actual.items())):
                raise ValueError(f"{path}: native uniform ownership changed")
        else:
            actual_slot = current_slot(row["asset"], row["asset_hash"], row["texture"], row["group"])
            if actual_slot is None or actual_slot != row["slot"]:
                raise ValueError(f"{path}: current-team ownership does not match the native source")
        if entries.get(int(row["asset_hash"], 16)) != (row["iso_offset"], row["asset_size"]):
            raise ValueError("Native master archive identity changed")
        offset = row["iso_offset"] + row["chunk_offset"] + 32
        if offset not in resources:
            body, decoded = source_bytes(stream, row)
            resources[offset] = [row, body, decoded, decoded]
        resource, body, original, target = resources[offset]
        if row["layout"] == "linear-shared-indices":
            shared_edits[offset].append((row, master))
            continue
        encoded, report, preview = encode(
            original, row["system"], row["video"], row["descriptor"], row["descriptor_offsets"], master,
            palette_colors=policy["palette_colors"].get(row["id"], palette_colors))
        target = merge_decoded(original, target, encoded, f"Native masters in {row['asset']}")
        resources[offset][3] = target
        reports.append({"id": row["id"], "asset": row["asset"], "texture": row["texture"], "resource_offset": offset,
                        "group": row["group"], "slot": row["slot"], "path": str(path), **report})
        preview_path = workspace / "_encoded" / f"{row['id']}.png"
        preview_path.parent.mkdir(exist_ok=True)
        preview.save(preview_path)
    for offset, edits in shared_edits.items():
        row, body, original, target = resources[offset]
        colors = min(policy["palette_colors"].get(item["id"], palette_colors) for item, _ in edits)
        encoded, details, previews = encode_shared(
            original, row["system"], row["video"], row["descriptor_offsets"],
            {item["descriptor"]: image for item, image in edits}, palette_colors=colors)
        resources[offset][3] = merge_decoded(original, target, encoded, f"Shared-index masters in {row['asset']}")
        cohort = {item["descriptor"]: item for item in sources
                  if item["iso_offset"] + item["chunk_offset"] + 32 == offset}
        for detail in details:
            item = cohort[detail["descriptor"]]
            reports.append({"id": item["id"], "asset": item["asset"], "texture": item["texture"],
                            "resource_offset": offset, "group": item["group"], "slot": item["slot"],
                            "path": str(files[item["id"]]), **detail})
            preview_path = workspace / "_encoded" / f"{item['id']}.png"
            preview_path.parent.mkdir(exist_ok=True)
            previews[detail["descriptor"]].save(preview_path)
    for offset, body, original, target, scratch, report in (court_edits or []) + (texture_edits or []):
        if offset in resources:
            row, existing_body, existing_original, edited = resources[offset]
            if original != existing_original or body != existing_body:
                raise ValueError("Native texture/control resources disagree on source bytes")
            if edited != original and any(edit[0] == offset for edit in texture_edits or []):
                if report.get("modifier") == "skin_tones":
                    raise ValueError("Skin-tone plan and native master target the same player texture; choose one source")
                raise ValueError("Lettering master and colour controls target the same texture; "
                                 "reset overlapping palette controls before editing its pixels")
            resources[offset][3] = merge_decoded(original, edited, target, "Controls and native masters")
        else:
            resources[offset] = [{"asset": report["asset"], "compressed": report.get("compressed", True), "scratch": scratch},
                                 body, original, target]
    patches, budgets, capacity_failures = [], [], []
    for offset, (row, body, original, target) in sorted(resources.items()):
        if original == target:
            continue
        first = next(index for index, (a, b) in enumerate(zip(original, target)) if a != b)
        failures = []
        scratch = row["scratch"]
        if row["compressed"] and repack_archive:
            cache_path = workspace / "_encoded" / "resources" / f"{digest(body + target)}.repack-v2"
            if cache_path.exists():
                cached = cache_path.read_bytes()
                if len(cached) < 20:
                    raise ValueError(f"{cache_path}: truncated resized resource cache")
                required_scratch = struct.unpack_from("<I", cached)[0]
                rebuilt = cached[4:]
            else:
                rebuilt, required_scratch = min(
                    (recompress(body, target, distance_bits=bits) for bits in dict.fromkeys((body[8], 9))),
                    key=lambda result: (len(result[0]), result[1]))
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("xb") as file:
                    file.write(struct.pack("<I", required_scratch) + rebuilt)
            if (len(rebuilt) % 16 or required_scratch % 16 or rebuilt[:8] != body[:8]
                    or len(target) + required_scratch < len(rebuilt)):
                raise ValueError(f"{cache_path}: invalid resized resource identity")
            scratch = max(scratch, required_scratch)
            validate_inplace(rebuilt, target, scratch)
            stream.seek(offset - 32)
            header = stream.read(32)
            if len(header) != 32:
                raise ValueError("Truncated resized resource header")
            fields = list(struct.unpack("<4s7I", header))
            if fields[1] != len(body) or fields[2] + fields[3] != len(original) or fields[4] != 0xFEEDBEEF:
                raise ValueError("Resized resource header differs from the native source")
            fields[1], fields[5] = len(rebuilt), scratch
            updated_header = struct.pack("<4s7I", *fields)
            if updated_header != header:
                patches.append((offset - 32, header, updated_header))
        elif row["compressed"]:
            cache_path = workspace / "_encoded" / "resources" / f"{digest(body + target)}.fixed-v2.bin"
            if cache_path.exists():
                rebuilt = cache_path.read_bytes()
                if len(rebuilt) != len(body) or rebuilt[:8] != body[:8]:
                    raise ValueError(f"{cache_path}: invalid cached resource identity")
                validate_inplace(rebuilt, target, row["scratch"])
            else:
                rebuilt = None
                for bits in dict.fromkeys((body[8], 9, 10, 11, 12, 8, 13)):
                    try:
                        rebuilt = rebuild_tail(body, len(original), target[first:], row["scratch"], distance_bits=bits)
                        break
                    except ValueError as error:
                        failures.append(f"bits={bits}: {error}")
                if rebuilt is None:
                    failed_path = workspace / "_encoded" / f"capacity_{offset:x}.bin"
                    failed_path.parent.mkdir(exist_ok=True)
                    failed_path.write_bytes(target)
                    capacity_failures.append({
                        "asset": row["asset"], "offset": offset, "stored": len(body), "scratch": row["scratch"],
                        "target": str(failed_path), "ids": [report["id"] for report in reports if report["resource_offset"] == offset],
                        "reasons": failures,
                    })
                    continue
                validate_inplace(rebuilt, target, row["scratch"])
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("xb") as file:
                    file.write(rebuilt)
        else:
            rebuilt = target
        verified = decode(rebuilt, len(original), collect_tokens=False)[0] if row["compressed"] else rebuilt
        if (not repack_archive and len(rebuilt) != len(body)) or verified != target:
            raise ValueError("Native resource compression/readback failed")
        patches.append((offset, body, rebuilt))
        budgets.append({"asset": row["asset"], "offset": offset, "stored": len(body), "scratch": row["scratch"],
                        "new_stored": len(rebuilt), "new_scratch": scratch,
                        "runtime_allocation_delta": scratch - row["scratch"],
                        "distance_bits": rebuilt[8] if row["compressed"] else None,
                        "decoded_sha256": digest(target)})
    report = {"workspace": str(workspace.resolve()), "masters": len(sources),
                     "textures": reports, "resources": budgets,
                     "courts": [edit[5] for edit in court_edits or []],
                     "stock_centerlogo": manifest["unseeded_centerlogo"], "exceptions": manifest["exceptions"],
                     "capacity_failures": capacity_failures, "encoding_policy": policy,
                     "repack_archive": repack_archive, "default_palette_colors": palette_colors}
    report["uniforms"] = ({"masters": len(uniforms["sources"]), "packages": len(uniforms["packages"]),
                          "migration": uniforms["migration"]} if uniforms else None)
    report["remaining"] = ({"masters": len(remaining["sources"]), "packages": remaining["packages"],
                           "complete": remaining["complete"], "migration": remaining["migration"]}
                          if remaining else None)
    if capacity_failures and not collect_failures:
        raise ValueError(f"{len(capacity_failures)} native resources exceed fixed capacity; run check for the complete review catalogue")
    return patches, report


def merge_decoded(original: bytes, previous: bytes, target: bytes, context: str) -> bytes:
    if len(original) != len(previous) or len(target) != len(original):
        raise ValueError(f"{context}: decoded resource length changed")
    a, b = np.frombuffer(original, dtype=np.uint8), np.frombuffer(target, dtype=np.uint8)
    changed = a != b
    edited = np.frombuffer(previous, dtype=np.uint8)
    if np.any((edited[changed] != a[changed]) & (edited[changed] != b[changed])):
        raise ValueError(f"{context}: conflicting writes; reset overlapping palette controls or master edits")
    combined = bytearray(previous)
    np.frombuffer(combined, dtype=np.uint8)[changed] = b[changed]
    return bytes(combined)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "check", "build"))
    parser.add_argument("--iso-source", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WS)
    parser.add_argument("--catalogue", type=Path, default=ROOT / "cache" / "texture_iso" / "catalogue.sqlite")
    parser.add_argument("--iso-out", type=Path)
    parser.add_argument("--repack-archive", action="store_true",
                        help="Experimental: pool package sectors within the existing disc extents")
    parser.add_argument("--palette-colors", type=int, choices=(16, 32, 64, 128, 256), default=256,
                        help="Default encoding colors; explicit per-master policies take precedence")
    args = parser.parse_args()
    try:
        if args.command == "export":
            report = export(args.iso_source, args.workspace, args.catalogue)
        else:
            if args.command == "build" and args.iso_out is None:
                parser.error("build requires --iso-out")
            if args.iso_out and (args.iso_out.resolve().is_relative_to(args.workspace.resolve())
                                 or args.iso_out.resolve() == args.iso_source.resolve()):
                raise ValueError("ISO output must be outside the workspace and different from source")
            with args.iso_source.open("rb") as stream:
                patches, report = prepare(stream, args.workspace, collect_failures=args.command == "check",
                                          repack_archive=args.repack_archive, palette_colors=args.palette_colors)
                copy_plan = None
                if args.repack_archive:
                    copy_plan, patches, report["archive"] = archive_iso.plan(stream, patches)
                if args.command == "build":
                    report = publish_iso_copy(stream, args.iso_out, patches, SOURCE_SHA256, ISO_SIZE, report,
                                              args.iso_out.with_name(args.iso_out.name + ".logos.json"),
                                              copy_plan=copy_plan)
        print(json.dumps(report, indent=2))
        if report.get("capacity_failures"):
            raise SystemExit(1)
    except (OSError, ValueError, MemoryError) as error:
        parser.exit(1, f"Native logo workflow failed: {error}\n")


if __name__ == "__main__":
    main()
