# Sprint Game Manager (SGM)

Desktop GUI for managing Intellivision Sprint Console ROMs and assets in a single folder, per `instructions.md`.

## Setup

```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## App config

On first run, the app creates `sgm.ini` in the current working directory (project root by default). It stores settings like `LastGameFolder` and expected image resolutions.
