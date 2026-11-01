"""The model picker next to every button that runs the model.

Choices: the local default, the other models installed in Ollama, and the Claude models from
Settings › Claude (only with an API key, and only for admins and users an admin gave "Claude").
What you pick is remembered per user as the default for the next run."""
from __future__ import annotations

import json
import time

import requests
from flask import g, request

from ..coach.llm import LABELS

PERM = "claude"
_tags: dict[str, tuple[float, list[str]]] = {}


def local_models(url: str) -> list[str]:
    """Models installed in Ollama (cached for 2 minutes, also when Ollama is down)."""
    hit = _tags.get(url)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    names: list[str] = []
    try:
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=1.5)
        if r.ok:
            names = sorted(m.get("name") for m in r.json().get("models", []) if m.get("name"))
    except (requests.RequestException, ValueError):
        pass
    _tags[url] = (time.time(), names)
    return names


def claude_models(store) -> list[str]:
    if not store.get("claude_api_key"):
        return []
    return [m.strip() for m in store.get("claude_models").split(",") if m.strip()]


def choices(store, user, with_local_list: bool = True) -> list[dict]:
    default = store.get("ollama_model")
    out = [{"value": "", "label": f"{default} (local)", "kind": "local"}]
    if with_local_list:
        for m in local_models(store.get("ollama_url")):
            if m not in (default, f"{default}:latest") and not m.startswith(f"{default}:"):
                out.append({"value": f"ollama:{m}", "label": f"{m} (local)", "kind": "local"})
    if user is not None and user.can(PERM):
        for m in claude_models(store):
            out.append({"value": f"claude:{m}", "label": LABELS.get(m, m), "kind": "claude"})
    return out


def last_choice(user) -> str:
    try:
        return str(json.loads(user.prefs or "{}").get("llm") or "")
    except ValueError:
        return ""


def picked(store) -> str:
    """The model sent with the form (field "llm"), checked against what this user may use; remembered."""
    user = g.user
    want = request.form.get("llm")
    if want is None:
        if request.is_json:
            want = (request.get_json(silent=True) or {}).get("llm")
    want = str(want if want is not None else last_choice(user))
    allowed = {c["value"] for c in choices(store, user)}
    if want not in allowed:
        want = ""
    if want != last_choice(user):
        try:
            prefs = json.loads(user.prefs or "{}")
        except ValueError:
            prefs = {}
        prefs["llm"] = want
        store.update_user(user.id, prefs=json.dumps(prefs))
    return want
