"""Which model answers: the local Ollama model, or Claude through Anthropic's API.

Every model call in Nexus goes through `chat_json(system, user, schema) -> dict`. `make_llm()`
builds the client for a choice like "ollama:gemma4:26b" or "claude:claude-sonnet-5-5" ("" = the
local default). Claude answers in the JSON format by being made to "call" a tool whose input is the
schema. Every Claude call is priced from its token counts and added up per day and month in
data/llm_usage.json; a monthly budget stops Claude calls (the local model takes over if fallback is on).
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import requests

from . import ollama as _ollama
from .ollama import OllamaError

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
# US$ per million tokens (input, output), from Anthropic's price list in October 2026. Unknown models are
# priced like the most expensive one, so the budget errs on the safe side.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
HAIKU_LONG = (0.50, 2.50)          # Haiku 5.5 above 100K input tokens
LABELS = {"claude-haiku-5-5": "Claude Haiku 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-opus-5-5": "Claude Opus 5.5"}
RECENT: "deque[tuple[float, float, int, str, float]]" = deque(maxlen=5000)   # (time, seconds, out tokens, model, US$)

_usage_lock = threading.Lock()
_usage_file: Path | None = None


class NoAnswer(RuntimeError):
    """The model answered, but with nothing usable."""


def user_error(e: BaseException) -> str:
    """What a person may see when the model couldn't answer: our own messages about the model (Ollama down,
    no Claude key, budget used up ...), never other exceptions (paths, internals: those go to the server log)."""
    if isinstance(e, (OllamaError, ClaudeError, NoAnswer)):
        return str(e)[:300] or "The model didn't answer."
    return "Something went wrong while the coach was answering. The server log has the details."


def claude_search_model(store) -> str:
    """The model that runs Claude web searches: the cheapest one offered (Haiku if it's in the list)."""
    offered = [m.strip() for m in (store.get("claude_models") or "").split(",") if m.strip()]
    for m in offered:
        if "haiku" in m:
            return m
    return min(offered, key=lambda m: PRICES.get(m, max(PRICES.values()))[0]) if offered else "claude-haiku-5-5"


class ClaudeError(RuntimeError):
    """The API can't be used right now (key, credit, budget, network): the local model may take over."""


def set_usage_file(path: Path) -> None:
    global _usage_file
    _usage_file = Path(path)


def price(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, max(PRICES.values()))
    if model == "claude-haiku-5-5" and tokens_in > 100_000:
        pin, pout = HAIKU_LONG
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


def read_usage() -> dict:
    if _usage_file is None or not _usage_file.exists():
        return {"months": {}, "days": {}}
    try:
        return json.loads(_usage_file.read_text())
    except ValueError:
        return {"months": {}, "days": {}}


def month_cost(month: str | None = None) -> float:
    m = read_usage().get("months", {}).get(month or datetime.now().strftime("%Y-%m"), {})
    return sum(v.get("usd", 0) for v in m.values())


def _add_usage(model: str, tokens_in: int, tokens_out: int, usd: float) -> None:
    if _usage_file is None:
        return
    now = datetime.now()
    with _usage_lock:
        d = read_usage()
        for scope, key in (("months", now.strftime("%Y-%m")), ("days", now.strftime("%Y-%m-%d"))):
            e = d.setdefault(scope, {}).setdefault(key, {}).setdefault(model, {"in": 0, "out": 0, "usd": 0.0, "calls": 0})
            e["in"] += tokens_in
            e["out"] += tokens_out
            e["usd"] = round(e["usd"] + usd, 6)
            e["calls"] += 1
        days = sorted(d["days"])
        for old in days[:-62]:                     # keep two months of days
            d["days"].pop(old, None)
        _usage_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = _usage_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        tmp.replace(_usage_file)


class ClaudeLLM:
    """Same interface as Ollama: chat_json(), check(), summary(), .model"""

    def __init__(self, api_key: str, model: str, temperature: float = 0.3, timeout_s: int = 300,
                 budget_usd: float = 0.0, max_tokens: int = 4096, session=None):
        self.api_key = api_key.strip()
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.budget_usd = budget_usd
        self.max_tokens = max_tokens
        self.s = session or requests
        self._stats: list[dict] = []
        self._lock = threading.Lock()
        self.cost = 0.0

    def check(self) -> None:
        if not self.api_key:
            raise ClaudeError("No Anthropic API key: add it under Settings › Claude.")
        if self.budget_usd and month_cost() >= self.budget_usd:
            raise ClaudeError(f"This month's Claude budget (US$ {self.budget_usd:.2f}) is used up.")

    def chat_json(self, system: str, user: str, schema: dict, retries: int = 3) -> dict:
        self.check()
        max_tokens = self.max_tokens
        last = None
        for attempt in range(retries + 1):
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": self.temperature, "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "tools": [{"name": "answer", "description": "Give your answer in exactly this format.", "input_schema": schema}],
                    "tool_choice": {"type": "tool", "name": "answer"}}
            t0 = time.monotonic()
            try:
                r = self.s.post(API_URL, json=body, timeout=self.timeout_s,
                                headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"})
            except requests.RequestException as e:
                last = f"no answer from the API ({e.__class__.__name__})"
                time.sleep(min(20, 2 ** attempt))
                continue
            if r.status_code in (429, 500, 502, 503, 504, 529):
                last = f"HTTP {r.status_code}: {_err(r)}"
                try:
                    wait = float(r.headers.get("retry-after", 0))
                except (TypeError, ValueError):
                    wait = 0
                time.sleep(min(60, max(wait, 2 ** (attempt + 1))))
                continue
            if r.status_code in (401, 403):
                raise ClaudeError("The Anthropic API key was refused (check it under Settings › Claude).")
            if r.status_code != 200:
                msg = _err(r)
                if "credit" in msg.lower() or "billing" in msg.lower():
                    raise ClaudeError(f"Anthropic API: {msg}")
                raise ClaudeError(f"Anthropic API rejected the request (HTTP {r.status_code}): {msg}")
            data = r.json()
            u = data.get("usage") or {}
            tin, tout = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
            usd = price(self.model, tin, tout)
            wall = time.monotonic() - t0
            self.cost += usd
            _add_usage(self.model, tin, tout, usd)
            RECENT.append((time.time(), wall, tout, self.model, usd))
            with self._lock:
                self._stats.append({"wall_s": wall, "in": tin, "out": tout})
            block = next((c for c in data.get("content") or [] if c.get("type") == "tool_use"), None)
            if block and isinstance(block.get("input"), dict) and data.get("stop_reason") != "max_tokens":
                return block["input"]
            if data.get("stop_reason") == "max_tokens":
                max_tokens = min(16000, max_tokens * 2)       # cut off: try again with more room
                last = "the answer was cut off"
                continue
            last = "the answer had no data"
        raise ClaudeError(f"Anthropic API request failed: {last}")

    def summary(self) -> dict:
        with self._lock:
            s = list(self._stats)
        if not s:
            return {}
        wall = sum(x["wall_s"] for x in s)
        return {"requests": len(s), "avg_s_per_request": round(wall / len(s), 1),
                "gen_tok_per_s": round(sum(x["out"] for x in s) / wall, 1) if wall else None,
                "avg_gen_tokens": round(sum(x["out"] for x in s) / len(s)), "cost_usd": round(self.cost, 4)}


class WithFallback:
    """Claude first; if the API can't be used (key, credit, budget, network), the local model takes over
    for the rest of the job."""

    def __init__(self, primary: ClaudeLLM, make_fallback):
        self.primary, self._make = primary, make_fallback
        self.fallback = None
        self.reason = ""
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return f"{self.primary.model} → {self.fallback.model} ({self.reason})" if self.fallback else self.primary.model

    def _switch(self, e: Exception) -> None:
        with self._lock:
            if self.fallback is None:
                self.reason = str(e)[:160]
                fb = self._make()
                fb.check()
                self.fallback = fb

    def check(self) -> None:
        try:
            self.primary.check()
        except ClaudeError as e:
            self._switch(e)

    def chat_json(self, system: str, user: str, schema: dict, **kw) -> dict:
        if self.fallback is None:
            try:
                return self.primary.chat_json(system, user, schema, **kw)
            except ClaudeError as e:
                self._switch(e)
        return self.fallback.chat_json(system, user, schema, **kw)

    def summary(self) -> dict:
        out = self.primary.summary()
        if self.fallback is not None:
            out = {**(self.fallback.summary() or {}), "cost_usd": out.get("cost_usd", 0), "fell_back": self.reason}
        return out


def _err(r) -> str:
    try:
        j = r.json()
        return str((j.get("error") or {}).get("message") or j)[:300]
    except ValueError:
        return (r.text or "")[:300]


def make_llm(cfg, choice: str | None = None):
    """choice: "" (local default), "ollama:<model>", "claude:<model>". Call .check() on the result."""
    choice = (cfg.llm if choice is None else choice) or ""
    o = cfg.ollama

    def local(model: str | None = None):
        return _ollama.Ollama(o.url, model or o.model, o.temperature, o.num_ctx, o.timeout_s, o.think)   # looked up now (tests swap it)
    if choice.startswith("claude:"):
        c = cfg.claude
        primary = ClaudeLLM(c.api_key, choice.split(":", 1)[1], o.temperature, max(60, o.timeout_s), c.budget_usd)
        return WithFallback(primary, local) if c.fallback else primary
    if choice.startswith("ollama:") and choice.split(":", 1)[1]:
        return local(choice.split(":", 1)[1])
    return local()


def label(choice: str, default_local: str) -> str:
    if choice.startswith("claude:"):
        m = choice.split(":", 1)[1]
        return LABELS.get(m, m)
    m = choice.split(":", 1)[1] if choice.startswith("ollama:") else default_local
    return f"{m} (local)"


__all__ = ["ClaudeError", "ClaudeLLM", "WithFallback", "make_llm", "price", "month_cost", "read_usage", "OllamaError"]
