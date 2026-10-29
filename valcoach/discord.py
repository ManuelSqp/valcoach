"""Discord webhooks: match prep (comps + game plans) and the weekly focus.

A webhook URL is all it needs (channel settings -> Integrations -> Webhooks -> New Webhook).
Posts never ping anyone (allowed_mentions is empty)."""
from __future__ import annotations

import re
import time

import requests

WEBHOOK_RE = re.compile(r"^https://(?:canary\.|ptb\.)?(?:discord|discordapp)\.com/api/webhooks/\d+/[\w-]+$")
RED, TEAL, AMBER = 0xFF4655, 0x2DD4BF, 0xF2B84B
MAX_EMBEDS = 10


class DiscordError(RuntimeError):
    pass


def valid_url(url: str) -> bool:
    return bool(WEBHOOK_RE.match((url or "").strip()))


def _cut(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def post(url: str, content: str = "", embeds: list[dict] | None = None, session=None) -> None:
    if not valid_url(url):
        raise DiscordError("That's not a Discord webhook URL")
    embeds = embeds or []
    chunks = [embeds[i:i + MAX_EMBEDS] for i in range(0, len(embeds), MAX_EMBEDS)] or [[]]
    for i, chunk in enumerate(chunks):
        body = {"username": "valcoach", "allowed_mentions": {"parse": []}, "embeds": chunk}
        if i == 0 and content:
            body["content"] = _cut(content, 1900)
        for attempt in range(3):
            r = (session or requests).post(url, json=body, timeout=15)
            if r.status_code == 429 and attempt < 2:          # rate limited: wait as told
                try:
                    time.sleep(min(10.0, float(r.json().get("retry_after", 2))))
                except Exception:
                    time.sleep(2)
                continue
            if r.status_code >= 300:
                raise DiscordError(f"Discord answered {r.status_code}: {_cut(r.text, 200)}")
            break


def post_file(url: str, content: str, filename: str, data: bytes, session=None) -> None:
    """One message with an attached file (e.g. a strat board as PNG)."""
    import json as _json
    if not valid_url(url):
        raise DiscordError("That's not a Discord webhook URL")
    payload = {"username": "valcoach", "allowed_mentions": {"parse": []}, "content": _cut(content, 1900)}
    r = (session or requests).post(url, data={"payload_json": _json.dumps(payload)},
                                   files={"files[0]": (filename, data, "image/png")}, timeout=30)
    if r.status_code >= 300:
        raise DiscordError(f"Discord answered {r.status_code}: {_cut(r.text, 200)}")


def prep_embeds(team_name: str, maps: list[dict], plans: dict[str, dict]) -> list[dict]:
    """maps: [{"map", "comps": [comp, ...]}] (top comps); plans: map -> saved game plans."""
    out = []
    for m in maps:
        lines = []
        for i, c in enumerate(m["comps"][:3], 1):
            picks = " · ".join(f"**{p['agent']}** ({p['player']})" for p in c["picks"])
            lines.append(f"**{i}.** {picks}  `{c['pattern']}`")
        fields = []
        for p in (plans.get(m["map"]) or {}).get("plans", [])[:3]:
            steps = "\n".join(f"• **{s['player']}**: {s['what']}" for s in p.get("steps", []) if s.get("what"))
            extra = f"\n⏱ {p['timing']}" if p.get("timing") else ""
            if p.get("if_then"):
                extra += "\n↪ " + " / ".join(p["if_then"][:2])
            fields.append({"name": _cut(f"{'⚔' if p.get('side') == 'attack' else '🛡'} {p['title']}", 256),
                           "value": _cut(f"{p.get('idea', '')}\n{steps}{extra}", 1024)})
        out.append({"title": f"{m['map']}", "color": RED, "description": _cut("\n".join(lines) or "No comp (not enough data).", 4000),
                    "fields": fields[:6], "footer": {"text": f"{team_name} · valcoach"}})
    return out


def focus_embeds(team_name: str, week: str, players: list[dict]) -> list[dict]:
    """players: [{"name", "roles", "focus": {...}}]"""
    out = []
    for p in players:
        f = p.get("focus") or {}
        if not f.get("focus"):
            continue
        n = f.get("number_to_watch") or {}
        body = f"{f.get('why', '')}\n" + "\n".join(f"• {x}" for x in f.get("in_game", []))
        if n.get("metric"):
            body += f"\n📈 {n['metric']}: {n.get('now', '?')} → {n.get('goal', '?')}"
        roles = f" · {', '.join(p['roles'])}" if p.get("roles") else ""
        out.append({"title": _cut(f"{p['name']}{roles}: {f['focus']}", 256), "description": _cut(body, 4000), "color": TEAL})
    if out:
        out[-1]["footer"] = {"text": f"{team_name} · week {week} · valcoach"}
    return out
