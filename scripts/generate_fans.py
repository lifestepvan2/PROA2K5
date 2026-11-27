"""Generate crowd clothing review copies, never editing live texture masters.

    python scripts\\generate_fans.py --020

Requires team.colorprimary and colorsecondary in the selected native team palette. Each invocation
writes a new folder under texture_auto/fans, using the live masters' filenames.
The crowd jersey uses the away uniform over white; _alt uses home over primary.
Sweatshirts use primary fabric. Generic shirts retain their art, with team-logo
caps alternating between primary and dark grey in alphabetical variant order.
Varsity uses primary/secondary over home; _alt uses dark grey/primary over away.
Its pooled-PPG leader's number uses each uniform's numbers.fill, without outlines.
Signs use primary with a logo, or _alt with contrasting text and team nickname.
"""
import argparse
import csv
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import openpyxl
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

import player_database
import team_palettes
import texture_iso_workspace as native
import uniform_iso_workspace as uniforms
from lettering_colours import parse_hex
from propagate_logos import LOGOS, LOGO_ID0, full_logo
from texlib import proa_slots

TEMPLATE = native.ROOT / "texture_templates" / "fan1_tmpl.png"
JERSEY_TEMPLATE = native.ROOT / "texture_templates" / "fan_jersey_undershirt.png"
SWEATSHIRT_TEMPLATE = native.ROOT / "texture_templates" / "fan_sweatshirt_tmpl.png"
VARSITY_TEMPLATE = native.ROOT / "texture_templates" / "fan_varsity_tmpl.png"
VARSITY_ACCENTS = native.ROOT / "texture_templates" / "fan_varsity_accents.png"
OUTPUT = native.ROOT / "texture_auto" / "fans"
SIZE = (256, 128)
DARK_GREY = (48, 48, 48)
SHIRT_REGIONS = ((0, 0, 158, 128), (158, 74, 256, 128))
CAP_REGION = (192, 0, 256, 50)
LOGO_BOXES = ((56, 30, 106, 79), (206, 6, 246, 43))
# Player-atlas panel bounds, source cutout depth, crowd cutout depth.
JERSEY_PANELS = ((0, 166, 76, 26), (166, 256, 128, 60),
                 (256, 422, 31, 9), (422, 512, 128, 60))
VARSITY_OPENING = (67, 22, 89, 99)
VARSITY_LOGO = (96, 33, 125, 54)


def team_info(index: int, path: Path = native.ROOT / "data" / "proa_teams.csv") -> tuple[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not 0 <= index < len(rows) or not rows[index].get("sheet") or not rows[index].get("nickname"):
        raise ValueError(f"{path}: missing team sheet/nickname for ProA index {index}")
    return rows[index]["sheet"], rows[index]["nickname"]


def scorer(sheet: str, roster: Path = native.ROOT / "proa_scraped.xlsx",
           stats_path: Path = native.ROOT / "data" / "proa_stats.json") -> tuple[str, str, float]:
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats.get("schema_version") != 2 or not isinstance(stats.get("players"), dict):
        raise ValueError(f"{stats_path}: expected schema 2 player stats")
    book = openpyxl.load_workbook(roster, read_only=True, data_only=True)
    candidates = []
    try:
        if sheet not in book.sheetnames:
            raise ValueError(f"{roster}: missing team sheet {sheet!r}")
        rows = book[sheet].iter_rows(values_only=True)
        header = next(rows, ())
        required = {"First Name", "Last Name", "ProA ID", "Jersey Number"}
        if not required.issubset(header):
            raise ValueError(f"{roster}: {sheet} requires columns {sorted(required)}")
        for values in rows:
            if not any(value is not None for value in values):
                continue
            row = dict(zip(header, values))
            pid = player_database.player_id(row["ProA ID"])
            entry = stats["players"].get(str(pid))
            ppg = entry.get("points_avg") if isinstance(entry, dict) else None
            if (isinstance(ppg, bool) or not isinstance(ppg, (int, float))
                    or not math.isfinite(ppg) or ppg < 0):
                raise ValueError(f"{sheet}: player {pid} has missing/invalid pooled points_avg")
            candidates.append((float(ppg), pid, row))
    finally:
        book.close()
    if not candidates:
        raise ValueError(f"{roster}: no players for {sheet}")
    ppg, _, row = min(candidates, key=lambda item: (-item[0], item[1]))
    number = player_database.field_value("Jersey Number", row["Jersey Number"])
    name = f"{row['First Name']} {row['Last Name']}"
    return name, str(number), ppg


def text_layer(text: str, size: tuple[int, int], colour: tuple[int, int, int]) -> Image.Image:
    if not text.strip() or not text.isprintable():
        raise ValueError("Fan lettering requires nonempty printable text")
    font = ImageFont.load_default(size=96)
    bounds = font.getbbox(text, stroke_width=2)
    mask = Image.new("L", (bounds[2] - bounds[0], bounds[3] - bounds[1]))
    ImageDraw.Draw(mask).text((-bounds[0], -bounds[1]), text, font=font,
                              fill=255, stroke_width=2, stroke_fill=255)
    mask = ImageOps.contain(mask, size, Image.Resampling.LANCZOS)
    result = Image.new("RGBA", size, (*colour, 0))
    result.paste(Image.new("RGBA", mask.size, (*colour, 255)),
                 ((size[0] - mask.width) // 2, (size[1] - mask.height) // 2), mask)
    return result


def contrast_colour(colour: tuple[int, int, int]) -> tuple[int, int, int]:
    rgb = np.array(colour, dtype=float) / 255
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = float(linear @ np.array([0.2126, 0.7152, 0.0722]))
    return (0, 0, 0) if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else (255, 255, 255)


def render_sign(source: Image.Image, logo: Path, primary: tuple[int, int, int],
                nickname: str | None = None) -> Image.Image:
    if source.size != (128, 128):
        raise ValueError("Crowd sign atlas must be (128, 128)")
    result = Image.new("RGBA", source.size, (*primary, 255))
    if nickname is None:
        result.alpha_composite(full_logo(logo, (108, 108)), (10, 10))
    else:
        colour = contrast_colour(primary)
        result.alpha_composite(text_layer("Auf geht's", (116, 40), colour), (6, 16))
        result.alpha_composite(text_layer(nickname, (116, 44), colour), (6, 68))
    result.putalpha(source.convert("RGBA").getchannel("A"))
    return result


def render_varsity(source: Image.Image, jersey: Image.Image, template: Image.Image,
                   accents: Image.Image, logo: Path, base: tuple[int, int, int],
                   trim: tuple[int, int, int], number: str,
                   number_fill: tuple[int, int, int]) -> Image.Image:
    if any(image.size != SIZE for image in (source, template, accents)):
        raise ValueError(f"Varsity atlas and templates must all be {SIZE}")
    if jersey.width != 2 * jersey.height:
        raise ValueError("Player jersey atlas must have a 2:1 aspect ratio")
    cloth = shaded_cloth(template, base)
    cloth.paste(shaded_cloth(template, trim), (0, 0), accents.convert("L"))
    result = source.convert("RGBA")
    result.paste(cloth, (0, 0), template.getchannel("A"))
    # Register the player front's centre (86) and neckline (76) to the jacket.
    atlas = jersey.convert("RGBa").resize((512, 256), Image.Resampling.LANCZOS)
    scale_y = (256 - 76) / (128 - 26)
    front = atlas.transform((158, 128), Image.Transform.AFFINE,
                            (166 / 158, 0, 86 - 79 * 166 / 158,
                             0, scale_y, 76 - 26 * scale_y),
                            Image.Resampling.BICUBIC).convert("RGBA")
    front.alpha_composite(text_layer(number, (14, 16), number_fill), (72, 59))
    body = Image.new("RGBA", SIZE)
    body.paste(front, (0, 0))
    opening = Image.new("L", SIZE)
    opening.paste(ImageChops.invert(template.getchannel("A")).crop(VARSITY_OPENING),
                  VARSITY_OPENING)
    result.paste(body, (0, 0), opening)
    left, top, right, bottom = VARSITY_LOGO
    result.alpha_composite(full_logo(logo, (right - left, bottom - top)), (left, top))
    result.putalpha(source.convert("RGBA").getchannel("A"))
    return result


def shaded_cloth(template: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    grey = np.asarray(template.convert("L"), dtype=np.float32)
    median = float(np.median(grey[:, :158]))
    if median <= 0:
        raise ValueError("Fabric template has no usable cloth brightness")
    shade = grey / median - 1
    # Black/white normal-blend shading stays visible on dark and light fabrics.
    strength = np.where(shade < 0, -shade, shade * 0.2)
    overlay = np.empty((SIZE[1], SIZE[0], 4), dtype=np.uint8)
    overlay[:, :, :3] = np.where(shade[:, :, None] < 0, 0, 255)
    overlay[:, :, 3] = np.rint(np.clip(strength, 0, 1) * 255).astype(np.uint8)
    cloth = Image.new("RGBA", SIZE, (*colour, 255))
    cloth.alpha_composite(Image.fromarray(overlay))
    return cloth


def render_cap(source: Image.Image, logo: Path,
               colour: tuple[int, int, int]) -> Image.Image:
    if source.size != SIZE:
        raise ValueError(f"Crowd cap atlas must be {SIZE}")
    result = source.convert("RGBA")
    result.paste((*colour, 255), CAP_REGION)
    left, top, right, bottom = LOGO_BOXES[1]
    result.alpha_composite(full_logo(logo, (right - left, bottom - top)), (left, top))
    result.putalpha(source.convert("RGBA").getchannel("A"))
    return result


def render(source: Image.Image, template: Image.Image, logo: Path,
           primary: tuple[int, int, int]) -> Image.Image:
    if source.size != SIZE or template.size != SIZE:
        raise ValueError(f"Crowd T-shirt and fabric template must both be {SIZE}")
    result = source.convert("RGBA")
    cloth = shaded_cloth(template, primary)
    for box in SHIRT_REGIONS:
        result.paste(cloth.crop(box), box)
    left, top, right, bottom = LOGO_BOXES[0]
    result.alpha_composite(full_logo(logo, (right - left, bottom - top)), (left, top))
    result.putalpha(source.convert("RGBA").getchannel("A"))
    return render_cap(result, logo, primary)


def render_sweatshirt(source: Image.Image, template: Image.Image, logo: Path,
                      primary: tuple[int, int, int]) -> Image.Image:
    if source.size != SIZE or template.size != SIZE:
        raise ValueError(f"Crowd sweatshirt and fabric template must both be {SIZE}")
    result = shaded_cloth(template, primary)
    left, top, right, bottom = LOGO_BOXES[0]
    result.alpha_composite(full_logo(logo, (right - left, bottom - top)), (left, top))
    result.putalpha(source.convert("RGBA").getchannel("A"))
    return result


def render_jersey(source: Image.Image, jersey: Image.Image, template: Image.Image,
                  undershirt: tuple[int, int, int]) -> Image.Image:
    if source.size != SIZE or template.size != SIZE:
        raise ValueError(f"Crowd jersey and undershirt template must both be {SIZE}")
    if jersey.width != 2 * jersey.height:
        raise ValueError("Player jersey atlas must have a 2:1 aspect ratio")
    mesh = []
    for left, right, source_depth, target_depth in JERSEY_PANELS:
        top = source_depth - target_depth * (256 - source_depth) / (128 - target_depth)
        mesh.append(((left, 0, right, 128),
                     (left, top, left, 256, right, 256, right, top)))
    # Keep each panel affine so sponsor art does not bend around the neckline.
    atlas = jersey.convert("RGBa").resize((512, 256), Image.Resampling.LANCZOS)
    body = atlas.transform((512, 128), Image.Transform.MESH, mesh, Image.Resampling.BICUBIC)
    body = body.resize((192, 128), Image.Resampling.LANCZOS).convert("RGBA")
    result = Image.new("RGBA", SIZE)
    result.paste(ImageChops.offset(body, 64, 0), (0, 0))
    grey = np.asarray(template.convert("L"), dtype=np.float32)
    tinted = np.rint(grey[:, :, None] / 255 * np.array(undershirt)).astype(np.uint8)
    overlay = Image.fromarray(tinted).convert("RGBA")
    overlay.putalpha(template.convert("RGBA").getchannel("A"))
    result.alpha_composite(overlay)
    result.putalpha(source.convert("RGBA").getchannel("A"))
    return result


def master(sources: list[dict], slot: int, texture: str, surface: str,
           variant: str | None = None) -> dict:
    rows = [row for row in sources
            if row["slot"] == slot and row["surface"] == surface and row["texture"] == texture
            and not row.get("warmup", False) and (variant is None or row["variant"] == variant)]
    label = " ".join(part for part in (surface, variant, texture) if part)
    if len(rows) != 1 or not rows[0]["editable"]:
        raise ValueError(f"Slot {slot:03}: expected exactly one editable {label} master")
    expected = (128, 128) if surface == "crowd" and texture == "crowdsign" else (
        SIZE if surface == "crowd" else (512, 256))
    if (rows[0]["width"], rows[0]["height"]) != expected:
        raise ValueError(f"Slot {slot:03}: unsupported {label} dimensions")
    return rows[0]


def generate(slot: int, *, workspace: Path = native.DEFAULT_WS, output_root: Path = OUTPUT,
             template_path: Path = TEMPLATE, logo_dir: Path = LOGOS,
             jersey_template_path: Path = JERSEY_TEMPLATE,
             sweatshirt_template_path: Path = SWEATSHIRT_TEMPLATE,
             varsity_template_path: Path = VARSITY_TEMPLATE,
             varsity_accents_path: Path = VARSITY_ACCENTS) -> Path:
    team_palettes.relative(slot)
    native.validate_workspace(workspace)
    if output_root.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("Review output must be outside the live workspace")
    slots = proa_slots()
    if slot not in slots:
        raise ValueError(f"Slot {slot:03} has no ProA team assignment")
    palette = team_palettes.load(workspace / "team_palettes", slot)
    colours = palette["team"]
    for field in ("colorprimary", "colorsecondary"):
        if field not in colours:
            raise ValueError(f"Add team.{field} to "
                             f"{workspace / 'team_palettes' / team_palettes.relative(slot)}")
    primary = parse_hex(colours["colorprimary"])
    secondary = parse_hex(colours["colorsecondary"])
    fills = {}
    for variant in ("home", "away"):
        if variant not in palette["uniforms"]:
            raise ValueError(f"Slot {slot:03}: varsity needs {variant} numbers.fill controls")
        fills[variant] = parse_hex(palette["uniforms"][variant]["numbers"]["fill"])
    sources = uniforms.load_manifest(workspace)["sources"]
    tshirt = master(sources, slot, "tshirt", "crowd")
    crowd = master(sources, slot, "jersey", "crowd")
    sweatshirt = master(sources, slot, "sweatshirt", "crowd")
    varsity = master(sources, slot, "varsity", "crowd")
    sign = master(sources, slot, "crowdsign", "crowd")
    generic_names = sorted({row["texture"] for row in sources
                            if row["slot"] == slot and row["surface"] == "crowd"
                            and row["texture"].startswith("generictshirt_")})
    if not generic_names or len(generic_names) % 2:
        raise ValueError(f"Slot {slot:03}: an even, nonzero number of generic T-shirt variants "
                         "is required to split cap colours equally")
    generic = [master(sources, slot, name, "crowd") for name in generic_names]
    away = master(sources, slot, "unif", "game", "away")
    home = master(sources, slot, "unif", "game", "home")
    crowd_rows = [tshirt, crowd, sweatshirt, varsity, sign, *generic]
    files = native.scan(workspace, [*crowd_rows, away, home])
    tshirt_path, crowd_path = files[tshirt["id"]], files[crowd["id"]]
    sweatshirt_path = files[sweatshirt["id"]]
    for row in crowd_rows:
        path = files[row["id"]]
        if path.suffix.lower() != ".png":
            raise ValueError(f"Crowd master must be a PNG: {path}")
    logo = logo_dir / f"{LOGO_ID0 + slots[slot]}.png"
    sheet, nickname = team_info(slots[slot])
    player, number, ppg = scorer(sheet)
    with Image.open(tshirt_path) as source, Image.open(template_path) as template:
        image = render(source, template, logo, primary)
    with Image.open(sweatshirt_path) as source, Image.open(sweatshirt_template_path) as template:
        sweatshirt_result = render_sweatshirt(source, template, logo, primary)
    with Image.open(crowd_path) as source, Image.open(jersey_template_path) as template, \
            Image.open(files[away["id"]]) as away_image, Image.open(files[home["id"]]) as home_image:
        away_result = render_jersey(source, away_image, template, (255, 255, 255))
        home_result = render_jersey(source, home_image, template, primary)
    varsity_path, sign_path = files[varsity["id"]], files[sign["id"]]
    with Image.open(varsity_path) as source, Image.open(varsity_template_path) as template, \
            Image.open(varsity_accents_path) as accents, \
            Image.open(files[home["id"]]) as home_image, Image.open(files[away["id"]]) as away_image:
        varsity_result = render_varsity(source, home_image, template, accents, logo,
                                        primary, secondary, number, fills["home"])
        varsity_alt = render_varsity(source, away_image, template, accents, logo,
                                     DARK_GREY, primary, number, fills["away"])
    with Image.open(sign_path) as source:
        sign_result = render_sign(source, logo, primary)
        sign_alt = render_sign(source, logo, primary, nickname)
    pending = [(Path(tshirt_path.name), image), (Path(sweatshirt_path.name), sweatshirt_result),
               (Path(crowd_path.name), away_result),
               (Path("_alt") / crowd_path.name, home_result),
               (Path(varsity_path.name), varsity_result),
               (Path("_alt") / varsity_path.name, varsity_alt),
               (Path(sign_path.name), sign_result),
               (Path("_alt") / sign_path.name, sign_alt)]
    for index, row in enumerate(generic):
        path = files[row["id"]]
        with Image.open(path) as source:
            cap = render_cap(source, logo, primary if index % 2 == 0 else DARK_GREY)
        pending.append((Path(path.name), cap))
    output_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"slot_{slot:03}_", dir=output_root))
    for relative, image in pending:
        output = directory / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as file:
            image.save(file, format="PNG")
        print(f"Review copy: {output}")
    for destination in sorted({files[row["id"]].parent for row in crowd_rows}):
        print(f"Live workspace unchanged. Crowd clothing destination: {destination}")
    print(f"Varsity number: {player}, #{number} ({ppg:g} pooled PPG; ties: lowest ProA ID).")
    print("Choose main OR _alt separately for jersey, varsity and sign; never copy both.")
    return directory / tshirt_path.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for slot in range(30):
        group.add_argument(f"--{slot:03}", dest="slot", action="store_const", const=slot,
                           help=f"generate review copies for NBA roster slot {slot:03}")
    args = parser.parse_args()
    try:
        generate(args.slot)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Fan generation refused: {error}\n")


if __name__ == "__main__":
    main()
