# Native uniform workspace

Edit uniforms in **`texture_workspace_ISO/uniforms`**, not the old PCSX2
workspace. The season ISO pipeline reads these masters automatically after
the initial export. No texture dumps or legacy COPY/LOD synchronization are
needed for subsequent builds.

## Export / migrate

Start with the native logo workspace already exported, then run:

```powershell
python scripts\uniform_iso_workspace.py export --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
```

The initial migration needs the pristine texture dumps, the native catalogue
at `cache/texture_iso/catalogue.sqlite`, and the old workspace. It matches
**original pixels**, never the edited artwork or an unverified old label.
It imports manual MASTER edits and their verified COPY/LOD targets, excludes
generated children, and also checks the copied legacy files in the ISO
workspace for independent edits. Conflicts and unmapped manual uniform edits
stop the export rather than silently reverting artwork.

Existing copied clothing, lettering and crowd folders are preserved under
`texture_workspace_ISO/_legacy_pcsx2/`. The old `texture_workspace` and live
PCSX2 replacements are never modified. The migration ledger in
`_iso_uniforms.json` records every manual source, hash and native destination.
Legacy naming problems are recorded there too: an untracked file with an
invalid dump ID is preserved, not guessed into a native target.

Re-export preserves existing native artwork and renamed/moved files by ID.
An unchanged inventory can be re-exported without the legacy sources/dumps.
Missing or duplicate native IDs fail explicitly.

## Editing

Example:

```text
uniforms/
  slot_021_Pistons/
    uh021/
      uh021_unif_unif__512x256__xxxxxxxx.png
      uh021_short_short__512x256__xxxxxxxx.png
    cscrowd021/
      cscrowd021_tshirt_tshirt__256x128__xxxxxxxx.png
```

- One base master per physical native texture, with `label__RES__ID`.
  Preserve the final eight-character ID. Labels and folders are informational;
  recursive scanning follows the ID even after renaming or moving a master.
- Slot folders use **roster slots**, not native asset IDs. Historical/special
  IDs without a current-team mapping have `native_NNN` folders. Unresolved
  package filenames remain explicit `unresolved_HASH` folders; exact original
  logo matches can identify their team, but old PCSX2 labels cannot.
- Export covers game and team-selection uniforms, the `wh/wa/wx` and
  `wu/pu/su/tu` families, coaches, bands, cheerleaders, mascots, lettering,
  crowd variants, and the separate `cscrowd`, `csch`, `cstrainer` packages.
  Structurally verified unnamed uniform packages are included too.
- Game and preview textures are separate native targets. Edit both when
  changing a design. The initial import seeds both wherever pristine-pixel
  evidence proves they used the old replacement.
- Logos already exported to `team_logos` remain there: no second editable
  uniform copy is created.
- Higher-resolution artist images are retained as defaults and resized only
  for encoding. RGB-only artwork preserves the original transparency.
- **No lower mip images are exported.** Encoding regenerates every stored or
  explicitly addressed native level from its base master. Geometry LODs are
  not texture mips.

Some crowd TSETs have several palettes but **one shared index plane**. Their
masters are editable separately, but encoding quantizes all variants together
within that shared 256-entry budget. Unedited variants participate too; their
faces and clothing are not silently replaced by the edited variant's palette.
Reports include per-variant RGB/alpha errors, and `_encoded` contains the
actual encoded previews. More complex independent designs can require
quantization across the entire cohort.

Team palette controls still handle lettering/court colours. Lettering,
native artwork and court intents are composed before compressing each resource
once. Incompatible edits to the same bytes are rejected: reset overlapping
name/number colour controls to the stock palette before independently editing
that texture's pixels.

## Check / build

Check all exported native masters and their shared archive allocation:

```powershell
python scripts\texture_iso_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --repack-archive
```

Then run the normal season pipeline:

```powershell
python scripts\update_season.py --skip-scrape --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "<NEW output ISO path>" --repack-archive
```

Use [archive repacking](./ArchiveRepacking.md) for variable-size compressed
textures. No default palette reduction or simplification of non-ProA artwork
is applied. All mods enter the allocator in original ISO coordinates.

Offline checks verify decoding, all regenerated mips, shared-resource
composition, native compression and sector capacity. They do not certify
runtime rendering. For one consolidated in-game review, disable old
logo/uniform replacements, boot fresh rather than loading a savestate, and
check:

| Surface | Review question |
|---|---|
| Team selection | Do home/away/alternate previews match their intended designs? |
| Close gameplay | Are jerseys, shorts, bands and independent lettering correct? |
| Distant gameplay | Do mip transitions retain the design without stock artwork flashing? |
| Bench / warmup | Are torso, sleeves and trousers correct for each used outfit? |
| Cheerleaders / mascots / coaches | Are their independently stored textures correct? |
| Crowd / cutscenes | Are the edited fan clothes correct, with other palette variants intact? |
| Other teams / special uniforms | Do untouched masters retain stock appearance? |

F10 cannot reload embedded ISO assets. Portraits and other not-yet-migrated
replacement classes remain outside this uniform migration.
