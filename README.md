# Sprint Game Manager (SGM)

Desktop GUI for managing Intellivision Sprint Console games (ROM, config, metadata, and images) for sideloading.

## Using the app (end users)

### 1) Pick your games folder
- Use the folder picker to choose the root folder that contains your game files.
- The game list populates from the detected basenames.

### 2) Select a game
- Click a game to edit its assets.
- The top-left warning counter reflects missing/invalid assets (including image resolution mismatches).

### Analyze the games folder
- Use the **Analyze** area to scan the currently selected games folder and compute warnings per game.
- Use the warning filters to show only specific issues (missing ROM/config/metadata/images, overlay conflicts, resolution mismatches, etc.).
- Enable **Only games with warnings** to quickly narrow the game list.
- Use the **select all / clear all** filter buttons to toggle filters faster.
- If you add/rename files, re-run Analyze (or Refresh) to update results.

### 3) Add / rename content
- Drag & drop accepted files into the app (or use the Add actions) to copy them into the selected game.
- Use **Change File Name** to rename the game (updates associated files).

### 4) Edit metadata
- Use the metadata editor panel to create/edit `<basename>.json` and save changes.

### 5) Manage images
Each image card supports:
- **Browse**: pick an image file.
- **Paste**: paste an image from the clipboard.
- **Drag & drop**: drop an image file onto the card.
- **Resize** (when shown): fixes wrong-resolution PNGs.

### 6) Overlays (1–3)
- **Build**: generate an overlay from a template + bottom image.
- **Blank**: sets the slot to the packaged empty overlay image.
- **Keep Ratio** (overlay cards only): when checked, Browse/Paste keeps the source aspect ratio and centers it on a transparent canvas (no stretching).
- **Reorder overlays**: if at least two overlay files exist, drag one overlay card onto another to swap/move their underlying files.
	- If both `_overlay.png` and `_overlay1.png` exist (conflict), reorder is blocked until resolved.

### 7) Snapshots (1–3)
- If you have multiple snap images, drag one snap card onto another to swap/move `_snap1/_snap2/_snap3`.

### 8) QR code
- Use the QR tools to generate/update the game QR image (including URL-based creation).

## Technical (developers)

### Setup

```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run

```powershell
python main.py
```

### Build standalone EXE (Windows)

```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-build.txt
./build_exe.ps1
```

Output: `dist\SprintGameManager.exe`

### App config

On first run, the app creates `sgm.ini` in the current working directory (project root by default). It stores settings like `LastGameFolder`, expected image resolutions, and overlay template override settings.
