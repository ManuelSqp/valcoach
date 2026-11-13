"""4.41: the lineup cards line up: every section in its own shared row (subgrid), fixed-shape role legend and
playstyle line, Struggles in and Best maps always there."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import _premier_team, _wait_stats, app, setup_admin, synthetic  # noqa: E402,F401

TPL = (Path(__file__).parent.parent / "nexus" / "web" / "templates" / "team_overview.html").read_text()


class MP:
    def setattr(self, obj, name, val):
        setattr(obj, name, val)


def test_template_shape():
    assert "grid-template-rows:subgrid" in TPL and "grid-row:span 8" in TPL
    assert "p.style.labels[:2]" in TPL and 'class="chip more"' in TPL          # one line of playstyle chips
    assert "{% for r in ['Duelist', 'Initiator', 'Controller', 'Sentinel'] %}" in TPL.split('class="legend4"')[1][:200]


def test_cards_have_the_same_sections(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    tid = _premier_team(app, c, MP())
    store = app.extensions["nexus"]["store"]
    for m in store.team(tid).member_list:
        _wait_stats(app, f"import:{m['pid']}")
    page = c.get(f"/teams/{tid}/overview").data.decode()
    cards = page.split('<div class="ocard">')[1:]
    assert len(cards) >= 5
    for card in cards:
        card = card.split('<div class="ocard">')[0]
        if "No games yet" in card:
            continue
        assert card.count('class="osect"') == 7, card[:300]
        heads = re.findall(r'<div class="osec"[^>]*>([^<]+)</div>', card)
        assert heads == ["Role", "Most played agents", "Agent roles", "Playstyle", "Thrives in", "Struggles in", "Best maps"]
        legend = card.split('class="legend4"')[1].split("</div>")[0]
        assert all(r in legend for r in ("Duelist", "Initiator", "Controller", "Sentinel"))
