"""Look & feel per user: the style (a whole different look and layout) and animation switches."""
from __future__ import annotations

# name -> (label, one line, Google Fonts css2 query or "")
STYLES = {
    "classic": ("Classic", "The original dark look.", ""),
    "broadcast": ("Esports broadcast", "Like a VCT stream overlay: big condensed type, angled corners, red, black and white.",
                  "family=Oswald:wght@500;600;700&family=Barlow:wght@400;500;600;700"),
    "minimal": ("Clean minimal", "Light and calm, soft cards, lots of space. Easiest to read on a phone.",
                "family=Inter:wght@400;500;600;700"),
    "neon": ("Neon glass", "Dark purple and teal glow, frosted panels.", "family=Space+Grotesk:wght@400;500;600;700"),
    "hud": ("Tactical HUD", "Like Valorant's own interface: thin teal lines, cut corners, a grid behind everything.",
            "family=Rajdhani:wght@500;600;700&family=JetBrains+Mono:wght@400;600"),
    "terminal": ("Data terminal", "Menu on the side, dense, monospace numbers: the most on one screen.",
                 "family=JetBrains+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600"),
    "editorial": ("Editorial magazine", "“The Valcoach”: big serif headlines on paper.",
                  "family=Playfair+Display:wght@700;900&family=Source+Sans+3:wght@400;600;700"),
    "playbook": ("Coach's playbook", "A clipboard: lined paper, sticky notes, handwritten headings.",
                 "family=Kalam:wght@400;700&family=Inter:wght@400;500;600"),
    "arcade": ("Retro arcade", "Pixel font, CRT scanlines, bright neon colours.", "family=Press+Start+2P&family=VT323"),
}
# switch -> (label, what it does)
ANIMATIONS = {
    "count": ("Numbers count up", "Stats roll up from 0 when a page opens."),
    "lift": ("Cards lift on hover", "Clickable cards rise a little under the mouse."),
    "tabs": ("Smooth page changes", "Pages fade into each other instead of jumping."),
    "loaders": ("Progress bars", "Running jobs show a progress bar and the current step instead of the raw log."),
    "toasts": ("Toasts", "Messages like “Saved” pop up briefly at the bottom instead of a box at the top."),
}


def ui_prefs(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    style = raw.get("style") if raw.get("style") in STYLES else "classic"
    anim = raw.get("anim") if isinstance(raw.get("anim"), dict) else {}
    return {"style": style, "anim": {k: bool(anim.get(k, True)) for k in ANIMATIONS}}


def fonts_url(style: str) -> str:
    q = STYLES.get(style, STYLES["classic"])[2]
    return f"https://fonts.googleapis.com/css2?{q}&display=swap" if q else ""
