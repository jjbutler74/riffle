# Riffle

Casts a photo slideshow from local folders to a Chromecast (2nd gen).

## Setup

1. **Python 3.11+** and a virtual environment:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

2. **ExifTool** (used for reading photo titles/dates/descriptions) — install
   separately and make sure it's on PATH:

   ```powershell
   winget install --id=OliverBetz.ExifTool -e
   ```

   If it's not on PATH, set `exiftool_path` in your config to its full path.

3. **Config file** — Riffle looks for `config.toml` in the platform config
   directory (`%APPDATA%\Riffle\config.toml` by default) unless you pass
   `--config path\to\config.toml`. Minimal example:

   ```toml
   [riffle]
   root_folders = [
       "D:/Photos/Family",
       "D:/Photos/Trips",
   ]
   # exiftool_path = "C:/Users/you/AppData/Local/Programs/ExifTool/ExifTool.exe"
   # chromecast_name = "Living Room TV"
   # interval_seconds = 30
   # http_port = 8420
   ```

   All other settings (`data_dir`, `http_host`, `max_width`/`max_height`,
   `exiftool_batch_size`, `reshuffle_on_wrap`) have sensible defaults — see
   `riffle/config.py`.

4. **Windows long paths**: if any of your photo paths might exceed 260
   characters, enable `LongPathsEnabled` (Local Group Policy or the
   `LongPathsEnabled` registry value under
   `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`).

## Usage

```powershell
riffle scan      # first run: walk root_folders, build the manifest, shuffle it
riffle rescan     # diff the filesystem against the manifest; new files are
                   # inserted at random positions in the unseen remainder
riffle status     # cursor position / photos remaining in the current cycle
riffle play        # serve photos over local HTTP and cast the slideshow
                    # (Ctrl+C to stop cleanly)
```

Add `-v` for debug logging, e.g. `riffle -v play`.

## Notes

- The Riffle PC and the Chromecast must be on the same network segment —
  device discovery uses mDNS, which typically doesn't cross VLANs/subnets.
- Only `.jpg`/`.jpeg` files are scanned in this version.
- Rendered/composited images are cached under `<data_dir>/cache`, keyed by
  file content hash + overlay text, so editing a caption or the source file
  produces a fresh cached image automatically. The cache is not
  automatically pruned in this version.
- Run tests with `pytest` from the project root (after `pip install -e ".[dev]"`).
