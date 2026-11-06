"""Redirect targets from forms and links ("?next=..."): only pages of this site.

Browsers read more than "//host" as another site: "/\\host", "\\\\host", and tabs or newlines inside the URL
are dropped first ("/<TAB>/host" becomes "//host"). So a target must start with a single "/", contain no
backslash, white space or control character, and parse without a scheme or host."""
from __future__ import annotations

from urllib.parse import urlparse


def local_path(target: str | None) -> str | None:
    """The target if it's a path on this site, else None."""
    if not target or len(target) > 2000 or not target.startswith("/") or target.startswith("//"):
        return None
    if any(c == "\\" or ord(c) <= 0x20 or ord(c) == 0x7F for c in target):
        return None
    p = urlparse(target)
    if p.scheme or p.netloc:
        return None
    return target
