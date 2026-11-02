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
   directory (`%LOCALAPPDATA%\Riffle\config.toml` by default -- note this is
   *Local* AppData, not *Roaming*) unless you pass `--config path\to\config.toml`.
   Copy [`config.sample.toml`](config.sample.toml) to that location and edit
   `root_folders`:

   ```powershell
   mkdir "$env:LOCALAPPDATA\Riffle" -Force
   copy config.sample.toml "$env:LOCALAPPDATA\Riffle\config.toml"
   notepad "$env:LOCALAPPDATA\Riffle\config.toml"
   ```

   All settings besides `root_folders` (`exiftool_path`, `chromecast_name`,
   `interval_seconds`, `http_host`/`http_port`, `max_width`/`max_height`,
   `data_dir`, `exiftool_batch_size`, `reshuffle_on_wrap`,
   `chromecast_host`, `hidden_folder_names`, `only_with_description`,
   `ignore_captions`, `skip_files`, `date_from`/`date_to`, and the
   caption toggles `show_location`, `show_folder_name`, `show_weekday`,
   `show_time`, `show_years_ago`) are optional and
   have sensible defaults — see the comments in `config.sample.toml` or
   `riffle/config.py`. Note that `only_with_description` defaults to **on**,
   so photos without a description are skipped until you turn it off.
   Text cameras write on their own ("OLYMPUS DIGITAL CAMERA", the model
   name, "IMG_1234", a timestamp) doesn't count as a description; add your
   own such phrases with `ignore_captions`.

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
