# Sprint Game Manager (SGM)

A desktop GUI application written in Python to manage Intellivision Sprint Console game ROMs and supporting assets in a single root folder. The app focuses on consistent basenames, asset presence, resolution validation, metadata editing, and streamlined file adds and renames.

## File types and naming conventions

All files share a common `<basename>` and reside in a single root folder (no subfolders). A “game” is identified by the presence of any one supported asset file that matches a `<basename>`.

### Supported files

- **Rom:** `.bin`, `.int`, `.rom` — Main game file
- **Config:** `.cfg` — Required for `.int` and `.bin` ROMs
- **Metadata:** `.json` — Editable metadata
- **Box art:** `<basename>.png` — Full-resolution box art
- **Box small:** `<basename>_small.png` — Smaller box art
- **Overlay big:** `<basename>_big_overlay.png` — Controller overlay (large)
- **Overlay controller:** `<basename>_overlay.png` — Controller overlay (standard)
- **QR code:** `<basename>_qrcode.png` — QR linking to manual
- **Snapshots:** `<basename>_snap1.png`, `<basename>_snap2.png`, `<basename>_snap3.png` — Up to 3 images

A game is included in the list if the folder contains at least one of the above files for a `<basename>`.

**Maximum assets:** Up to 11 files per game basename (ROM + config + metadata + box + box small + overlay big + overlay controller + QR + 3 snaps).

## Application configuration

The application reads an ASCII configuration file on startup (located in current working directory). Defaults are applied if keys are missing. On successful browse, `LastGameFolder` is set.

- **LastGameFolder:** Path to the last browsed game folder. Default: `none`
- **DesiredMaxBaseFileLength:** Maximum basename length for warning. Default: `30`
- **DesiredNumberOfSnaps:** Desired snapshots count (0–3). Default: `2`
- **BoxResolution:** Expected resolution for `<basename>.png`. Default: `186x256`
- **BoxSmallResolution:** Expected resolution for `<basename>_small.png`. Default: `148x204`
- **OverlayResolution:** Expected resolution for `<basename>_overlay.png`. Default: `228x478`
- **OverlayBigResolution:** Expected resolution for `<basename>_big_overlay.png`. Default: `300x478`
- **QrCodeResolution:** Expected resolution for `<basename>_qrcode.png`. Default: `123x123`
- **SnapResolution:** Expected resolution for `<basename>_snapN.png`. Default: `640x400`
- **UseBoxImageForBoxSmall:** If `True`, Box Small is auto-derived from Box. Default: `True`

If this application configuration does not exist on startup, it should be created in the current working directory using provided defaults.
### Example config (ASCII)

```ini
LastGameFolder=none
DesiredMaxBaseFileLength=30
DesiredNumberOfSnaps=2
BoxResolution=186x256
BoxSmallResolution=148x204
OverlayResolution=228x478
OverlayBigResolution=300x478
QrCodeResolution=123x123
SnapResolution=640x400
UseBoxImageForBoxSmall=True
```

## Browse games folder list

### Folder browsing and auto-load

- **Open folder:** Browse and open a folder on the PC; read all contents.
- **Auto-load:** If `LastGameFolder` is set, auto-load it on application start.
- **Game detection:** If at least one supported file exists for a `<basename>`, list that basename in the games list.

### Refresh and updates

- **Refresh:** Re-read folder contents and update the list.
- **List updates on add:** If a newly added file's basename doesn't match an existing game, add the new basename to the list; do not duplicate existing entries.

## Adding files to the folder

- **Accepted types:** `.bin`, `.int`, `.rom`, `.cfg`, `.json`, `.png`
- **Add methods:** Browse files button or drag-and-drop
- **File copy:** Added files are copied into the games folder
- **Overwrite prompt:** If a file already exists, prompt the user before overwriting
- **Basename handling:** Newly added files contribute to game detection by basename

## Game details

When a game is selected in the list, populate the details panel with contextual controls and warnings.

### Base file name

- **Display:** Show the `<basename>`
- **Length warning:** If the basename length exceeds `DesiredMaxBaseFileLength`, show a warning
- **Change file name:** Button `Change File Name` prompts for a new `<basename>` and renames all files for the selected game, preserving extensions and suffixes on confirm

### ROM file

- **Display:** Show the `.int`, `.bin`, or `.rom` file
- **Missing warning:** If no ROM file is present, show a warning
- **Add ROM:** Browse or drag-and-drop accepted; copy to games folder using `<basename>` with original extension

### Config file

- **Display:** Show the `.cfg` file
- **Conditional warning:** If ROM is `.int` or `.bin` and `.cfg` is missing, show a warning. If ROM is `.rom` or ROM is missing, no warning.
- **Add config:** Browse or drag-and-drop accepted; copy as `<basename>.cfg`

### Metadata editor

- **File presence:** If `<basename>.json` is missing, show a warning and a `Create JSON` button. Creating JSON produces a default `<basename>.json` defaulting name to <basename>.
- **Editable fields:** `name`, `nb_players`, `editor`, `year`, and `description` in multiple languages via tabs
- **Save behavior:** `Save` button is enabled when there are pending changes; saves back to `<basename>.json`

#### Default JSON template

```json
{
  "name": "Beauty and the Beast",
  "nb_players": 1,
  "editor": "Imagic",
  "year": 1982,
  "description": {
    "en": "",
    "fr": "",
    "es": "",
    "de": "",
    "it": ""
  }
}
```

## Image controls

Each image type has its own card with shared and unique behaviors.

### Shared image behaviors

- **Thumbnail:** Display a thumbnail if present
- **Missing warning:** Warn when file is missing
- **Resolution validation:** Compare against configured expected resolution; warn on mismatch
- **Add/replace methods:** Browse, drag-and-drop, and paste-from-clipboard
- **Format conversion:** Convert added/pasted images to PNG
- **Resizing:** Resize to configured resolution before saving
- **File naming:** Save using the naming convention for that image type
- **Replace and revert:** `Replace Image` to supply new image; `Use Original` to revert if applicable (overwrite on replace)

### Unique image behaviors

- **Box / Box Small linkage:** If `UseBoxImageForBoxSmall = True`, adding Box auto-generates Box Small and disables the Box Small control; otherwise operate independently
- **QR Code creation:** Generate QR PNG from a user-entered URL and save as `<basename>_qrcode.png` at configured resolution
- **Snapshots management:** Support drag-and-drop reordering across `_snap1`, `_snap2`, `_snap3` and rename files accordingly on reorder
- **Presence warnings:** Compare number of snapshots present to `DesiredNumberOfSnaps` and warn on missing files up to that number

## Technologies

- **Primary language:** Python
- **UI library:** PySide6
- **Graphics library:** Pillow
- **QR code library:** qrcode

## Implementation notes

- **UI layout (PySide6):** Split view with left list of basenames and right tabbed pane for game details
- **Top bar:** Folder browse, Refresh, and status indicators (path, warning count)
- **Details pane tabs:** Base Name, ROM, Config, Metadata, Images (Box, Box Small, Overlay Big, Overlay Controller, QR Code, Snap1/2/3)

### File operations and validation

- **Detection:** Parse all files and build a map keyed by `<basename>` to known asset types
- **Renaming:** Rename all matched files when changing `<basename>`, preserving suffixes and extensions
- **Adding files:** Copy into games folder; prompt before overwrite
- **Resolution checks:** Use Pillow to open images and compare size to config; warn on mismatch

### Clipboard and drag-and-drop

- **Clipboard paste:** Accept image content and process like other add methods
- **Drag-and-drop:** Accept files into the list or specific cards; constrain by accepted types

### Config lifecycle

- **Startup:** Load ASCII config and apply defaults for missing keys.  if not config present, the create it.
- **Persist:** Update `LastGameFolder` when a folder is browsed successfully
- **Validation:** Constrain `DesiredNumberOfSnaps` to 0–3 and sanitize resolution values

## Error handling and logging

- **Overwrite prompts:** Clear Yes/No prompt
- **IO errors:** Show concise error banners and preserve current state
- **Non-destructive operations:** Do not overwrite existing files on failed conversions/resizes
- **Logging (optional):** Info for user actions, Warning for validation failures, Error for IO/parse failures

## Acceptance criteria

- **Browse and auto-load:** Can open any folder and auto-load last folder if configured
- **Game list:** Shows basenames when at least one matching file exists; `Refresh` updates correctly
- **Add files:** Supports browse and drag-and-drop; copies to folder; prompts on overwrite; updates game list for new basenames
- **Base name:** Shows basename, warns on length, and renames all files when changed
- **ROM:** Displays current ROM, warns if missing, accepts ROM add and saves with basename
- **Config:** Displays `.cfg`; warns only if ROM is `.bin`/`.int` and `.cfg` missing
- **Metadata:** Creates default JSON when missing; provides editable fields and language tabs; `Save` writes changes
- **Images (shared):** Thumbnails, missing/resolution warnings, add/replace via browse/drag/paste; convert to PNG and resize to configured dimensions
- **Images (unique):** Box Small auto-derived when enabled; QR created from URL; Snapshots reorder with correct file renaming; warnings governed by `DesiredNumberOfSnaps`
- **Resolutions:** Use exact dimensions from config for validations and conversions
- **No subfolders:** All operations occur in a single root folder
