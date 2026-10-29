# Review fixes on top of 2.15.0 (29.10.2026)

Ich han da Changes nid gschwriebe es het mich agschiese das formuliere dorum AI text wos suber zämmefast

These fixes were made on 2.2.0 and 2.7.0 and lost twice when a new version was unzipped over them. To keep
them: apply `valcoach-fixes.patch` to your source **before** building the next version
(`patch -p1 < valcoach-fixes.patch` in the project folder, or `git apply valcoach-fixes.patch`).

## Coaching quality

**`parse.py`, `analysis/player.py`, `pipeline.py`: "zero utility" coaching (`has_utility`)**
The live API fills the match totals (`players[].ability_casts`, e.g. `grenade: 30`) but sends `null` for every
per-round cast. `_utility_present()` also checked the match totals, so `has_utility` was `True` for every real match,
and the round prompts said `utility_casts: none` ("your utility usage is zero"). The check now only looks at the
per-round casts. If they're missing, the match stats fall back to the real match totals (`utility_per_round`,
new `ults_used`). The new `test_live_api_utility_shape` covers the real data shape.

**`coach/prompts.py`, `coach/engine.py`, `coach/teamreview.py`, `stats/weekly.py`, `stats/gameplans.py`,
`stats/tips.py`: the model never saw the field descriptions**
Ollama uses the JSON schema only to force the output format; `description` texts in a schema are not shown to
the model. That's why "headline: one sentence, no player name" still produced "Post-Match Review: BurnTheGoat#NOW",
summaries were "Round 3 Review: …", and `better_option` was "N/A". New `field_guide(schema)` turns the descriptions
into an "Output fields" section of the system prompt. It is used by the round and match review **and by the 2.12+
features** (team review, weekly focus, game plans, map tips, pro watch list), which had the same problem.
Descriptions were added for `better_option`, `went_well`, `mistakes`, `key_moment`, `strengths`, issues and IGL notes.

**`coach/prompts.py`, `coach/engine.py`, `report.py`: "check the VOD" without a VOD**
The prompt told the model to "check the VOD at 0:42" when facts were missing, so it put this into `better_option`
even when no VOD existed. Now: without a VOD the model is told there is no recording. With a VOD, these
hints go into a new optional field `check_in_vod`, shown in the report as "Check in the VOD". `clean_feedback()`
drops filler (`N/A`, `None. …`), so the report hides the box instead of showing it.
On the live model (gemma4:26b, Sunset match): title-only summaries went from 23 of 23 to 0, "N/A" from 3 to 0,
and VOD mentions without a VOD from 20 to 0.

**`pipeline.py`, `parse.py`, `models.py`, `web/__init__.py`, `profile.html`: deathmatch etc. could be coached**
History includes Deathmatch, Team Deathmatch (`hurm`) and Gauntlet (`abilitydraftarena`). These have no sides or economy,
so the analysis was nonsense. New `Match.mode_type` and `coachable()` check: the match list (recent and stored
archive) shows "not coachable", and the coach/notes pages and `pipeline.run` refuse these matches.

**`analysis/team.py`: time-outs were never detected**
The check looked for a result like "Round timer…", but the API only sends `Elimination`, `Defuse`, `Detonate` or `""`.
A time-out is now worked out from the data (no plant, attackers still alive, defenders won): result "Time expired"
plus a flag for both sides.

## Security and stability

**`web/static/strat.js`, `web/strats.py`: a team member could plant code in a strat board (stored XSS)** *(new in 2.13+)*
The properties panel builds HTML from `i.n`, `i.r`, `i.len`, `i.ang` without escaping, and `strat_save` stored any
JSON. A teammate could save e.g. `"n": "\"><img src=x onerror=…>"`, and it would run in the browser of everyone who
opens the board, including the owner/admin. Now the editor forces these values to numbers (`num()`), and the server
keeps only well-typed item fields (`clean_board()`: numbers for `x y x2 y2 r len ang n size`, length-limited strings
for `t id a s label c`, `dash` as bool, `pts` as number pairs). **If you add a new item field, add it to
`ITEM_NUMBERS` / `ITEM_STRINGS`, or it will be dropped on save.**

**`web/__init__.py`: forms could be sent from other websites (CSRF)**
Only `SameSite=Lax` cookies protected the forms. Every POST now checks the browser's `Origin` (or `Referer`) header.
A form from another site gets 403. Requests without these headers (CLI, scripts) are unaffected, and
`X-Forwarded-Host` is accepted for a reverse proxy.

**`web/__init__.py`, `store.py`, `settings.html`: no limits per user**
With sign-up enabled, anyone could fill the disk or flood the shared queue. New settings: *Max reports per user at
once* (default 3, also applies to *Run again*) and *Max VOD upload size* (default 20 GB). Uploads are also refused if
less than 1 GB of disk would stay free. All of this is checked before the upload body is read.

**`web/jobs.py`, `store.py`: the same job could run twice**
A double click on *Run again* submitted the job twice. The queued → running switch is now one atomic update (`claim_job`).

**`web/__init__.py`: deleting a player during a running report**
The profile and its folder were deleted under the running job. This is now refused until the job finishes.

**`web/__init__.py`, `pipeline.py`, `coach/engine.py`: crashes (500) on bad input**
A non-numeric anchor round/kill crashed the coach form. It's now validated before an upload is stored. Hand-edited
notes YAML with bad keys, a list, or broken syntax crashed the notes page and coaching. Those entries are now skipped.

**`pipeline.py`, `web/__init__.py`: match ID not validated**
`load_match` accepts file paths (`*.json`), and the web passed the URL's match ID straight in. Web match IDs must now be
letters, digits and dashes (anything else returns 404), and the CLI rejects malformed IDs.

**`web/__init__.py`: in-memory lists without a limit**
The failed-login table and the match-list cache grew forever. Expired lockouts are pruned above 1,000 entries,
and the cache keeps at most 200 entries.

## Other
- `pyproject.toml`: Flask ≥ 3.1 (per-request upload limit).
- `README.md`: known limits updated (live API works, video not yet tested on a real recording, no per-round
  utility, replay estimates without a VOD, teams are shared now). The user limits, non-coachable modes and
  the origin check are documented.
- Tests: 12 new (97 total, all passing).
