"""Preview native ISO workspace edits through PCSX2 texture replacements.

    python scripts/texture_workspace.py sync [--ws texture_workspace_ISO]
    python scripts/texture_workspace.py sync --dry-run

`sync` exact-matches native texture pixels (including stored mip levels) to
PCSX2 dumps and writes only changed native artwork. It does not modify an ISO.
`export` remains available for the old PCSX2 workspace; `sync` no longer reads it.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

import gen_logo_replacements as logos
import gen_replacements as faces
import gen_skin_replacements as skins
import texcluster
import texture_iso_workspace as iso_workspace
import uniform_labels
from texture_catalogue import pixel_digest
from texlib import REPL_DIR, ROOT, dump_files, family, load_rgba
from uniform_lods import skipped

DEFAULT_WS = ROOT / "texture_workspace"
NATIVE_DEFAULT_WS = ROOT / "texture_workspace_ISO"
NATIVE_MANIFESTS = ("_iso_logos.json", "_iso_uniforms.json", "_iso_textures.json")
PREVIEW_STATE = "_pcsx2_preview_state.json"
EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
TOKEN = re.compile(r"__([0-9a-f]{8})(?:\W|$)")

# family -> group for families that are homogeneous
FAMILY_GROUPS = {
    "00001994": "loading_video_tiles", "00002a9b": "crowd_and_referee_sprites",
    "00000d93": "jersey_name_plates", "000011d3": "jersey_name_plates", "00001613": "jersey_name_plates",
    "000015d3": "jersey_name_plates", "00002253": "uniforms", "00002254": "uniforms",
    "00001e13": "uniform_parts", "00001e14": "uniform_parts", "00001e53": "uniform_parts",
    "00001553": "team_icons_small", "00001554": "team_icons_small",
}
SIZE_SUBFOLDER = {"jersey_numbers", "uniforms", "uniform_parts", "jersey_name_plates", "ui_fragments", "other_logos",
                  "head_and_body_skin"}


def token(key):
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")


def sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def managed_keys():
    out = {k: "faces/icons" for k in faces.managed_keys()}
    out.update({k: "team logo" for k in logos.managed_keys()})
    out.update({k: "light-reserve skin" for k in skins.managed_keys()})
    return out


def load_labels():
    """data/texture_labels/labels.csv (key,label,group,sub,...): team label prefix and optional group/sub override per dump key."""
    p = ROOT / "data/texture_labels/labels.csv"
    return {r["key"]: r for r in csv.DictReader(open(p, encoding="utf-8"))} if p.exists() else {}


def catalog(files=None, ws=None):
    """One dict per dump: key, family, w, h, group, sub, label. Known maps first, then family rules, then clusters."""
    files = files or dump_files()
    ws = ws or DEFAULT_WS
    names = {}
    for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8")):
        names[int(r["record"])] = (r["team"], f"{r['first']}_{r['last']}")
    face_of = {}
    for r in csv.DictReader(open(ROOT / "data/texture_map/record_faces.csv")):
        face_of.setdefault(r["key"], int(r["record"]))
    logo_of, sign_of = {}, {}
    for r in logos.logo_matches():
        if r["key"] not in logo_of or float(r["score"]) > float(logo_of[r["key"]]["score"]):
            logo_of[r["key"]] = r
    for r in csv.DictReader(open(logos.SRC, encoding="utf-8")):
        if r["mode"] == "B" and float(r["score"]) >= 0.8:
            sign_of[r["key"]] = r["team"]
    model = json.loads(texcluster.MODEL.read_text())
    cnames = json.loads(texcluster.NAMES.read_text())
    labels = load_labels()
    out = []
    for key, path in sorted(files.items()):
        fam = family(key)
        with Image.open(path) as im:
            w, h = im.size
        group, sub, label = None, "", None
        if key in face_of:
            team, nm = names.get(face_of[key], ("unknown", f"record{face_of[key]}"))
            group, sub, label = "player_faces", team, nm
        elif fam in ("00001dd3", "00001dd4"):
            group, sub, label = "player_faces", "_unmapped", "face"
        elif key in logo_of:
            team = logo_of[key]["team"]
            group, sub, label = "team_logos", team, f"{team}_logo"
        elif fam in FAMILY_GROUPS:
            group = FAMILY_GROUPS[fam]
        elif fam in model:
            group = cnames[fam][texcluster.classify(texcluster.feature(path), fam, model)]
        else:
            group = "ui_fragments"
        lab = labels.get(key, {})
        if lab.get("group"):
            group, sub = lab["group"], lab.get("sub", "")
        if group in SIZE_SUBFOLDER and not (lab.get("group") and lab.get("sub")):
            sub = f"{w}x{h}"
        label = label or f"{group}_{w}x{h}"
        if lab.get("label"):
            label = f"{lab['label']}_{label}"
        if key in sign_of and not lab.get("label"):
            label += f"_has-{sign_of[key]}-logo"
        out.append(dict(key=key, family=fam, w=w, h=h, group=group, sub=sub, label=safe(label)))
    return mark_uniform_roles(out, ws)


def mark_uniform_roles(rows, ws):
    """Uniform role files keep their identity, with clearly labelled teams grouped into subfolders."""
    mp = uniform_labels.load_mapping(ws)
    for r in rows:
        m = mp.get(r["key"])
        if m:
            r["group"], r["sub"] = "uniforms", uniform_labels.team_folder(m["label"]) or ""
            r["label"] = f"{m['role'].upper()}__{m['label']}__{m['size']}"
    return rows


def rel_path(row):
    parts = [row["group"]] + ([row["sub"]] if row["sub"] else [])
    return Path(*parts) / f"{row['label']}__{token(row['key'])}.png"


def scan(ws):
    """token -> newest file in the working folder."""
    found = {}
    for p in ws.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS and not skipped(p.relative_to(ws).parts[:-1]):
            m = TOKEN.search(p.stem + " ")
            if m:
                previous = found.get(m.group(1))
                if previous is not None:
                    keep, drop = (p, previous) if p.stat().st_mtime > previous.stat().st_mtime else (previous, p)
                    print(f"warning: duplicate workspace ID {m.group(1)}: using {keep}, ignoring {drop}")
                    found[m.group(1)] = keep
                else:
                    found[m.group(1)] = p
    return found


def read_manifest(ws):
    mf = ws / "_manifest.csv"
    if not mf.exists():
        return {}
    with mf.open(encoding="utf-8", newline="") as file:
        return {r["token"]: r for r in csv.DictReader(file)}


def export(ws):
    ws.mkdir(parents=True, exist_ok=True)
    files = dump_files()
    managed = managed_keys()
    rows = catalog(files, ws)
    toks = [token(r["key"]) for r in rows]
    assert len(set(toks)) == len(toks), "token collision"
    old, found = read_manifest(ws), scan(ws)
    role_tokens = uniform_labels.role_files(ws)  # ROLE__LABEL__RES__ID files are never renamed or moved by the export
    new, added, moved, dropped, kept = {}, 0, 0, 0, 0
    for r in rows:
        t = token(r["key"])
        if r["key"] in managed:
            p = found.get(t)
            if p and t in old and sha1(p) == old[t]["sha1"]:
                p.unlink()
                dropped += 1
            continue
        want = rel_path(r)
        p = found.get(t)
        if p is not None and t in old:
            osha = old[t]["sha1"]
            if (t not in role_tokens and p == ws / old[t]["relpath"] and p != ws / want
                    and not (ws / want).exists() and sha1(p) == osha):
                (ws / want).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(p, ws / want)
                p, moved = ws / want, moved + 1
            new[t] = dict(old[t], relpath=str(p.relative_to(ws)), group=r["group"])
            kept += 1
            continue
        a = load_rgba(files[r["key"]]).copy()
        a[..., 3] = np.minimum(255, np.round(a[..., 3].astype(np.float32) * 255 / 128)).astype(np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(a, "RGBA").save(buffer, format="PNG")
        original = buffer.getvalue()
        if p is None:
            p = ws / want
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(original)
            added += 1
        else:
            kept += 1
        new[t] = dict(token=t, key=r["key"], group=r["group"], relpath=str(p.relative_to(ws)),
                      w=r["w"], h=r["h"], sha1=hashlib.sha1(original).hexdigest())
    with open(ws / "_manifest.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, ["token", "key", "group", "relpath", "w", "h", "sha1"])
        wr.writeheader()
        wr.writerows(new.values())
    print(f"export: {added} new, {kept} existing, {moved} regrouped, {dropped} removed (now pipeline-managed) -> {ws}")
    for g in sorted({v["group"] for v in new.values()}):
        print(f"  {g}: {sum(v['group'] == g for v in new.values())}")
    fresh = [v["key"] for t, v in new.items() if t not in old and uniform_candidate(v["key"])]
    if fresh:
        print(f"{len(fresh)} new uniform textures - matching them against the existing groups ...")
        if uniform_labels.adopt(ws):
            export(ws)  # refresh groups / paths of the renamed files
    uniform_labels.report(ws)


def uniform_candidate(key):
    return family(key) in uniform_labels.UNIFORM_FAMILIES


def lod_from(img, size):
    """Mip-style downscale of an RGBA image (alpha-weighted so transparent texels do not bleed)."""
    return img.convert("RGBa").resize(size, Image.BOX).convert("RGBA")


def convert_image(image, original_path, mode, has_alpha):
    original = load_rgba(original_path)
    height, width = original.shape[:2]
    image = image.convert("RGBA")
    if not has_alpha:
        image.putalpha(255)
    target_size = (width, height)
    if image.size != target_size:
        if mode == "stretch":
            image = image.convert("RGBa").resize(target_size, Image.LANCZOS).convert("RGBA")
        else:
            scale = (min if mode == "contain" else max)(width / image.width, height / image.height)
            resized = image.convert("RGBa").resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS
            ).convert("RGBA")
            pad = (255, 255, 255, 255) if not has_alpha else (0, 0, 0, 0)
            canvas = Image.new("RGBA", target_size, pad)
            left, top = max(0, (resized.width - width) // 2), max(0, (resized.height - height) // 2)
            right, bottom = left + min(width, resized.width), top + min(height, resized.height)
            crop = resized.crop((left, top, right, bottom))
            canvas.alpha_composite(
                crop,
                (max(0, (width - resized.width) // 2), max(0, (height - resized.height) // 2)),
            )
            image = canvas
    pixels = np.asarray(image).copy()
    pixels[..., 3] = (
        np.round(pixels[..., 3].astype(np.float32) * 128 / 255).astype(np.uint8)
        if has_alpha else original[..., 3]
    )
    return Image.fromarray(pixels, "RGBA")


def read_preview_state(path):
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    files = state.get("files") if isinstance(state, dict) else None
    if (not isinstance(state, dict)
            or state.get("schema") != 1
            or state.get("source_sha256") != iso_workspace.SOURCE_SHA256
            or not isinstance(files, dict)):
        raise ValueError(f"{path}: invalid PCSX2 preview state")
    for key, entry in files.items():
        if (not isinstance(key, str) or not key or Path(key).name != key
                or not isinstance(entry, dict)
                or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", ""))
                or not isinstance(entry.get("source_ids"), list)
                or any(not isinstance(source_id, str) for source_id in entry["source_ids"])):
            raise ValueError(f"{path}: invalid preview state entry for {key!r}")
    return files


def sync(ws, mode, dry, force_regen=False):
    ws = Path(ws)
    iso_workspace.validate_workspace(ws)
    sources = []
    for filename in NATIVE_MANIFESTS:
        manifest_path = ws / filename
        if not manifest_path.is_file():
            raise ValueError(f"{manifest_path}: native texture manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict)
                or manifest.get("schema") != 1
                or manifest.get("source_sha256") != iso_workspace.SOURCE_SHA256
                or not isinstance(manifest.get("sources"), list)):
            raise ValueError(f"{manifest_path}: native texture manifest schema/source mismatch")
        sources.extend(manifest["sources"])
    if not sources:
        raise ValueError(f"{ws}: native texture manifests contain no sources")
    rows_by_id = {}
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("Native texture manifest contains an invalid source row")
        source_id = row.get("id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Native texture manifest contains a source without a valid ID")
        if source_id in rows_by_id:
            raise ValueError(f"Native texture manifests contain duplicate source ID {source_id}")
        if (not row.get("path")
                or not isinstance(row.get("original_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["original_digest"])
                or not isinstance(row.get("original_display_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["original_display_digest"])):
            raise ValueError(f"{source_id}: native source is missing preview metadata")
        levels = row.get("mip_digests") or [row["original_digest"]]
        if not isinstance(levels, list) or not levels or levels[0] != row["original_digest"]:
            raise ValueError(f"{source_id}: native mip digests do not start with the base image digest")
        if any(not isinstance(digest, str) for digest in levels):
            raise ValueError(f"{source_id}: invalid native mip digest")
        rows_by_id[source_id] = row

    found = iso_workspace.scan(ws, sources)
    dumps = dump_files()
    if not dumps:
        raise ValueError("No PCSX2 texture dumps found; dump the textures before preview sync")
    digest_keys = collections.defaultdict(list)
    dump_info = {}
    for key, path in dumps.items():
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            digest = pixel_digest(*rgba.size, rgba.tobytes())
            dump_info[key] = (path, digest, rgba.size)
        digest_keys[digest].append(key)

    candidates = collections.defaultdict(dict)
    for row in sources:
        levels = row.get("mip_digests") or [row["original_digest"]]
        for level, digest in enumerate(levels):
            for key in digest_keys.get(digest, ()):
                previous = candidates[key].get(row["id"])
                if previous is None or level < previous[1]:
                    candidates[key][row["id"]] = (row, level)

    matched_ids = {source_id for matches in candidates.values() for source_id in matches}
    source_state, changed_images = {}, {}
    for source_id in matched_ids:
        row = rows_by_id[source_id]
        with Image.open(found[source_id]) as image:
            has_alpha = image.mode in ("RGBA", "LA", "PA", "RGBa") or "transparency" in image.info
            current = image.convert("RGBA")
            unchanged = iso_workspace.image_digest(current) == row["original_display_digest"]
            if not unchanged:
                changed_images[source_id] = (current.copy(), has_alpha)
        source_state[source_id] = unchanged

    previews, mapping_conflicts = {}, {}
    for key, matches in candidates.items():
        original_path, original_digest, original_size = dump_info[key]
        outputs = []
        for source_id, (row, level) in matches.items():
            if source_state[source_id]:
                outputs.append((original_digest, None))
                continue
            image, has_alpha = changed_images[source_id]
            source_image = lod_from(image, original_size) if level else image
            output = convert_image(source_image, original_path, "stretch" if level else mode, has_alpha)
            outputs.append((iso_workspace.image_digest(output), output))
        signatures = {digest for digest, _ in outputs}
        if len(signatures) != 1:
            mapping_conflicts[key] = sorted(matches)
            continue
        output_digest = signatures.pop()
        if output_digest == original_digest:
            continue
        output_image = next(
            image for digest, image in outputs if digest == output_digest and image is not None
        )
        buffer = io.BytesIO()
        output_image.save(buffer, format="PNG")
        data = buffer.getvalue()
        previews[key] = {
            "data": data,
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_ids": sorted(matches),
        }

    managed = managed_keys()
    managed_skipped = set(previews) & managed.keys()
    for key in managed_skipped:
        previews.pop(key)

    state_path = ws / PREVIEW_STATE
    previous_state = read_preview_state(state_path)
    next_state = {}
    written = removed = unchanged_count = output_conflicts = 0
    for key, preview in sorted(previews.items()):
        target = REPL_DIR / f"{key}.png"
        previous = previous_state.get(key)
        current_hash = sha256(target) if target.is_file() else None
        if previous is None:
            if current_hash is not None:
                if current_hash == preview["sha256"]:
                    unchanged_count += 1
                else:
                    output_conflicts += 1
                    print(f"warning: preserve unowned PCSX2 replacement {target}")
                continue
        elif current_hash is not None and current_hash not in (previous["sha256"], preview["sha256"]):
            output_conflicts += 1
            next_state[key] = previous
            print(f"warning: preserve externally changed PCSX2 replacement {target}")
            continue
        elif current_hash == preview["sha256"] and not force_regen:
            unchanged_count += 1
            next_state[key] = {name: preview[name] for name in ("sha256", "source_ids")}
            continue
        if dry:
            print("write", target)
        else:
            REPL_DIR.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_bytes(preview["data"])
            temporary.replace(target)
        written += 1
        next_state[key] = {name: preview[name] for name in ("sha256", "source_ids")}

    for key, previous in previous_state.items():
        if key in next_state:
            continue
        if key in managed:
            next_state[key] = previous
            continue
        target = REPL_DIR / f"{key}.png"
        if not target.is_file():
            continue
        if sha256(target) != previous["sha256"]:
            output_conflicts += 1
            next_state[key] = previous
            print(f"warning: preserve externally changed stale replacement {target}")
            continue
        if dry:
            print("remove", target)
        else:
            target.unlink()
        removed += 1

    if not dry and next_state != previous_state:
        state = {
            "schema": 1,
            "source_sha256": iso_workspace.SOURCE_SHA256,
            "files": next_state,
        }
        temporary = state_path.with_name(state_path.name + ".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temporary.replace(state_path)

    unmapped = len(sources) - len(matched_ids)
    print(
        f"preview sync: {written} written, {removed} removed, {unchanged_count} unchanged, "
        f"{len(mapping_conflicts)} mapping conflicts, {output_conflicts} replacement conflicts, "
        f"{len(managed_skipped)} pipeline-managed skipped, {unmapped} native masters without exact PCSX2 matches."
    )
    if written or removed:
        print("Press F10 in PCSX2 to reload.")
    return {
        "written": written,
        "removed": removed,
        "unchanged": unchanged_count,
        "mapping_conflicts": mapping_conflicts,
        "replacement_conflicts": output_conflicts,
        "managed_skipped": len(managed_skipped),
        "unmapped": unmapped,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["export", "sync"])
    ap.add_argument("--ws", type=Path, help="workspace directory (defaults depend on command)")
    ap.add_argument("--fit", choices=["stretch", "contain", "cover"], default="stretch",
                    help="how images with a different aspect ratio are fitted (default: stretch)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-regen", action="store_true",
                    help="sync: rewrite already-owned PCSX2 previews even when their bytes are unchanged")
    a = ap.parse_args()
    if a.force_regen and a.cmd != "sync":
        ap.error("--force-regen is only supported by sync")
    if a.cmd == "export":
        export(a.ws or DEFAULT_WS)
    else:
        sync(a.ws or NATIVE_DEFAULT_WS, a.fit, a.dry_run, a.force_regen)


if __name__ == "__main__":
    main()
