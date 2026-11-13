"""Faster pages over the internet: gzip and long caching of versioned files.

Nexus is served straight by waitress (no nginx in front), so nothing compressed the responses: the aim trainer page
was ~240 KB of HTML plus ~110 KB of script on every visit. Two things here:

- gzip: pages, JSON and static text files (CSS, JS, SVG) go out gzipped when the browser accepts it and they're
  bigger than MIN_BYTES. Static files are compressed once and kept in memory (by path and ETag). Never for partial
  answers (video ranges), 304s, streamed answers or what is already encoded.
- caching: a static file asked for with ?v=<version> (every page does that) may be kept by the browser for a year;
  a new version has a new URL. Without ?v= nothing changes (no-cache, checked every time).

install(app) must come before every other after_request hook: Flask runs them last-registered first, so this one
runs last, after the page has been translated."""
from __future__ import annotations

import gzip
import threading

from flask import Flask, request

MIN_BYTES = 1024
LEVEL = 6
YEAR = 365 * 24 * 3600
TYPES = ("text/", "application/json", "application/javascript", "application/manifest+json", "image/svg+xml")
STATIC_CACHE_MAX = 64                     # static files kept compressed in memory

_static: dict[tuple[str, str], bytes] = {}
_lock = threading.Lock()


def accepts_gzip(header: str | None) -> bool:
    """'gzip' in Accept-Encoding and not turned off with q=0."""
    for part in (header or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() in ("gzip", "*"):
            q = params.strip()
            return not (q.startswith("q=") and q[2:].strip() in ("0", "0.0", "0.00", "0.000"))
    return False


def compressible(resp) -> bool:
    """A complete 200 answer of a text type, not encoded yet. A static file counts as streamed (a file wrapper):
    it's handled on its own."""
    return (resp.status_code == 200 and (resp.direct_passthrough or not resp.is_streamed)
            and "Content-Encoding" not in resp.headers and any((resp.mimetype or "").startswith(t) for t in TYPES))


def _gzip_static(resp) -> bytes | None:
    etag, _ = resp.get_etag()
    key = (request.path, etag or "")
    with _lock:
        hit = _static.get(key)
    if hit is not None:
        if hasattr(resp.response, "close"):
            resp.response.close()                   # the file wasn't read: close it
        return hit
    resp.direct_passthrough = False
    raw = resp.get_data()
    if len(raw) < MIN_BYTES:
        return None
    out = gzip.compress(raw, LEVEL, mtime=0)
    with _lock:
        if len(_static) >= STATIC_CACHE_MAX:
            _static.pop(next(iter(_static)))
        _static[key] = out
    return out


def install(app: Flask) -> None:
    default_age = app.get_send_file_max_age

    def max_age(filename):
        return YEAR if request.args.get("v") else default_age(filename)
    app.get_send_file_max_age = max_age

    @app.after_request
    def compress(resp):
        if not compressible(resp):
            return resp
        resp.vary.add("Accept-Encoding")
        if not accepts_gzip(request.headers.get("Accept-Encoding")):
            return resp
        if resp.direct_passthrough:                      # a static file
            if not request.path.startswith("/static/"):
                return resp
            data = _gzip_static(resp)
            if data is None:
                return resp
        else:
            raw = resp.get_data()
            if len(raw) < MIN_BYTES:
                return resp
            data = gzip.compress(raw, LEVEL, mtime=0)
        etag, weak = resp.get_etag()
        resp.set_data(data)
        resp.headers["Content-Encoding"] = "gzip"
        if etag:
            resp.set_etag(etag + "-gz", weak)
        return resp
