# Changelog

The running version is shown next to the logo in the web app, in *Settings*, at the top of
every report, and with `valcoach --version`. Update: unzip over your install (keep `data/`),
`pip install -e .`, `sudo systemctl restart valcoach`.

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
- **VOD fixes from the first real recording** (in 2.16.0 on GitHub, details in [CHANGES.md](CHANGES.md)): big
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
- **Includes Manuel's review fixes on 2.15.0** (details in [CHANGES.md](CHANGES.md)): real utility numbers from the
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
