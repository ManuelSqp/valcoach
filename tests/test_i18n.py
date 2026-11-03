import json
from pathlib import Path

from valcoach import i18n
from valcoach.i18n import Catalog, translate_html, tr


def cat():
    return Catalog({"Save": "Speichern", "# of # won": "# von # gewonnen", "{x} can't play": "{x} kann nicht spielen",
                    "{x} on {y}": "{x} auf {y}", "Jett": "Jett", "Ascent": "Ascent", "Weak on {x}.": "Schwach auf {x}.",
                    "Delete this report?": "Diesen Report löschen?"})


def test_lookup_exact_numbers_and_patterns():
    c = cat()
    assert c.lookup("Save") == "Speichern"
    assert c.lookup("12 of 20 won") == "12 von 20 gewonnen"
    assert c.lookup("burn can't play") == "burn kann nicht spielen"
    assert c.lookup("Jett on Ascent") == "Jett auf Ascent"           # all parts known: a loose pattern counts
    assert c.lookup("Fall back after your first kill on Ascent") is None
    assert c.lookup("Lets play heavy on Corrode") is None           # people's own text stays as it is
    assert c.text("  Save \n") == "  Speichern \n"
    assert c.lookup("Weak on Lotus (0–2).") == "Schwach auf Lotus (0–2)."
    # numbers inside a part and in the fixed text each go back where they belong; "#TAG" isn't a number
    c2 = Catalog({"Swap every # rounds.": "Alle # Runden tauschen.", "{x} (# of the rounds: {y}.)": "{x} (# der Runden: {y}.)",
                  "lost": "verloren", "Team {x}, # points": "Team {x}, # Punkte"})
    assert c2.lookup("Swap every 3 rounds. (4 of the rounds: lost.)") == "Alle 3 Runden tauschen. (4 der Runden: verloren.)"
    assert c2.lookup("Team Red#RED, 300 points") == "Team Red#RED, 300 Punkte"


def test_translate_html_text_and_attributes_but_not_scripts():
    c = cat()
    i18n.catalog.cache_clear()
    page = ('<html><body><button title="Save">Save</button><p>3 of 5 won</p>'
            '<script>const s = "Save";</script><code>Save</code><span translate="no" title="Save">Save</span>'
            '<form data-q="Delete this report?"></form><input type="submit" value="Save"><textarea>Save</textarea></body></html>')
    orig = i18n.catalog
    try:
        i18n.catalog = lambda lang: c if lang == "de" else None
        out = translate_html(page, "de")
    finally:
        i18n.catalog = orig
    assert '<button title="Speichern">Speichern</button>' in out
    assert "<p>3 von 5 gewonnen</p>" in out
    assert 'const s = "Save";' in out and "<code>Save</code>" in out and "<textarea>Save</textarea>" in out
    assert 'data-q="Diesen Report löschen?"' in out and 'value="Speichern"' in out
    assert '<span translate="no" title="Save">' in out
    assert translate_html(page, "en") == page


def test_german_catalog_loads_and_covers_the_menu():
    i18n.catalog.cache_clear()
    c = i18n.catalog("de")
    assert c is not None
    for en in ("Match day", "Strategy", "Performance", "Practice", "Roster & setup", "Review evening", "Log out"):
        assert c.lookup(en), en
    data = json.loads((Path(i18n.__file__).parent / "de.json").read_text(encoding="utf-8"))
    for k, v in data.items():                       # numbers and parts survive the translation
        if k.startswith("_"):
            continue
        assert k.count("#") == v.count("#"), k
        for part in __import__("re").findall(r"\{\w+\}", k):
            assert part in v, (k, v)
    assert tr("**Practice today at 19:00** (Squad): Warm-up", "de").startswith("**Heute Training um 19:00**")


def test_pick_language_from_browser():
    assert i18n.pick("de-CH,de;q=0.9,en;q=0.8") == "de"
    assert i18n.pick("fr-FR,fr") == "en"
    assert i18n.pick(None) == "en"
