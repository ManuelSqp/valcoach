"""Push notifications for the installed app (and desktop browsers): Web Push with VAPID keys.

The server makes its own key pair the first time it's needed (kept in the database, the private
key is never shown). Each browser / phone that turns notifications on stores a subscription;
messages go to all of a user's subscriptions, gone ones (404 / 410) are removed.

What is sent (each can be switched off per user under Account):
  report   a coaching report you started is done (or failed)
  match    match day: 90 minutes before the match time, with a link to the match screen
iOS shows them only for the app added to the home screen (iOS 16.4+); everything needs HTTPS.
"""
from __future__ import annotations

import json
import threading
from datetime import date

KINDS = {"report": ("Report ready", "When a coaching report you started is done or failed."),
         "match": ("Match day", "90 minutes before your match time, with a link to the match screen.")}


def available() -> bool:
    try:
        import pywebpush  # noqa: F401
        import py_vapid  # noqa: F401
        return True
    except Exception:
        return False


def keys(store) -> tuple[str, str]:
    """(public key for the browser, private key PEM); made once and kept in the settings."""
    pub, priv = store.get("push_vapid_public"), store.get("push_vapid_private")
    if pub and priv:
        return pub, priv
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01, b64urlencode
    v = Vapid01()
    v.generate_keys()
    priv = v.private_pem().decode()
    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pub = b64urlencode(raw)
    store.set("push_vapid_private", priv)
    store.set("push_vapid_public", pub)
    return pub, priv


def wants(user, kind: str) -> bool:
    try:
        prefs = json.loads(user.prefs or "{}")
    except ValueError:
        prefs = {}
    return bool((prefs.get("notify") or {}).get(kind, True))


def _send_one(store, sub: dict, payload: dict, priv: str, claim: str) -> bool:
    from py_vapid import Vapid01
    from pywebpush import WebPushException, webpush
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": json.loads(sub["keys"] or "{}")},
                data=json.dumps(payload), vapid_private_key=Vapid01.from_pem(priv.encode()),
                vapid_claims={"sub": claim}, timeout=10, ttl=6 * 3600)
        return True
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):                       # the browser dropped it: forget it
            store.remove_push_sub(sub["endpoint"])
        return False
    except Exception:
        return False


def send(store, user_id: int, title: str, body: str, url: str = "/", tag: str = "", kind: str | None = None,
         wait: bool = False) -> int:
    """Send to every device of one user. Returns the number of devices (sending runs in the background)."""
    if not available():
        return 0
    subs = store.push_subs(user_id)
    if not subs:
        return 0
    if kind:
        u = store.user(user_id)
        if u is None or not wants(u, kind):
            return 0
    _, priv = keys(store)
    claim = store.get("push_claim") or "mailto:valcoach@localhost"
    payload = {"title": title, "body": body, "url": url, "tag": tag or kind or "valcoach"}

    def run():
        for s in subs:
            _send_one(store, s, payload, priv, claim)
    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True, name="push").start()
    return len(subs)


def match_day_tick(store, match_window) -> list[int]:
    """Once per team and match day, when the match window opens: ping everyone who sees the team."""
    done = []
    today = date.today().isoformat()
    users = store.users()
    for t in store.all_teams():
        if not match_window(t):
            continue
        info = t.sync_info
        if (info.get("push") or {}).get("match_day") == today:
            continue
        info.setdefault("push", {})["match_day"] = today
        store.update_team(t.id, sync=info)
        for u in users:
            if any(x.id == t.id for x in store.teams_for_user(u.id)):
                send(store, u.id, f"Match day: {t.name}", "Your match is coming up. Open the match screen for the comp, plans and strats.",
                     url=f"/teams/{t.id}/match", tag=f"match-{t.id}", kind="match")
        done.append(t.id)
    return done
