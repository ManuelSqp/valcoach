"""Look & feel per user: the style (a whole different look and layout) and animation switches."""
from __future__ import annotations

# name -> (label, one line, Google Fonts css2 query or "")
STYLES = {
    "classic": ("Nexus", "The standard look: calm navy, amber for things you can do. Light or dark with the moon button.", ""),
    "original": ("Original red", "The colours from before 3.0: Valorant red on deep navy.", ""),
    "broadcast": ("Esports broadcast", "Like a VCT stream overlay: big condensed type, angled corners, red, black and white.",
                  "family=Oswald:wght@500;600;700&family=Barlow:wght@400;500;600;700"),
    "minimal": ("Clean minimal", "Light and calm, soft cards, lots of space. Easiest to read on a phone.",
                "family=Inter:wght@400;500;600;700"),
    "neon": ("Neon glass", "Dark purple and teal glow, frosted panels.", "family=Space+Grotesk:wght@400;500;600;700"),
    "hud": ("Tactical HUD", "Like Valorant's own interface: thin teal lines, cut corners, a grid behind everything.",
            "family=Rajdhani:wght@500;600;700&family=JetBrains+Mono:wght@400;600"),
    "terminal": ("Data terminal", "Dense, monospace numbers, a narrow menu: the most on one screen.",
                 "family=JetBrains+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600"),
    "editorial": ("Editorial magazine", "“The Nexus”: big serif headlines on paper.",
                  "family=Playfair+Display:wght@700;900&family=Source+Sans+3:wght@400;600;700"),
    "playbook": ("Coach's playbook", "A clipboard: lined paper, sticky notes, handwritten headings.",
                 "family=Kalam:wght@400;700&family=Inter:wght@400;500;600"),
    "arcade": ("Retro arcade", "Pixel font, CRT scanlines, bright neon colours.", "family=Press+Start+2P&family=VT323"),
}
# where the menu sits (phones always get the ☰ drawer)
NAVS = {"side": ("On the left", "A column with every group open or closed, like a file browser."),
        "top": ("At the top", "A bar across the page; each group opens as a dropdown. More room for wide pages.")}
# how wide the page may get
WIDTHS = {"auto": ("Like the style", "Full width only in Data terminal, the others stay centred."),
          "narrow": ("Centred", "At most about 1240 px, easier to read on a wide screen."),
          "full": ("Full width", "The whole window, in every style: more tables and charts at once.")}
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
    nav = raw.get("nav") if raw.get("nav") in NAVS else "side"
    width = raw.get("width") if raw.get("width") in WIDTHS else "auto"
    from ..i18n import DEFAULT, LANGS
    lang = raw.get("lang") if raw.get("lang") in LANGS else DEFAULT
    return {"style": style, "nav": nav, "width": width, "lang": lang, "explicit_lang": raw.get("lang") in LANGS,
            "anim": {k: bool(anim.get(k, True)) for k in ANIMATIONS}}


def fonts_url(style: str) -> str:
    """Fonts ship with Nexus now (static/fonts, loaded by each style's CSS): nothing comes from Google."""
    return ""
