# Changelog

The running version is shown next to the logo in the web app, in *Settings*, at the top of
every report, and with `valcoach --version`. Update: unzip over your install (keep `data/`),
`pip install -e .`, `sudo systemctl restart valcoach`.

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
