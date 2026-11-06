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

1. Download `valcoach-companion-setup.exe` from the newest [release](https://github.com/ManuelSqp/valcoach/releases)
   and run it. Windows may warn that the installer is unknown (it isn't signed): *More info › Run anyway*.
   It installs for your Windows user only (no admin rights) into `%LOCALAPPDATA%\Programs\valcoach companion`,
   with a Start menu entry; the downloaded installer can be deleted right after. Uninstall it under
   *Settings › Apps*.
2. Enter the valcoach address (e.g. `https://coach.example.com`), your valcoach username and password, and
   *Log in*. The app gets a key for this PC; the password isn't stored. The key is in Windows' Credential Manager.
   *Account › Companion app* in valcoach lists your devices and logs one out; changing your password logs out all.
3. Pick your player, check the two folders (it looks for KovaaK's in your Steam libraries and for Medal in
   `Videos\Medal`), and switch on *Start with Windows* if you like.

Closing the window keeps it running in the tray; *Quit* in the tray menu ends it.

## Versions and updates

The app has **the same version as valcoach** (4.4.0 and 4.4.0); a test checks that `companion/valcoach_companion/
__init__.py` and `valcoach/__init__.py` agree. Once a day (and on *Check for updates*) the app looks for a newer
valcoach release on GitHub that has the installer attached. *Update now* downloads it to the temp folder, checks it
against the SHA-256 GitHub lists for the file, and runs it silently: it closes the app, replaces the files and
starts the app again. Running from Python source instead, *Open download* opens the release page.

**Publishing a release:** after merging, push the version as a tag:

```
git switch main && git pull
git tag v4.4.0
git push origin v4.4.0
```

`.github/workflows/companion.yml` checks that the tag matches valcoach's version, builds the app and the installer
on Windows and attaches `valcoach-companion-setup.exe` to the release `v4.4.0` (creating it if it isn't there yet).
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

On Windows, with Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```bash
pip install -e . "./companion[build]"
cd companion
python -c "from valcoach_companion.app import logo; logo(256).save('icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])"
pyinstaller --noconfirm --onedir --windowed --name valcoach-companion --icon icon.ico --collect-data customtkinter \
  --collect-binaries imageio_ffmpeg --collect-submodules keyring --hidden-import pystray._win32 run_companion.py
iscc /DAppVersion=4.4.0 installer.iss          # -> dist\valcoach-companion-setup.exe
```

*Run workflow* on the companion workflow does the same on GitHub (the installer is under the run's Artifacts).
Without building anything: `pip install ./companion` then `python -m valcoach_companion`.
