"""Updates from GitHub: the newest release tagged companion-vX.Y.Z, downloaded and swapped in for the running .exe.

Windows can't overwrite a running .exe, but it can rename it: the new file is downloaded next to it, the running one
becomes valcoach-companion.exe.old, the new one takes its name, the app starts it and quits. The next start removes
the .old file. The download comes from GitHub over HTTPS and must match the release's SHA-256 (GitHub lists it for
every file) and size before anything is replaced.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

from . import __version__

REPO = os.environ.get("VALCOACH_COMPANION_REPO", "ManuelSqp/valcoach")
API = "https://api.github.com/repos/{repo}/releases?per_page=30"
TAG_RE = re.compile(r"^companion-v(\d+)\.(\d+)\.(\d+)$")
ASSET = "valcoach-companion.exe"


class UpdateError(RuntimeError):
    pass


def version_tuple(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def latest(current: str = __version__, session=None) -> dict | None:
    """The newest released companion app if it's newer than this one: {version, url, size, sha256, page, notes}."""
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
    """The new .exe into `folder` (as .download until it's complete and checked)."""
    url = info.get("url", "")
    if not url.startswith("https://github.com/") and not url.startswith("https://objects.githubusercontent.com/"):
        raise UpdateError("The download isn't on GitHub")
    s = session or requests
    part = Path(folder) / (ASSET + ".download")
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
    return part


def can_install() -> bool:
    """Only the .exe can replace itself (running from Python source: update with git / pip instead)."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def install(new: Path) -> None:
    """Swap the new .exe in and start it. The caller quits right after."""
    exe = Path(sys.executable)
    old = exe.with_name(exe.name + ".old")
    old.unlink(missing_ok=True)
    os.replace(exe, old)                       # a running .exe can be renamed, not overwritten
    try:
        os.replace(new, exe)
    except OSError:
        os.replace(old, exe)                   # put the old one back
        raise
    subprocess.Popen([str(exe)], close_fds=True, creationflags=0x00000008)   # DETACHED_PROCESS


def cleanup() -> None:
    """Remove what the last update left behind."""
    if not getattr(sys, "frozen", False):
        return
    exe = Path(sys.executable)
    for leftover in (exe.with_name(exe.name + ".old"), exe.with_name(ASSET + ".download")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass                               # the old one may still be closing: next start
