"""Updates from GitHub: the newest valcoach release (tag vX.Y.Z, the same version as the web app) that has the
companion's installer attached.

The installer is downloaded to the temp folder, must match the release's SHA-256 (GitHub lists it for every file)
and size, and then runs silently: it closes the app, replaces the installed files and starts the app again.
The next start removes the downloaded installer.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from . import __version__

REPO = os.environ.get("VALCOACH_COMPANION_REPO", "ManuelSqp/valcoach")
API = "https://api.github.com/repos/{repo}/releases?per_page=30"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ASSET = "valcoach-companion-setup.exe"
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/SP-"]


class UpdateError(RuntimeError):
    pass


def version_tuple(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def latest(current: str = __version__, session=None) -> dict | None:
    """The newest released companion installer if it's newer than this app: {version, url, size, sha256, page, notes}."""
    s = session or requests
    try:
        r = s.get(API.format(repo=REPO), timeout=15, headers={"Accept": "application/vnd.github+json",
                                                              "User-Agent": f"valcoach-companion/{current}"})
    except requests.RequestException as e:
        raise UpdateError(f"GitHub isn't reachable ({e.__class__.__name__})") from None
    if r.status_code != 200:
        raise UpdateError(f"GitHub answered HTTP {r.status_code}")
    best = None
    for rel in r.json():
        m = TAG_RE.match(str(rel.get("tag_name") or ""))
        if not m or rel.get("draft") or rel.get("prerelease"):
            continue
        asset = next((a for a in rel.get("assets") or [] if a.get("name") == ASSET), None)
        if asset is None:
            continue
        v = tuple(int(x) for x in m.groups())
        if best is None or v > best[0]:
            digest = str(asset.get("digest") or "")
            best = (v, {"version": ".".join(map(str, v)), "url": asset.get("browser_download_url", ""),
                        "size": int(asset.get("size") or 0),
                        "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
                        "page": rel.get("html_url", ""), "notes": str(rel.get("body") or "")[:2000]})
    if best and best[0] > version_tuple(current):
        return best[1]
    return None


def download(info: dict, folder: Path, progress=lambda done, total: None, session=None) -> Path:
    """The installer into `folder` (as .download until it's complete and checked) -> its final path."""
    url = info.get("url", "")
    if not url.startswith("https://github.com/") and not url.startswith("https://objects.githubusercontent.com/"):
        raise UpdateError("The download isn't on GitHub")
    s = session or requests
    final = Path(folder) / f"valcoach-companion-setup-{info.get('version', 'new')}.exe"
    part = final.with_name(final.name + ".download")
    h = hashlib.sha256()
    done = 0
    try:
        with s.get(url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                raise UpdateError(f"The download answered HTTP {r.status_code}")
            with open(part, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    progress(done, info.get("size") or 0)
    except requests.RequestException as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"The download stopped ({e.__class__.__name__})") from None
    if info.get("size") and done != info["size"]:
        part.unlink(missing_ok=True)
        raise UpdateError("The download is incomplete")
    if info.get("sha256") and h.hexdigest() != info["sha256"]:
        part.unlink(missing_ok=True)
        raise UpdateError("The download doesn't match the release (SHA-256): nothing was changed")
    os.replace(part, final)
    return final


def can_install() -> bool:
    """Only on Windows, from the built app (running from Python source: update with git / pip instead)."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def install(setup: Path) -> None:
    """Start the installer silently; the caller quits right after (the installer also closes the app if needed,
    and starts it again when it's done)."""
    subprocess.Popen([str(setup), *SILENT], close_fds=True, creationflags=0x00000008)   # DETACHED_PROCESS


def cleanup() -> None:
    """Remove installers from earlier updates (and the .exe the very first version left next to itself)."""
    for f in Path(tempfile.gettempdir()).glob("valcoach-companion-setup-*.exe*"):
        try:
            f.unlink()
        except OSError:
            pass                               # still running: next start
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        exe.with_name(exe.name + ".old").unlink(missing_ok=True)
