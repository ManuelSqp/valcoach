# Changelog

The running version is shown next to the logo in the web app, in *Settings*, at the top of
every report, and with `nexus --version` (`valcoach --version` up to 4.4). Update: `git pull`, `pip install -e .`,
`sudo systemctl restart nexus` (or `docker compose up -d --build`). `data/` and `config.toml` aren't touched.

## 4.35.0
- **3D maps** (*Practice › 3D maps*), first step: a map rebuilt from the replay files on the server. Every spot a player
  stood on is floor at that height (also a second floor above, like Heaven over Market), the gaps between paths close
  together are filled, everything else is a wall. Rebuilt again when new replays of the map come in.
- Walk around it: WASD, Shift to walk, Ctrl to crouch, Space to jump, F to fly, your Valorant sensitivity for the
  mouse. Steps and ramps are walked up, walls and boxes block you.
- Radar in the corner (R) and callout names in the world (C), both switched on and off and remembered; colours per area
  of the map (sites, mid, attacker and defender side) from a palette per map.
- With one or two replays a map is incomplete: corners nobody walked into are missing, and walls stand where nobody
  went. It gets better with every replay. The rebuild is tuned on test data so far and will be tuned on real replays.
- German texts.

## 4.34.0
- **Plays as** (Team settings › Teammates with access): the owner links a teammate's account to their player, so they
  can edit their own pool on the comp sheet even when their in-game name doesn't match the Riot ID.
- The comp sheet tells a teammate who isn't linked yet how to get linked, instead of just not showing *Edit*.
- Replay files: Nexus now keeps 10 positions per second per player from new uploads (was 4), for the 3D map rebuild
  coming next. Corrected: replays exist for Unrated, Competitive, Swiftplay and Premier, not only Competitive and
  Premier (Nexus never filtered by mode, only the texts were wrong).
- German texts.

## 4.33.0
- **Sandbox** (bottom of the aim trainer page): make your own scenarios from the trainer's 14 building blocks (flicks,
  targets that vanish, several on a wall, spider, bursts, moving targets, pop-ups, one taps, strafe tracking, path
  tracking, around you, switch tracking, peeks, hold the angle). Sliders and switches for every setting, *Try it*
  before saving, save for yourself or a team, change or remove your own (the team owner can remove the team's).
- Share a scenario as a code (`NX1-…`); pasting one adds the same scenario. Only settings are stored, never code, and
  the server checks every value against its range.
- Your scenarios keep scores like the built-in ones, and tagged with a skill they join that skill's sessions (at their
  difficulty) and its rating.
- German texts.

## 4.32.0
- **Train one skill** (aim trainer): pick tracking, snappy flicks, one taps, micro-adjusting, target switching,
  reaction or peeks and angles, and 10, 20 or 30 minutes. A session walks up that skill's ladder of scenarios (easy to
  hard) from the first one you aren't steady at yet, two 40 s rounds each, after a warm-up round.
- **Adaptive rounds**: after every round of a session the next one gets harder (targets 8% smaller, 7% faster) when it
  went well, easier when it didn't; the results screen says which. These rounds don't count for your bests.
- **Skill ratings** (0–100): per skill from your last 12 runs of its scenarios (accuracy, time on target, speed, how
  hard the scenario and the round were), with a chart by day. They compare you with yourself.
- **One taps**: 7 new scenarios where only the first shot counts, a miss and the target is gone: heads at head
  height near, far and close, three at once, quick ones, peeks from cover, and the doorway with an enemy model.
  108 scenarios in all.
- German texts.

## 4.31.0
- **VOD review**: watch a match recording together. *Review the recording together* on a report with a recording,
  or *Team › Practice › Recordings* for all of the team's recordings (with how many comments each has). Pause, draw
  on the frame (pen, arrow, circle, five colours), comment at that moment; each drawing shows at its time in the
  video. The timeline marks the rounds (won or lost, from the report) and the comments; jump to a round, slow down
  to 0.25×, step frame by frame. Teammates' new comments come in while you watch.
- Everyone in a team with that player can watch and comment (the recording too, not the rest of the report);
  whoever wrote a comment and the report's owner can remove it.
- German texts.

## 4.30.0
- **Scrims** (*Team › Practice › Scrims*): the team's scrim log. Per scrim: date, opponent, map, score, the side you
  started on and the first half (optional), what went well and what didn't, in words and as topics (retakes, trades,
  pistol rounds, comms and more). Over all scrims: won–lost, rounds won, the last ten results, per map and per
  opponent, rounds won per side, and *What the scrims show*: the topics that keep coming up as a problem or keep
  working, the best and worst map, the weaker side. Filter by map or opponent.
- Everyone in the team adds scrims; whoever wrote one and the team owner can change or remove it.
- German texts.

## 4.29.0
- **Sound** (*Practice › Sound*): hear where a sound comes from (headphones). Footsteps, a reload or a beep play once
  from somewhere around you, in 3D (the browser's HRTF panner); click the direction on a radar. Modes: *Direction*,
  *Distance* (also near or far) and *Height* (also above, same floor or below). 15 sounds a round, the closer the more
  points. Shows how far off you are on average, front/back mix-ups, and a wheel of how far off you are by direction.
  *Test the sound* checks left and right.
- The sounds are made in the browser, not Valorant's: what's trained is hearing the direction.
- German texts.

## 4.28.0
- **Map angles** in the aim trainer (above the library, and as a scenario in *Duels*): pick a map and where you stand
  (hold a site facing its main, or take it from main facing the site). Enemy models peek from behind cover at the
  callouts in front of you, at their real direction and distance on the map; the callout's name shows when one
  appears. Only headshots kill. The maps you play most come first.
- The map data has callout positions but no walls or heights, so every enemy is at your height and each spot gets a
  piece of cover.
- German texts.

## 4.27.0
- **Callouts** (*Practice › Callouts*): a quiz on the minimap. *Learn* shows every callout of a map, *Find it* names
  one and you click where it is, *Name it* lights up a spot and you pick its name from four nearby ones (keys 1–4).
  12 questions a round, faster answers score more, the callouts you get wrong come up more often. Per map: how many
  you know, best scores per mode, the ones you miss most. The maps you play most come first.
- German texts.

## 4.26.0
- **KovaaK's is gone from the web pages**: no KovaaK's page, no KovaaK's routines in the Aim library or warm-up, no
  KovaaK's share codes in *Add a routine*, no KovaaK's question in *Ask the coach* (and the coach no longer gets your
  KovaaK's scores), no KovaaK's in Settings, Account and This PC. If your warm-up was a KovaaK's one, it falls back
  to the Nexus trainer warm-up (if you've played the trainer, or have no warm-up routine of your own).
- Nothing is deleted: the code, your imported scores and saved share codes stay, and the desktop app's endpoints still
  work. One switch brings it all back: `WEB = True` in `nexus/stats/kovaaks.py`.
- German texts.

## 4.25.0
- **KovaaK's has its own page** (*Aim › KovaaK's*): the coach's playlists, community share codes, your imported scores
  and the scenarios the coach picks from moved off the Aim page. The Aim page is now the warm-up, what your matches
  show, the routines and the library; one card at the bottom opens KovaaK's (with how many runs you imported).
  Everything works as before: downloads, imports, the desktop app, KovaaK's runs as warm-up days.

## 4.24.0
- **57 more aim trainer scenarios, 100 in all**, modelled on the drill types KovaaK's and Aim Lab are known for
  (our own versions, names and texts), in two new groups and the old ones:
  - Moving targets: bouncing targets (normal, fast, close, tiny), a target that jinks, targets that hop up and fall,
    a moving target that respawns (near and far), strafing targets and strafing heads, a horde walking at you
    (normal and fast), shrinking targets.
  - Switch tracking: three moving targets, each goes down after a moment of fire on it; also fast, evasive (they
    dodge while you're on them), wide, small and floating.
  - Flicks: behind you (up to 175°), spider 180, speed and precision versions, low and high flicks.
  - Switching and precision: grid speed / precision, six shot precision, wide walls with three and five targets,
    heads at any range, triple tap, burst flicks (a group of three or four, far from the last group: wide and micro).
  - Reflex: side vision (far to the sides), pop-ups (several at once), friend or foe (don't shoot the blue ones, they
    cost points; also fast), reflex close and at head height.
  - Tracking: line tracing, arcs, stars (also micro), circles (also small), blink tracking (the target jumps away),
    tracking above and below you, long strafes (also close), zig-zag, fast around you.
- Results show the blue targets you hit (friend or foe) and the targets you took down (switch tracking).
- German texts.

## 4.23.0
- **Aim trainer scenario library**: 32 new scenarios, 43 in all, in six groups with a difficulty each:
  - Flicks: mid-range, wide (50–70°), vertical, tiny, spider (out and back to the middle).
  - Switching: six shot, head-line switching, close switching (up to 65° apart), tiny switching, double tap
    (two hits per target).
  - Reflex: targets that vanish after about a second, shorter after every hit (normal, small, wide).
  - Precision: pinpoint, far head-line, far spider, micro spider.
  - Duels: far and fast peeks; the doorway with an enemy model as close angle, long angle, jiggle peeks, wide swings
    and runners (headshots only).
  - Tracking: smooth, fast strafes, small target, jumping strafes, crouch spam, around you (a target circling you),
    air tracking, up and down.
- The scenario list is a library: filter by group and difficulty, search (in English and German), "not tried yet".
- The daily training picks from the whole library by what your matches show.
- German texts.

## 4.22.0
- **Quiz on the playback**: each question shows the round on the minimap up to the moment it asks about, locked
  there (no later kills on the bar or in the list, no round length) until you answer; then it plays on so you see
  what happened. If your coaching report of that match commented on the round, the coach's summary, mistakes and
  better option are shown with a link to the report. Questions from older quizzes work as before, without the map.
- **Who should learn what** (*Strategy › Comp sheet*): the agents your maps need (ideal comp, or picked by a third
  of the teams in your lobbies) that nobody has in their pool, the thin roles, and per player the one or two of
  those agents that fit best (how much they play the role, their ACS on it against players of their rank on the
  same agents; a player who alone covers another role stays there). *＋ Add to pool* adds it to the player's pool.
- The review evening's playback builder is shared with the quiz.
- German texts.

## 4.21.0
- **Team economy** (*Strategy › Economy*): the team's buys in your matches together, next to the teams in the same
  lobbies (same maps, patch and ranks): round win rate per buy and per matchup, forces that were lost and left you
  broke the next round, split buys (2+ on rifles while 2+ save), the round after a won pistol, who bought while the
  team saved (and the other way round) and how many rounds per match are lost to buys. Plain lines on what stands
  out; the weekly focus coach gets the same numbers.
- **The opponent's replays on match day**: when a scouted Premier team is in your replay files (3+ of the same
  players), the opponent card on the *Match screen* and the team's scouting page show its habits on the map with a
  link to *Replay scouting* and *Write counter-plans*. The *Match-day brief* (page and Discord post) lists every team
  of your division you have replays of.
- Fixed: posting the match-day brief to Discord failed when only one side's round win rate was known.
- German texts (also the matchup descriptions on *Rounds & economy*).

## 4.20.0
- **Lineups from your replay files** (*Strategy › Lineups*): utility one of you threw from about the same spot
  (within 4 m) to about the same spot (within 3 m) three times or more shows as a suggestion, with a small map of
  the throw, where it lands, the usual time and who throws it. *＋ Add* puts it in the library (add a clip later).
  The replay extracts are worked out once more to know where each throw came from.
- **Notes in your coaching reports**: the report's playback has *✎ Note* too (only you see them), *⇢ Strat board*
  (into your team's strat book) and the new picture buttons. Older reports get them as well (the current playback
  is loaded into the report).
- **A moment as a picture**: *⤓ Picture* saves the playback as it's shown (zoom, utility, notes) as a PNG; *📷 Discord*
  posts it with the notes around that time, from a report to the team's clip channel and from a review evening to
  its review channel.
- German texts.

## 4.19.0
- **Counter-plans from replay scouting**: on *Replay scouting*, *Write counter-plans for <map>* gives the coach the
  team's habits from the replay files (setup and spots at 20 s, utility with place and time, plants) together with
  your numbers, comp and roles. It writes 3 game plans (2 attack, 1 defense) built to punish those habits, each
  saying which habit it uses. They show under *Game plans* as *Counter-plans against …* (replacing that map's
  plans; *Write plans* makes general ones again) and the Discord match prep names the opponent.
- **Goals from "You vs your rank"**: every number that's behind your rank (or, where you're there already, a rank
  higher) has a *＋ Goal* button. It sets a goal for the next 10 games on the Habits page, which checks itself
  against your games. New goal numbers for that: kills, deaths and assists per round.
- German texts for both.

## 4.18.0
- **You vs your rank** (*Stats & maps*): your ACS, kills / deaths / assists / damage per round, headshot share, KAST
  and opening duels against the other players of your rank in your own matches (within one division, by the rank
  shown in each match), and against the players a rank higher once there are enough of them. Clear differences in
  green / red plus a line on the biggest ones. Game rows are rebuilt once from the cache (row v7) to get everyone's
  numbers; the coach gets the comparison too.
- **Notes on the playback** (*Review evening*): pause, press *✎ Note*, draw on the map and write a line. Everyone
  sees it on the time bar and in the *Notes* list; the drawing shows around its time and the playback stops there
  (*stop at notes*, can be switched off). Your own notes can be deleted, the host can delete all.
- **⇢ Strat board** on the review evening's playback: this moment as a new board in the strat book, with everyone
  alive where they stand (both teams, with names), the utility that's up and the drawings.
- **Replay scouting** (*Match day › Replay scouting*): from the replay files of your matches, how a team you played
  sets up (e.g. "A 2 · Mid 1 · B 2" at 20 s), the spots it takes, the utility it throws (type, place, usual time) and
  where it plants, per map and side, on the map. Works for your own team too ("how readable are we"). A team met
  more than once (three or more of the same players) is put together.
- The review evening's minimap uses the replay file when there is one (all ten players' paths, placed utility).
- German texts for all of it.

## 4.17.0
- **When you play best** (*Progress*): your win rate by game in the session (games less than 75 minutes apart count
  as one session), after 0 / 1 / 2+ losses in a row, by time of day and by weekday, each bar green / red when it is
  5 points above / below your overall win rate, faded when it rests on few games. When a difference is clear the
  page says it in a sentence ("From the 4th game of a session the win rate drops from 56% to 41%: stopping after 3
  games is worth trying"). The coach gets the same numbers.
- **Who plays well together** (team *Player overview*): every pair of teammates with games, win rate, how often they
  traded each other and how often both died alone in the same round, plus the best and weakest pair, the pair that
  trades each other most and the one that splits up most. The weekly focus coach sees each player's pairs.
- German texts for both.

## 4.16.4
- **Rank over time stays current**: besides HenrikDev's stored rank history (long, but only updated when HenrikDev
  looks the account up, so it could lag days behind), every import now also reads the live history of the last
  ranked games. Both are merged, nothing is counted twice. The import log shows both ("recent rank", "rank
  history").
- The rank chart's labels no longer blow up on wide screens (normal font and size).

## 4.16.3
- **Placed utility in the round playback** (reports with a replay file): smokes (grey areas), slows and mollies /
  damage zones (coloured areas), walls, traps, recon bolts and drones (pulsing ring), orbs and flashes (ability
  icon), each at its spot for as long as it lasted, outlined in the owner's team colour; hover for who and which
  ability. From vrfkit's effect actors (class, spawn spot, open / close); a thrown projectile is placed where it
  last moved. Replays stored before are read again once; run the coaching again for older reports.

## 4.16.2
- **Utility in the round playback** (reports with a replay file): a ⚡ pulse where a player used an ability, small
  ticks under the time bar (your casts taller), "⚡ N" abilities so far next to each player, your own casts in
  *Round events*, and a *utility* switch to hide them. Buy-phase casts show at 0:00. Reports made before this
  update get it when the coaching is run again.

## 4.16.1
- **Replay files on the Server page** (*Server*, admins): how many matches have a replay file, their size, how many
  were uploaded in the last 7 and 30 days, the last upload, how many still have the .vrf, how many were lined up
  with the match data and how many have ability casts, replays per map, and whether vrfkit works. Their size is
  also listed under *Disk*.

## 4.16.0
- **Utility timing from replay files**: the ability casts in the replay (vrfkit's *AbilityCastsThisRound*) give
  *Utility before the first fight*, *Died without using utility* and *First ability* (median, attack / defense)
  on *Habits › From your replay files*, and the coaching run sees each round's casts. Replays stored before are
  read again once (needs the kept .vrf and vrfkit).
- **Check-in reminder on Discord**: a Premier review posted to Discord starts with "How did it go?" and a link to
  that match's check-in. Reviewed Premier matches show on the check-in page right away, before the next stats
  update.
- **Releases tag themselves**: merging a PR that raises the version tags exactly that commit and starts the
  Windows app build (`.github/workflows/release-tag.yml`); it refuses when the three version numbers differ. No
  more `git tag` by hand.

## 4.15.0
More accurate coaching: the coach knows how reliable each number is, sees more than the kill moments, and learns
whether its advice worked.
- **Replay-file numbers** (*Habits › From your replay files*): untradeable deaths (no teammate within 15 m then
  or in the next 3 s), retake arrival (got to the spike, after how many seconds), and setups: where each player
  stands 20 s into the round per map and side, with the win rate of each spot. Also given to the coach.
- **Recent games and the current patch count more**: half the weight every 45 days, older patches 60 %, stronger
  lobbies a bit more. Used by the comp maker (all modes) and the coach; shown on *Stats & maps › How much the
  numbers tell*.
- **Buy state and lobby strength**: rounds split into full buys, anti-eco and your own eco / force (round win
  rate, K/D), with a note when the K/D mostly comes from anti-ecos; games against stronger / similar / weaker
  lobbies. The buy states are part of *Thrives in / Struggles in*.
- **"Solid" or "early sign"** on every playstyle label and situation (*), and in the coach's data; the coach must
  quote the number behind each point and call early signs early signs.
- **Goals** (*Habits › Goals*): a number, a target and the next games, checked automatically after every game
  (reached / missed). Set by the weekly focus, by *Make it a goal* on a habit, or by hand. The coach sees the
  results and changes approach where a goal was missed.
- **Post-match check-in** (*Match day › Check-in*): who called, comms and mood (1–5), one line, in about 20
  seconds. From 3 votes, the IGL suggestion follows the team's answers instead of a guess. Used in Premier reviews,
  the weekly focus and *Ask the coach*.
- New habit: **Dying with utility unused** (deaths in rounds without any ability, from the match data).
- Rows are rebuilt from the cached matches at the next stats update (patch, lobby ranks, kills per round).

## 4.14.1
- **Comp sheet uses the space better.**
  - *Ideal composition*: a map with a comp is now one full-width row: the map with its source and buttons on the
    left, then a wide column per agent with the players who have it in their pool (green = high in the pool, red =
    low; long names are shortened, hover for the full name). Maps without a comp are small cards below and no longer
    stretch to the height of the others.
  - *Agent pool*: each column shows the top 8 agents, "+ N more" / *Show all agents* opens every list at once so
    the columns stay comparable. Long player names no longer push the column header out.

## 4.14.0
- **Follow our agent pools**: a new switch next to *Make comps with* (comps page), on the comp sheet and in the
  team settings. When it's on, the comps use each player's agent pool from the comp sheet in every mode (Map
  rules + your stats, Most comfortable, From the web, Your stats only), for drafts and the Discord prep too:
  - agents a player marked *won't play* are left out;
  - agents he ranked high get a bonus; in *Most comfortable* his own order counts instead of games played;
  - agents he added by hand can be picked even without games (no "new agent" penalty in *From the web*).
  Each pick says why, e.g. "#1 in Sam's agent pool". Off by default; the team owner switches it.

## 4.13.0
- **Comp sheet** (*Strategy › Comp sheet*): the team's agent pool and ideal comps on one page.
  - *Agent pool*: a column per player, best agent first and coloured green to red, made from the stats (most played,
    then win rate). Each player can reorder his own list, add agents and mark agents he won't play; the team owner
    can edit every list. *Back to the stats* resets a list.
  - *Ideal composition*: per map the comp web sources name most (searched with one click, also when the comps page
    uses another mode) or 5 agents set by hand. Under every agent: who has it in his pool and at which rank,
    "nobody" if no one does.
- **Fix: "From the web" said web search was off** although it is on (DuckDuckGo by default). The check looked at a
  setting that doesn't exist; it now uses *Settings › Web search*.
- **Explanations that open**: the labels in the player overview (playstyle, thrives / struggles, suggested role,
  IGL / Operator, table cells) show their explanation in a popup on hover, on keyboard focus and on tap (phones).
  Before, only a "?" cursor appeared and nothing came up.

## 4.12.0
- **Playstyle labels** in the player overview, independent of the team role: up to three of *Aggressive*,
  *Patient*, *Clutch player*, *Trader*, *Lone wolf*, *Survivor*, *Fragger*, *Playmaker*, *Brawler*,
  *Long-range duelist*, *Operator player*. Hover a label to see the numbers behind it.
- **Thrives in / struggles in** per player: opening duels, clutches, retakes, post-plants, close / mid / long-range
  duels, attack vs defense, fighting away from vs next to the team, trading teammates; compared with typical ranked
  values, with a minimum number of rounds and small samples pulled towards typical. In the full view too.
- Both come from the round data of the stored games; no model needed.

## 4.11.0
- **Player overview** (*Roster & setup › Player overview*): who plays what, at a glance. Per player the role (yours
  from *Roles*, else the suggestion) and IGL / Operator, the most played agents, the split over Duelist / Initiator /
  Controller / Sentinel, the playstyle (four bars, in words, closest pro) and the best maps. On top: which agent roles
  every starter plays regularly, roles nobody covers, two players with the same main. Two views: **Top 5 agents**
  (cards) and **All agents** (every agent and every map in a table, players side by side). Calculated from the games,
  no model needed.

## 4.10.1
- **Make comps right on the comps page** (Strategy › Comps): pick how the comps are made (Map rules + your stats,
  Most comfortable, From the web, Your stats only) and click *Make comps*; no trip to the team settings. With
  *From the web*, the selected map is searched right away if it hasn't been yet. Teammates see which mode is used;
  the team owner changes it.

## 4.10.0
- **Comp suggestions, four modes** (team settings): *Map rules + your stats* (default, as in 4.9), *Most comfortable*
  (every player on what he plays most, on that map first; win rates don't count), *From the web* (comps that web
  sources name for the map, handed to your players by their numbers, with the sources linked; *Search comps for
  <map>* / *All maps* on the comps page, needs Settings › Web search) and *Your stats only* (as before 4.9).
  Drafts and the Discord prep use the team's mode too.
- **"You are" is gone** from the comps page: you are the team player whose Riot ID is your in-game name (Account),
  linked by itself. Links set before stay.
- **Dropdowns readable in every style**: the open list of a select (e.g. the model picker) was see-through in the
  Neon and HUD styles, especially in the Windows app.
- Security (CodeQL): replay file paths only take a match id and must stay inside the replays folder; the vrfkit
  test no longer shows the system's error text (it goes to the server log).
- README: installing vrfkit without Docker needs a C compiler and linker (`build-essential`).

## 4.9.0
- **Replay files**: VALORANT's own replay of a match (`.vrf`, downloaded in the game's match history, Competitive and
  Premier) has every player's position for the whole round. Upload it on the match's coach page (*Replay file* card)
  or let the Nexus app send new ones by itself (*This PC › Replay files*). Nexus reads it with
  [vrfkit](https://github.com/yakisoba0728/vrfkit) and lines it up with the match data by the kills, so:
  - the round coaching gets where **both teams** really were, per 10 s (setups, stacks, rotations, timings), not only
    what your minimap showed;
  - the report's replay draws **all ten players' real paths** instead of estimating them between kills;
  - no recording is needed for that; a VOD still gives the jump buttons.
- **Switch back**: *Settings › Replay files › Positions* = *VOD minimap only* makes reports exactly as before.
  With *Replay file when there is one* (default), a match without a replay file, or with one that doesn't fit the
  match data, uses the VOD minimap as before. The report header says which positions were used.
- **vrfkit**: the Docker image builds it. Without Docker install it once (README, *Replay files*); *Settings › Replay
  files › Test* checks it. New dependency: `pyarrow` (`pip install -e .` installs it).
- **Team comps with map rules**: *Comp suggestions* in the team settings. *Map rules + your stats* (default) adds what
  the stats can't know: the role mixes that work on each map, the agents a map needs or rewards (a Viper wall on Breeze
  and Icebox, recon on Ascent, …), and for every comp a controller, at most two duelists, someone to flash corners and
  someone for information. Every rule that changed a comp is shown under it, and the picks say why. *Your stats only*
  makes comps exactly as before. Admins edit the rules under *Settings › Map rules for team comps*; a team's own map
  meta still wins.
- Nexus app for Windows 4.9.0: sends replay files from VALORANT's Demos folder (on by default; each file once, one the
  server can't read is not sent again).

## 4.8.0
- **Aim insights** (*Practice › Aim insights*, or *Aim insights* on the trainer page): every round in the aim trainer
  now measures how you aim, and the page shows what stands out over the last 30 days:
  - flicks per direction: slower to the left than to the right (or up than down), small corrections or big turns that
    take long, flying past targets or stopping short;
  - where missed shots land (above, below, left, right of the target);
  - tracking: on target while it moves left against right, behind or ahead of it, how long it takes to be back on it
    after a direction change;
  - duels: reaction to peeks from the left and the right, where your crosshair waited (below or above head height), body
    shots instead of headshots;
  - how much your scores jump around.
- Each finding says what was measured, gives tips for your **hand and grip** (pick right or left hand and palm, claw or
  fingertip on the page: a slow side toward the thumb needs more forearm, flying past with a fingertip grip needs a
  little palm contact, …) and links the scenarios to play (*Play …* opens the scenario in the trainer). What's already
  good is listed too.
- **Charts**: a skill profile (flick speed, accuracy, small fixes, tracking, reaction, crosshair placement,
  consistency), a wheel of flick speed per direction coloured by flying past or stopping short, a map of where missed
  shots land around the target, tracking left and right with a behind/ahead gauge, peeks per side with where your
  crosshair waited, flick time by size, and scores over time per scenario.
- **Focus training**: the scenarios for the top findings, two rounds each, on the insights page and as a third plan on
  the trainer page. Finishing it ticks it off on the Aim page like the warm-up and training.
- The coach (*Ask the coach*) knows the top findings, your strengths and your grip.
- Only rounds played from this version on carry the measurements; older scores stay as they are.

## 4.7.2
- **Availability: everyone sets only their own days**, the team owner too. And nobody has to pick who they are: Nexus
  finds your player by the in-game name you entered when signing up (or under *Account*, `Name#TAG`), or by an
  existing link to your player on the team page. Your row is at the top and marked *You*; the other rows can't be
  clicked. Without an in-game name, the page says where to set it.

## 4.7.1
- Sens finder chart: point at a dot to see that round: the sens, cm per 360° with your DPI, how good it was compared
  with that test's best, and the day and length of the test (tap on a phone). The dot nearest the pointer is picked,
  so dots close together can each be reached.

## 4.7.0
- **No more pauses in the sens test**: a new flick target was placed from where you aimed, and after a few low ones it
  could land in the floor, hidden, so you searched until the round moved on. Targets now always stay between floor and
  ceiling, every part of a round starts at your crosshair, and between rounds a line says which test is next. If the
  browser itself stands still (another program, a busy tab), the result says so, so it isn't taken for the trainer.
- **Crosshair inside the trainer**: *Crosshair* on the start, pause and result screens opens the settings next to the
  game, so you see your real crosshair while changing it (Valorant code in and out as before). Esc or *Done* closes it.
- **Sens finder in 5, 15 and 30 minutes.** 15 and 30 minutes play close flicks, far flicks, close, far and reactive
  tracking in every round and show which sens each part likes (flicks often like a little less than tracking). 30
  minutes: more sensitivities, the close ones three times, your own sens at the start, middle and end to measure tiring,
  and a minute's break halfway. Longer tests count more (15 min twice, 30 min three times). Tiring is now worked out
  from all rounds at your own sens.
- **New scenarios**, grouped into flicks, duels and tracking: *Close flicks* (big targets far to the side, an enemy next
  to you), *Far flicks* (small targets on a long angle), *Close tracking*, *Far tracking*, *Reactive tracking* (short
  ADAD strafes and sudden stops), and **Hold the angle**: you hold a doorway and an enemy model swings wide, jiggles or
  runs through from the left or the right. Only a headshot kills; body shots and enemies that got away are counted.
  Today's training can pick them too.

## 4.6.1
- **Aim trainer: fullscreen** while playing, on by default (a switch next to the sensitivity; F switches it while
  playing). In the Nexus app the whole window goes fullscreen.
- **Crosshair drawn on the screen's real pixels**: with Windows display scaling (e.g. 125%) the browser stretched it
  by a fraction of a pixel, which made the lines look smeared and uneven. It's also exactly the same on all four
  sides now (the right and bottom lines sat one pixel further out), in the game and in the preview.

## 4.6.0
- **Aim trainer** (*Practice › Aim trainer*): Nexus's own aim trainer in the browser and in the Nexus app. It plays
  like Valorant: your Valorant sensitivity, Valorant's field of view (103° at 16:9) and raw mouse input through
  pointer lock (Chrome, Edge and the Nexus app; other browsers say that Windows' acceleration applies). Five
  scenarios: grid flicks, head-line flicks, micro taps, peek reaction (enemies peek from behind cover) and strafe
  tracking. *Today's warm-up* is three short rounds; *today's training* picks the scenarios that fit what your matches
  show, the one furthest below your best first. Scores, best and trend per scenario, kept per player. Finishing a
  warm-up or training ticks it off on the Aim page, where both are new routines (*Open the trainer*).
- **Sens finder** (in the aim trainer), in two modes. *Quick* (about 5 minutes): one warm-up at your sens, then ten
  20-second rounds of a mixed test (flicks, micro corrections, tracking), five sensitivities from 70% to 130% of yours
  and five close around the best of those. *Thorough* (about 11 minutes, counts twice): two warm-ups, then 21 rounds of
  25 seconds, seven from 65% to 150%, six close values played twice each, and your own sens at the start and the end:
  how much worse the last one was shows how much you tired, and the rounds in between are corrected for it. Both
  blind and in random order. It measures how you hit: overshooting the target (too fast),
  stopping short (too slow), time to hit, accuracy and time on the moving target. A curve through the results gives the
  recommended sens and the range that works about as well, with cm per 360° and a chart. Tests of the last 90 days are
  combined (each scaled to its own day), and it says how sure it is (one quick test, or several days that agree). If the best
  was at the end of what was tested, the next test starts there. A change of more than about 10% comes as weekly steps.
- **Crosshair** (in the aim trainer): like Valorant's crosshair, in screen pixels: colour, outlines, centre dot, inner
  and outer lines (length, thickness, gap, opacity), with a preview. Paste your Valorant crosshair code to take it over,
  or copy yours as a code for Valorant. Kept per player.
- **Esc pauses properly**: during a round and during the countdown, with *Continue* (also Enter or Space), a short
  countdown back in, and the round goes on where it stopped. Esc no longer closes the trainer by accident, and when the
  browser needs a moment after Esc before it can lock the mouse again, *Continue* waits for it.
- In the sens finder's test the moving target now appears right at the crosshair and moving, with *Track it* and the
  target lighting up while you're on it (it looked like a pause before). Between rounds: 2 seconds instead of 3.
- **Mouse & monitor** (*Practice › Mouse & monitor*): the real DPI of your mouse (move it a known distance along a
  ruler, several tries averaged, compared with the DPI you set, with a hint when the browser's display scaling is the
  difference), the polling rate, the refresh rate your screen really shows (with a moving test square), and a button
  test that catches worn switches that double-click. Plus eDPI and cm per 360° with the DPI you set and the one
  measured. *Save* keeps the values for the trainer and the coach.
- *Ask the coach* knows the trainer scores and your mouse (sensitivity, measured DPI, cm per 360°, polling and screen
  rate).

## 4.5.0
- **valcoach is now Nexus.** The name in the app, the Python package (`nexus/`), the command (`nexus web`,
  `nexus --version`), the service (`deploy/nexus.service`), the Docker image and the environment variables
  (`NEXUS_BACKUP_ROOTS`, `NEXUS_MODEL`). What carries over by itself: `data/valcoach.db` is renamed to
  `data/nexus.db` at the first start (with its `-wal`/`-shm` files), backups named `valcoach-backup-…` still count
  for the list and how many are kept, the old `VALCOACH_*` variables still work, logins and the language cookie
  stay. Once on the server: `pip uninstall -y valcoach && pip install -e .`, then install `nexus.service` instead
  of `valcoach.service` (README › *Coming from valcoach*). The GitHub repository keeps its name for now.
- **Nexus for Windows instead of the companion app.** One app that shows Nexus in its own window (WebView2) with
  everything the website has, plus **This PC** in the menu, which only exists in the app: the player, a tile each
  for playlists, scores and Medal, the two folders, the switches, the activity, *Sync now*, updates and *Change
  server*. You log in in the window like on the website; the website then gives the app its own key for that PC
  (`POST /account/devices/pair`, with the session and the usual same-site check), so there's no second login. Tray
  icon, *Start with Windows*, the installer and the updates stay. Links to other websites open in the browser, and
  only Nexus's own pages can talk to the app.
- **From the companion app:** it updates to the new app by itself (each release has the installer a second time
  under its old name, `valcoach-companion-setup.exe`). The installer removes the old program file and shortcuts,
  the app takes over the settings, what was uploaded already, the device key and *Start with Windows*.
- *Account*: the section is now *Nexus app for Windows*; the coach page says *From the Nexus app*.

## 4.4.2
- **Companion app without the long scroll:** a sidebar with *Overview*, *KovaaK's*, *Medal* and *Settings*, one page
  at a time, in a wider window. *Overview* has the player, a tile each for playlists, scores and Medal (on, off or
  "check folder", with the last result; a click opens its page) and the activity. Status and *Sync now* stay at the
  bottom of the sidebar. Logged out, the app only shows a login card.

## 4.4.1
- **The installer is built however a release is made:** pushing a tag `vX.Y.Z`, publishing a release on GitHub's
  page (that didn't start the build before, so v4.4.0 had no installer at first), or *Actions › companion › Run
  workflow* with *release* set to a tag, which attaches the installer to that existing release afterwards.
- A test's fake GitHub check looked for `api.github.com` anywhere in the address (CodeQL warned); it checks the start
  of the address now. The app itself always checked the start.
- The test workflow only gets read access to the repository (CodeQL's advice for workflows).

## 4.4.0
- **Companion app: an installer instead of a loose .exe.** `valcoach-companion-setup.exe` installs it for your
  Windows user (no admin rights) into `%LOCALAPPDATA%\Programs\valcoach companion`, with a Start menu entry and an
  uninstaller under *Settings › Apps*; the downloaded installer can be deleted right away. Uninstalling also
  removes *Start with Windows*.
- **The companion app has valcoach's version** (this one is 4.4.0 too, after 1.1.0). Releases are the normal
  valcoach tags `vX.Y.Z`: pushing one builds the installer on Windows and attaches it to that release (the workflow
  refuses a tag that doesn't match the version, and a test checks that both version numbers agree). The
  `companion-v...` tags are gone.
- **Updates go through the installer:** the app downloads it to the temp folder, checks it against the SHA-256
  GitHub lists for the file and runs it silently; the app closes and starts again by itself.

## 4.3.1
- **Companion app 1.1.0:**
  - **Updates itself.** Once a day (and on *Check for updates*) it looks for a newer release on GitHub; *Update now*
    downloads it, checks it against the SHA-256 GitHub lists for the file, swaps it in and restarts. To publish a
    version: raise it in `companion/valcoach_companion/__init__.py`, merge, push the tag `companion-vX.Y.Z` (the
    workflow refuses a tag that doesn't match).
  - **New look:** dark, in valcoach's colours, with cards for account, KovaaK's, Medal, activity and the app,
    switches instead of checkboxes, a status in the header (up to date / working / logged out) and *Sync now* at
    the bottom. The .exe and the window have valcoach's diamond as icon.
  - The window and the background sync could save the settings at the same moment and lose a write; they take
    turns now.

## 4.3.0
- **Companion app for Windows** (new, in `companion/`): a small tray app for each player that every few minutes
  - puts the coach's KovaaK's warm-up and training playlists into KovaaK's Playlists folder (dated, once a day;
    the coach's own files older than a month are removed, nothing else is touched),
  - sends new KovaaK's scores from KovaaK's `stats` folder to the Aim page,
  - cuts your matches out of **Medal** session recordings and uploads them: Medal names a recording after its start
    to the millisecond, Riot's data has each match's start and length, so every match in an evening-long
    recording is found, however long you were in the menu. Cut without re-encoding, 90 s before and 60 s after the
    match; a recording whose length doesn't fit its times (Medal paused) is skipped instead of cut wrong.
  Each part can be switched off. Built as one .exe by GitHub Actions (push a tag `companion-v1.0.0`).
- **The coach page picks the companion app's clip** of a match by itself (*From the companion app*). Like any
  uploaded VOD it's deleted after the report; clips no report used are deleted after 14 days
  (`companion_keep_days`).
- **Account › Companion app**: the devices logged in to your account, each with *Log out*. The app logs in with
  username and password once and gets its own key for that PC (only its hash is stored; it only opens the app's
  `/api/companion/...` calls, and changing your password logs out every device). Logging in from the app counts
  toward the same lockout as the login page.
- The match list gives each match's length to the app (`length_s`).

## 4.2.2
- **Settings › Web search › Test shows each search on its own line** with its own ✓ or ✗ (before: one line with a
  green ✓ as soon as either search worked, even when the main one had failed).
- **DuckDuckGo's refusal is described correctly:** it often refuses searches that don't come from a browser, even the
  very first one, so it isn't about searching too much. The hint now recommends SearXNG as the main search and
  DuckDuckGo as the backup at most. valcoach doesn't try to get around DuckDuckGo's check.

## 4.2.1
From code reviews of 4.2:
- **Search the web for KovaaK's playlists runs in the background.** It reads up to six pages and used to keep one of
  the server's few web workers busy for up to a minute; now the page asks every few seconds until it's done.
- **Web pages are read from exactly the address that was checked.** Before, the check looked the name up and the
  download looked it up again, so a name that changes its answer in between (DNS rebinding) could have reached the
  LAN. HTTPS still checks the certificate for the name.
- Web search: the pages that get read are the best hit of *each* search (before: the first three hits of the first
  search), the search cache keeps at most 500 searches, and a model that writes no search queries is logged.
- Errors when the coach can't answer (*Ask the coach*, questions about a round) show valcoach's own messages
  (Ollama not reachable, no Claude key, budget used up ...); anything else shows a general message and the details
  go to the server log.
- `X-Forwarded-Host` only counts for the form check when the request comes from a reverse proxy on this machine or
  the local network.
- **The database uses SQLite's WAL mode**: pages keep loading while a job writes. Nothing to do: it switches on at
  the next start.
- Faster report parsing: kills are grouped by round once instead of searched for every round, and the deaths of a
  round are worked out once instead of up to four times.
- `knowledge/playbook.example.yaml` uses `teammate1` again, like the copy in the app.
- `werkzeug`, `markupsafe` and `urllib3` are listed as dependencies (valcoach imports them itself).
- New: `CONTRIBUTING.md` (setup, tests, what a pull request needs), `SECURITY.md` (how to report a problem
  privately, what valcoach protects), `.pre-commit-config.yaml` (ruff before every commit: `pre-commit install`).
- README: the overview is a diagram GitHub draws (Mermaid), with a table of contents below it.

## 4.2.0
- **Ask the coach** (*Practice › Ask the coach*): a chat with the coach about one player. It knows the player's recent
  form, agents, maps, habits, what their aim needs and their KovaaK's scores, and remembers the conversation (per user
  and player; *New conversation* starts over). Answers are written in the background, with the model picker like
  everywhere else.
- **Web search for the coach** (*Settings › Web search*): **DuckDuckGo** by default (free, no setup; it has no
  official search API, so valcoach reads its plain results page, and it blocks a server for a while after many
  searches), your own **SearXNG** server (free; it must allow JSON, see the README) or **Claude's web search**
  (Anthropic key, US$ 10 per 1,000 searches, in the Claude budget). A **backup search** takes over when the main
  one fails or finds nothing, e.g. DuckDuckGo with SearXNG as backup. Set it to *Off* to turn web search off. For each question the model decides whether to look something up (patch changes, abilities, pros,
  KovaaK's playlists; at most three searches), reads the best pages and answers with the pages it used as links.
  Also in *Ask the coach about this round* in reports. Pages are only read from public addresses (never the server
  itself, your LAN or cloud metadata, also after redirects), at most 600 KB, text only. A *Test* button checks it.
- **KovaaK's playlists from the community** on the Aim page: 39 public playlists by share code (the Valorant /
  Counter-Strike routines, ones for a single problem such as micro-flicks, peeking or reactivity, and the Voltaic
  fundamentals by level), from the community list at github.com/officialpure/Resources. The four that fit what your
  matches show, at about your level (from your imported scores), are on top; *Add to routines* puts one in your or
  your team's routines. Paste the code in KovaaK's under *Sandbox › Online Playlists › Enter Share Code* and it
  downloads every scenario. With web search, *Search the web* finds more share codes online.
- **Page width** under Account › Look & feel: *Like the style* (as before: only Data terminal uses the whole width),
  *Centred* or *Full width*, for every style.
- **Backups to a read-only folder are explained**: instead of *[Errno 30] Read-only file system* the error says that
  the systemd service may only write to its data folder and which `ReadWritePaths=` line to add. Saving a backup folder
  in Settings now checks that valcoach can actually write there.
- **Security (found by GitHub's CodeQL scan):**
  - Redirects after logging in, switching the language and the Aim page's buttons only go to pages of valcoach.
    Before, a crafted link such as `/login?next=/\evil.example` could send someone to another site after logging in
    (browsers read `/\` and `/<tab>/` like `//`).
  - Web search errors shown in the browser (Settings › Test, Ask the coach, the Aim page) are fixed texts now;
    the details from the search server or the exception only go to the server log.
  - The backup folder must be a full path without `..` inside `/mnt`, `/media`, `/srv`, `/home`, `/backup(s)`,
    `/var/backups` or the data folder. Other places: list them in the environment variable `VALCOACH_BACKUP_ROOTS`
    (separated by `:`), e.g. in the systemd service.
- German for everything new.

## 4.1.2
- **Fix: valcoach didn't start on Python 3.11.** One line in the agent details (utility note) used nested f-string
  quotes, which only Python 3.12+ can read, although 3.11 is supported. 3.12 and 3.13 (Docker) weren't affected.
- **The tests now run on Python 3.11 and 3.12**, and a linter (ruff, settings in `pyproject.toml`) checks every pull
  request, so syntax a supported Python can't read, undefined names and leftover imports are caught before merging.
  Run it locally with `ruff check valcoach tests` (it comes with `pip install -e ".[dev]"`).
- **Ollama retries wait** (2 s, then 4 s, at most 8 s) when the server can't be reached or answers with an error,
  e.g. while it's still loading the model, instead of trying again instantly and failing. A reply that isn't valid JSON
  is still retried right away.
- With Claude and the local model as fallback, Claude now gets the caller's retry setting too.
- An unknown coaching mode (not `both`, `team` or `player`) stops with a clear message instead of a crash halfway.
- Server errors show valcoach's error page (with a hint to check the server log) instead of a bare *Internal Server Error*.
- Dependabot keeps the GitHub Actions in the workflow up to date.
- Tests: the Premier page test no longer expects a fixed map (it failed once the season reached week 3), and the
  *Ask the coach* test waits longer, so it doesn't fail on a busy machine.
- Cleanup: unused imports and variables removed; `.git` is no longer sent to Docker builds.
- README: install and update with git instead of a zip, what the server needs (GPU memory for the model, CPU for the
  video part, disk space for VODs), *Known limits* updated for the fixes from the first real recording.
- `valcoach-fixes.patch` is removed (everything in it has been in the code since 2.17.0) and `CHANGES.md` moved to
  `notes/review-fixes-2.15.md`.

## 4.1.1
- KovaaK's playlists from the coach carry the date (DD-MM-YYYY) in their name and file name, e.g.
  *valcoach warm-up 03-11-2026* in `valcoach_warmup_03-11-2026.json`: older ones can stay in the Playlists folder and
  you can tell them apart. A second download on the same day has the same name and replaces that day's file.
- The training playlist is no longer the warm-up with more runs: it plays **other scenarios** than that day's
  warm-up, at most two runs each (about 10–13 different ones), medium first and then harder ones for what your
  matches need, and ends with something different (a kind you don't train otherwise, often tracking). A scenario
  is only repeated when your scenario list has nothing new left.

## 4.1.0
- **KovaaK's playlists from the coach** (Practice › Aim): a **warm-up** (~10 min) and a **training** playlist (~25 min),
  built from what your matches show and changed every week. *Download for KovaaK's*, save the file in
  `FPSAimTrainer › Saved › SaveGames › Playlists` (it replaces last week's) and open it under *Local Playlists*;
  scenarios you don't have yet download by themselves.
  - A low headshot rate gets micro-adjusting and head-level scenarios, losing first duels gets reaction and peeking
    ones, and so on. Each scenario shows what it trains, its level and your best and last score.
  - The coach's warm-up is a routine like the others: tick it off, make it your or the team's warm-up (match screen,
    Home, practice plan, the push before the match). Anyone with imported scores gets it as the default warm-up.
- **Your KovaaK's scores:** import the `.csv` files from `FPSAimTrainer › stats` (or the folder as a zip; runs already
  imported are skipped). Per scenario: runs, best, last, a small chart and the trend. Once you're steady near your best
  on a scenario, the next playlists use harder ones of the same kind. Days with a KovaaK's run count as warm-up days
  in *Does warming up help?*
- **More scenarios for the coach:** 53 are built in (all from well-known playlists). Add your own: import playlist
  files (every scenario in them joins the list, and the playlist itself becomes a routine with its share code), add
  one by hand with what it trains and its level, or let them come in with your scores. Per user or for the whole team.
- German: messages made of several sentences are translated sentence by sentence.

## 4.0.0
- **Deutsch:** the whole interface in German, picked per user under Account › Look & feel › Language (English stays
  the default). Menus, every page, buttons, messages, confirmations, the minimap replay and notifications on your
  phone. The login page follows the browser's language and has a Deutsch / English switch.
  - **Discord posts** have their own language per team (Team settings › Discord › Language of the posts).
  - The coach's texts (reports, reviews, tips, quiz) stay in each player's coaching language, as before. People's
    own notes, strat names and drafts are never changed.
  - The change notes on *What's new* stay in English.
  - How it works: pages are written in English and translated on the way out from one list
    (`valcoach/i18n/de.json`). Text that scripts add later goes through the same list in the browser. Anything
    missing from the list simply stays English, so a new feature never breaks the German interface.
- **Menu at the top fits any width:** the bar measures itself and shrinks step by step only as far as needed
  (icons, your name and uptime, the picker names, the logo text, spacing, finally group icons only). Long player and team
  names or the longer German labels no longer run into the icons on the right.
- Examples and placeholders are generic now (`Name#TAG`, *teammate1* in the example playbook, all regions in the
  region hint) instead of one player's names.

## 3.8.0
- **Aim** (Practice, per player): aim routines and a warm-up before matches.
  - **Routines:** five built-in ones for the Range and Deathmatch (warm-up, headshot-only, peeking, micro-adjusting,
    spray), plus your own and your team's: an **Aimlabs share link** (opens Aimlabs and offers the playlist), a
    **KovaaK's share code** (with a copy button), any other link, or steps. Each says what it trains.
  - **For you:** the routines that fit what your matches show: a low headshot rate → crosshair placement and
    micro-adjusting, losing first duels → peeking and flicks. Match data shows *that* you lose duels, not *why*,
    so the page says so and you can pick anything else.
  - **Your warm-up:** the one you pick, else the team's warm-up (the owner sets it), else the
    shortest routine marked *Warm-up* (yours and the team's before the built-in ones).
    It shows on the match screen and the Home banner on match days, is the warm-up item in the practice plan, and
    comes as a notification 30 minutes before the match (Account › Notifications › Warm-up).
  - **Done today**, with an optional score you type in (valcoach can't read Aimlabs or KovaaK's). Your scores per
    routine are listed, and after a few weeks the page compares your headshot rate on warm-up days with the other days.
- Inputs without a type no longer look greyed out (review evening note, new aim form).

## 3.7.0
- **Review evening** (Practice): go through one match round by round together, on a shared screen or each on his own.
  - Pick any match two or more of you played (or *Review it together* on a Premier review). Whoever starts it hosts:
    he moves from round to round, everyone who follows the host jumps along. Arrow keys move, *Key rounds only*
    jumps through the rounds that decided the match.
  - Every round: won or lost and how, both teams' buys, the first kill, the plant, who was alive at the end, deaths
    nobody traded, the kill feed, your five players' numbers and the minimap replay.
  - Everyone marks his own round: **my fault**, **good** or **talk about it** (keys 1, 2, 3), with a short note.
    The strip at the top shows which rounds are marked; everyone's marks show up live.
  - **Summary:** the rounds to talk about with the notes, every player's rounds, and what keeps coming up in the
    rounds you flagged (deaths nobody traded, thrown leads, post-plants...). The host puts that into this week's
    practice plan (it stays in when the plan is made again), the owner can post it to Discord.
- **Round types for scouted opponents** (Opponents › a team): their pistol, eco, force and full-buy win rates, what
  they buy after a lost pistol, the round after a won pistol, post-plants and retakes, with lines like *after a lost
  pistol they force-buy 70% of the time*. The important ones also show up in *How to play them* and on the match
  screen. Teams scouted before 3.7 get it with *Scout again* (the matches are cached, so it's quick).
- **Server page:** how much of the model is in GPU memory (*9.1 of 12 GB on the GPU*), a warning when part of it
  runs on the CPU, and the context length.
- Fixes: sub-points on *What's new* are a list again instead of one long line; a damaged draft no longer breaks the
  Drafts page; error pages no longer show a menu entry as the current page.

## 3.6.0
- **Agents & roles › an agent in detail** (*Details* next to every agent):
  - **Progress over time:** your combat score game by game (5-game average) with each win and loss, and your first
    games on the agent against your latest (ACS, win rate, K/D).
  - **Utility per agent:** how often you use each ability per round (by name, e.g. Updraft, Tailwind), against
    everyone else on that agent in your matches, with a note when you use something much less than others.
  - **You against your lobbies:** combat score, kills, deaths, assists, first duels and headshot rate against every
    other player on the same agent in your matches, with where you stand (*better than 63 %*).
- **Agent × map:** win rate and games for every agent on every map in one grid, good and bad cells coloured.
- **Rounds & economy** (Performance): pistol, eco, force and full-buy win rates (per side), uneven buys (anti-eco,
  force against a full buy, eco against a full buy...), the bonus round after a won pistol, post-plants, retakes,
  and rounds where you bought while the team saved. Plain-language findings when something stands out.
- **Teammates** (Performance): everyone you played with 3+ times: games, win rate, your combat score with them, premade
  or random, on which maps; best and weakest duo; solo against with a party.
- Games now also store ability use, every round's buys, your teammates and everyone's numbers by agent. Games loaded
  before 3.6 get them with the next *Load new games* (rebuilt from the stored matches, nothing is downloaded again;
  the nightly sync does it for team members). The pages say when that's still missing.

## 3.5.0
- **Habit tracker** (Practice › Habits, per player): six habits that cost rounds, measured game by game: dying far
  from the team, deaths nobody trades, losing the first duel, rounds without impact, a low headshot rate, and dying
  at the same spot (named, e.g. *Dying at B Main on attack*).
  - Your last 10 games with round data against the 20 before: **Gone**, **Getting better**, **Still there**,
    **Getting worse** or **Fine**, with both numbers, the line where it starts to cost rounds, and a small chart of
    the last 20 games.
  - **What the coach said:** problems named in your reports and Premier reviews are matched to a habit by their
    words, with the numbers before and after that report: *better since*, *no change since*, *worse since*. Tips that
    don't match a number are listed below, the most repeated first.
  - A drill for every habit that's still there, and *Make it my focus* for this week.
- **Practice plan** (Practice › Practice plan, per team): this week's sessions, made instantly every Monday (no
  model needed) from the team's habits, this week's map and its strats and lineups, and the newest Premier review.
  - Every session: warm-up, a team drill for the habit most players still have (with who it's for), the week's map
    (attack strats one day, defense the next, then lineups), a review together, and play time. The practice before a
    match day becomes match prep with the brief and the match screen.
  - Anyone in the team ticks items off and adds their own; the owner sets days, start time and length, makes it again
    and posts it to Discord. Below: each starter's two open habits with a solo drill.
  - Reminder 60 minutes before each session: on Discord (switch it on) and as a push notification (*Practice*,
    can be switched off under Account).
- **Menu at the top:** your name and the uptime next to your avatar, like in the left menu (hidden on narrow
  screens).
- Ctrl+K finds Habits, Match screen and Practice plan.

## 3.4.0
- **Match screen** (Match day › Match screen): everything for the match you're playing on one page, made for a
  second monitor or a phone next to you. The map, an **Attack / Defense** switch (keys `A` / `D`), the comp with
  everyone's agent and weekly focus, who's playing, the game plans for that side with every player's step, your
  strats (*Play* opens them right there), lineups for that side (your agent first) and, once you know who you got,
  the opponent's scouting. Your own lines are highlighted. `F` for full screen.
- **"Live" from your match times:** valcoach doesn't read the game, but it knows your match days and match time
  (*Brief before each match*). From 90 minutes before until 3 hours after, Home shows *Open match screen* first and
  the menu marks *Match screen* as **Live**.
- **Install valcoach as an app** (Account › Install as an app): on Android, iPhone, Windows and Mac. Own icon,
  own window, starts fast (the look is kept on the device), and an *offline* page when the server isn't reachable.
  No app store. Pages and your data are never stored on the device.
- **Push notifications** (Account, per device): *Report ready* when a coaching report you started is done (or
  failed), and *Match day* 90 minutes before your match with a link to the match screen. Switch each kind on or off;
  *Send a test*. iPhone and iPad need the installed app (iOS 16.4+). The server makes its own keys; nothing goes
  through a third-party service except the browser's own push service. Needs HTTPS (you have it through NPM).
- **Share a report:** *Make a share link* on a finished report's page: a read-only link a teammate can open
  without an account (the recording plays too). *Stop sharing* turns the link off at once.
- New dependency: `pywebpush` (installed by `pip install -e .`).

## 3.3.0
- **Unrated counts too:** *Import match history* / *Load new games* now also load your Unrated games (the last
  ~60 with round data and up to 300 older ones, like Competitive and Premier). The first import after the update
  takes a bit longer and uses more HenrikDev requests; later ones only fetch what's new.
- Two more queue tabs on Stats & maps, Agents & roles, Rank & progress and Pros & videos: **Unrated** and
  **Everything** (ranked + Unrated). *All ranked* stays Competitive + Premier, so your ranked numbers don't change.
  Team comps can use *Everything* too (Team settings › Use games from).
- Rank over time still only uses Competitive (Unrated has no RR).

## 3.2.0
- **Agents & roles** (Performance › Agents & roles, per player):
  - **What you pick:** the agent class you play most (Duelist, Initiator, Controller, Sentinel) with games and win
    rate per class, your most played agent, the class where your numbers are best compared with your own average,
    and the role a team owner set for you.
  - **What your habits fit:** the team role your games point to (Entry, Second entry, Lurker, Anchor, Support) with
    the numbers behind it, all role scores 0–100, and IGL / Operator on top when they score high. Says *clear fit*,
    *leaning* or *no clear role yet*.
  - **Suggestion:** whether the two match, if not which class suits your habits better, a note when your team gave
    you a different role, and three agents to try (the most picked at your level first).
  - **All your agents:** every agent you played with games, win rate, ACS, K/D, ADR, KAST, first duels and how many
    of them you won, best map; sort by any column, open the numbers per map. Agents you haven't played yet below.
  - All ranked / Competitive / Premier like the other pages.
- *Stats & agents* is now called **Stats & maps** (its focus is the maps; the agents have their own page).
- Ctrl+K finds the new page and the newer team pages (This week, Availability, Match-day brief, Opponents).

## 3.1.0
- **Menu at the top or on the left** (Account › Look & feel › Menu). *At the top* puts the same menu in a bar across
  the page: the team and player pickers, then *Home* and the five groups as dropdowns (they close when you click
  elsewhere or press Escape), and What's new, Server, Users, Settings, your account, light/dark and log out as
  icons on the right. The group you're in is underlined. On narrower screens the bar drops the icons and labels it
  can do without; on a phone the menu is always behind ☰. Works with every style.

## 3.0.2
- **Fix:** on the match-day brief the comp's agent pictures overlapped the player names. The comp now shows as five
  tiles (agent picture, agent, player, backup pick) like on *This week*; long names are shortened with "…" and shown
  in full on hover.

## 3.0.1
- **Fix:** the team and player pickers at the top of the menu were see-through in the *Neon glass* and *Tactical
  HUD* styles, so the open list overlapped the menu behind it. Lists, the search box, messages and the phone menu
  now always have a solid background.
- The pickers close when you click anywhere else or press Escape.

## 3.0.0
**New design.** Every page was rebuilt on one design system; all features, data and links stay the same.
- **One menu for everything**, on the left (a ☰ button on phones). At the top you pick the *team* and the *player*
  it works on (opening a team or player page picks it for you). Below, five groups that open and close:
  *Match day* (This week, Availability, Match-day brief, Opponents), *Strategy* (Comps, Drafts, Game plans,
  Strat book, Lineups), *Performance* (Matches & reports, Stats & agents, Rank & progress), *Practice* (Training,
  Weekly focus, Quiz, Pros & videos) and *Roster & setup* (Roles, Team notes, Player & playbook, Team settings).
  The menu remembers which groups you opened; *This week* shows the week's map, *Quiz* how many questions wait.
- **Every page starts the same way:** where you are, a title that matches the menu, one line of context, and the
  page's buttons on the right. Map and queue switches are one kind of tab everywhere.
- **Home:** the week's map large at the top (with the minimap behind it), who can play on the next match day as
  one chip per player and your Yes / Maybe / No right there.
- **This week (Premier):** the comp as five agent tiles, the season as week tiles with the current week marked,
  match days as toggle buttons, results as *Won* / *Lost*.
- **Reports** use the same colours and type, with the score green or red.
- **Light and dark** with the moon button at the bottom of the menu (standard style).
- **Styles rebuilt** for the new layout: Esports broadcast, Clean minimal, Neon glass, Tactical HUD, Data
  terminal, Editorial magazine, Coach's playbook, Retro arcade, and new *Original red* (the colours before 3.0).
  Account › Look & feel shows a real preview of each.
- **Fonts ship with valcoach** (Archivo and the styles' fonts, all OFL licensed, in `static/fonts`): nothing is
  loaded from Google any more.
- Colours mean one thing each: amber = something you can do, teal = good or won, coral = bad or lost.
  Labels are no longer in capitals.

## 2.25.0
- **Home page "Today":** everything for today in one place, instead of clicking through five pages.
  - Per team: this week's map with the match-day brief, the next match day with who's playing (and who could sub),
    your own ✓ / ? / ✗ for it right there, and your focus.
  - For you: warm-up done or not and your streak, your rank and the change in 14 days, a quiz waiting, your last
    report.
  - Jobs running or failed in the last day, and what teammates changed since your last visit (strats, drafts,
    notes, Premier reviews). New accounts get three first steps instead.
- **Simpler navigation:** *Home*, *Teams*, your own player (the one named like your in-game name under Account) and
  everyone else under *Players ▾*, instead of every player in the top bar. Player links open Stats & agents.
- **Team tabs grouped:** *Match prep* (Premier first, then Comps, Drafts, Game plans, Strat book), *Players* (Weekly
  focus, Roles, Notes) and *⚙ Settings* (members, maps & Discord).
- **Faster pages:** players' game files are read once per change instead of on every page, and a team's comps,
  roles and tips are kept until the team or someone's games change.
- **Backups** (Settings › Backups, on by default): every night from 04:00 the database, players, teams, notes,
  strats and reports go into one .tar.gz, the newest 14 are kept. Set the folder to your NAS. *Back up now*, and
  the last backup shows in Settings and on the server overview.
- **Reports:** filter the rounds: ★ lessons, leads thrown, your deaths, lost rounds.
- **Discord:** optional channels for Premier reviews and for clips (empty = #match-prep as before).
- **Settings:** a section menu at the top (match data, local model, Claude, video, pros, server, backups).
- Smaller: the empty Progress and Training pages have an *Import history* button; schedule times say which time
  zone the server uses.

## 2.24.0
- **Ask the coach about a round:** under every round of a report opened in valcoach, ask a question ("Should I
  have saved?", "What if I'd waited for the flash?"). The model gets that round's facts and its own feedback,
  answers in a few sentences, and the questions and answers stay with the report. Pick the model next to *Ask*.
  Works on older reports too.
- **Clips:** next to the VOD jump buttons in a report (round start, first kill, your death…), *⬇ clip* cuts 15
  seconds from there as an MP4 (720p, with sound) and *→ Discord* posts it to your team's channel. Clips are
  kept, so the second time is instant. Needs ffmpeg on the server: `sudo apt install ffmpeg`.
- **On the map** (Stats & agents › a map): where you die (red) and get kills (green), drawn on the minimap at the
  callout, for attack and defense; bigger = more often.
- **AFK in reports:** rounds where a teammate was AFK or never left spawn (Riot's own flags) get a chip.
- **Strat history:** *History* in the strat editor lists earlier versions of the board (one per 10 minutes of
  editing, and one whenever someone else edits) with who saved it; *Restore* brings one back, and the board as it
  was stays in the history.
- **Test buttons** in Settings for the HenrikDev key, the Anthropic key (also says if an offered model isn't
  available to the key) and the Ollama model.
- **Tests on GitHub:** every pull request and every push to main runs the test suite (GitHub Actions). The PR
  shows a green check or a red cross before you merge.

## 2.23.1
- **Last active** on Users: when each user was last on the site (any page, updated at most once a minute), with
  "● online now" for the last 5 minutes. *Last login* only changes when someone types their password, and logins
  last a long time, so it said little. Also on each user's page, and the server overview counts who's online.

## 2.23.0
- **Claude as a model, picked per run.** Next to every button that runs the model (Start coaching, tips, what to
  watch, game plans, weekly focus, Premier reviews, the quiz) there's now a model picker: your local default, the
  other models installed in Ollama, and with an Anthropic API key Claude Haiku 5.5, Sonnet 5.5 and Opus 5.5 (☁).
  - Your last pick is remembered as the default for the next run. *All maps* and *Run again* use the same model.
  - *Settings › Claude*: API key (also `ANTHROPIC_API_KEY`), which Claude models are offered, a **monthly budget**
    (Claude stops when it's spent), and **fallback**: if Claude can't be used (no key, no credit, budget used up,
    API down), the local model finishes the job and the report says so.
  - *Model for automatic jobs*: what the nightly Premier reviews and the weekly focus use.
  - Only admins and users with **Can use Claude** (Users › user) see the Claude models; the server checks it too.
  - What it costs: every request is priced from its tokens (Anthropic's October 2026 prices). The report header
    shows the cost of that run; the server overview shows today, this month per model, the budget and the last
    30 days.
- Any other installed Ollama model can be picked per run too, to compare models on the same match.

## 2.22.0
- **Quiz → practice:**
  - After each answer: *🎯 Make this my focus* sets the best call as your own focus for this week. It shows on
    Training, on the team's Weekly focus page next to the coach's pick, and in the match-day brief.
  - Every answer is saved per category (alone at the end, first death far from the team, a lead that slipped). The
    quiz page shows how often you pick the best call in each one. A category under 60% (with 3+ answers) shows up
    on Training under *What to work on*, with a decision drill.
  - Rate each question as *good*, *unrealistic* or *too obvious*. The next quiz gets the good ones as examples and
    the others as what to avoid.
- **👍 / 👎 on reports:** every line of the coach's round feedback (key moment, mistakes, better option) can be
  rated. Liked lines become examples for your next coaching runs, next to your own notes; disliked ones are what
  the coach should avoid. On your own lines, *🎯* makes one your focus for the week. Works on reports made from
  2.22 on, opened from valcoach.
- **Faster notes:** one-click tags under every round ("died alone", "late rotate", "util too early"…), and what the
  coach said about the round last time is shown greyed out, so you can correct it in your own words. It's never
  filled in for you: the notes only help because they're yours.
- **Strat playback for the IGL:** each step can have a call ("1:20 Omen smokes B Main, Jett dash in behind"), shown
  big on the map while it plays. *Step by step* makes the playback wait for a click (or Space / →) before each
  step, for walking the team through it in voice.
- **Availability:**
  - Notes like "from 21:00" show on the day cards, in the brief and in the Discord brief.
  - *🔔 Remind* posts who hasn't answered for the next match days to Discord.
  - With a player's Discord user ID (Availability › Discord IDs, owner only), the reminder pings them; only those
    IDs can be pinged, never @everyone.
- **Rank over time:** games with a coaching report are ringed and open the report on click.
- Fixed: a Premier roster sync forgot "Use my own list" (the team maps went back to following the stage pool).

## 2.21.0
- **"This week" works again on the Premier tab.** HenrikDev's season data still lists an older season, and that
  replaced the built-in stage, so no week matched today. Now the API's schedule is only used when it covers today;
  otherwise the built-in stage (V26A6) is, with a note saying why. Between two weeks the card names the next map.
  Team owners get a *Raw season data* link under the stage schedule to see what HenrikDev returns.
- **Availability** (Premier › Availability): everyone marks ✓ / ? / ✗ for the match days of the next two weeks (the
  days from *Brief before each match*), with a short note on right-click ("from 21:00"). Each day shows who's
  confirmed, who hasn't answered, and the five planned for that day's map (your *main* draft, else the suggested
  comp). If a planned player can't play, the free players are ranked by games on that agent, then on that role.
  Players change their own row once linked to their player; the team owner can change all rows. The brief, the
  Premier overview and the Discord brief show "who's playing" too.
- **Rank over time** on Progress: your rank and RR after every ranked game as a line with tier bands, the change
  in the last 14 days and your peak. The RR history is loaded on *Import* and kept locally (HenrikDev only keeps a
  window of it); without it, the rank shown in each match is used.
- **Strat playback:** *▶ Play* in the strat editor (or ▶ on a board in the list) animates the steps: agents and
  abilities move to their next spot, new things fade in, removed ones fade out, with the step name on the map.
  0.5×, 1× or 2×; Esc or a click on *Stop* ends it. New steps remember what they were copied from, older boards
  are matched by agent.
- **Quiz** (new player tab): moments from your own last games (left alone in a 1vX, a first death far from your
  team that nobody traded, a lead of two or more that slipped) become questions with 3-4 calls. The model writes
  them from what you could know at that moment; after you answer you see the best call, why, and what really
  happened. Scores are kept.
- **Server overview** (click the uptime clock, or Users › Server overview): HenrikDev requests per minute and per
  day, rate limits hit, whether the model is online and loaded, background jobs running or failed, the scheduler,
  and disk use per folder. Admins can give it to anyone (Users › user › *Can see the server overview*) without
  making them admin. It shows no keys, logs or anyone's games.
- Fixed: the progress text of running scouting, match reviews and schedule jobs on the Premier pages never
  updated (the status check treated them as players).

## 2.20.0
- **Nine styles**, picked per user under *Account › Look & feel*. Each one changes the whole look and layout, not
  just the colours: **Classic** (as before), **Esports broadcast** (VCT overlay: condensed type, angled red bars),
  **Clean minimal** (light, soft cards), **Neon glass** (purple and teal glow, frosted panels), **Tactical HUD**
  (like Valorant's own interface: teal lines, cut corners, a grid), **Data terminal** (menu on the side, dense,
  monospace numbers), **Editorial magazine** ("The Valcoach" masthead, serif headlines on paper), **Coach's
  playbook** (a clipboard with lined paper and sticky notes) and **Retro arcade** (pixel font, CRT scanlines).
- **Animations with a switch each** (Account › Look & feel): numbers count up, clickable cards lift on hover,
  smooth page changes, progress bars with the current step instead of the raw log for running jobs (the log is
  one click away), and toasts for messages like "Saved". With *reduce motion* set on your computer they stay off.
- **Quick search:** Ctrl+K (or /, or the search button in the top bar) jumps to any player and their tabs, any team
  tab, a map's game plans or drafts, a draft or a strat board.
- **Lineups library** (Strat book › Lineups): one entry per lineup with the agent, ability, side, site, a clip link
  (YouTube shows a thumbnail) and a note, per map and filterable. In the strat editor, a selected ability shows its
  lineups for the map. Only https links are accepted.
- **Phones:** every page checked at phone width, nothing scrolls sideways any more (wide tables scroll inside
  their card).

## 2.19.1
- **Premier stage schedule:** which map is played in which week, read from the Premier season data (HenrikDev),
  refreshed once a day and with the nightly sync. If the API doesn't give the maps, the current stage (V26A6: Bind,
  Corrode, Sunset, Haven, Summit, Abyss, Lotus, playoffs 6 December) is built in.
  - The Premier tab shows the stage week by week with dates, this week highlighted, and your results per week.
  - **A Premier team's maps follow the stage's map pool** (in week order), so Corrode and Summit show up everywhere
    (Comps, Drafts, Game plans, Strat book). *Use my own list* on the Premier tab switches back to the maps you set.
  - Game plans, Drafts and Comps open on this week's map.
  - Monday/Tuesday between two weeks already counts as the coming week, so the brief and plans are for the next map.
- **Summit** added to the known maps.

## 2.19.0
- **Progress** (new player tab): the last 10 weeks, week by week, for win rate, ACS, K/D, KAST, first duels won,
  deaths traded, deaths far from the team, rounds survived, headshots, clutches, retakes and ADR. Each one shows
  the trend (last 2 weeks vs the 6 before) in green or red.
  - **Did the weekly focus work?** For every focus you got, the number it was about, before and in the games since,
    with the goal and a verdict (goal reached / better / no change / worse). The *Weekly focus* tab shows the same
    for last week's focus next to every player.
- **Clutches, retakes, post-plants** (on Progress): 1v1 to 1v5 won/played, retakes won when they planted while you
  were alive, and post-plants won when your team planted.
- **Training** (new player tab):
  - **Aim fundamentals:** your headshot share, and your fights by range (under 10 m, 10–25 m, over 25 m): how many
    you take and how many you win. Also first duels and deaths far from the team.
  - **What to work on**, and **your warm-up**: about 20 minutes of drills in Valorant's Range and modes, picked
    for your weak spots. *Done today* keeps a streak (last 14 days shown).
  - **Learn from your teammates:** who in your team is best at what you're weakest at.
  - **Agents to learn: up to 5 instead of 1**, each with a learning path: learn the kit (guide videos), watch a pro
    who plays it, 5 unrated games, lineups for your maps, 10 ranked games, Premier-ready (15 games, 50%+ won). The
    steps tick themselves from your games on that agent. The *Roles* tab lists the 5 too.
- **Timing windows** (Game plans): when your first fight, your plant and the flank kills usually happen on each map,
  and when attackers first make contact on each site on defense, on a 0–100 s timeline, plus when your lurker
  should be in position.
- Game data is read again from the match cache once (new numbers: shots, fight distances, clutches, retakes):
  nothing to download.

## 2.18.0
- **Premier tab** (new team tab), built around how Premier works: the map is fixed for the week, the opponent is
  found only when you queue, and always from your own division.
  - **This week:** the week's map (from the Premier schedule, from your first match this week, or set by hand),
    your comp for it (the draft marked *Our comp*, else the suggested comp), your record on the map, and who in your
    division is strongest there.
  - **Match-day brief:** one page (made for the phone) with the comp, your numbers on the map, the game plans,
    everyone's weekly focus and who you might meet. Posted to #match-prep automatically before your matches: pick
    the match days, the time and how many minutes before. *Post brief to Discord now* works any time.
  - **Division & scouting:** every team in your division is scouted in advance from its recent Premier matches,
    and refreshed every night. When you get matched their page is already there. Teams from outside the list
    (playoffs) can be scouted by Name#TAG.
  - **A team's page:** how to play them (strong and weak maps, who takes their first duels, sites they hit, fast
    or slow executes, lost retakes, pistols), their players and agents, their comps per map.
  - **Map veto for playoffs:** your record against theirs on every map, with which maps to ban first, which to
    pick, and which side to start on.
  - **Automatic match reviews:** every night, new Premier matches get a team review (MVP, the rounds that decided
    it, one thing for each player, who traded whom), posted to #match-prep. The page shows every player's review.
    Only new matches, never old ones; *Review new matches* runs it right away.
- **Phones:** the top navigation turns into a menu button on small screens, and the team tabs scroll sideways.

## 2.17.1
- **VOD uploads go up in 16 MB pieces.** Size limit, report limit and free disk are now checked before the first
  byte is sent, not after the whole file has arrived, and a lost connection only repeats one piece. No request may
  be bigger than 17 MB any more, so nobody can fill the disk without logging in. Temp files stay in `data/tmp`.
  A proxy in front of valcoach must allow bodies of at least 17 MB.
- **API keys stay out of error messages.** A network error could show the YouTube key or a Discord webhook URL on
  pages teammates can open. The YouTube key now goes in a header, and Discord errors no longer contain the URL.
- **A report no longer says "done" when the model failed.** If it fails on every round, the job ends with an error
  and the reason. If it stops answering, the run stops waiting after a few rounds instead of timing out on all of
  them. If only some rounds fail, the report says which ones at the top.
- **A playbook with the wrong structure no longer breaks a run.** `maps` must list each map by name; the profile
  form now says so when you save it.

## 2.17.0
- **Drafts** (new team tab): roster drafts per map, made together.
  - Five player slots (starters or subs). Drag agents from the list onto a player, add a backup pick, drag between
    slots to swap, drag out to remove, or click a slot and then an agent. Works with mouse, pen and touch.
  - Start empty (your starters already in the slots) or from one of the 3 suggested comps for the map.
  - Every slot shows that player's numbers on the agent (games and win rate on this map and overall) and their
    best agents on the map to pick with one click.
  - *Check*: role mix, and warnings for the same agent twice, a player in two slots, no controller / initiator /
    sentinel, 3+ duelists, and players who haven't played their agent yet.
  - Status *Idea / Trying / Our comp*, a role or job per player ("IGL", "lurk B"), notes from your discussions,
    *Duplicate*, *Post to Discord* (#match-prep). Saves by itself; the list shows everyone's drafts per map.
  - Only team members and real agents are stored (same idea as the strat board): nothing another member saves
    can run in your browser.
- **VOD fixes from the first real recording** (in 2.16.0 on GitHub, details in [notes/review-fixes-2.15.md](notes/review-fixes-2.15.md)): big
  uploads no longer fill `/tmp`, ultrawide recordings (black bars) work, "Based on side" minimap orientation is
  calibrated, the minimap summary no longer counts 11 allies, your own icon is followed from your API positions.

## 2.16.0
- **Pro & videos: pick the pro.** Click any of the 3 pro cards to select it. Everything below then follows that pro:
  - the white marks on your playstyle bars,
  - a "Copying <pro>" box with what to take over from them and habits to practise,
  - **What to watch**: searches built around that pro (them on your shared agent and map, how they do the thing
    they're better at than you, their other agent, your weakest map with their VODs), plus your own habit fixes.
  - Each pro gets its own guide. *Write what to watch for <pro>* writes the selected one; *All 3 pros* writes all
    three in one go (one model run each) so switching is instant. Cards show "✓ guide written".
  - Guides written before this version still show for your closest pro.
- **Includes Manuel's review fixes on 2.15.0** (details in [notes/review-fixes-2.15.md](notes/review-fixes-2.15.md)): real utility numbers from the
  live API, the model now sees the field descriptions (also for the new per-pro watch guide), no "check the VOD"
  without a VOD, deathmatch / team deathmatch / gauntlet can't be coached, time-outs are detected, the strat board
  only stores typed fields (stored XSS), forms from other sites are blocked (CSRF), limits per user (reports at
  once, upload size, free disk), a job can't run twice, safer match IDs and inputs. Requires Flask 3.1+.
- The project is a git repo now: updates come as a commit on top of `main` instead of a zip over the folder.
- **Uptime clock** in the top bar: how long valcoach has been running, ticking live. Hover it for the start time
  and how long the server itself has been up.

## 2.15.0
- **Nightly sync.** Every team syncs by itself every night at 02:00 (server time): the Premier roster first (if the
  team is linked to Premier), then everyone's stats, just like pressing the two buttons. On by default; change the
  hour or turn it off under *Members, maps & Discord* → *Automatic sync*. If the server was off at that hour it
  catches up within 3 hours. The buttons still work any time, and the team header shows "syncs nightly 02:00".
- **Roles table sorts.** Click a column (IGL, Entry, …, or Player): ascending, click again for descending, a third
  time for the normal order. Your ticked roles move with the rows.
- **Game plans:** the 3 comps are tidy now: each comp is one row of 5 (agent + player), with the role mix written
  out underneath ("1 duelist, 2 initiators, …") instead of wrapping onto a second line.

## 2.14.0
- **Strat book: abilities look and size like in the game.**
  - Smokes are drawn at their real radius as clouds in the agent's colour (Omen purple, Brimstone tan, Viper green,
    Astra violet, Clove pink, Harbor blue, Jett pale blue, Cypher white), so you can tell whose smoke is whose. The
    outline still shows us / enemy.
  - Line and area abilities are full shapes you aim from where they're cast: **Fault Line** (7.5 m wide, 8–56 m),
    Rolling Thunder, Armageddon, Hunter's Fury, Nightfall, Paranoia, Cascade, Contingency, Kill Contract... Drag the
    yellow handle to aim, and stretch where the ability can.
  - Walls have their length: Toxic Screen (up to 60 m), Blaze, High Tide, Barrier Orb, Trapwire, Cosmic Divide;
    Fast Lane is two walls.
  - Mollies, slows, stuns and reveals are circles at their size (Snake Bite, Nanoswarm, Lockdown...).
  - Sizes from the Valorant wiki where it lists them; the rest are marked *estimated* on the board. Every radius
    and length can be changed per item (↺ puts it back).
- Click an ability (no drag) to drop it at that agent on the board: lines start at the agent and point into the map.
- Select an agent on the board and its abilities show up under *Selected*.
- The generic Smoke and Molly shapes are gone from the palette (use the agent's ability instead); boards that
  already have them still show them.

## 2.13.0
- **Strat book** (new team tab): boards on the real minimap, saved per team and map, editable by everyone in the team.
  - Drag any agent and every ability of every agent (icons from valorant-api.com) onto the map, plus smokes,
    mollies, stun/slow/flash zones, markers and numbers. Draw arrows (dashed for rotates/lurks), paths, walls, text.
  - Us / enemy colours, a player name under each agent, ability areas with a real radius in meters.
  - Steps (e.g. Setup → Fake A → Lurk timing): a new step starts as a copy, the step before shows faded.
  - Undo/redo, copy, delete, zoom, callouts on/off, keyboard shortcuts; saves by itself.
  - Download a step as a picture, or post it with the notes to #match-prep.
- **Draw it** on every game plan opens it on the strat board, with the plan's steps as notes.

## 2.12.0
- **Shared teams:** add teammates' accounts under *Members, maps & Discord*. They see the team (comps,
  game plans, weekly focus, roles, notes) and their teammates' stats, read-only; only the owner changes settings.
  Each picks *Which one is you?* on the team page; an in-game name that matches a player links them automatically.
- **In-game names:** accounts have a display name (e.g. `adv1ce#LFT`), set under Account or when signing up.
- **Notes tab:** notes about the team or a player, per map if you like; everyone in the team sees them.
  Next to them, tips from your matches together (who dies outnumbered or alone where, which duos trade each other).
- **Game plans tab:** per map, the model writes 3 plays (2 attack, 1 defense) with a step for every player by
  name, agent and role, timings, if/then adjustments and the numbers behind it (sites you hit, first-fight timing,
  where you get killed from behind, mid control, what opponents plant). Your notes and roles are used.
- **Weekly focus tab:** one focus per player for the week, from their last 2 weeks vs. before, their team role,
  the data tips and notes about them, with a number to watch. Shown on everyone's dashboard.
- **Discord:** webhooks for #match-prep (top 3 comps per map + game plans) and #weekly-focus; test message;
  automatic weekly focus post on a day and hour you choose. Posts never ping anyone.
- Comps tab: 2nd and 3rd comp options per map.

## 2.11.4
- **What's new page:** click the version next to the logo to see this changelog in the app. After an
  update, everyone sees a one-time note with a link (and a red dot on the version until they've looked).

## 2.11.3
- Fix: Premier import with no member list and only one Premier match so far (start of a season).
  The roster now comes from the team's Premier roster inside the match data, or else from the side
  of the match your own player was on; only then from players who appear in 2+ matches.

## 2.11.2
- Fix: Premier import failed with "returned the team without members" when HenrikDev sends the roster
  with only player ids (name/tag empty). Names now come from the team's Premier matches, then from
  HenrikDev's account-by-id lookup; with no member list at all, the regulars of the team's matches are used.
  The import log says how many members came back and how many had names.

## 2.11.1
- Version number shown in the web app (next to the logo and in Settings), in every report,
  in `valcoach --version`, in the README and in this changelog. Zips are named with the version.

## 2.11.0
- **Premier import:** create a team from your Premier `Name#TAG` + region. Loads the roster, adds the
  players (existing ones reused), picks starters from the last 10 Premier matches, imports everyone.
  *Sync Premier roster* keeps your starter/sub choices and roles. Division, points and record on the team page.
- **Roles tab:** 0–100 fit per player for IGL (a guess), Entry, Second entry, Lurker, Anchor, Support,
  Operator, Flex; assign roles yourself; suggested lineup keeps them; checks when an assigned role doesn't
  show in the data; an agent to learn per player.
- **Whole-team match review:** every teammate gets went well / to fix / how the team can help them;
  *Together* tab with trades, untraded, alone and outnumbered deaths. CLI: `coach --team`.
- Game rows store more per-game numbers (rebuilt from cached matches on the next *Update*).

## 2.10.0
- **Pro & videos tab:** your playstyle as four percentiles vs. your lobbies, the 3 closest pros
  (editable list in Settings), up to 6 targeted YouTube searches, and model-written "watch for" notes.
  Optional YouTube Data API key shows the videos inline.

## 2.9.1
- Teams first in the top bar and on the dashboard; team page split into Comps (all maps at a glance)
  and Members & maps; a role mix set in the map meta is followed whenever possible.

## 2.9.0
- **Stats & agents:** history import (recent full matches + archive), per map / agent numbers, opening
  duels and death spots per side, findings, model-written tips per map, solo-queue pick helper.
- **Teams:** comps per map from everyone's stats, substitutes ("if someone is missing"), map meta.

## 2.8.0
- With a VOD, teammates' paths are measured from your minimap; spotted enemies drawn on the replay.
- Estimated movement between kills at running speed (hold, then move just in time).

## 2.7.0
- Report: round list on the left, sticky replay / video panel on the right; smaller map;
  plain mouse wheel scrolls (Ctrl + wheel zooms); generic "Round N review" summaries hidden.

## 2.6.1 and earlier
- Headless OpenCV (servers without libGL); playable continuous round replay with agent portraits;
  older matches via HenrikDev's archive; accounts, workspaces, systemd/Docker; VOD sync + minimap tracking.
