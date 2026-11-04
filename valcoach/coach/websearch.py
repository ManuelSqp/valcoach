"""Web search for the coach (4.2): look things up instead of guessing, and show where it came from.

Three ways to search, picked under Settings › Web search, plus a backup used when the main one fails or
finds nothing:

* DuckDuckGo (default): its plain HTML search page, free and without a key. DuckDuckGo has no search API and
  blocks a server for a while when it searches a lot; then the backup takes over.
* SearXNG: your own search server (free, no key). It must answer JSON: in SearXNG's settings.yml,
  `search: formats: [html, json]`. valcoach asks `<url>/search?q=...&format=json`.
* Claude: Anthropic's web search tool, with the Claude API key from Settings › Claude. Costs US$ 10 per
  1,000 searches plus the tokens, counted in the Claude budget.

`research()` is what the coach uses: the model first writes up to three search queries for the question
(or none when the player's own data answers it), the results are searched, the best pages are read, and
the caller gives them to the model as numbered sources. Answers name the sources they used.

Reading pages: only http(s) pages on public addresses (no localhost, LAN or cloud metadata addresses, also
after redirects), at most 600 KB, text and HTML only, a few seconds each.
"""
from __future__ import annotations

import html as _html
import ipaddress
import logging
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

log = logging.getLogger(__name__)

PROVIDERS = {"": "Off", "duckduckgo": "DuckDuckGo (free, no setup)", "searxng": "SearXNG (your own search server)",
             "claude": "Claude's web search (Anthropic API)"}
SEARCH_USD = 0.01                  # Claude: US$ 10 per 1,000 searches
MAX_PAGE_BYTES = 600_000
PAGE_TIMEOUT = 8
UA = "valcoach (self-hosted Valorant coach)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
DDG_URL = "https://html.duckduckgo.com/html/"
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
CACHE_S = 6 * 3600


NAMES = {"duckduckgo": "DuckDuckGo", "searxng": "SearXNG", "claude": "Claude's web search"}
# what went wrong -> what the admin should know (fixed texts: nothing from the exception or the remote server
# is shown in the browser, only logged)
REASONS = {
    "unreachable": "{name} isn't reachable",
    "blocked": "{name} is blocking searches from this server for now (too many in a short time)",
    "http": "{name} answered with an error",
    "json_off": "{name} refused JSON: add json to search › formats in its settings.yml and restart it",
    "no_json": "{name} didn't answer JSON: add json to search › formats in its settings.yml",
    "no_key": "No Anthropic API key (Settings › Claude)",
    "budget": "This month's Claude budget is used up",
    "key_refused": "The Anthropic API key was refused",
}


class SearchError(RuntimeError):
    """A search that didn't work. provider and reason are keys of NAMES and REASONS; detail is for the log only."""

    def __init__(self, provider: str, reason: str, detail: str = ""):
        self.provider, self.reason, self.detail = provider, reason, detail
        super().__init__(f"{provider}: {reason}" + (f" ({detail})" if detail else ""))


def describe(e: BaseException) -> str:
    """A search error in words, built only from fixed texts (safe to show in the browser)."""
    if not isinstance(e, SearchError):
        return "the search failed"
    name = next((v for k, v in NAMES.items() if k == e.provider), "the search")
    text = next((v for k, v in REASONS.items() if k == e.reason), "{name} failed")
    return text.format(name=name)


# ----------------------------------------------------------------------------- settings
def _usable(store, p: str) -> bool:
    if p == "duckduckgo":
        return True
    if p == "searxng":
        return bool((store.get("searxng_url") or "").strip())
    if p == "claude":
        return bool(store.get("claude_api_key"))
    return False


def provider(store) -> str:
    """The main search that's set up and usable, or ''."""
    p = store.get("search_provider") or ""
    return p if p in PROVIDERS and _usable(store, p) else ""


def backup(store) -> str:
    """The search used when the main one fails or finds nothing, or ''."""
    b = store.get("search_backup") or ""
    return b if b in PROVIDERS and b != provider(store) and provider(store) and _usable(store, b) else ""


def _one(store, p: str):
    if p == "duckduckgo":
        return lambda q, n=6: duckduckgo(q, n)
    if p == "searxng":
        url = store.get("searxng_url").strip()
        return lambda q, n=6: searxng(url, q, n)
    if p == "claude":
        from .llm import claude_search_model
        key, model = store.get("claude_api_key"), claude_search_model(store)
        budget = float(store.get("claude_budget_usd") or 0)
        return lambda q, n=6: claude(key, model, q, n, budget)
    return None


def with_backup(main, spare):
    """Try the main search; when it fails or finds nothing, the backup."""
    if spare is None:
        return main

    def search(q, n=6):
        try:
            hits = main(q, n)
        except SearchError as e:
            log.info("web search: %s, trying the backup", e)
            return spare(q, n)
        return hits or spare(q, n)
    return search


def searcher(store):
    """search(query, n) for the configured provider (falling back to the backup), or None."""
    main = _one(store, provider(store))
    if main is None:
        return None
    return with_backup(main, _one(store, backup(store)))


# ----------------------------------------------------------------------------- providers
def _clean(s, limit: int = 400) -> str:
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()[:limit]


class _DDGParser(HTMLParser):
    """Results on DuckDuckGo's HTML page: a.result__a (title + link) and a.result__snippet in each result."""

    def __init__(self):
        super().__init__()
        self.out: list[dict] = []
        self._in: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        a = dict(attrs)
        cls = a.get("class") or ""
        if "result__a" in cls:
            self.out.append({"url": a.get("href") or "", "title": "", "snippet": ""})
            self._in, self._buf = "title", []
        elif "result__snippet" in cls and self.out:
            self._in, self._buf = "snippet", []

    def handle_endtag(self, tag):
        if tag == "a" and self._in and self.out:
            self.out[-1][self._in] = " ".join("".join(self._buf).split())
            self._in = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def _is_ddg(host: str | None) -> bool:
    """duckduckgo.com itself or one of its subdomains (not e.g. evil-duckduckgo.com)."""
    host = (host or "").lower().rstrip(".")
    return host == "duckduckgo.com" or host.endswith(".duckduckgo.com")


def _ddg_url(href: str) -> str:
    """DuckDuckGo sometimes links through //duckduckgo.com/l/?uddg=<the real address>."""
    if href.startswith("//"):
        href = "https:" + href
    p = urlparse(href)
    if _is_ddg(p.hostname) and p.path.startswith("/l/"):
        real = parse_qs(p.query).get("uddg", [""])[0]
        return unquote(real) if real else ""
    return href


def ddg_results(page: str) -> list[dict]:
    pr = _DDGParser()
    pr.feed(page)
    out, seen = [], set()
    for x in pr.out:
        url = _ddg_url(x["url"])
        host = urlparse(url).hostname or ""
        if not url.startswith(("http://", "https://")) or _is_ddg(host) or url in seen:
            continue                                     # ads go through duckduckgo.com/y.js
        seen.add(url)
        out.append({"title": _clean(x["title"], 160) or url, "url": url, "snippet": _clean(x["snippet"])})
    return out


def duckduckgo(query: str, n: int = 6, session=None) -> list[dict]:
    """DuckDuckGo's plain HTML search page (it has no search API). Free and without a key, but DuckDuckGo
    slows down or blocks a server that searches a lot: that's what the backup search is for."""
    hit = _cache.get(("duckduckgo", query))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1][:n]
    s = session or requests
    try:
        r = s.post(DDG_URL, data={"q": query, "b": "", "kl": "wt-wt"}, timeout=15,
                   headers={"User-Agent": BROWSER_UA, "Accept": "text/html", "Referer": "https://html.duckduckgo.com/"})
    except requests.RequestException as e:
        raise SearchError("duckduckgo", "unreachable", e.__class__.__name__) from None
    text = r.text if r.status_code == 200 else ""
    if r.status_code in (202, 403, 429) or "anomaly-modal" in text or "challenge-form" in text:
        raise SearchError("duckduckgo", "blocked", f"HTTP {r.status_code}")
    if r.status_code != 200:
        raise SearchError("duckduckgo", "http", f"HTTP {r.status_code}")
    out = ddg_results(text)
    if out:
        _cache[("duckduckgo", query)] = (time.time(), out)
    return out[:n]


def searxng(base: str, query: str, n: int = 6, session=None) -> list[dict]:
    hit = _cache.get(("searxng", query))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1][:n]
    s = session or requests
    try:
        r = s.get(base.rstrip("/") + "/search", params={"q": query, "format": "json", "safesearch": 1},
                  headers={"User-Agent": UA, "Accept": "application/json"}, timeout=15)
    except requests.RequestException as e:
        raise SearchError("searxng", "unreachable", e.__class__.__name__) from None
    if r.status_code == 403:
        raise SearchError("searxng", "json_off", "HTTP 403")
    if r.status_code != 200:
        raise SearchError("searxng", "http", f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise SearchError("searxng", "no_json") from None
    out, seen = [], set()
    for x in data.get("results") or []:
        url = str(x.get("url") or "")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append({"title": _clean(x.get("title"), 160) or url, "url": url, "snippet": _clean(x.get("content"))})
    _cache[("searxng", query)] = (time.time(), out)
    return out[:n]


def claude(api_key: str, model: str, query: str, n: int = 6, budget_usd: float = 0.0, session=None) -> list[dict]:
    """Anthropic's server-side web search: one search, the results with what Claude read in them."""
    from .llm import API_URL, API_VERSION, _add_usage, month_cost, price
    hit = _cache.get(("claude", query))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1][:n]
    if not api_key:
        raise SearchError("claude", "no_key")
    if budget_usd and month_cost() >= budget_usd:
        raise SearchError("claude", "budget", f"US$ {budget_usd:.2f}")
    body = {"model": model, "max_tokens": 1200,
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
            "messages": [{"role": "user", "content":
                          f"Search the web for: {query}\nThen quote the most useful facts from the results, briefly, "
                          "with their sources. Copy codes, names and numbers exactly."}]}
    s = session or requests
    try:
        r = s.post(API_URL, json=body, timeout=90,
                   headers={"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"})
    except requests.RequestException as e:
        raise SearchError("claude", "unreachable", e.__class__.__name__) from None
    if r.status_code in (401, 403):
        raise SearchError("claude", "key_refused")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        raise SearchError("claude", "http", f"HTTP {r.status_code} {msg[:160]}".strip())
    data = r.json()
    u = data.get("usage") or {}
    tin, tout = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
    searches = int((u.get("server_tool_use") or {}).get("web_search_requests") or 1)
    _add_usage(model, tin, tout, price(model, tin, tout) + searches * SEARCH_USD)
    results: dict[str, dict] = {}
    for block in data.get("content") or []:
        if block.get("type") == "web_search_tool_result" and isinstance(block.get("content"), list):
            for x in block["content"]:
                url = str(x.get("url") or "")
                if url.startswith(("http://", "https://")) and url not in results:
                    results[url] = {"title": _clean(x.get("title"), 160) or url, "url": url, "snippet": ""}
        elif block.get("type") == "text":
            for c in block.get("citations") or []:
                url = str(c.get("url") or "")
                if url in results:
                    quote = _clean(c.get("cited_text"), 300)
                    if quote and quote not in results[url]["snippet"]:
                        results[url]["snippet"] = (results[url]["snippet"] + " " + quote).strip()[:600]
    out = list(results.values())
    _cache[("claude", query)] = (time.time(), out)
    return out[:n]


# ----------------------------------------------------------------------------- reading a page
def public_url(url: str) -> bool:
    """http(s) on a public address: never the server itself, the LAN or cloud metadata."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


def page_text(url: str, limit: int = 4000, session=None) -> str:
    """The readable text of a public web page ('' when it can't be read)."""
    s = session or requests
    for _ in range(4):                                  # follow redirects ourselves, checking each address
        if not public_url(url):
            return ""
        try:
            r = s.get(url, headers={"User-Agent": UA, "Accept": "text/html,text/plain"}, timeout=PAGE_TIMEOUT,
                      allow_redirects=False, stream=True)
        except requests.RequestException:
            return ""
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        break
    else:
        return ""
    try:
        if r.status_code != 200:
            return ""
        ctype = (r.headers.get("content-type") or "").lower()
        if ctype and not ctype.startswith(("text/html", "text/plain", "application/xhtml")):
            return ""
        raw = b""
        for chunk in r.iter_content(65536):
            raw += chunk
            if len(raw) > MAX_PAGE_BYTES:
                break
    except requests.RequestException:
        return ""
    finally:
        r.close()
    text = raw.decode(r.encoding or "utf-8", errors="replace")
    return html_text(text)[:limit]


def html_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|form|iframe)\b.*?</\1\s*>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|pre)>", "\n", text)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = (re.sub(r"[ \t\r\f\v]+", " ", x).strip() for x in text.split("\n"))
    return "\n".join(x for x in lines if x)


# ----------------------------------------------------------------------------- for the coach
QUERY_SYSTEM = """You help a Valorant coach answer a player's question. Decide whether a web search would help:
- Search for things that change or that you might not know exactly: patch changes, agent abilities and
  costs, the current map pool, lineups, pro players and teams, aim trainer playlists, scenarios and share codes,
  settings, crosshair codes, guides.
- Don't search for what the player's own data below answers (their stats, rounds, habits): return no queries.
- At most {n} short queries in English, the way you'd type them into a search engine. Include "Valorant" or
  "KovaaK's" where it helps."""
QUERY_SCHEMA = {"type": "object", "properties": {
    "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                "description": "search queries, or [] when no search is needed"}}, "required": ["queries"]}

SOURCES_RULES = """
Web results are numbered [1], [2] ... below. They can be outdated or wrong: prefer the player's own data for
anything about the player, use the web for facts about the game, and say when sources disagree. Name the
numbers of the sources you used in "sources" (and only those). Copy codes, names and numbers from them exactly;
never invent a share code, a scenario name or a link."""


def queries_for(llm, question: str, context: str = "", n: int = 3) -> list[str]:
    from .prompts import field_guide
    user = (f"What the coach already knows:\n{context[:3000]}\n\n" if context else "") + f"Question: {question}"
    try:
        out = llm.chat_json(QUERY_SYSTEM.format(n=n) + field_guide(QUERY_SCHEMA), user, QUERY_SCHEMA)
    except Exception:
        return []
    qs = []
    for q in out.get("queries") or []:
        q = re.sub(r"\s+", " ", str(q)).strip()[:120]
        if q and q.lower() not in {x.lower() for x in qs}:
            qs.append(q)
    return qs[:n]


def research(search, queries: list[str], per_query: int = 4, read: int = 3, page_chars: int = 2500,
             reader=None) -> tuple[list[dict], list[str]]:
    """Run the searches; read the best few pages. -> (sources [{n, title, url, snippet, text}], errors)"""
    sources: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    for q in queries:
        try:
            hits = search(q, per_query)
        except Exception as e:                       # a broken search never breaks the answer
            log.warning("web search %r: %s", q, e)
            msg = describe(e)
            if msg not in errors:
                errors.append(msg)
            continue
        for h in hits:
            if h["url"] in seen:
                continue
            seen.add(h["url"])
            sources.append(dict(h, text=""))
    # read the top result of each query first, then the rest
    reader = reader or page_text
    for s in sources[:read]:
        s["text"] = reader(s["url"], page_chars) or ""
    for i, s in enumerate(sources, 1):
        s["n"] = i
    return sources[:10], errors


def sources_block(sources: list[dict]) -> str:
    if not sources:
        return ""
    parts = []
    for s in sources:
        body = s.get("text") or s.get("snippet") or ""
        parts.append(f"[{s['n']}] {s['title']} ({s['url']})\n{body[:2500]}")
    return "\n\nWeb results:\n" + "\n\n".join(parts)


def cited(sources: list[dict], numbers) -> list[dict]:
    """The sources an answer says it used, as {title, url} (numbers it made up are dropped)."""
    by = {s["n"]: s for s in sources}
    out, seen = [], set()
    for x in numbers or []:
        try:
            s = by.get(int(x))
        except (TypeError, ValueError):
            continue
        if s and s["url"] not in seen:
            seen.add(s["url"])
            out.append({"title": s["title"], "url": s["url"]})
    return out[:6]


# ----------------------------------------------------------------------------- KovaaK's share codes
SHARE_CODE_RE = re.compile(r"\bKovaaKs[A-Z][A-Za-z0-9]{5,60}\b", re.I)


def find_share_codes(search, queries: list[str], known: set[str] | None = None, reader=None,
                     limit: int = 12) -> tuple[list[dict], list[str]]:
    """KovaaK's playlists found on the web: [{name, code, url, title}]. The name is the text in front of the
    code on its line ("Voltaic Easy - KovaaKs..."), else the page title."""
    known = {k.lower() for k in (known or set())}
    sources, errors = research(search, queries, per_query=5, read=6, page_chars=60000, reader=reader)
    found: dict[str, dict] = {}
    for s in sources:
        for text in (s.get("snippet") or "", s.get("text") or ""):
            for line in text.split("\n"):
                for m in SHARE_CODE_RE.finditer(line):
                    code = m.group(0)
                    if code.lower() in known or code.lower() in found:
                        continue
                    before = re.sub(r"[\s:–—|\-=>•*#\[\]()]+$", "", line[:m.start()]).strip()
                    before = re.split(r"[.!?]\s|share ?code", before, flags=re.I)[-1].strip(" :-–—")
                    name = before[-60:].strip() if 2 < len(before) <= 80 else ""
                    found[code.lower()] = {"name": name or s["title"][:60], "code": code, "url": s["url"], "title": s["title"]}
                    if len(found) >= limit:
                        return list(found.values()), errors
    return list(found.values()), errors
