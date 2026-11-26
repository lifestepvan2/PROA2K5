"""Prepare roster-bound, model-local complexion patches for one combined ISO build.

Skin Tone 0/blank preserves automatic casting; 1..6 select lightest..darkest.
The generated plan is a recipe, not a second ISO. Compilation verifies the current
roster, pristine assets and unchanged geometry/alpha. Fixed spans are preserved
unless archive repacking is explicitly selected throughout the season pipeline.
"""
import base64
import csv
import hashlib
import io
import json
import os
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image
from skimage import color

from inventory_lettering_iso import asset_hash
from patch_lettering_iso import digest
from patch_preview_lettering_iso import SOURCE_SHA256
from player_database import field_value
from player_texture_iso import (player_asset_name, read_archive, read_asset, replace_texture, replace_video,
                                 texture_resource)
from face_embed import TEX_CROP
from txtr_match import SWZ

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "data" / "face_match" / "skin_tone_plan.json"
PLAYER_MAP = ROOT / "data" / "roster_build" / "player_map.csv"
P_SKIN = 0x69
SIGMA = (22, 10, 10)


def tone_value(row):
    return field_value("Skin Tone", row.get("skin_tone") or 0)


def signature(rows):
    result, ids, pids = [], set(), {}
    for row in rows:
        proa_id, pid = str(row["proa_id"]), int(row.get("override_pid") or row["pid"])
        tone = tone_value(row)
        if proa_id in ids:
            raise ValueError(f"Duplicate player {proa_id} in skin-tone roster")
        ids.add(proa_id)
        if pid in pids and (tone or pids[pid][1]):
            raise ValueError(f"Skin Tone requires a unique PID: {proa_id} and {pids[pid][0]} share {pid}")
        pids[pid] = (proa_id, tone)
        result.append({"proa_id": proa_id, "pid": pid, "skin_tone": tone})
    return sorted(result, key=lambda row: row["proa_id"])


def read_rows(path=PLAYER_MAP):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def workbook_requests(path):
    import openpyxl
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    requested = []
    try:
        for sheet in workbook:
            if sheet.title.startswith("_"):
                continue
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows)
            if "Skin Tone" not in headers:
                continue
            for values in rows:
                row = dict(zip(headers, values))
                if row.get("ProA ID") and field_value("Skin Tone", row.get("Skin Tone") or 0):
                    requested.append(str(row["ProA ID"]))
    finally:
        workbook.close()
    return requested


class Assets:
    def __init__(self, stream, verify_hash=True):
        self.stream = stream
        self.entries = read_archive(stream, verify_hash)

    @cache
    def asset(self, pid, side):
        return read_asset(self.stream, self.entries, player_asset_name(pid, side))

    @cache
    def resource(self, pid, side, part):
        return texture_resource(self.asset(pid, side)[1], part)


def rgb_of(video, width, height):
    if len(video) != width * height + 1024:
        raise ValueError("Invalid indexed skin texture")
    palette = np.frombuffer(video[-1024:], dtype=np.uint8).reshape(256, 4)
    indices = np.frombuffer(video[:width * height], dtype=np.uint8).reshape(height, width)
    return palette[SWZ[indices], :3]


def skin_lab(rgb, box=None):
    lab = color.rgb2lab(np.asarray(rgb, dtype=float) / 255)
    if box is None:
        height, width = lab.shape[:2]
        box = (0, 0, width, height)
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    patch = lab[y0 + int(.35 * height):y0 + int(.65 * height),
                x0 + int(.3 * width):x0 + int(.7 * width)]
    return np.median(patch.reshape(-1, 3), axis=0)


def recolour_face_video(video, target_lab):
    """Keep face indices/alpha; shift only skin-like palette entries in CIE Lab."""
    rgb = rgb_of(video, 256, 256)
    source = skin_lab(rgb, TEX_CROP)
    palette = np.frombuffer(video[-1024:], dtype=np.uint8).reshape(256, 4).copy()
    lab = color.rgb2lab(palette[None, :, :3].astype(float) / 255)[0]
    distance = np.sqrt((((lab - source) / np.array(SIGMA)) ** 2).sum(axis=1))
    weight = np.clip(1.8 - distance, 0, 1)
    shifted = lab + weight[:, None] * (np.asarray(target_lab) - source)
    shifted[:, 0] = np.clip(shifted[:, 0], 0, 100)
    palette[:, :3] = np.rint(color.lab2rgb(shifted[None, :, :])[0] * 255).astype(np.uint8)
    return video[:-1024] + palette.tobytes()


def donor_candidates(assets, defaults, keys=None):
    """Rank native donor textures by their shared image content."""
    tones = {}
    for row in defaults:
        if row["team_slot"] and int(row["team_slot"]) < 39:
            record = bytes.fromhex(row["hex"])
            tones.setdefault(int.from_bytes(record[4:6], "little"), record[P_SKIN])
    groups = {}
    for pid, leg in sorted(tones.items()):
        if not all(asset_hash(player_asset_name(pid, side)) in assets.entries for side in ("h", "a")):
            continue
        for part in ("arm", "neck"):
            _, _, decoded, system, _ = assets.resource(pid, "h", part)
            image_hash = digest(decoded[system:])
            groups.setdefault((leg, part), {}).setdefault(image_hash, []).append(pid)
    return {
        group: [min(pids) for pids in sorted(images.values(), key=lambda pids: (-len(pids), min(pids)))]
        for group, images in groups.items()
    }


def _choose_donor(assets, target, candidates, part, leg, *, repack_archive=False):
    failures = []
    for donor in candidates.get((leg, part), []):
        try:
            for side in ("h", "a"):
                replace_texture(assets.asset(target, side)[1], assets.asset(donor, side)[1], part,
                                repack_archive=repack_archive)
            return donor
        except ValueError as error:
            failures.append(f"{donor}: {error}")
    detail = "; ".join(failures[:3]) or "no native donors available"
    advice = "" if repack_archive else " Retry the ISO pipeline with --repack-archive to allow lossless resource growth."
    raise ValueError(f"PID {target}: no compatible {part} donor for leg tone {leg}: {detail}.{advice}")


def load_candidates(assets, defaults=None, keys=None):
    if defaults is None:
        with (ROOT / "data" / "nba_defaults" / "players_unknown.csv").open(encoding="utf-8") as file:
            defaults = list(csv.DictReader(file))
    return donor_candidates(assets, defaults, keys)


def create_plan(stream, rows, defaults=None, keys=None, *, repack_archive=False):
    roster = signature(rows)
    plan = {"schema": 1, "source_sha256": SOURCE_SHA256, "roster": roster, "players": [],
            "repack_archive": repack_archive}
    requested = [row for row in roster if row["skin_tone"]]
    if not requested:
        return plan
    assets = Assets(stream)
    candidates = load_candidates(assets, defaults, keys)
    for row in requested:
        pid, leg = row["pid"], 6 - row["skin_tone"]
        arm = _choose_donor(assets, pid, candidates, "arm", leg, repack_archive=repack_archive)
        neck = _choose_donor(assets, pid, candidates, "neck", leg, repack_archive=repack_archive)
        recipes = []
        for side in ("h", "a"):
            _, _, decoded, system, _ = assets.resource(neck, side, "neck")
            target_lab = skin_lab(rgb_of(decoded[system:], 128, 64))
            _, _, face, face_system, _ = assets.resource(pid, side, "face")
            video = recolour_face_video(face[face_system:], target_lab)
            try:
                replace_video(assets.asset(pid, side)[1], "face", video, repack_archive=repack_archive)
            except ValueError as error:
                raise ValueError(f"{row['proa_id']} PID {pid} {side}: face recolour cannot fit: {error}") from error
            recipes.append({
                "side": side, "source_asset_sha256": digest(assets.asset(pid, side)[1]),
                "face_palette_hex": video[-1024:].hex(),
                "target_lab": target_lab.tolist(),
            })
        plan["players"].append({**row, "leg_byte": leg, "arm_donor": arm, "neck_donor": neck, "assets": recipes})
    compile_plan(stream, plan, rows, assets, candidates, repack_archive=repack_archive)
    return plan


def validate_roster(plan, rows):
    if (plan.get("schema") != 1 or plan.get("source_sha256") != SOURCE_SHA256
            or plan.get("roster") != signature(rows)):
        raise ValueError("Skin-tone plan is stale or incompatible; rerun face_match.py --iso-source PRISTINE.iso")
    if type(plan.get("repack_archive", False)) is not bool:
        raise ValueError("Invalid skin-tone archive storage mode")
    requested = {row["proa_id"]: row for row in plan["roster"] if row["skin_tone"]}
    players = plan.get("players")
    if (not isinstance(players, list) or len(players) != len(requested)
            or {row["proa_id"] for row in players} != set(requested)):
        raise ValueError("Skin-tone plan does not cover every requested player exactly once")
    for row in players:
        expected = requested[row["proa_id"]]
        if any(row[key] != expected[key] for key in ("pid", "skin_tone")) or row["leg_byte"] != 6 - row["skin_tone"]:
            raise ValueError("Skin-tone plan player or leg byte mismatch")
    return players


def compile_plan(stream, plan, rows, assets=None, candidates=None, *, repack_archive=False, texture_edits=None):
    players = validate_roster(plan, rows)
    if not players:
        return [], []
    if plan.get("repack_archive", False) and not repack_archive:
        raise ValueError("Skin-tone plan requires --repack-archive for the combined ISO build")
    assets = assets or Assets(stream)
    candidates = load_candidates(assets) if candidates is None else candidates
    patches, reports = [], []
    for row in players:
        pid = row["pid"]
        for part in ("arm", "neck"):
            if row[f"{part}_donor"] not in candidates.get((row["leg_byte"], part), []):
                raise ValueError(f"Skin-tone {part} donor is outside the requested bucket or conflicts with legacy PNGs")
        if len(row["assets"]) != 2 or {recipe["side"] for recipe in row["assets"]} != {"h", "a"}:
            raise ValueError("Skin-tone plan requires both home and away assets")
        for recipe in row["assets"]:
            side = recipe["side"]
            offset, original = assets.asset(pid, side)
            if digest(original) != recipe["source_asset_sha256"]:
                raise ValueError(f"Skin-tone source changed: {player_asset_name(pid, side)}")
            patched, changes = original, []
            for part in ("arm", "neck"):
                if texture_edits is None:
                    patched, report = replace_texture(patched, assets.asset(row[f"{part}_donor"], side)[1], part,
                                                       repack_archive=repack_archive)
                else:
                    _, _, donor, donor_system, _ = assets.resource(row[f"{part}_donor"], side, part)
                    report = decoded_intent(assets, pid, side, part, donor[donor_system:], texture_edits)
                report["source_chunk_offset"] = assets.resource(pid, side, part)[0]
                changes.append(report)
            _, _, decoded, system, _ = assets.resource(pid, side, "face")
            palette = bytes.fromhex(recipe["face_palette_hex"])
            if len(palette) != 1024 or palette[3::4] != decoded[-1021::4]:
                raise ValueError("Skin-tone face palette must preserve all original alpha bytes")
            video = decoded[system:-1024] + palette
            # A saved recipe must match the specified donor, not arbitrary supplied RGB.
            _, _, neck, neck_system, _ = assets.resource(row["neck_donor"], side, "neck")
            target_lab = skin_lab(rgb_of(neck[neck_system:], 128, 64))
            if video != recolour_face_video(decoded[system:], target_lab):
                raise ValueError("Skin-tone face palette differs from its donor-derived recolour")
            if texture_edits is None:
                patched, report = replace_video(patched, "face", video, repack_archive=repack_archive)
            else:
                report = decoded_intent(assets, pid, side, "face", video, texture_edits)
            report["source_chunk_offset"] = assets.resource(pid, side, "face")[0]
            changes.append(report)
            if texture_edits is None and patched != original:
                patches.append((offset, original, patched))
            reports.append({
                "proa_id": row["proa_id"], "pid": pid, "skin_tone": row["skin_tone"],
                "leg_byte": row["leg_byte"], "arm_donor": row["arm_donor"], "neck_donor": row["neck_donor"],
                "asset": player_asset_name(pid, side), "offset": offset, "size": len(original),
                "new_size": len(patched) if texture_edits is None else None, "repack_archive": repack_archive,
                "original_sha256": digest(original),
                "patched_sha256": digest(patched) if texture_edits is None else None, "resources": changes,
                "composition": "asset-patch" if texture_edits is None else "decoded-resource-intents",
            })
    return patches, reports


def decoded_intent(assets, pid, side, part, video, edits):
    chunk, body, original, system, scratch = assets.resource(pid, side, part)
    if len(video) != len(original) - system:
        raise ValueError(f"PID {pid}: incompatible {part} decoded intent")
    target = original[:system] + video
    if target != original:
        offset = assets.asset(pid, side)[0] + chunk + 32
        edits.append((offset, body, original, target, scratch,
                      {"asset": player_asset_name(pid, side), "compressed": True, "modifier": "skin_tones", "part": part}))
    return {"part": part, "source_chunk_offset": chunk, "decoded_sha256": digest(target),
            "composition": "decoded-resource-intent"}


def save_plan(path, plan):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    created = False
    try:
        with temporary.open("x", encoding="utf-8") as file:
            created = True
            json.dump(plan, file, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if created and temporary.exists():
            temporary.unlink()


def load_patches(stream, path, rows=None, *, repack_archive=False, texture_edits=None):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    return compile_plan(stream, plan, read_rows() if rows is None else rows, repack_archive=repack_archive,
                        texture_edits=texture_edits)


def populate_workspace(stream, workspace, plan_path=PLAN):
    """Write all roster-requested complexion textures into their native masters."""
    import remaining_texture_workspace
    import texture_iso_workspace as native
    from native_texture import display
    from texture_catalogue import texture_images

    edits = []
    _, reports = load_patches(stream, plan_path, repack_archive=True, texture_edits=edits)
    intents = {offset: (body, target) for offset, body, _, target, _, _ in edits}
    sources = remaining_texture_workspace.load_manifest(workspace)["sources"]
    lookup = {(row["asset"], row["texture"], row["iso_offset"] + row["chunk_offset"] + 32): row
              for row in sources}
    selected = {}
    for report in reports:
        for resource in report["resources"]:
            offset = report["offset"] + resource["source_chunk_offset"] + 32
            key = (report["asset"], resource["part"], offset)
            if key not in lookup:
                raise ValueError(f"No native master for complexion texture {key}")
            row = lookup[key]
            body, original = native.source_bytes(stream, row)
            if offset in intents:
                expected, target = intents[offset]
                if expected != body:
                    raise ValueError(f"{row['id']}: complexion source differs from workspace manifest")
            else:
                target = original
            images, _, _, _ = texture_images(target, row["system"], row["video"],
                                               row["descriptor"], row["descriptor_offsets"])
            selected[row["id"]] = display(images[0])
    update_generated_masters(workspace, sources, selected)
    return {"masters": len(selected), "players": len(reports) // 2}


def update_generated_masters(workspace, sources, images):
    """Preserve pre-automation art and restore it when the generated edit is removed."""
    import texture_iso_workspace as native
    import workspace_images

    state_path = workspace / "_generated_skin.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"schema": 1, "masters": {}}
    if state.get("schema") != 1 or not isinstance(state.get("masters"), dict):
        raise ValueError(f"{state_path}: invalid generated skin state")
    known = {row["id"]: row for row in sources}
    if (set(state["masters"]) | set(images)) - known.keys():
        raise ValueError("Generated skin state references unknown native masters")
    rows = [known[token] for token in set(state["masters"]) | set(images)]
    paths = native.scan(workspace, rows, require_all=False)
    missing = set(images) - paths.keys()
    if missing:
        raise ValueError(f"Missing generated skin masters: {', '.join(sorted(missing))}")
    staged = []
    for token, path in paths.items():
        current = path.read_bytes()
        current_hash = hashlib.sha256(current).hexdigest()
        previous = state["masters"].get(token)
        if previous is not None:
            if not isinstance(previous, dict) or not isinstance(previous.get("generated"), list):
                raise ValueError(f"{state_path}: invalid state for {token}")
            backup = base64.b64decode(previous["backup"], validate=True)
            hashes = previous["generated"]
        else:
            backup, hashes = current, []
        if token in images:
            if current_hash not in hashes:
                backup = current
            output = workspace_images.image_bytes(path, images[token])
            output_hash = hashlib.sha256(output).hexdigest()
            hashes = sorted(set(hashes) | {output_hash})
            state["masters"][token] = {"backup": base64.b64encode(backup).decode("ascii"),
                                       "generated": hashes}
            if output != current:
                staged.append((path, output))
        elif current_hash in hashes:
            with Image.open(io.BytesIO(backup)) as image:
                expected = Image.registered_extensions().get(path.suffix.lower())
                output = backup if image.format == expected else workspace_images.image_bytes(path, image)
            if output != current:
                staged.append((path, output))
    state_bytes = (json.dumps(state, sort_keys=True, indent=2) + "\n").encode("utf-8")
    workspace_images.replace(state_path, state_bytes)
    for path, content in staged:
        workspace_images.replace(path, content)
