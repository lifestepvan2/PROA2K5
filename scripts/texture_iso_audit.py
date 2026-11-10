"""Non-destructive workspace/native-source bridge and batched identification review.

    python scripts\\texture_iso_audit.py --catalogue CACHE.sqlite --out NEW_DIRECTORY

Mappings compare ORIGINAL dump pixels, never the artist's modified pixels. Every
workspace entry, managed target and live replacement receives a row, including
unresolved targets. No artist file, label, sync state, dump or replacement is changed.
"""
import argparse
import collections
import csv
import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageDraw

import texture_workspace as workspace
from texlib import DUMP_DIRS, REPL_DIR, dump_files
from texture_catalogue import database_summary, open_catalogue, pixel_digest
from uniform_lods import skipped

IMAGE_COLUMNS = ("key", "token", "path", "group", "role", "label", "manual_edit", "generated",
                 "replacement_present", "managed", "width", "height", "status", "blocker", "reason", "native_count",
                 "native_ids", "native_assets", "native_names", "native_context",
                 "proposed_group", "label_review", "original_digest", "inherited_from", "candidate_native_ids")


def write_csv(path: Path, columns: tuple | list, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def original_digest(path: Path) -> str:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        return pixel_digest(*rgba.size, rgba.tobytes())


def read_workspace(ws: Path) -> tuple[dict, dict, list[str]]:
    manifest_path = ws / "_manifest.csv"
    if not manifest_path.is_file():
        raise ValueError("Workspace manifest is missing; existing artist files cannot be audited safely")
    with manifest_path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows or not set(("token", "key", "relpath", "sha1", "group")) <= rows[0].keys():
        raise ValueError("Invalid or empty workspace manifest")
    tokens, keys = [row["token"] for row in rows], [row["key"] for row in rows]
    if len(set(tokens)) != len(tokens) or len(set(keys)) != len(keys):
        raise ValueError("Duplicate workspace manifest identities")
    known_tokens = set(tokens)
    found, warnings = {}, []
    for path in sorted(ws.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in workspace.EXTS or skipped(path.relative_to(ws).parts[:-1]):
            continue
        token = workspace.TOKEN.search(path.stem + " ")
        if token:
            found.setdefault(token[1], []).append(path)
    for token, paths in found.items():
        if len(paths) > 1:
            warnings.append(f"Duplicate workspace ID {token}: " + ";".join(str(p.relative_to(ws)) for p in paths))
        if token not in known_tokens:
            warnings.append(f"Artist ID absent from manifest: {token}")
    return {row["key"]: row for row in rows}, found, warnings


def snapshot(ws: Path) -> dict[str, str]:
    result = {}
    for path in ws.rglob("*"):
        if path.is_file() and (path.suffix.lower() in workspace.EXTS or path.name in ("_manifest.csv", "_state.json")):
            result[str(path.relative_to(ws))] = workspace.sha1(path)
    return result


def native_index(connection: sqlite3.Connection) -> tuple[dict, dict]:
    sources = {}
    by_digest = collections.defaultdict(list)
    for row in connection.execute("""
        SELECT t.*,a.name AS asset,a.ownership,i.level,i.digest
        FROM textures t JOIN assets a ON a.hash=t.asset_hash
        LEFT JOIN images i ON i.texture_id=t.id ORDER BY t.id,i.level
    """):
        source = dict(row)
        sources[source["id"]] = source
        if source["digest"]:
            by_digest[source["digest"]].append(source)
    return sources, by_digest


def proposed_group(sources: list[dict]) -> str:
    names = {source["name"] for source in sources}
    owners = [json.loads(source["ownership"]) for source in sources]
    if owners and all(owner["kind"] == "portrait_collection" for owner in owners):
        return "player_faces"
    if owners and all(owner["kind"] == "player_model" for owner in owners) and names <= {"arm", "neck", "face", "hair"}:
        return "head_and_body_skin"
    if names and all(name.endswith("_flipchip_00") for name in names):
        return "team_icons_small"
    if names and names <= {"unif", "short", "pnt", "top", "slv"}:
        return "uniforms"
    if names and names <= {"names", "numbers"}:
        return "jersey_name_plates" if names == {"names"} else "jersey_numbers"
    return ""


def label_review(row: dict, sources: list[dict]) -> str:
    if not sources:
        return ""
    reasons = []
    group = proposed_group(sources)
    if group and row["group"] and row["group"] != group:
        reasons.append(f"native role suggests {group}, not {row['group']}")
    old_label = row["label"] or Path(row["path"]).stem
    labelled_teams = {name for name in workspace.uniform_labels.TEAM_NAMES if old_label.startswith(name)}
    if row["label"]:
        parsed = workspace.uniform_labels.parse_label(row["label"])
        if parsed and parsed["team"] in workspace.uniform_labels.TEAM_NAMES:
            labelled_teams.add(parsed["team"])
    owner_teams = set()
    all_team_owned = bool(sources)
    for source in sources:
        owner = json.loads(source["ownership"])
        if owner["kind"] == "uniform":
            owner_teams.add(owner["team"])
        elif owner["kind"] == "arena":
            owner_teams.update(team["team"] for team in owner["teams"])
        else:
            all_team_owned = False
    if labelled_teams and all_team_owned and not labelled_teams.intersection(owner_teams):
        reasons.append("labelled team differs from every exact native owner")
    if len(owner_teams) > 1:
        reasons.append("image has multiple native team owners; do not infer exclusive attribution")
    if row["label"] and row["role"]:
        expected = {"Jersey": "unif", "Shorts": "short", "WUtorso": "top", "WUsleeves": "slv", "WUlegs": "pnt"}
        parsed = workspace.uniform_labels.parse_label(row["label"])
        if parsed and expected[parsed["item"]] not in {source["name"] for source in sources}:
            reasons.append("uniform item label disagrees with exact native texture names")
    return "; ".join(reasons)


def build_rows(manifest: dict, found: dict, state: dict, files: dict, replacements: dict,
               managed: dict, index: dict) -> list[dict]:
    rows = []
    for key in sorted(manifest.keys() | replacements.keys() | managed.keys()):
        m = manifest.get(key, {})
        paths = found.get(m.get("token", ""), [])
        path = paths[0] if len(paths) == 1 else None
        sha = workspace.sha1(path) if path else ""
        generated = bool(sha and sha == state.get("_workspace_auto", {}).get(key))
        edited = bool(sha and sha != m.get("sha1") and not generated)
        role = workspace.uniform_labels.NAME.fullmatch(path.stem) if path else None
        row = dict.fromkeys(IMAGE_COLUMNS, "")
        row.update(key=key, token=m.get("token", workspace.token(key)),
                   path=str(path) if path else m.get("relpath", ""), group=m.get("group", ""),
                   role=role[1] if role else "", label=role[2] if role else "",
                   manual_edit=int(edited), generated=int(generated),
                   replacement_present=int(key in replacements), managed=managed.get(key, ""))
        row["status"], row["reason"] = "unresolved", ""
        row["blocker"] = "source-not-identified"
        sources = []
        if len(paths) > 1:
            row["blocker"] = "duplicate-workspace-id"
            row["reason"] = "duplicate workspace ID; no newest-file selection during migration"
        elif key in manifest and not path:
            row["blocker"] = "missing-artist-file"
            row["reason"] = "workspace artist file is missing"
        elif key not in files:
            row["blocker"] = "missing-original-dump"
            row["reason"] = "original dump missing; edited/replacement pixels are not source evidence"
        else:
            row["original_digest"] = original_digest(files[key])
            with Image.open(files[key]) as image:
                row["width"], row["height"] = image.size
            sources = index.get(row["original_digest"], [])
            if sources:
                row["status"] = "exact"
                row["blocker"] = ""
                row["reason"] = "dimensions and original PS2-range RGBA match; all native aliases retained"
            else:
                row["reason"] = "no exact decoded native image; inspect packed transfers, scene/set sources or runtime derivation"
                if row["managed"] == "faces/icons" and key.split("-")[-1] in ("00001dd3", "00001dd4"):
                    row["blocker"] = "portrait-source-unproved"
                    row["reason"] = "portrait PID ownership known to generator; native portrait storage/decoder remains unproved"
                elif row["role"]:
                    row["blocker"] = "uniform-transfer-or-inheritance-unproved"
                    row["reason"] = "labelled uniform lacks exact native pixels; packed game uploads/CLUT and the master-child source relation require verification"
                elif row["group"] == "jersey_name_plates":
                    row["blocker"] = "lettering-render-source-unproved"
                    row["reason"] = "no exact native image; distinguish native glyph atlas from runtime-rendered player name"
                elif row["group"] == "loading_video_tiles":
                    row["blocker"] = "video-frame-source-unproved"
                    row["reason"] = "dump classified as video tile; movie/frame source and timing need verification, not a standalone texture guess"
                elif row["managed"] == "team logo":
                    row["blocker"] = "logo-variant-or-scene-transfer-unproved"
                    row["reason"] = "generator-owned logo variant has no exact decoded source; scene/atlas transfer and embedded-sign composition remain unverified"
                elif row["group"] in ("arena_props", "arena_wordmarks", "broadcast_and_sponsors", "courts_and_floors"):
                    row["blocker"] = "scene-image-or-atlas-unproved"
                    row["reason"] = "legacy arena category, not source proof; scene material/atlas pixel location and transfer decoding remain unverified"
        unique = {source["id"]: source for source in sources}
        row.update(native_count=len(unique), native_ids=";".join(sorted(unique)),
                   native_assets=";".join(sorted({s["asset"] for s in sources})),
                   native_names=";".join(sorted({s["name"] for s in sources})),
                   native_context=json.dumps([json.loads(owner) for owner in sorted({s["ownership"] for s in sources})]),
                   proposed_group=proposed_group(sources), label_review=label_review(row, sources))
        if path:
            row["path"] = str(path)
        rows.append(row)
    by_label = collections.defaultdict(list)
    for row in rows:
        if row["label"]:
            by_label[row["label"]].append(row)
    for members in by_label.values():
        masters = [row for row in members if row["role"] == "MASTER"]
        if len(masters) != 1:
            continue
        master = masters[0]
        for row in members:
            if row["role"] in ("COPY", "LOD"):
                row["inherited_from"] = master["key"]
                row["candidate_native_ids"] = master["native_ids"]
                if row["status"] != "exact":
                    row["reason"] += "; workspace label links to master, not independent ISO ownership evidence"
    return rows


def portrait_rows(rows: list[dict], sources: dict) -> list[dict]:
    """Keep the proven portrait bundle separate from model-local face UV images."""
    by_key = {row["key"]: row for row in rows}
    result = []
    for player, keys in workspace.faces.face_keys()[0]:
        pid = int(player["pid"])
        candidates = [s for s in sources.values()
                      if s["asset_hash"] == "35cb8d72" and s["name"] == f"{pid:04}"]
        for key in keys:
            row = by_key.get(key)
            if not row:
                continue
            source = workspace.faces.ROOT / "assets" / "PS_out" / f"{player['proa_id']}.png"
            matched = row["status"] == "exact"
            if not matched and candidates and row["blocker"] == "portrait-source-unproved":
                row["blocker"] = "portrait-pid-dump-conflict"
                row["reason"] = (f"native portrait bundle/PID {pid:04} exists, but pixels differ from the legacy dump; "
                                 "review stale dump/PID ownership before choosing a destination")
                row["candidate_native_ids"] = ";".join(sorted(s["id"] for s in candidates))
                row["label_review"] = f"portrait PID {pid} and legacy dump disagree; confirm intended donor/PID before migration"
            elif matched and row["native_names"] == "nophoto":
                row["label_review"] = "shared nophoto placeholder; choose a unique donor PID or retain the placeholder, not a global replacement"
            result.append({
                "key": key, "pid": pid, "proa_id": player["proa_id"],
                "input": str(source.relative_to(workspace.faces.ROOT)), "input_present": source.is_file(),
                "status": row["status"], "native_ids": row["native_ids"],
                "pid_descriptor_ids": ";".join(sorted(s["id"] for s in candidates)),
                "pid_descriptor_matches": bool({s["id"] for s in candidates}.intersection(row["native_ids"].split(";"))),
                "reason": row["reason"],
            })
    return result


def missing_inputs(managed: dict, replacements: dict) -> list[dict]:
    faces = {}
    for row, keys in workspace.faces.face_keys()[0]:
        for key in keys:
            faces[key] = row["proa_id"]
    result = []
    for key in sorted(managed.keys() - replacements.keys()):
        proa_id = faces.get(key)
        source = workspace.faces.ROOT / "assets" / "PS_out" / f"{proa_id}.png" if proa_id else None
        result.append({"key": key, "owner": managed[key], "proa_id": proa_id or "",
                       "input": str(source.relative_to(workspace.faces.ROOT)) if source else "",
                       "input_present": source.is_file() if source else "",
                       "reason": "headshot input missing" if source and not source.is_file()
                       else "managed output missing; regenerate or explicitly review its disposition"})
    return result


def review_pack(output: Path, rows: list[dict], files: dict, limit: int,
                connection: sqlite3.Connection) -> dict:
    candidates = [row for row in rows if row["label_review"] or
                  (row["status"] == "exact" and row["proposed_group"] and
                   any(word in row["path"].lower() for word in ("unknown", "unmapped", "unsorted", "ui_fragments")))]
    candidates.sort(key=lambda row: (-int(row["blocker"] == "portrait-pid-dump-conflict" or
                                         (row["managed"] == "faces/icons" and row["native_names"] == "nophoto")),
                                     -int(bool(row["manual_edit"] or row["replacement_present"])),
                                     -int(bool(row["label_review"])), row["key"]))
    questions = []
    for index, row in enumerate(candidates):
        questions.append({
            "item_id": row["token"], "batch": 1 + index // 20, "key": row["key"],
            "current_path": row["path"], "native_assets": row["native_assets"],
            "native_names": row["native_names"], "suggested_group": row["proposed_group"],
            "candidate_native_ids": row["candidate_native_ids"],
            "evidence": row["label_review"] or "native names provide context for an unidentified workspace item",
            "question": "Confirm the role/label and intended shared scope. Keep artist files unchanged until a later approved relabel.",
            "decision": "", "target_scope": "", "proposed_label": "", "notes": "",
        })
    columns = list(questions[0]) if questions else [
        "item_id", "batch", "key", "current_path", "native_assets", "native_names",
        "suggested_group", "candidate_native_ids", "evidence", "question", "decision", "target_scope", "proposed_label", "notes"]
    write_csv(output / "review_questions.csv", columns, questions)
    for start in range(0, min(len(candidates), limit), 20):
        page = candidates[start:min(start + 20, limit)]
        sheet = Image.new("RGB", (1000, 5 * 250), "white")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(page):
            x, y = (index % 4) * 250, (index // 4) * 250
            conflict = row["blocker"] == "portrait-pid-dump-conflict"
            thumb_width = 75 if conflict else 115
            source = files.get(row["key"])
            if source:
                with Image.open(source) as image:
                    rgba = image.convert("RGBA")
                    alpha = rgba.getchannel("A").point(lambda value: min(255, round(value * 255 / 128)))
                    rgba.putalpha(alpha)
                    rgba.thumbnail((thumb_width, 150))
                    sheet.paste(rgba, (x + 5, y + 5), rgba)
            artist = Path(row["path"])
            if artist.is_file():
                with Image.open(artist) as image:
                    rgba = image.convert("RGBA")
                    rgba.thumbnail((thumb_width, 150))
                    sheet.paste(rgba, (x + (85 if conflict else 130), y + 5), rgba)
            if conflict:
                candidate_id = row["candidate_native_ids"].split(";")[0]
                candidate = connection.execute("""
                    SELECT p.width,p.height,p.rgba FROM images i JOIN pixels p ON p.digest=i.digest
                    WHERE i.texture_id=? AND i.level=0
                """, (candidate_id,)).fetchone()
                if candidate is None:
                    raise ValueError(f"Portrait review candidate lacks native pixels: {candidate_id}")
                rgba = Image.frombytes("RGBA", (candidate["width"], candidate["height"]),
                                       zlib.decompress(candidate["rgba"]))
                rgba.putalpha(rgba.getchannel("A").point(lambda value: min(255, round(value * 255 / 128))))
                rgba.thumbnail((thumb_width, 150))
                sheet.paste(rgba, (x + 165, y + 5), rgba)
            label = (f"{row['token']}\n{(row['native_names'] or row['label_review'])[:36]}\n"
                     f"{row['proposed_group']}\n{row['native_assets'][:36]}")
            draw.text((x + 5, y + 155), "Dump / Artist / PID native" if conflict else "Original/native    Artist", fill="black")
            draw.text((x + 5, y + 172), label.encode("ascii", "replace").decode(), fill="black")
        sheet.save(output / f"review_batch_{start // 20 + 1:03}.png")
    (output / "review_instructions.txt").write_text(
        "IDENTITY / SHARING REVIEW\n"
        "Each sheet contains up to 20 items. Match the eight-character ID to review_questions.csv.\n"
        "Left: original dump, exactly equal to decoded native pixels. Right: current artist file.\n"
        "EXCEPTION: PID-conflict cards show Dump / Artist / PID native; equality is NOT claimed.\n"
        "These are source-identification previews, NOT encoded ISO quality previews.\n"
        "Use decision: keep-current / accept-role / restrict-scope / needs-investigation.\n"
        "Fill target_scope for shared images and proposed_label only when appropriate.\n"
        "Native aliases are evidence, not permission to patch every consumer.\n"
        "No answer is automatically applied. Labels, IDs, folders and images stay unchanged.\n"
        "Unpictured rows remain in the full question queue. Codec/source blockers are not human questions.\n",
        encoding="utf-8")
    return {"questions": len(questions), "pictured": min(len(candidates), limit),
            "note": "The CSV includes the complete queue; sheets are bounded. Codec/source blockers are machine research, not human identification questions."}


def audit(catalogue_path: Path, ws: Path, output: Path, review_limit: int = 40,
          files: dict | None = None, replacements: dict | None = None,
          managed: dict | None = None) -> dict:
    if review_limit < 0:
        raise ValueError("Review limit cannot be negative")
    if output.exists():
        raise ValueError("Audit directory already exists; choose a new output directory")
    protected = [ws, REPL_DIR, workspace.faces.ROOT / "assets", *DUMP_DIRS]
    files = dump_files() if files is None else files
    replacements = {p.stem: p for p in REPL_DIR.glob("*.png")} if replacements is None else replacements
    for root in protected:
        if output.resolve().is_relative_to(root.resolve()):
            raise ValueError("Audit output must be outside artist/replacement/input directories")
    for path in [*files.values(), *replacements.values()]:
        if path.resolve().is_relative_to(output.resolve()):
            raise ValueError("Audit output contains a source image")
    before = snapshot(ws)
    manifest, found, warnings = read_workspace(ws)
    state_path = ws / "_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    managed = workspace.managed_keys() if managed is None else managed
    with closing(open_catalogue(catalogue_path)) as connection:
        sources, index = native_index(connection)
        rows = build_rows(manifest, found, state, files, replacements, managed, index)
        portraits = portrait_rows(rows, sources) if managed else []
        output.mkdir(parents=True, exist_ok=False)
        write_csv(output / "workspace_mapping.csv", IMAGE_COLUMNS, rows)
        for table in ("assets", "resources", "textures"):
            query = connection.execute(f"SELECT * FROM {table}")
            write_csv(output / f"{table}.csv", [column[0] for column in query.description],
                      [dict(row) for row in query])
        missing = missing_inputs(managed, replacements) if managed else []
        write_csv(output / "missing_managed.csv",
                  ("key", "owner", "proa_id", "input", "input_present", "reason"), missing)
        write_csv(output / "portrait_sources.csv",
                  ("key", "pid", "proa_id", "input", "input_present", "status", "native_ids",
                   "pid_descriptor_ids", "pid_descriptor_matches", "reason"), portraits)
        active = [r for r in rows if r["manual_edit"] or r["replacement_present"] or r["managed"]]
        seeds = [r for r in rows if r["manual_edit"] or r["managed"]]
        write_csv(output / "active_targets.csv", IMAGE_COLUMNS, active)
        write_csv(output / "seed_targets.csv", IMAGE_COLUMNS, seeds)
        summary = {
            "catalogue": database_summary(connection), "workspace_entries": len(manifest),
            "workspace_mapping_rows": len(rows), "replacement_pngs": len(replacements),
            "managed_keys": len(managed), "missing_managed": len(missing),
            "portrait_keys": len(portraits),
            "portrait_pid_exact": sum(row["pid_descriptor_matches"] for row in portraits),
            "manual_sources": sum(row["manual_edit"] for row in rows),
            "generated_workspace_images": sum(row["generated"] for row in rows),
            "all_mapping_status": dict(collections.Counter(row["status"] for row in rows)),
            "active_targets": len(active),
            "seed_targets": len(seeds),
            "active_mapping_status": dict(collections.Counter(row["status"] for row in active)),
            "active_blockers": dict(collections.Counter(row["blocker"] for row in active if row["blocker"])),
            "label_review_items": sum(bool(row["label_review"]) for row in rows),
            "warnings": warnings, "review": review_pack(output, rows, files, review_limit, connection),
            "workspace_unchanged": before == snapshot(ws),
            "scope": "Inspection only. Exact pixels prove content aliases, not exclusive ownership or safe patch fan-out.",
        }
        if not summary["workspace_unchanged"]:
            raise ValueError("Workspace changed while auditing; discard this report and rerun")
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--ws", type=Path, default=workspace.DEFAULT_WS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review-limit", type=int, default=40)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.catalogue, args.ws, args.out, args.review_limit), indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Native texture audit failed: {error}\n")


if __name__ == "__main__":
    main()
