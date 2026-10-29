"""Minimal Ollama chat client with structured (JSON-schema) output and speed stats."""
from __future__ import annotations

import json
import re
import threading
import time

import requests

# "" = leave it to the model's default, "off" / "on" = send Ollama's `think` flag
THINK_CHOICES = ("", "off", "on")


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, url: str, model: str, temperature: float = 0.3, num_ctx: int = 16384,
                 timeout_s: int = 300, think: str = ""):
        self.url = url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.timeout_s = timeout_s
        self.think = think if think in THINK_CHOICES else ""
        self._stats: list[dict] = []
        self._lock = threading.Lock()

    def check(self) -> None:
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            raise OllamaError(f"Ollama not reachable at {self.url}: {e}") from e
        names = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
        wanted = {self.model.lower(), f"{self.model.lower()}:latest"}
        match = next((n for n in names if n.lower() in wanted), None)
        if match is None:
            raise OllamaError(f"Model '{self.model}' is not installed in Ollama "
                              f"(run: ollama pull {self.model}). Installed: {sorted(names)}")
        self.model = match           # use the exact installed spelling

    def chat_json(self, system: str, user: str, schema: dict, retries: int = 2) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        if self.think:
            payload["think"] = self.think == "on"
        last_err = None
        for _ in range(retries + 1):
            t0 = time.monotonic()
            try:
                r = requests.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout_s)
            except requests.RequestException as e:
                last_err = e
                continue
            if r.status_code == 400:
                # bad request (e.g. model doesn't support `think`): retrying won't help
                raise OllamaError(f"Ollama rejected the request: {_error_text(r)}")
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}: {_error_text(r)}"
                continue
            body = r.json()
            self._record(body, time.monotonic() - t0)
            content = body.get("message", {}).get("content", "")
            try:
                return parse_json(content)
            except ValueError as e:
                last_err = e
        raise OllamaError(f"Ollama request failed: {last_err}")

    # ---- speed stats --------------------------------------------------
    def _record(self, body: dict, wall_s: float) -> None:
        msg = body.get("message", {}) or {}
        thinking = msg.get("thinking") or ""
        inline = re.findall(r"<think>(.*?)</think>", msg.get("content", "") or "", re.S)
        with self._lock:
            self._stats.append({
                "wall_s": wall_s,
                "prompt_tokens": body.get("prompt_eval_count") or 0,
                "prompt_s": (body.get("prompt_eval_duration") or 0) / 1e9,
                "gen_tokens": body.get("eval_count") or 0,
                "gen_s": (body.get("eval_duration") or 0) / 1e9,
                "thinking_chars": len(thinking) + sum(len(x) for x in inline),
            })

    def summary(self) -> dict:
        """Averages over all requests so far (for comparing models)."""
        with self._lock:
            s = list(self._stats)
        if not s:
            return {}

        def rate(tok: str, sec: str) -> float | None:
            t, d = sum(x[tok] for x in s), sum(x[sec] for x in s)
            return round(t / d, 1) if d > 0 else None

        return {
            "requests": len(s),
            "avg_s_per_request": round(sum(x["wall_s"] for x in s) / len(s), 1),
            "prompt_tok_per_s": rate("prompt_tokens", "prompt_s"),
            "gen_tok_per_s": rate("gen_tokens", "gen_s"),
            "avg_gen_tokens": round(sum(x["gen_tokens"] for x in s) / len(s)),
            "thinking": any(x["thinking_chars"] > 0 for x in s),
        }


def _error_text(r: requests.Response) -> str:
    try:
        return str(r.json().get("error", r.text))[:300]
    except ValueError:
        return r.text[:300]


def parse_json(text: str) -> dict:
    text = text.strip()
    # some reasoning models put their thinking inline; drop it before parsing
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)   # tolerate code fences / chatter
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"No JSON object in model output: {text[:200]}")
