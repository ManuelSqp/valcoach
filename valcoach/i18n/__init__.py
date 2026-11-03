"""The interface in other languages (4.0: English and German).

Pages are written in English. For a user who picked another language, every finished HTML page is
translated on its way out: each piece of text between tags and the text in title, placeholder,
aria-label, data-q (confirm questions) and button values is looked up in the catalog
(valcoach/i18n/<lang>.json). Text the browser adds later (JavaScript) goes through the same catalog in
the page (static/i18n.js). Discord posts and notifications use it too.

Lookup for one piece of text (whitespace squeezed, trimmed):
  1. exactly as it is
  2. with every number written as # ("12 of 20 won" -> "# of # won"); the numbers go back in order
  3. patterns with named parts ("{name} can't play" -> "{name} kann nicht spielen"); a part may
     itself be translated if it is in the catalog
Anything not found stays English: names, notes, strats and the coach's texts are never touched
(the coach writes in each player's coaching language already).
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

LANGS = {"en": "English", "de": "Deutsch"}
DEFAULT = "en"
_DIR = Path(__file__).resolve().parent
NUM_RE = re.compile(r"(?<![\w#])[-+]?\d+(?:[.,'’]\d+)*(?![\w])")
WS_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"(<!--.*?-->|<[^>]+>)", re.S)
ATTR_RE = re.compile(r'(\s(?:title|placeholder|aria-label|data-q|data-confirm|alt)=")([^"]*)(")')
VALUE_RE = re.compile(r'(\svalue=")([^"]*)(")')
SKIP_TAGS = {"script", "style", "pre", "code", "textarea", "kbd"}
LETTER_RE = re.compile(r"[A-Za-z]")
MARK = "\ue000"                       # a number, inside the catalog ("#" there; "#TAG" and "#channel" stay literal)
MARK_RE = re.compile(r"#(?![A-Za-z])")


class Catalog:
    def __init__(self, data: dict):
        self.exact: dict[str, str] = {}
        self.patterns: list[tuple[re.Pattern, str, list[str], bool]] = []
        for k, v in (data or {}).items():
            if not isinstance(v, str) or not v or k.startswith("_"):
                continue
            k = MARK_RE.sub(MARK, WS_RE.sub(" ", k).strip())
            v = MARK_RE.sub(MARK, v)
            if re.search(r"\{\w+\}", k):
                names = re.findall(r"\{(\w+)\}", k)
                rx = "^" + re.sub(r"\\\{(\w+)\\\}", lambda m: f"(?P<{m.group(1)}>.+?)", re.escape(k)) + "$"
                # a pattern with little fixed text ("{x} on {y}") only counts when all its parts are known
                # (an agent, a map, a phrase): otherwise it would change people's own notes
                fixed = len(LETTER_RE.findall(re.sub(r"\{\w+\}", "", k)))
                loose = fixed < 4 or (fixed < 8 and k.startswith("{"))
                try:
                    self.patterns.append((re.compile(rx, re.S), v, names, loose))
                except re.error:
                    continue
            else:
                self.exact[k] = v
        # longest (most specific) patterns first
        self.patterns.sort(key=lambda p: -len(p[0].pattern))

    def lookup(self, s: str, depth: int = 0) -> str | None:
        if s in self.exact:
            return self.exact[s]
        nums = NUM_RE.findall(s)
        if nums:
            key = NUM_RE.sub(MARK, s)
            t = self.exact.get(key)
            if t is not None and t.count(MARK) == len(nums):
                it = iter(nums)
                return re.sub(MARK, lambda _m: next(it), t)
        if depth > 0:                         # parts of a pattern: only whole known phrases
            return None
        key = NUM_RE.sub(MARK, s) if nums else None
        for pat in self.patterns:                 # most specific first; each on the text and on its #-form
            out = self._apply(pat, s, depth)
            if out is None and key is not None:
                out = self._apply(pat, key, depth, nums)
            if out is not None:
                return out
        return None

    def _apply(self, pat, s: str, depth: int, nums: list[str] | None = None) -> str | None:
        """One pattern on s. With nums, s is the #-form: each part gets its own numbers back before it's looked
        up, and the numbers in the pattern's fixed text are filled in afterwards."""
        rx, tmpl, names, loose = pat
        m = rx.match(s)
        if not m:
            return None
        out, known, used = tmpl, 0, set()
        for n in names:
            part = m.group(n)
            if nums is not None and MARK in part:
                i0 = s[:m.start(n)].count(MARK)
                k = part.count(MARK)
                it = iter(nums[i0:i0 + k])
                part = re.sub(MARK, lambda _m: next(it), part)
                used.update(range(i0, i0 + k))
            tr = self.lookup(part, depth + 1) if LETTER_RE.search(part) else None
            known += tr is not None or not LETTER_RE.search(part)
            out = out.replace("{" + n + "}", (tr if tr is not None else part).replace(MARK, "#"))
        # a pattern with little fixed text ("{x} on {y}") only counts when all its parts are known
        if loose and known < len(names):
            return None
        if nums is not None:
            rest = [x for i, x in enumerate(nums) if i not in used]
            if out.count(MARK) != len(rest):
                return None
            it = iter(rest)
            out = re.sub(MARK, lambda _m: next(it), out)
        return out

    def text(self, s: str) -> str:
        """One piece of text, keeping its leading and trailing white space."""
        core = s.strip()
        if not core or not LETTER_RE.search(core):
            return s
        norm = WS_RE.sub(" ", core)
        t = self.lookup(norm)
        if t is None:
            return s
        i = s.find(core[0])
        return s[:i] + t + s[i + len(core):]


@lru_cache(maxsize=None)
def catalog(lang: str) -> Catalog | None:
    if lang == DEFAULT or lang not in LANGS:
        return None
    p = _DIR / f"{lang}.json"
    try:
        return Catalog(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def tr(text: str, lang: str | None) -> str:
    """Plain text (Discord posts, notifications, flash messages): line by line."""
    c = catalog(lang or DEFAULT)
    if c is None or not text:
        return text
    return "\n".join(_tr_line(c, line) for line in text.split("\n"))


def _tr_line(c: Catalog, line: str) -> str:
    t = c.text(line)
    if t != line:
        return t
    # "**Title** rest" / "• item": translate the pieces around Markdown marks
    parts = re.split(r"(\*\*|__|•|·|: )", line)
    if len(parts) == 1:
        return line
    return "".join(p if p in ("**", "__", "•", "·", ": ") else c.text(p) for p in parts)


def translate_html(page: str, lang: str | None) -> str:
    """A whole HTML page: text between tags and the attributes people read."""
    c = catalog(lang or DEFAULT)
    if c is None:
        return page
    out = []
    skip: list[str] = []
    for tok in TAG_RE.split(page):
        if not tok:
            continue
        if tok[0] == "<" and tok.endswith(">"):
            if tok.startswith("<!--"):
                out.append(tok)
                continue
            m = re.match(r"</?\s*([a-zA-Z0-9-]+)", tok)
            name = m.group(1).lower() if m else ""
            closing = tok.startswith("</")
            opens_skip = name in SKIP_TAGS and not closing and not tok.endswith("/>")
            if name in SKIP_TAGS and closing and skip and skip[-1] == name:
                skip.pop()
            # the tag's own attributes are translated even when its content isn't (a textarea's placeholder)
            if not skip and not closing and ('translate="no"' not in tok):
                tok = ATTR_RE.sub(lambda a: a.group(1) + _attr(c, a.group(2)) + a.group(3), tok)
                if name in ("input", "button") and re.search(r'type="(submit|button|reset)"', tok):
                    tok = VALUE_RE.sub(lambda a: a.group(1) + _attr(c, a.group(2)) + a.group(3), tok)
            if opens_skip:
                skip.append(name)
            out.append(tok)
            continue
        if skip:
            out.append(tok)
            continue
        if LETTER_RE.search(tok):
            raw = html.unescape(tok)
            t = c.text(raw)
            out.append(html.escape(t, quote=False) if t != raw else tok)
        else:
            out.append(tok)
    return "".join(out)


def _attr(c: Catalog, v: str) -> str:
    raw = html.unescape(v)
    t = c.text(raw)
    return html.escape(t) if t != raw else v


def pick(accept: str | None) -> str:
    """The best interface language for a browser's Accept-Language header (people not logged in)."""
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return DEFAULT


def client_catalog(lang: str) -> dict:
    """The catalog as the browser's i18n.js reads it."""
    p = _DIR / f"{lang}.json"
    try:
        return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}
