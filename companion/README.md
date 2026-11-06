# valcoach companion

A small Windows app for each player. It sits in the tray (bottom right) and every few minutes:

- **puts the coach's KovaaK's playlists into KovaaK's**: today's warm-up and training, dated
  (`valcoach_warmup_DD-MM-YYYY.json`), into KovaaK's Playlists folder. In KovaaK's: *Playlists › Local Playlists*.
  The coach's own files older than a month are removed; nothing else in that folder is touched.
- **sends new KovaaK's scores** from KovaaK's `stats` folder to valcoach (the Aim page uses them).
- **cuts your matches out of Medal recordings and uploads them.** On the match's coach page in valcoach the
  recording is then picked already (*From the companion app*).

Each of the three can be switched off.

## Install

1. Download `valcoach-companion.exe` from the repository's
   [releases](https://github.com/ManuelSqp/valcoach/releases) (tags `companion-v...`).
2. Start it. Windows may warn that the app is unknown (it isn't signed): *More info › Run anyway*.
3. Enter the valcoach address (e.g. `https://coach.example.com`), your valcoach username and password, and
   *Log in*. The app gets a key for this PC; the password isn't stored. The key is in Windows' Credential Manager.
   *Account › Companion app* in valcoach lists your devices and logs one out; changing your password logs out all.
4. Pick your player, check the two folders (it looks for KovaaK's in your Steam libraries and for Medal in
   `Videos\Medal`), and tick *Start with Windows* if you like.

Closing the window keeps it running in the tray; *Quit* in the tray menu ends it.

## Updates

The app looks for a newer release once a day (and on *Check for updates*). When there is one, a bar at the top
says so, and *Update now* downloads it, checks it against the SHA-256 GitHub lists for the file, swaps it in and
restarts the app: nothing else to do. Running it from Python source instead, *Open download* opens the release page.

**Publishing a new version:** raise `__version__` in `companion/valcoach_companion/__init__.py` (and in
`companion/pyproject.toml`), merge, then push a tag with the same version:

```
git switch main && git pull
git tag companion-v1.1.0
git push origin companion-v1.1.0
```

The workflow refuses a tag that doesn't match the app's version, builds the .exe on Windows and creates the release.
Every installed app offers the update within a day.

## How the matches are found in a Medal recording

Medal names a session recording after the moment it started, to the millisecond:
`MedalTVValorant20260701203418498.mp4` started on 01.07.2026 at 20:34:18.498 (your PC's time). Riot's match data
has each match's start and length, so a match sits at *match start − recording start* into the file, however long
you were in the menu before and however many matches the recording holds. The app cuts each one out with
ffmpeg (without re-encoding: fast, same quality, 90 s before and 60 s after the match) and uploads only that part.
valcoach's kill-feed sync lines it up exactly afterwards.

- Only recordings from when you first logged in the app onwards are looked at (not your whole Medal library).
- A recording counts as finished when it hasn't changed for two minutes.
- If start + length don't fit the time the file stopped (Medal paused the recording, the clock jumped), the
  recording is skipped and the log says so, instead of cutting at the wrong place.
- Clips Medal saves separately (`...498-1774815019.mp4`) are ignored.
- Only matches valcoach can coach (not Deathmatch etc.), and only the last 10 matches of your player.
- The cut is written to your temp folder first, so a 40-minute match needs a few GB free on drive C: for a
  moment.

## Build it yourself

```bash
pip install "./companion[build]"
cd companion
python -c "from valcoach_companion.app import logo; logo(256).save('icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])"
pyinstaller --noconfirm --onefile --windowed --name valcoach-companion --icon icon.ico --collect-data customtkinter \
  --collect-binaries imageio_ffmpeg --collect-submodules keyring --hidden-import pystray._win32 run_companion.py
```

GitHub Actions does the same on Windows (`.github/workflows/companion.yml`): push a tag `companion-v1.0.0` and the
.exe lands in a release. Without installing: `pip install ./companion` then `python -m valcoach_companion`.
