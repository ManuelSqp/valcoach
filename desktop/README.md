# Nexus for Windows

Nexus in its own window, plus what only works on your PC. The window shows your Nexus server like the browser
does (same pages, same login); the menu gets one more entry, **This PC**, that only exists in the app. In the
background, every few minutes, the app:

- **puts the coach's KovaaK's playlists into KovaaK's**: today's warm-up and training, dated
  (`nexus_warmup_DD-MM-YYYY.json`), into KovaaK's Playlists folder. In KovaaK's: *Playlists › Local Playlists*.
  The coach's own files older than a month are removed; nothing else in that folder is touched.
- **sends new KovaaK's scores** from KovaaK's `stats` folder to Nexus (the Aim page uses them).
- **cuts your matches out of Medal recordings and uploads them.** On the match's coach page in Nexus the
  recording is then picked already (*From the Nexus app*).

Each of the three can be switched off under *This PC*, which also shows the folders, what the app did lately and
updates.

## Install

1. Download `nexus-setup.exe` from the newest [release](https://github.com/ManuelSqp/valcoach/releases)
   and run it. Windows may warn that the installer is unknown (it isn't signed): *More info › Run anyway*.
   It installs for your Windows user only (no admin rights) into `%LOCALAPPDATA%\Programs\Nexus`,
   with a Start menu entry; the downloaded installer can be deleted right after. Uninstall it under
   *Settings › Apps*. It needs Microsoft Edge WebView2, which Windows 10 and 11 already have.
2. Enter the Nexus address (e.g. `https://coach.example.com`) and log in on the page that opens, like on the
   website. The login is kept between starts.
3. Logged in, the website gives the app its own key for this PC (stored in Windows' Credential Manager; the
   password never reaches the app). *Account › Nexus app for Windows* lists your PCs and logs one out; changing
   your password logs out all. Logging in with another account in the app moves the key to that account.
4. Open *This PC*: pick your player, check the two folders (it looks for KovaaK's in your Steam libraries and for
   Medal in `Videos\Medal`), and switch on *Start with Windows* if you like.

Closing the window keeps it running in the tray; *Quit* in the tray menu ends it, *Change server…* connects it to
another Nexus. Links to other websites open in your browser.

**Coming from the companion app (up to 4.4)?** It updates itself to this app like to any new version (or run
`nexus-setup.exe` over it). Its settings, what it uploaded already and *Start with Windows* are taken over; log in
once in the new window.

## Versions and updates

The app has **the same version as Nexus** (4.5.0 and 4.5.0); a test checks that `desktop/nexus_desktop/
__init__.py` and `nexus/__init__.py` agree. Once a day (and on *This PC › Check for updates*) the app looks for a newer
Nexus release on GitHub that has the installer attached. *Update now* downloads it to the temp folder, checks it
against the SHA-256 GitHub lists for the file, and runs it silently: it closes the app, replaces the files and
starts the app again. Running from Python source instead, *Open download* opens the release page.

**Publishing a release** (4.16): merge the PR that raises the version. `.github/workflows/release-tag.yml`
sees the new version on main, checks that `pyproject.toml`, `nexus/__init__.py` and `desktop/nexus_desktop/
__init__.py` agree, tags exactly the merged commit (`vX.Y.Z`) and starts the desktop build for it. A version that
already has a tag is left alone. Tagging by hand still works:

```
git switch main && git pull
git tag v4.5.0
git push origin v4.5.0
```

`.github/workflows/desktop.yml` checks that the tag matches Nexus's version, builds the app and the installer
on Windows and attaches `nexus-setup.exe` to that release (creating it if it isn't there yet), and the same file
as `valcoach-companion-setup.exe` for companion apps up to 4.4.
Publishing the release on GitHub's page instead works too. If a release ever has no installer: *Actions ›
desktop › Run workflow*, *release* = its tag (e.g. `v4.5.0`).
Every installed app offers the update within a day.

## How the matches are found in a Medal recording

Medal names a session recording after the moment it started, to the millisecond:
`MedalTVValorant20260701203418498.mp4` started on 01.07.2026 at 20:34:18.498 (your PC's time). Riot's match data
has each match's start and length, so a match sits at *match start − recording start* into the file, however long
you were in the menu before and however many matches the recording holds. The app cuts each one out with
ffmpeg (without re-encoding: fast, same quality, 90 s before and 60 s after the match) and uploads only that part.
Nexus's kill-feed sync lines it up exactly afterwards.

- Only recordings from when you first used the app onwards are looked at (not your whole Medal library).
- A recording counts as finished when it hasn't changed for two minutes.
- If start + length don't fit the time the file stopped (Medal paused the recording, the clock jumped), the
  recording is skipped and the log says so, instead of cutting at the wrong place.
- Clips Medal saves separately (`...498-1774815019.mp4`) are ignored.
- Only matches Nexus can coach (not Deathmatch etc.), and only the last 10 matches of your player.
- The cut is written to your temp folder first, so a 40-minute match needs a few GB free on drive C: for a
  moment.

## Build it yourself

On Windows, with Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```bash
pip install -e . "./desktop[build]"
cd desktop
python -c "from nexus_desktop.app import logo; logo(256).save('icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])"
pyinstaller --noconfirm --onedir --windowed --name nexus --icon icon.ico --collect-data webview \
  --collect-binaries webview --hidden-import webview.platforms.winforms --hidden-import webview.platforms.edgechromium \
  --hidden-import clr --collect-binaries imageio_ffmpeg --collect-submodules keyring --hidden-import pystray._win32 \
  run_nexus.py
iscc /DAppVersion=4.5.0 installer.iss          # -> dist\nexus-setup.exe
```

*Run workflow* on the desktop workflow does the same on GitHub (the installer is under the run's Artifacts).
Without building anything: `pip install ./desktop` then `python -m nexus_desktop`.

## How the window and the app talk

The pages of the connected server (and only those: the app checks the page's address on every call) can call the
app through pywebview's bridge (`window.pywebview.api`): `status`, `set` (the switches and the player), `pick_folder`,
`sync_now`, `paired`, `check_updates`, `update_now`, `change_server`, `fullscreen` (the aim trainer). The website's part is `base.html` (shows *This
PC* and pairs: `POST /account/devices/pair` with the session, the key goes straight to the app) and
`this_pc.html`. The app itself still talks to Nexus only through `/api/companion/...` with its device key.
