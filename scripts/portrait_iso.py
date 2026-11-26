"""Generate roster-linked native portrait masters without modifying the workspace."""
import csv
import struct
from pathlib import Path

from PIL import Image

import player_database
import remaining_texture_workspace
import roster_iso
import texture_iso_workspace
import workspace_images
from roster_stats import PLAYER_BASE, PLAYER_COUNT, PLAYER_STRIDE

ROOT = Path(__file__).resolve().parents[1]
PLAYER_MAP = ROOT / "data" / "roster_build" / "player_map.csv"
HEADSHOTS = ROOT / "assets" / "PS_out"
PORTRAIT_ASSET = "35cb8d72"
WIN = (0, 3, 102, 125)
CROP = (75, 20, 415, 427)


def make_face(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    background = Image.new("RGB", image.size, "white")
    background.paste(image, mask=image.getchannel("A"))
    face = background.crop(CROP).resize((WIN[2] - WIN[0], WIN[3] - WIN[1]), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (128, 128), "white")
    canvas.paste(face, WIN[:2])
    return canvas


def roster_name(payload: bytes, field: int) -> str:
    pointer = struct.unpack_from("<i", payload, field)[0]
    start = field + pointer - 1
    end = start
    while payload[end:end + 2] != b"\0\0":
        end += 2
    return payload[start:end].decode("utf-16le")


def prepare(roster: Path, workspace: Path, player_map: Path = PLAYER_MAP,
            headshots: Path = HEADSHOTS) -> tuple[dict, dict]:
    payload = roster.read_bytes()
    roster_iso.validate_payload(payload)
    manifest = remaining_texture_workspace.load_manifest(workspace)
    portraits = {}
    for row in manifest["sources"]:
        if row["asset_hash"] != PORTRAIT_ASSET:
            continue
        name = row["texture"]
        if name in portraits:
            raise ValueError(f"Duplicate native portrait name {name!r}")
        portraits[name] = row["id"]
    if not portraits:
        raise ValueError("Native texture workspace has no portrait collection")
    with player_map.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"{player_map}: no roster players")
    generated, missing, suppressed, owners = {}, [], [], {}
    placeholder = None
    records, players = set(), set()
    for row in rows:
        proa_id = player_database.player_id(row["proa_id"])
        record, pid = int(row["record"]), int(row["pid"])
        if not 0 <= record < PLAYER_COUNT or record in records or proa_id in players:
            raise ValueError(f"{player_map}: duplicate or invalid player record/ProA ID")
        records.add(record)
        players.add(proa_id)
        offset = PLAYER_BASE + record * PLAYER_STRIDE
        portrait_id = struct.unpack_from("<H", payload, offset + 6)[0]
        if (struct.unpack_from("<H", payload, offset + 4)[0] != pid or portrait_id != pid
                or roster_name(payload, offset + 0x10) != row["first"]
                or roster_name(payload, offset + 0x0C) != row["last"]):
            raise ValueError(f"{player_map}: player {proa_id} does not match the final roster payload")
        if payload[offset + 8] & 2:
            suppressed.append(proa_id)
            continue
        name = f"{portrait_id:04}"
        if name not in portraits:
            raise ValueError(f"Player {proa_id}: native portrait {name} is missing")
        if name in owners:
            raise ValueError(f"Players {owners[name]} and {proa_id} share native portrait {name}")
        owners[name] = proa_id
        source = headshots / f"{proa_id}.png"
        if not source.is_file():
            missing.append(proa_id)
            if placeholder is None:
                options = [item for item in manifest["sources"]
                           if item.get("asset") == "global.iff" and item.get("scene") == "nophoto"
                           and item["texture"] == "nophoto"]
                if len(options) != 1:
                    raise ValueError("Native texture workspace requires one global nophoto master")
                path = texture_iso_workspace.scan(workspace, options)[options[0]["id"]]
                with Image.open(path) as image:
                    placeholder = image.convert("RGBA")
            generated[portraits[name]] = placeholder.copy()
        else:
            generated[portraits[name]] = make_face(source)
    return generated, {"players": len(rows), "generated": len(generated) - len(missing),
                       "placeholders": len(missing),
                       "missing_headshots": missing, "suppressed_portraits": suppressed}


def populate(roster: Path, workspace: Path, player_map: Path = PLAYER_MAP,
             headshots: Path = HEADSHOTS) -> dict:
    images, report = prepare(roster, workspace, player_map, headshots)
    manifest = remaining_texture_workspace.load_manifest(workspace)
    rows = [row for row in manifest["sources"] if row["id"] in images]
    paths = texture_iso_workspace.scan(workspace, rows)
    staged = []
    for row in rows:
        path = paths[row["id"]]
        image = images[row["id"]]
        staged.append((path, workspace_images.image_bytes(path, image)))
    for path, content in staged:
        workspace_images.replace(path, content)
    return report
