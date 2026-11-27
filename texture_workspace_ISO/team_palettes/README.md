# Team palettes

These are the copied ISO-workspace controls used by the
[native logo/season workflow](../../docs/NativeLogoWorkflow.md). They are
independent of the original `texture_workspace/team_palettes` controls.

Edit `000/colours.json` through `029/colours.json`: one document per **NBA roster
slot**, not arena filename. ProA assignments are in
[team_slots.csv](../../data/team_slots.csv). All 30 slots and all 79 existing
uniform variants are supported. Existing lettering edits were migrated unchanged.

## JSON schema

```json
{
  "schema": 1,
  "team": {
    "colorprimary": "#B51514",
    "colorsecondary": "#EEEEEE",
    "colorjersey1": "#B51514",
    "colorjersey2": "#000000",
    "colorui1": "#B51514",
    "colorui2": "#000000"
  },
  "uniforms": {
    "home": {
      "names": {
        "mode": "monochrome",
        "fill": "#FFFFFF",
        "outline1": "#000000",
        "outline2": "#FFFFFF"
      },
      "numbers": {
        "mode": "outlined",
        "fill": "#FFFFFF",
        "outline1": "#B51514",
        "outline2": "#000000"
      }
    }
  },
  "court": {
    "mode": "recolour",
    "primary": "#B51514",
    "secondary": "#000000",
    "lines": "#FFFFFF"
  }
}
```

Every RGB value is six hexadecimal digits, optionally prefixed by `#`. No alpha
authoring is exposed. Keep all actual variants (`home`, `away`, and `alt` where
present); the abbreviated example shows only `home`.

| Value | Effect |
|---|---|
| `team.colorprimary` | Optional crowd clothing/cap and alternative undershirt colour for the standalone review-copy generator; no automatic build effect |
| `team.colorsecondary` | Optional validated RGB metadata; currently unused by generators and builds |
| `team.colorjersey1` | Reserved for native cloth migration; legacy cloth uses the original workspace |
| `team.colorjersey2` | Reserved for native cloth migration; legacy cloth uses the original workspace |
| `team.colorui1`, `team.colorui2` | Two roster/UI RGB triplets; independent of cloth and lettering |
| `uniforms.<variant>.names.fill` | Jersey name-letter fill |
| `uniforms.<variant>.numbers.fill` | Jersey-number fill, shared by gameplay and team-select preview |
| `outline1`, `outline2` | Source-relative first/second outline blend colours in `outlined` mode |
| `court.primary` | Apron / outer court colour bands; some arenas link these to paint |
| `court.secondary` | Plain zone paint and filled-circle/key masks |
| `court.lines` | Common thin-line colour, plus Hornets' apron stripe |

Lettering modes: `palette` reads the existing `<variant>/*.palette.png` RGB
swatches; `monochrome` uses `fill`; `outlined` uses all three colours. Names and
numbers are independent. The JSON stores all authoring controls, but palette mode
still intentionally uses the editable PNGs.

Court mode: `original` leaves the entire court untouched (default); `recolour`
applies all three slots. Original-mode values are representative source colours,
not a promise to reproduce the original court when switched to recolour.
Overwritten plain paint loses authored vertex RGB/opacity gradients and uses
material alpha 255: with neutral vertex alpha 128 this produces full GS opacity
128, like the solid filled-circle interior. Mask alpha and non-zone material
alpha remain unchanged, as do hardwood, lighting, reflections and geometry.
Raptors' shared floor/paint materials also share this opacity increase.
Logos/lettering textures are not recoloured. Neutral hardwood-overlay materials
are left alone.

**Arena profiles deliberately differ.** Raptors/Paderborn (022): primary controls
linked apron/paint regions; secondary controls linked dark floor/key regions.
No material splitting is required. Hornets (011): primary merges the original
teal/purple/gold apron bands, lines replaces its white stripe, and mip mixtures
are regenerated. Full/half-circle paint masks use secondary. Some arenas have
no separate plain zone layer; the tool does not invent one.

**Hawks (009):** uses a reduced **material-tint** profile to fit its tight
compression allocation: primary/secondary recolour the existing materials; lines
tints the original masks without replacing their palettes. Originally coloured
segments therefore retain their source hue influence rather than becoming an exact
requested RGB. Authored vertex colour/opacity and material alpha are retained in this profile.
Two distinct three-colour presets passed the fixed-span checks.
Every build still verifies its exact requested profile and refuses overflow
without publishing an ISO; no controls are silently ignored or downgraded.

## Commands (repository root)

### Optional fan-texture review copies

```powershell
python scripts\generate_fans.py --020
```

Use the three-digit **roster slot** (`--012` through `--029` for the assigned
ProA teams), not the crowd package number. Add `team.colorprimary` and
`team.colorsecondary` to that slot's JSON first. These remain optional for
existing build workflows, but the generator requires both explicitly and never
falls back to another colour. The JSON must also contain home and away
`uniforms.<variant>.numbers.fill` controls.

Each invocation creates a new `texture_auto/fans/slot_020_<unique>/` folder
outside the live workspace. PNGs have the current target masters' filenames,
including their native IDs. Review them, then manually copy/move accepted files to the destination
printed by the script and confirm replacement only if satisfied. Rerunning never
overwrites earlier review copies or live edits. The output folder is Git-ignored.

The generator reuses the logo-free grayscale
[`fan1_tmpl.png`](../../texture_templates/fan1_tmpl.png) for cloth wrinkles,
recolours the shirt and cap with `colorprimary`, and fits the assigned ProA logo
into the original chest and cap logo boxes. Shoes, swatches and alpha come from
the current T-shirt master unchanged.

The `sweatshirt` atlas uses primary-colour fabric and the ProA chest logo, with
its own knit hem, collar and long-sleeve wrinkles preserved by the reusable
[`fan_sweatshirt_tmpl.png`](../../texture_templates/fan_sweatshirt_tmpl.png).
The template comes from the original slot-020 sweatshirt with the NBA logo
replaced by a feathered patch of neighbouring fabric. It is not regenerated
from live artwork. Unlike the T-shirt atlas, the sweatshirt has **no cap panel**:
its upper-right sleeve fabric is recoloured, not stamped with a second logo.

All six `generictshirt_*` variants are also exported, changing **only** the cap
rectangle (pixels x=192..255, y=0..49) and adding the ProA cap logo. Their shirt
artwork, shoes, swatches and alpha remain pixel-identical to the current masters.
Cap backgrounds alternate deterministically in alphabetical variant order:

- `black`, `purple`, `white`: `colorprimary`.
- `blue`, `red`, `yellow`: dark grey (`#303030`).

Thus exactly half have each cap colour; the names describe the **unchanged shirt**
colours. Variants are discovered from the manifest, not guessed from filenames;
an empty or odd-sized set is rejected rather than silently breaking the equal split.

The same run also generates the crowd `jersey` atlas from the team's current
**gameplay away** `unif` master over a white T-shirt. `_alt/` contains the
alternative using the **gameplay home** master over `colorprimary`. Both alternatives
keep the final crowd master's filename, so copying either one needs no rename.
Choose **one**, not both, for the live crowd jersey.

The player jersey is remapped panel-by-panel into the crowd atlas's wrapped torso
layout. Its front/back neck depths are registered to the crowd layout; an immutable
[`fan_jersey_undershirt.png`](../../texture_templates/fan_jersey_undershirt.png)
overlay preserves the original crowd neck/armhole silhouettes and sleeve wrinkles.
This template was extracted from the original slot-020 crowd jersey: only
top-connected neutral fabric and the separate sleeve panel are opaque; jersey
artwork is transparent. Edit the grayscale fabric/alpha only if intentionally
changing this shared template. No template is regenerated from live fan artwork.
Sponsor/logo artwork is copied from the manually edited player jerseys, not
recreated from palette colours or team logos. Atlas registration is checked offline; review
the fit in game before accepting, especially for custom player-jersey layouts.
The template expects the standard 2:1 player atlas; incompatible dimensions,
missing/ambiguous gameplay masters, or missing inputs are errors before publication.

The `varsity` jacket has two versions:

- Main: `colorprimary` jacket, `colorsecondary` ribbing/accents, gameplay **home**
  jersey visible through the opening.
- `_alt/`: dark grey (`#303030`) jacket, `colorprimary` accents, gameplay **away**
  jersey underneath.

Both carry the team chest logo and the jersey number of that team's highest
**pooled multi-season `points_avg`** player from
[`proa_stats.json`](../../data/proa_stats.json), restricted to players on the
assigned sheet in `proa_scraped.xlsx`. This intentionally uses the rating
pipeline's pooled PPG, not current-season PPG. Equal PPG selects the lowest
numeric ProA ID. The number comes from the workbook's `Jersey Number`; the
script prints the chosen player, number and PPG. Missing/invalid PPG or an invalid
selected number is an error, not a random-player fallback.

Numbers use a portable, resizable Pillow built-in font, made monochrome with
`uniforms.home.numbers.fill` for main and `uniforms.away.numbers.fill` for `_alt`.
No outlines, preview atlases or cached lettering colours are used. This requires
Pillow 10.1+ with FreeType, as supplied by current Pillow wheels.

The reusable [`fan_varsity_tmpl.png`](../../texture_templates/fan_varsity_tmpl.png)
and [`fan_varsity_accents.png`](../../texture_templates/fan_varsity_accents.png)
retain jacket folds and define accent coverage. The fabric comes from the
handmade slot-021 example, with its chest badge patched out; the
slot-020 white inset defines the jersey opening. Template alpha excludes the
opening, neck void and lower central swatch. Those latter two regions and the
entire atlas alpha are preserved from the current target master. Only the
opening receives the registered player-jersey front and added number; sponsor
art is naturally cropped by the jacket. The templates are fixed assets, never
regenerated from live artwork.

The `crowdsign` atlas is primary-colour with the centred team logo. Its `_alt/`
version instead has two large, fitted lines:

```text
Auf geht's
<nickname>
```

`nickname` comes from [`proa_teams.csv`](../../data/proa_teams.csv), e.g. `Merlins`,
not the full sheet/club name. Text is black or white, whichever has the higher
sRGB relative-luminance contrast against `colorprimary`. Each line is fitted
independently inside the 128x128 sign, including multiword nicknames. Original
sign alpha is preserved.

Each standard team run produces eleven main PNGs plus three alternatives
in `_alt/` (fourteen PNGs total). Choose main **or** `_alt` independently for
the crowd jersey, varsity and sign; each alternative keeps its final target
filename. All required inputs are validated/rendered before a review folder is
created, so input errors cannot publish a partial set.
There is **no integration into builds, exports or texture propagation**.

### Existing palette/ISO commands

```powershell
# Export missing assets and refresh lettering previews, preserving edits:
python scripts\lettering_workspace.py export --workspace texture_workspace_ISO\team_palettes --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Validate combined lettering + court edits without changing the workspace:
python scripts\lettering_workspace.py check --workspace texture_workspace_ISO\team_palettes --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Publish a verified new ISO (never overwrite source or an existing output):
python scripts\lettering_workspace.py build --workspace texture_workspace_ISO\team_palettes --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\team-colours.iso"
```

`build_roster.py --team-palettes texture_workspace_ISO\team_palettes` reads the UI
colours here; season automation passes that workspace automatically.
`create_baseline_jersey.py` still reads cloth colours from the original workspace.
`proa_teams.csv` now contains only names/arena metadata.
Season updates accept `--team-palettes PATH` (the old `--lettering-workspace`
spelling is an alias) and use the same directory for roster and ISO generation.
`reset --slot N` resets only lettering controls/swatches, **not** team/court colours.
`check`/`build` do not refresh previews. There is no generated full-court preview.
Boot a published ISO fresh; texture reload and old save states do not establish
that its court resources were freshly loaded.

Only the JSONs and this README are versioned. Original swatches, editable PNGs,
previews and the source manifest remain local; export them from the pristine ISO
when setting up a fresh checkout.
