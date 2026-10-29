"""Self-contained HTML report (open in any browser; VOD plays from disk)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from jinja2 import Environment, select_autoescape

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ meta.map }} {{ meta.score }} · valcoach</title>
<style>
:root{--bg:#0f1218;--panel:#171c25;--line:#262d3a;--text:#e8ebf0;--muted:#8a93a6;--red:#ff4655;--win:#35d0a0;--loss:#ff4655;--amber:#f2b84b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;gap:24px;align-items:baseline;flex-wrap:wrap}
header h1{margin:0;font-size:22px;letter-spacing:.04em;text-transform:uppercase}header h1 b{color:var(--red)}
.muted{color:var(--muted)}.wrap{padding:20px 24px;max-width:1700px;margin:0 auto}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 18px;margin-bottom:16px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin:0 0 12px}
h3{font-size:15px;margin:14px 0 6px}ul{margin:4px 0;padding-left:18px}li{margin:3px 0}
.timeline{display:flex;gap:3px;flex-wrap:wrap;margin:4px 0 14px}.tl{width:30px;height:30px;border-radius:4px;display:grid;place-items:center;font-size:12px;font-weight:600;cursor:pointer;border:2px solid transparent;color:#0f1218}
.tl.w{background:var(--win)}.tl.l{background:var(--loss)}.tl.i3{border-color:var(--amber)}.tl.half{margin-left:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}.stat{background:#11151c;border:1px solid var(--line);border-radius:6px;padding:8px 10px}.stat b{display:block;font-size:18px}
.badge{font-size:11px;padding:2px 7px;border-radius:999px;font-weight:700;text-transform:uppercase}
.rounds{display:grid;grid-template-columns:minmax(0,1fr) minmax(380px,560px);gap:18px;align-items:start}
@media (max-width:1050px){.rounds{grid-template-columns:1fr}.rpanel{position:static!important;order:-1;max-height:none!important}}
.rlist{display:grid;gap:6px}.round{scroll-margin-top:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px}
.round.sel{border-color:#4a5468}.round.open{border-color:var(--red)}
.rhead{display:flex;gap:8px;align-items:center;cursor:pointer;width:100%;background:none;border:0;color:var(--text);font:inherit;text-align:left;padding:9px 12px}
.rhead:hover{background:#1b212c;border-radius:8px}.rn{font-weight:800;min-width:24px;font-variant-numeric:tabular-nums}
.res{font-size:11px;font-weight:800;width:20px;height:20px;display:grid;place-items:center;border-radius:5px;color:#0f1218;flex:none}.res.w{background:var(--win)}.res.l{background:var(--loss)}
.rside{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;width:30px}
.chips{display:flex;gap:5px;flex-wrap:wrap;flex:1;min-width:0}.chip{font-size:11.5px;padding:1px 8px;border-radius:999px;background:#222938;color:#c3cad8;white-space:nowrap}
.chip.g{background:rgba(53,208,160,.14);color:var(--win)}.chip.r{background:rgba(255,70,85,.14);color:var(--loss)}.chip.a{background:rgba(242,184,75,.14);color:var(--amber)}.chip.m{background:none;color:var(--muted);padding-left:0}
.caret{color:var(--muted);transition:transform .15s}.round.open .caret{transform:rotate(180deg)}
.rsum{display:block;color:var(--muted);font-size:13px;padding:0 12px 9px 44px;margin-top:-4px}
.round.open .rsum{display:none}
.rbody{display:none;padding:2px 14px 14px 44px}.round.open .rbody{display:block}
.rbody .lead{font-size:14.5px;margin:2px 0 8px}
.rpanel{position:sticky;top:10px;max-height:calc(100vh - 20px);overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.rp-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}.rp-head b{font-size:15px;flex:1}
.tab{background:#222938;color:var(--muted);border:1px solid var(--line);border-radius:7px;padding:4px 12px;font:inherit;font-size:13px;cursor:pointer}.tab.on{color:var(--text);border-color:var(--red)}
.badge.w{background:rgba(53,208,160,.15);color:var(--win)}.badge.l{background:rgba(255,70,85,.15);color:var(--loss)}.badge.side{background:#222938;color:var(--muted)}
.rbody{display:none;margin-top:10px}.round.open .rbody{display:block}.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:800px){.cols{grid-template-columns:1fr}}
.good li::marker{color:var(--win)}.bad li::marker{color:var(--loss)}.better{border-left:3px solid var(--amber);padding:4px 10px;background:#1c1a14;border-radius:0 6px 6px 0;margin-top:6px}
.jump{background:#222938;color:var(--text);border:1px solid var(--line);border-radius:5px;padding:3px 8px;font-size:12px;cursor:pointer;margin:2px}.jump:hover{border-color:var(--red)}
pre{white-space:pre-wrap;background:#0b0e13;border:1px solid var(--line);border-radius:6px;padding:10px;font-size:12px;color:#b9c1d0;max-height:340px;overflow:auto}
details summary{cursor:pointer;color:var(--muted);font-size:12px;margin-top:10px}
.vodcol{position:sticky;top:12px;align-self:start}video{width:100%;border-radius:8px;background:#000}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted);font-weight:500}
.replay{margin:12px 0 6px}
.ttabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px}.ttb{background:#222938;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}.ttb.on{border-color:var(--red)}
.tpanel{display:none}.tpanel.on{display:block}
.tstats{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-bottom:8px}.tstats b{color:var(--text);font-size:15px}.tstats .warn b{color:var(--amber)}
.rolechip{background:rgba(53,208,160,.14);color:var(--win);border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700}
.rref{font-size:11px;background:#222938;border-radius:4px;padding:0 5px;margin-left:3px;text-decoration:none;color:var(--muted)}.rref:hover{color:var(--text)}
.rp{display:grid;grid-template-columns:1fr;gap:10px;outline:none}
.rp:fullscreen{background:var(--bg);padding:16px;grid-template-columns:minmax(0,1fr) 300px;align-items:start;overflow:auto}
.rp:fullscreen .rp-svg{max-width:calc(100vh - 150px)}.rp:fullscreen .rp-side{grid-template-columns:1fr}
.rp-stage{position:relative;max-width:calc(100vh - 230px);margin:0 auto;width:100%}
.rp-svg{width:100%;aspect-ratio:1/1;height:auto;display:block;background:#11151c;border:1px solid var(--line);border-radius:10px;touch-action:none;cursor:grab;user-select:none}
.rp-zoom{position:absolute;top:8px;right:8px;display:flex;flex-direction:column;gap:4px;z-index:2}
.rp-zoom button{width:34px;height:34px;border-radius:8px;border:1px solid var(--line);background:rgba(23,28,37,.92);color:var(--text);font-size:17px;cursor:pointer}
.rp-zoom button:hover{border-color:var(--red)}
.rp-bar{display:flex;gap:10px;align-items:center;margin-top:10px}
.rp-bar button,.rp-bar select{background:#222938;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer}
.rp-play{min-width:46px;font-size:15px}.rp-time{font-variant-numeric:tabular-nums;color:var(--muted);min-width:92px}
.rp-scrub{position:relative;flex:1;height:30px;display:flex;align-items:center}.rp-scrub input{width:100%;accent-color:var(--red);position:relative;z-index:1;margin:0}
.rp-ticks{position:absolute;left:8px;right:8px;top:0;bottom:0;pointer-events:none}.rp-tick{position:absolute;top:3px;width:3px;height:9px;border-radius:2px;transform:translateX(-1px)}.rp-tick.spike{height:12px;top:1px;width:5px}
.rp-opts{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:12.5px;color:var(--muted);margin-top:8px}.rp-opts label{cursor:pointer}.rp-opts input{accent-color:var(--red);vertical-align:-2px}
.rp-note{flex-basis:100%;font-size:12px}
.rp-better{border-left:3px solid var(--amber);padding:6px 10px;background:#1c1a14;border-radius:0 6px 6px 0;margin-top:10px;font-size:13px}
.rp-side{display:grid;grid-template-columns:1fr 1fr;gap:10px;min-width:0;align-items:start}.rp-col{display:flex;flex-direction:column;gap:5px;min-width:0}.rp-h{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-top:4px}
.rp-roster{display:grid;gap:4px}.rp-row,.rp-ev{display:flex;align-items:center;gap:8px;width:100%;text-align:left;background:#11151c;border:1px solid var(--line);border-radius:8px;padding:5px 8px;color:var(--text);font:inherit;font-size:13px;cursor:pointer}
.rp-row:hover,.rp-ev:hover{border-color:#3a4458}.rp-row.sel{border-color:var(--amber);background:#1c1a14}.rp-row.dead{opacity:.5}
.rp-nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rp-nm small{color:var(--muted);margin-left:6px}.rp-st{font-size:11px;color:var(--red)}
.rp-av{width:26px;height:26px;border-radius:50%;border:2px solid;object-fit:cover;flex:none;display:inline-block}.rp-av.sm{width:20px;height:20px}
.rp-feed{display:grid;gap:4px;max-height:420px;overflow:auto}.rp-ev{font-size:12.5px;gap:6px;opacity:.55}.rp-ev b{font-variant-numeric:tabular-nums;color:var(--muted);margin-right:2px}
.rp-ev.past{opacity:1}.rp-ev.now{border-color:var(--red);background:#1d1418}.rp-arrow{font-weight:700}.rp-spike{width:10px;height:10px;transform:rotate(45deg);display:inline-block;flex:none}
.small{font-size:12px}.duels td,.duels th{padding:4px 8px}.issue{margin-bottom:10px}.review .headline{font-size:17px;font-weight:600;margin:4px 0 6px}.review h3{margin-top:16px}.plan{width:100%}.plan td,.plan th{padding:6px 8px;vertical-align:top}.issue .ev{color:var(--muted);font-size:13px}.err{color:var(--amber)}
</style></head><body>
<header><h1>{{ meta.map }} <b>{{ meta.score }}</b></h1>
<span>{{ meta.player }} · {{ meta.agent }}</span><span class="muted">{{ meta.queue }} · {{ meta.started_at }} · model {{ meta.model or 'none (facts only)' }}{% if meta.llm_stats %} · {{ meta.llm_stats.avg_s_per_request }} s/request · {{ meta.llm_stats.gen_tok_per_s }} tok/s{% endif %}{% if meta.valcoach_version %} · valcoach {{ meta.valcoach_version }}{% endif %}</span></header>
<div class="wrap"><main>

<section class="card"><h2>Rounds</h2><div class="timeline">
{% for r in rounds %}<div class="tl {{ 'w' if r.team_facts.won else 'l' }} {{ 'i3' if r.feedback.importance == 3 }} {{ 'half' if r.number in halves }}" title="R{{ r.number }} {{ r.team_facts.side }} {{ r.feedback.summary|default('') }}" onclick="openRound({{ r.number }})">{{ r.number }}</div>{% endfor %}
</div><span class="muted">Amber border = round with a big lesson. Click a round to open it{% if vod %} and jump the VOD{% endif %}.</span></section>

{% if review %}<section class="card review"><h2>Match review</h2>
{% if review.error %}<p class="err">Match review failed: {{ review.error }}</p>{% endif %}
{% if review.headline %}<p class="headline">{{ review.headline }}</p>{% endif %}
{% set has_team = review.team_issues or review.igl_notes %}
{% set has_me = review.player_issues %}
<div class="{{ 'cols' if has_team and has_me else '' }}">
{% if has_team %}<div>
{% if review.team_issues %}<h3>Team issues</h3>{% for i in review.team_issues %}<div class="issue"><b>{{ i.issue }}</b><div class="ev">{{ i.evidence }}</div><div>→ {{ i.fix }}</div></div>{% endfor %}{% endif %}
{% if review.igl_notes %}<h3>IGL notes</h3><ul>{% for n in review.igl_notes %}<li>{{ n }}</li>{% endfor %}</ul>{% endif %}
</div>{% endif %}
{% if has_me %}<div>
<h3>Your issues</h3>{% for i in review.player_issues %}<div class="issue"><b>{{ i.issue }}</b><div class="ev">{{ i.evidence }}</div><div>→ {{ i.fix }}</div></div>{% endfor %}
</div>{% endif %}
</div>
<div class="cols">
{% if review.strengths %}<div><h3>Strengths</h3><ul class="good">{% for x in review.strengths %}<li>{{ x }}</li>{% endfor %}</ul></div>{% endif %}
{% if review.practice_plan %}<div><h3>Practice plan</h3>
{% if review.practice_plan[0] is mapping %}<table class="plan"><tr><th>Drill</th><th>Where</th><th>Min</th></tr>
{% for d in review.practice_plan %}<tr><td>{{ d.drill }}{% if d.fixes %}<div class="ev">for: {{ d.fixes }}</div>{% endif %}</td><td>{{ d.where }}</td><td>{{ d.minutes }}</td></tr>{% endfor %}</table>
{% else %}<ol>{% for x in review.practice_plan %}<li>{{ x }}</li>{% endfor %}</ol>{% endif %}
</div>{% endif %}
</div>
</section>{% endif %}

{% if team_review and team_review.players %}<section class="card team" id="team"><h2>Your team</h2>
<div class="ttabs">{% for p in team_review.players %}<button class="ttb{{ ' on' if loop.first }}" onclick="teamTab({{ loop.index0 }})">{{ p.name }} <span class="muted">{{ p.agent }}</span></button>{% endfor %}
<button class="ttb" onclick="teamTab(-1)">Together</button></div>
{% for p in team_review.players %}{% set fb = p.feedback or {} %}
<div class="tpanel{{ ' on' if loop.first }}" data-i="{{ loop.index0 }}">
<div class="tstats">{% for k, label in (('kills','K'),('deaths','D'),('assists','A')) %}<span><b>{{ p.stats[k] }}</b> {{ label }}</span>{% endfor %}
<span><b>{{ p.stats.acs }}</b> ACS</span><span><b>{{ (p.stats.kast*100)|round|int }}%</b> KAST</span>
<span><b>{{ p.stats.first_kills }}/{{ p.stats.first_deaths }}</b> FK/FD</span><span><b>{{ p.stats.trades }}</b> trades</span>
<span class="{{ 'warn' if p.stats.alone_deaths >= 3 }}"><b>{{ p.stats.alone_deaths }}</b> died alone</span>
<span class="{{ 'warn' if p.stats.outnumbered_deaths >= 4 }}"><b>{{ p.stats.outnumbered_deaths }}</b> died outnumbered</span>
{% for r in p.roles %}<span class="rolechip">{{ r }}</span>{% endfor %}</div>
{% if p.error %}<p class="err">Review failed: {{ p.error }}</p>{% endif %}
{% if fb.summary %}<p class="headline" style="font-size:15px">{{ fb.summary }}</p>{% endif %}
<div class="cols">
{% if fb.went_well %}<div><h3>Went well</h3><ul class="good">{% for x in fb.went_well %}<li>{{ x.point }} {% for n in x.rounds %}<a class="rref" href="#r{{ n }}" onclick="openRound({{ n }});return false">R{{ n }}</a>{% endfor %}</li>{% endfor %}</ul></div>{% endif %}
{% if fb.fix %}<div><h3>To fix</h3><ul class="bad">{% for x in fb.fix %}<li><b>{{ x.issue }}</b> {% for n in x.rounds %}<a class="rref" href="#r{{ n }}" onclick="openRound({{ n }});return false">R{{ n }}</a>{% endfor %}<div>→ {{ x.try }}</div></li>{% endfor %}</ul></div>{% endif %}
</div>
{% if fb.teammates_can_help %}<div class="better" style="margin-top:10px"><b>How the team can help {{ p.name }}:</b> {{ fb.teammates_can_help }}</div>{% endif %}
{% if p.repeat_death_spots %}<p class="muted small" style="margin-top:8px">Died more than once at: {% for d in p.repeat_death_spots %}{{ d.where }} on {{ d.side }} ({{ d.deaths }}×){{ ', ' if not loop.last }}{% endfor %}</p>{% endif %}
{% if not p.feedback and not p.error %}<p class="muted small">Numbers only (no model run).</p>{% endif %}
</div>{% endfor %}
<div class="tpanel" data-i="-1">
<table><tr><th>Player</th><th>Trades for others</th><th>Deaths not traded</th><th>Died alone</th><th>Died outnumbered (2+ close)</th><th>First deaths</th></tr>
{% for p in team_review.players %}<tr><td>{{ p.name }}</td><td>{{ p.stats.trades }}</td><td>{{ p.stats.untraded_deaths }} / {{ p.stats.deaths }}</td><td>{{ p.stats.alone_deaths }}</td><td>{{ p.stats.outnumbered_deaths }}</td><td>{{ p.stats.first_deaths }}</td></tr>{% endfor %}</table>
{% if team_review.trade_pairs %}<h3>Who traded whom</h3><ul>{% for t in team_review.trade_pairs %}<li>{{ t.traded_by }} traded {{ t.died }} {{ t.times }}×</li>{% endfor %}</ul>
{% else %}<p class="muted">No trades between teammates in this match.</p>{% endif %}
</div>
</section>{% endif %}

<section class="card"><h2>Numbers</h2>
<h3>Team</h3><div class="grid">
<div class="stat"><span class="muted">Attack</span><b>{{ ts.attack_won }}/{{ ts.attack_played }}</b></div>
<div class="stat"><span class="muted">Defense</span><b>{{ ts.defense_won }}/{{ ts.defense_played }}</b></div>
<div class="stat"><span class="muted">Pistols</span><b>{{ ts.pistols_won }}/{{ ts.pistols_played }}</b></div>
<div class="stat"><span class="muted">First kill rate</span><b>{{ (ts.first_kill_rate*100)|round|int }}%</b></div>
<div class="stat"><span class="muted">Win after FK / FD</span><b>{{ (ts.first_kill_conversion*100)|round|int }}% / {{ (ts.first_death_conversion*100)|round|int }}%</b></div>
<div class="stat"><span class="muted">Deaths traded</span><b>{{ (ts.trade_rate*100)|round|int }}%</b></div>
<div class="stat"><span class="muted">Isolated deaths</span><b>{{ (ts.isolated_death_rate*100)|round|int }}%</b></div>
<div class="stat"><span class="muted">Post-plant wins</span><b>{{ (ts.post_plant_win_rate*100)|round|int }}% ({{ ts.plants }})</b></div>
<div class="stat"><span class="muted">Retakes</span><b>{{ ts.retakes_won }}/{{ ts.retakes_attempted }}</b></div>
<div class="stat"><span class="muted">Leads thrown / comebacks</span><b>{{ ts.advantages_thrown }} / {{ ts.comebacks }}</b></div>
</div>
<h3>{{ ps.riot_id }} ({{ ps.agent }})</h3><div class="grid">
<div class="stat"><span class="muted">K / D / A</span><b>{{ ps.kills }}/{{ ps.deaths }}/{{ ps.assists }}</b></div>
<div class="stat"><span class="muted">ACS · ADR</span><b>{{ ps.acs }} · {{ ps.adr }}</b></div>
<div class="stat"><span class="muted">KAST · HS%</span><b>{{ ps.kast_pct }}% · {{ ps.hs_pct }}%</b></div>
<div class="stat"><span class="muted">FK / FD</span><b>{{ ps.first_kills }} / {{ ps.first_deaths }}</b></div>
<div class="stat"><span class="muted">Trade kills</span><b>{{ ps.trade_kills }}</b></div>
<div class="stat"><span class="muted">Deaths traded</span><b>{{ ps.traded_death_pct }}%</b></div>
<div class="stat"><span class="muted">Isolated deaths</span><b>{{ ps.isolated_deaths }}</b></div>
<div class="stat"><span class="muted">Clutches</span><b>{{ ps.clutches }}</b></div>
</div>
{% if ps.avg_damage_to_killer is not none or ps.duels_by_range %}
<h3>Duels</h3><div class="grid">
{% if ps.view_analysis %}{% set dv = ps.deaths_by_my_view or {} %}{% set kv = ps.kills_by_victim_view or {} %}
<div class="stat"><span class="muted">Died looking at killer</span><b>{{ dv.get('facing', 0) }} / {{ ps.deaths }}</b><span class="muted small">lost aim duels</span></div>
<div class="stat"><span class="muted">Died to side / behind</span><b>{{ dv.get('side', 0) + dv.get('behind', 0) }}</b><span class="muted small">positioning / awareness</span></div>
<div class="stat"><span class="muted">Kills on unaware enemies</span><b>{{ kv.get('side', 0) + kv.get('behind', 0) }} / {{ ps.kills }}</b></div>
{% endif %}
{% if ps.avg_damage_to_killer is not none %}<div class="stat"><span class="muted">Avg damage to your killer</span><b>{{ ps.avg_damage_to_killer }}</b></div>
<div class="stat"><span class="muted">Deaths without damage</span><b>{{ ps.deaths_without_damage }}</b><span class="muted small">no shot back</span></div>{% endif %}
</div>
<div class="cols" style="margin-top:10px">
{% if ps.duels_by_range %}<table class="duels"><tr><th>Range</th><th>Kills</th><th>Deaths</th></tr>
{% for rg in ['close (<10 m)', 'mid (10-25 m)', 'long (>25 m)'] %}{% if rg in ps.duels_by_range %}<tr><td>{{ rg }}</td><td>{{ ps.duels_by_range[rg].kills }}</td><td>{{ ps.duels_by_range[rg].deaths }}</td></tr>{% endif %}{% endfor %}</table>{% endif %}
{% if ps.shots_by_weapon %}<table class="duels"><tr><th>Main weapon</th><th>Rounds</th><th>HS%</th><th>Leg%</th></tr>
{% for w, d in weapons %}<tr><td>{{ w }}</td><td>{{ d.rounds }}</td><td>{{ d.hs_pct }}</td><td>{{ d.leg_pct }}</td></tr>{% endfor %}</table>{% endif %}
</div>
{% endif %}
{% if ps.top_death_areas %}<p class="muted">Most deaths at: {% for a in ps.top_death_areas %}{{ a[0] }} ({{ a[1] }}){{ ', ' if not loop.last }}{% endfor %}</p>{% endif %}
<details><summary>Scoreboard</summary><table><tr><th>Player</th><th>Agent</th><th>Team</th><th>K</th><th>D</th><th>A</th><th>ACS</th></tr>
{% for p in meta.roster|sort(attribute='acs', reverse=True) %}<tr><td>{{ p.name }}</td><td>{{ p.agent }}</td><td>{{ p.team }}</td><td>{{ p.k }}</td><td>{{ p.d }}</td><td>{{ p.a }}</td><td>{{ p.acs }}</td></tr>{% endfor %}</table></details>
</section>

<section class="rounds" id="rounds">
<div class="rlist">
<h2 style="margin:4px 0 6px">Rounds <span class="muted" style="text-transform:none;letter-spacing:0;font-weight:400">· click a round to open it and show it on the map</span></h2>
{% for r in rounds %}{% set f = r.feedback %}{% set t = r.team_facts %}{% set p = r.player_facts %}
<div class="round" id="r{{ r.number }}">
<button class="rhead" onclick="selectRound({{ r.number }}, true)" aria-expanded="false">
<span class="rn">{{ r.number }}</span>
<span class="res {{ 'w' if t.won else 'l' }}">{{ 'W' if t.won else 'L' }}</span>
<span class="rside">{{ 'ATK' if t.side == 'attack' else 'DEF' }}</span>
<span class="chips">
<span class="chip m">{{ t.our_buy }} vs {{ t.opp_buy }}</span>
{% if t.first_kill_ours is sameas true %}<span class="chip g">first kill</span>{% elif t.first_kill_ours is sameas false %}<span class="chip r">first death</span>{% endif %}
{% if t.plant_site %}<span class="chip">plant {{ t.plant_site }} {{ t.plant_time }}{% if t.defused %} · defused{% endif %}</span>{% endif %}
{% if p and p.kills %}<span class="chip g">you {{ p.kills }}K</span>{% endif %}
{% if p and not p.survived %}<span class="chip r">you died {{ p.death_time }}</span>{% endif %}
{% if p and p.clutch %}<span class="chip a">clutch {{ p.clutch }}</span>{% endif %}
{% if t.threw_advantage %}<span class="chip r">lead thrown</span>{% endif %}
{% if t.won_from_disadvantage %}<span class="chip g">comeback</span>{% endif %}
{% if f.importance == 3 %}<span class="chip a">★ lesson</span>{% endif %}
</span>
<span class="caret">▾</span>
</button>
{% if r.summary_ok %}<span class="rsum">{{ r.summary_ok }}</span>{% endif %}
<div class="rbody">
{% if r.summary_ok %}<p class="lead">{{ r.summary_ok }}</p>{% endif %}
{% if f.error %}<p class="err">LLM failed for this round: {{ f.error }}</p>{% endif %}
{% if f.key_moment %}<p><b>Key moment {{ f.key_moment.time }}:</b> {{ f.key_moment.what }}</p>{% endif %}
{% if f.check_in_vod %}<p class="muted"><b>Check in the VOD:</b> {{ f.check_in_vod }}</p>{% endif %}
{% if r.vod %}<div>{% if r.vod.start is not none %}<button class="jump" onclick="seek({{ r.vod.start }})">▶ round start</button>{% endif %}
{% if r.vod.first_kill is defined %}<button class="jump" onclick="seek({{ r.vod.first_kill - 3 }})">first kill</button>{% endif %}
{% if r.vod.your_death is defined %}<button class="jump" onclick="seek({{ r.vod.your_death - 5 }})">your death</button>{% endif %}
{% for k in r.vod.kills %}<button class="jump" onclick="seek({{ k - 3 }})">k{{ loop.index }}</button>{% endfor %}</div>{% endif %}
<div class="{{ 'cols' if f.team and f.player else '' }}">
{% if f.team %}<div><h3>Team</h3><ul class="good">{% for x in f.team.went_well %}<li>{{ x }}</li>{% endfor %}</ul><ul class="bad">{% for x in f.team.mistakes %}<li>{{ x }}</li>{% endfor %}</ul>{% if f.team.better_option %}<div class="better">{{ f.team.better_option }}</div>{% endif %}</div>{% endif %}
{% if f.player %}<div><h3>You</h3><ul class="good">{% for x in f.player.went_well %}<li>{{ x }}</li>{% endfor %}</ul><ul class="bad">{% for x in f.player.mistakes %}<li>{{ x }}</li>{% endfor %}</ul>{% if f.player.better_option %}<div class="better">{{ f.player.better_option }}</div>{% endif %}</div>{% endif %}
</div>
{% if r.own_note %}<p class="muted"><b>Your note:</b> {{ r.own_note }}</p>{% endif %}
<details><summary>Facts sent to the coach</summary><pre>{{ r.llm_input }}</pre></details>
</div>
</div>{% endfor %}
</div>
<aside class="rpanel" id="rpanel">
<div class="rp-head"><b id="rp-title">Round 1</b>
<button class="tab on" id="tab-map" onclick="showTab('map')">Replay</button>
{% if vod %}<button class="tab" id="tab-vod" onclick="showTab('vod')">Video</button>{% endif %}</div>
<div class="replay" id="rp-box"></div>
{% if vod %}<div id="vodbox" hidden><video id="vod" src="{{ vod }}" controls preload="metadata"></video>
<p class="muted small">Sync: {{ sync.method }}, offset {{ sync.global_offset_s }} s, {{ sync.matched_kills }}/{{ sync.total_kills }} kills matched.</p></div>{% endif %}
</aside>
</section>
</main>
</div>
<script id="replay-data" type="application/json">{{ replay_json|safe }}</script>
<script>
const VOD = document.getElementById('vod');
const START = {{ starts|safe }};
window.VALCOACH_START = START;
window.VALCOACH_REPLAY = JSON.parse(document.getElementById('replay-data').textContent);
let CUR = null;
function showTab(which) {
  const box = document.getElementById('rp-box'), vb = document.getElementById('vodbox');
  box.hidden = which !== 'map'; if (vb) vb.hidden = which !== 'vod';
  document.getElementById('tab-map').classList.toggle('on', which === 'map');
  const tv = document.getElementById('tab-vod'); if (tv) tv.classList.toggle('on', which === 'vod');
  if (which !== 'vod' && VOD) VOD.pause();
}
function seek(t) { if (!VOD) return; showTab('vod'); VOD.currentTime = Math.max(0, t); VOD.play().catch(() => {}); }
function showReplay(n) {
  const box = document.getElementById('rp-box');
  if (box._destroy) box._destroy();
  box.innerHTML = ''; delete box.dataset.built; box.dataset.round = n;
  document.getElementById('rp-title').textContent = 'Round ' + n;
  const R = (window.VALCOACH_REPLAY.rounds || {})[n];
  if (!R || !R.events || !R.events.length) { box.innerHTML = '<p class="muted">No replay data for this round.</p>'; return; }
  valcoachBuild(box);
}
function selectRound(n, toggleBody) {
  const el = document.getElementById('r' + n);
  if (!el) return;
  if (toggleBody) {
    const open = !(el.classList.contains('open') && CUR === n);
    el.classList.toggle('open', open);
    el.querySelector('.rhead').setAttribute('aria-expanded', open);
  }
  document.querySelectorAll('.round.sel').forEach(x => x.classList.remove('sel'));
  el.classList.add('sel');
  if (CUR !== n) { CUR = n; showReplay(n); showTab('map'); }
}
function teamTab(i) {
  document.querySelectorAll('.tpanel').forEach(p => p.classList.toggle('on', Number(p.dataset.i) === i));
  document.querySelectorAll('.ttb').forEach((b, j, all) => b.classList.toggle('on', i === -1 ? j === all.length - 1 : j === i));
}
function openRound(n) {
  const el = document.getElementById('r' + n);
  if (!el.classList.contains('open') || CUR !== n) selectRound(n, true);
  el.scrollIntoView({behavior: 'smooth', block: 'start'});
}
</script>
<script>{{ replay_js|safe }}</script>
<script>{% if rounds %}selectRound({{ rounds[0].number }}, false);{% endif %}</script>
</body></html>"""


def render_report(report: dict, out_path: Path, vod_path: str | None = None,
                  vod_url: str | None = None) -> Path:
    """vod_url (web app) wins over vod_path (CLI: file path made relative to the report)."""
    env = Environment(autoescape=select_autoescape(["html"]))
    tpl = env.from_string(TEMPLATE)
    vod_rel = vod_url
    if vod_rel is None and vod_path:
        try:
            vod_rel = os.path.relpath(Path(vod_path).resolve(), out_path.parent.resolve())
        except ValueError:          # different drive on Windows
            vod_rel = Path(vod_path).resolve().as_uri()
    half = 4 if "swift" in (report["meta"].get("queue") or "").lower() else 12
    halves = {half + 1, 2 * half + 1}
    starts = {r["number"]: (r["vod"] or {}).get("start") for r in report["rounds"]}
    better = {}
    for r in report["rounds"]:
        bp = (r.get("feedback") or {}).get("better_position") or {}
        if bp.get("callout") and bp.get("callout") != "position was fine":
            better[r["number"]] = bp
    replay = {"map": report.get("map"), "better": better, "agents": report.get("agents") or {},
              "rounds": {r["number"]: r.get("replay") for r in report["rounds"] if r.get("replay")}}
    # "</" must not appear inside a <script> block
    replay_json = json.dumps(replay, separators=(",", ":")).replace("</", "<\\/")
    sw = (report["player_stats"] or {}).get("shots_by_weapon") or {}
    weapons = sorted(((w, d) for w, d in sw.items() if d.get("rounds")), key=lambda x: -x[1]["rounds"])
    html = tpl.render(
        meta=report["meta"], ts=report["team_stats"], ps=report["player_stats"],
        rounds=[_defaults(r) for r in report["rounds"]], review=report.get("match_review") or {},
        team_review=report.get("team_review"),
        vod=vod_rel, sync=report.get("sync") or {}, halves=halves, starts=json.dumps(starts),
        replay_json=replay_json, weapons=weapons,
        replay_js=(Path(__file__).parent / "replay.js").read_text(encoding="utf-8"),
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path


ROUND_PREFIX = re.compile(r"^\s*round\s*:?\s*\d+\s*[:.\-–—]\s*", re.I)
GENERIC_SUMMARY = re.compile(r"^\s*(round\s*\d+\s*(review|recap|summary|analysis)?\b|review\b)", re.I)


def _useful_summary(s: str | None) -> str | None:
    """Drop empty headings like 'Round 3 review for Player (Agent).' that some models write."""
    s = (s or "").strip()
    s = ROUND_PREFIX.sub("", s).strip()       # "Round 3: ..." / "round: 3: ..." -> "..."
    if s:
        s = s[0].upper() + s[1:]
    if not s:
        return None
    if GENERIC_SUMMARY.match(s) and len(s) < 90:
        return None
    return s


def _defaults(r: dict) -> dict:
    r = dict(r)
    r["feedback"] = r.get("feedback") or {}
    r["summary_ok"] = _useful_summary(r["feedback"].get("summary"))
    return r
