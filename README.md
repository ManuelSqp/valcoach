# valcoach

**Version 4.2.0** · what changed in each version: [CHANGELOG.md](CHANGELOG.md) · the running version is shown
next to the logo in the web app, in *Settings*, at the top of every report, and in `valcoach --version`.

Local Valorant coach for **your team (IGL / macro)** and **you individually**,
with a web app so several players can use it.

```
HenrikDev v4 match data ──► analysis (trades, economy, first contact, plants,
        │                     clutches, isolation, positions at every kill)
        │                                   │
VOD ──► kill-feed sync ──► minimap tracking ┤   (rotations, stacks, your path)
                                            ▼
                        compact round facts ──► Ollama (JSON schema output)
                                            ▼
                         HTML report with round timeline + VOD jump buttons
```

---

## 1. Install

```bash
git clone https://github.com/ManuelSqp/valcoach.git && cd valcoach
python3 -m venv .venv          # Python 3.11 or newer
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                     # ~170 tests, ~3 min, builds a synthetic match + VOD
ollama pull qwen3.8:27b       # default; alternatives below
```

**Update:** `git pull`, then `pip install -e .` and restart the app (`sudo systemctl restart valcoach`,
or `docker compose up -d --build`). Your `data/` folder and `config.toml` aren't in git, so they stay as they are.

### What the server needs

- **The model is the heavy part.** The suggested models are 16–19 GB. The coaching is fast when the whole model
  fits in GPU memory (NVIDIA or Apple Silicon unified memory); if only part of it fits, Ollama runs the rest on the
  CPU and every report takes much longer. The *Server* page shows how much of the model is on the GPU. A smaller model
  or Claude (no GPU needed, see below) are the alternatives.
- **The video part** (sync, minimap, clips) runs on the CPU with OpenCV and ffmpeg; a faster CPU just means
  the VOD step finishes sooner.
- **Disk space:** VODs are several GB each. Uploaded VODs are stored in `data/`, so plan space for them or delete
  old ones.
- **ffmpeg** for clips (`sudo apt install ffmpeg` / `brew install ffmpeg`); without it, everything else still works.

### Which model

Any Ollama model works; set it in *Settings → Ollama → Model*. Some good choices:

| Model | Download | Notes |
|---|---|---|
| `qwen3.8:27b` (default) | ~18 GB | Dense, newest Qwen |
| `gemma4:26b` | ~16 GB | MoE, only ~4B active per token, so much faster per round |
| `gemma4:31b` | ~19 GB | Dense; the bigger Gemma |

Both families are reasoning models. *Settings → Reasoning* is **Off** by
default (fast; the task is turning facts into feedback, not puzzle-solving).
Try **On** if the feedback is shallow. Compare models by coaching the same
match with each and use *Run again*.

**Claude (optional).** With an Anthropic API key under *Settings → Claude*,
Claude Haiku, Sonnet and Opus show up in the model picker next to every button
that runs the model (coaching, tips, game plans, weekly focus, reviews, quiz,
what to watch). The local model stays the default; each user's last pick is
remembered. Admins can use Claude; other users only after *Users → Can use
Claude*. A monthly budget stops Claude when it's spent, and with fallback on the
local model finishes the job if the API can't be used. Nightly reviews and the
weekly focus use *Model for automatic jobs*. Costs per day and month are on the
server overview. The key can also come from `ANTHROPIC_API_KEY`.

**Web search (optional).** Under *Settings → Web search* the coach can look things up instead of guessing (patch
changes, abilities, pros, KovaaK's playlists and share codes) in *Ask the coach*, in the questions about a round of a
report and on the Aim page; answers list the pages they used. Pick a main search and a backup, which takes over
when the main one fails or finds nothing:
- **DuckDuckGo** (the default): free, nothing to set up. DuckDuckGo has no official search API, so valcoach reads its
  plain HTML results page; it blocks a server for a while when it searches a lot, which is what the backup is for.
- **SearXNG**, your own search server (free, nothing leaves your network except the searches). It has to answer
  JSON: in SearXNG's `settings.yml` set `search: formats: [html, json]` and restart it. Enter its URL (or set
  `SEARXNG_URL`, which also makes it the backup).
- **Claude's web search** with the Anthropic key: US$ 10 per 1,000 searches plus tokens, counted in the Claude budget.

*Test* checks the main search and the backup one by one. Set the main search to *Off* to turn web search off.

The model decides per question whether to search (at most three searches) and reads the top pages. Pages are only
fetched from public addresses, never from the server itself or your LAN.

## 2. Start the web app

```bash
source .venv/bin/activate
valcoach web                  # http://<ip>:10070
```

Options: `--port 10070`, `--host 127.0.0.1` (this PC only), `--data data`
(folder for the database, cache, uploads and reports).

On the first start you create the **admin account**. If you used an earlier
version, your existing players and reports move into that account
automatically.

Then in the browser:

1. **Settings** (admin): paste the HenrikDev API key (HenrikDev Discord → `#get-a-key`
   → *VALORANT (Basic Key)*), check that Ollama shows as reachable, choose the model.
2. **Users** (admin): add an account for each teammate, optionally with a
   recordings folder on the server. Or turn on *Allow sign-up* in Settings so
   they can create their own accounts.
3. **+ Player**: Riot name, tag, region (EU), default coaching mode and,
   optionally, the team playbook (there's an *Insert example* button).
4. Open the player → **Recent matches** → **Coach** on a match.
5. Choose what to coach, pick the recording (or *No VOD*, or upload one) →
   **Start coaching**. The job page shows progress; **Open report** when done.
6. **Notes** next to each match: write what went wrong/right per round. This is the
   biggest quality lever: notes for the match go to the coach, and your notes from
   other matches teach it the kind of feedback you want.

### Finding your way

One menu on the left (☰ on a phone). At the top you pick the **team** and the **player** it works on; opening a team
or player page picks it for you. Below: *Match day* (This week, Availability, Match-day brief, Opponents),
*Strategy* (Comps, Drafts, Game plans, Strat book, Lineups), *Performance* (Matches & reports, Stats & maps,
Agents & roles, Rounds & economy, Teammates, Rank & progress), *Practice* (Training, Habits, Aim, Ask the coach, Practice plan, Review evening, Weekly focus, Quiz, Pros & videos) and *Roster & setup* (Roles, Team notes,
Player & playbook, Team settings). Ctrl+K searches everything. *Home* shows what's up today. The look (10 styles,
light or dark, menu on the left or at the top, centred or full width) is under Account.

**Deutsch / English:** every user picks the interface language under Account › Look & feel (the login page
follows the browser, or the switch above the form). Menus, pages, messages, notifications and, per team, the
Discord posts are translated; the coach's own texts stay in each player's coaching language. Translations live
in `valcoach/i18n/de.json` (`#` = any number, `{name}` = any text); a missing line simply stays English.

**On your phone or a second screen:** Account › *Install as an app* puts valcoach on your home screen (no app
store) and turns on notifications (report ready, match day). *Match day › Match screen* shows the comp, plans,
strats, lineups and the opponent for the match you're playing, with an Attack / Defense switch. A finished report
can be shared as a read-only link (on its page: *Make a share link*).

**Habits and practice:** *Practice › Habits* tracks six habits that cost rounds game by game (gone, getting better,
still there, getting worse) and checks whether the coach's tips worked. *Practice › Practice plan* makes the team's
week of practice from those habits, the week's map, its strats and lineups, with reminders on Discord and your phone.
*Practice › Review evening* goes through one match round by round together: the host moves, everyone follows on his
own screen and marks his own rounds (my fault, good, talk about it); the summary goes into the practice plan.
*Practice › Aim* keeps aim routines (Aimlabs share links, KovaaK's codes, steps for the Range), picks the ones that fit
your matches and sets your warm-up, which shows on the match screen, in the practice plan and as a push before the match.
For KovaaK's the coach writes the playlists itself: download one (dated DD-MM-YYYY in its name), save it in
`FPSAimTrainer/Saved/SaveGames/Playlists` and it shows up under *Local Playlists*. Import your KovaaK's scores (the `.csv` files in `FPSAimTrainer/stats`, or the
folder as a zip) and it moves you to harder scenarios once you're steady at your best. More scenarios: import any
playlist file, add one by hand, or let them come in with your scores. *Playlists from the community* suggests public
KovaaK's playlists by share code (paste it under *Sandbox › Online Playlists › Enter Share Code*), and with web search
the coach finds more online.

**Ask the coach:** *Practice › Ask the coach* is a chat with the coach about one player. It knows the player's stats,
habits, aim and KovaaK's scores and remembers the conversation (per user and player).

### What's in a report

- **Rounds**: the list on the left has one button per round showing what happened at a glance
  (buy, first kill/death, plant, when you died, clutch, lead thrown, comeback, ★ = round with a lesson).
  Click a round to expand the coaching (key moment, team and personal feedback, VOD jumps); the panel
  on the right switches to that round's replay. It stays in view while you scroll. The **Video** tab
  shows the VOD; 🎬 buttons jump there.
- **Round replay**: plays the whole round on the minimap, with play/pause,
  0.5–4× speed and a timeline with a tick for every kill and the plant.
  - Every player is shown as their agent portrait in a ring of the team colour, greyed with ✕ once dead.
  - Trails show the last few seconds of movement, and view cones appear around each kill snapshot.
  - **Click a player** (on the map or in the list) to draw their whole route for the round with
    timestamps, e.g. to see how long a flank took.
  - The kill feed on the right jumps to each event. Zoom with the + / − buttons or Ctrl + mouse wheel (the plain wheel scrolls the page),
    drag to pan, and use ⛶ for fullscreen. Keys: space = play/pause, ← → = 1 s.
  - 🎬 jumps the VOD to the same moment (if the report has one).
  - **What's measured vs. estimated:** the API gives everyone's position only at kills, plants and
    defuses. Everyone starts in their spawn. In between, movement is estimated as the shortest
    walkable route at running speed: from spawn they move first and then wait; later they hold
    their last known spot and move just in time to reach the next one. Solid icons are known
    positions; faded icons with a dashed ring are estimates.
  - **With a VOD** your own path and your **teammates' paths** are measured from your minimap
    (they're on it all round, also while you spectate). Who is who is taken from the exact API
    positions at every kill and carried between kills; where two icons cross or merge and the
    identity is unclear, that stretch is estimated instead. Teammates measured like this show
    "tracked on video" in the player list, and the log says per round how much was covered.
  - **Enemies** are only on your minimap while someone sees them; those sightings are drawn as red
    rings (no name: the minimap doesn't tell which enemy it is).
  - The coach's **better spot** (dashed circle + arrow) shows up around its time.
- **Duels**: did you die while looking at your killer (lost aim duel), or was they
  at your side / behind you (positioning)? Damage you did to your killer, kills and
  deaths by range, headshot / leg-shot share per main weapon.
- View directions come from the API. valcoach checks them per match (killers must
  face their victims); if the data doesn't fit, duel analysis falls back to
  positions and damage and the log says so.

### Stats, agents and team comps

**Performance › Stats & maps.** *Import match history* loads your Competitive, Premier and Unrated games from HenrikDev
in the background: the last ~60 per queue with full round data (10 per request) and up to 300 older ones per
queue from the stored archive (summaries only, 20 per request). *Update* later only fetches what's new.

- **Maps and agents**: games, win rate, ACS, K/D per map and per agent, filterable by queue (All ranked,
  Competitive, Premier, Unrated, or Everything).
- **Agents & roles** (its own page): every agent you played with all numbers (sortable, per map on click), the
  agent class you pick most, the team role your habits fit (0–100 per role, from first fights, trades, fights far
  from the team, holding a site, assists, Operator), whether the two match, and three agents to try. *Details* on
  an agent: progress over time, utility per ability and you against everyone else on that agent in your matches;
  plus an agent × map grid.
- **Rounds & economy**: pistol / eco / force / full-buy win rates, uneven buys, bonus rounds, post-plants and retakes.
- **Teammates**: who you win with (games, win rate, your ACS with them, premade or random).
- **One map in detail**: your agents there, team win rate per side, where you take opening duels and how often
  you win them, where you die and how often that gets traded, and what's played at your level (all 10 players
  of your matches). Short findings are listed only when there's enough data behind them.
- **Coach tips**: *Write tips* has your model turn those numbers into an agent pool verdict (main / backup /
  drop) and tips per side, each with its evidence. Runs in the background, uses the same Ollama settings.
- **Pick helper** (solo queue): choose the map and what your teammates locked; it ranks your agents by your
  numbers on that map and what the team still needs (Controller first). If you don't play the missing role,
  it says so and names what's played at your level.

**From your Premier team.** On *Teams*, enter your Premier team as `Name#TAG` and its region. The app loads the
roster from HenrikDev, adds every player (players you already have are reused), makes the 5 who played the most
recent Premier matches the starters and the rest subs, and imports everyone's stats in the background.
*Sync Premier roster* on the team page picks up roster changes later and keeps the roles you set.
Every team also syncs by itself each night at 02:00 server time (Premier roster, then everyone's stats); change
the hour or turn it off under *Members, maps & Discord* → *Automatic sync*.

**Roles tab.** Every player gets a 0–100 fit for IGL, Entry, Second entry, Lurker, Anchor, Support, Operator and
Flex, from their games with round data (first into fights, trades, how far from the team they fight on attack,
which site they hold on defense and how long they survive there, Operator rounds, how many agent roles they play).
IGL can't be seen in data (no comms): its number is a guess from traits that make calling easier. Tick the roles a
player actually has: the **suggested lineup** keeps them and fills the rest with the best fits, a role that doesn't
show in someone's data gets a gentle "worth talking about", and each player gets an **agent to learn** (an agent
role that suits their team role and that the team is thin on, picked from what's played at your level).

**Whole-team match review.** *Review the whole team* on the coach page (on by default) adds a **Your team** section to
the report: every player of your team gets what went well, what to fix (with round links) and **how the team can
help them**, judged against their roles. The *Together* tab shows trades, deaths not traded, deaths alone and
deaths while outnumbered for everyone, and who traded whom. CLI: `valcoach coach <match> --team`.

**Sharing a team.** Teammates get their own login (admin: *Users*, or turn on sign-up) with their in-game name.
Under *Members, maps & Discord → Teammates with access* you add them; they then see the team and their teammates'
stats (view only) and can write notes. Tabs on a team: **Comps**, **Game plans** (3 detailed plays per map with a
step per player), **Weekly focus** (one focus per player), **Roles**, **Notes** (yours + tips from your matches
together) and, for the owner, **Members, maps & Discord**.

**Look & feel.** Every user picks a style (ten, from Classic to Retro arcade) and switches the animations on or
off under *Account › Look & feel*. **Ctrl+K** (or `/`) opens a quick search for players, team tabs, maps, drafts
and strat boards. The strat book has a **Lineups** library with clip links per map, agent and ability.

**Progress and Training** (player tabs). *Progress* shows your numbers week by week with trends, whether each
weekly focus moved its number, and clutches / retakes / post-plants. *Training* has your aim fundamentals (headshots,
fights by range), what to work on, a 20-minute warm-up with a streak, teammates to learn from, and up to five agents
to learn with a learning path that ticks itself from your games.

**Premier.** On a team linked to Premier, *Match day › This week* has this week's map, *Match-day brief* (also posted
to Discord before your matches: set days, time and minutes before), reviews of your Premier matches (every night,
posted to #match-prep), and *Opponents*: every team in your division scouted in advance from its recent
Premier matches, with a page per team (how to play them, players, comps per map) and a map veto for playoffs.
The first division scout takes a few minutes (HenrikDev rate limit); after that it's quick and runs nightly.

**Drafts.** On a team, *Drafts* → pick a map → *+ New draft* (your starters in the slots) or *Use* one of the
suggested comps. Drag agents from the list onto a player (the small box under it is a backup pick), drag between
slots to swap, drag out to remove; or click a slot and then an agent. Each slot shows that player's games and win
rate on the agent (on this map and overall) and their best agents here. *Check* shows the role mix and warnings
(same agent twice, no controller, a player who has never played their agent). Status *Idea / Trying / Our comp*,
notes for what you discussed, *Duplicate*, *Post to Discord*. Everyone in the team can edit; it saves by itself.

**Strat book.** On a team, *Strat book* → *New strat* (or *Draw it* on a game plan). Drag agents and their
abilities onto the minimap (or click an ability to drop it at that agent), add arrows, walls and text, split the
play into steps, and write the calls in the notes. Abilities are drawn at their in-game size and in the agent's
colour: smokes as clouds (Omen purple, Brimstone tan, Viper green, Astra violet, Clove pink, Harbor blue...),
mollies and zones as circles, and lines like Fault Line, Rolling Thunder, Armageddon or Toxic Screen start where
they're cast; drag the yellow handle to aim and stretch them (within the ability's real range). Sizes are in
`web/abilityshapes.py`; the ones marked approx are estimates and every size can be changed on the board. Everyone in the team can edit; it saves by itself. *PNG* downloads the current step, *Post to Discord* sends
it to #match-prep. Shortcuts: `V` select, `A` arrow, `P` path, `W` wall, `T` text, `Del`, `Ctrl+D` copy,
`Ctrl+Z` undo, `←`/`→` steps, `Ctrl`+wheel zoom.

**Discord.** Paste a webhook URL per channel (channel settings → Integrations → Webhooks → New Webhook):
#match-prep gets the top 3 comps per map and the game plans (*Post to Discord* on the Game plans tab),
#weekly-focus gets the weekly focus, automatically on the day and hour you choose (server time).

**Player → Pro & videos** compares your playstyle with pros and gives you videos to watch:

- **Your playstyle** in four numbers: how often you take the first duel, kills, assists and survival, each as a
  percentile among the players in your own matches (from the round data of all 10 players per match).
- **Pros with a similar style**: half style, a quarter role, a quarter shared agents, with what you have in common
  and the biggest difference. The pro list is a starting point written from public play styles as of mid-2026;
  admins edit it under *Settings → Pro players* (rosters change).
- **Pick a pro**: click a card (the closest is selected at first). The summary and *What to watch* follow it.
- **What to watch**: up to six YouTube searches built around the selected pro and your numbers: that pro on your
  agent and map, how they do what they're better at than you, their other agent, your weakest map, and your weak
  spots (e.g. the area where you lose opening duels). *Write what to watch for* has your model add, per search,
  what to look for, plus what to copy from that pro and habits to practice; *All 3 pros* writes it for each.
- **Inline videos (optional)**: add a YouTube Data API key under *Settings → Pro players & videos* (Google Cloud
  console → enable *YouTube Data API v3* → Credentials → API key). The page then shows the videos themselves
  (recent uploads, cached for a day; the free quota is about 100 searches a day). Without a key it shows search links.

**Teams** (*All teams* in the team picker at the top of the menu) is for Premier: add your teammates as players,
make a team, and under **Members & maps** choose 5 starters, any substitutes and the map pool. Then press
*Update everyone's stats*. **Strategy › Comps** shows all maps at a glance (one row per player, one column per
map); click a map for the details:

- a comp: one agent per starter, from their win rate and ACS with that agent on that map (pulled towards
  their overall numbers when there are few games), how much they play it, and how often it's played at your
  level. Every comp needs a Controller, an Initiator and a Sentinel. Dashed cards have little data behind them.
- **If someone is missing**: which sub comes in on which agent, and who should switch.
- **Map meta** (optional, per team): `prefer` / `avoid` agents and a fixed role mix per map, e.g.
  `Lotus: {roles: 1D 1I 2C 1S}`. A role mix you set is followed whenever the players' pools allow it.

The current patch meta isn't available from any API, so "played at your level" comes from your own matches,
and the meta box is where you put what you know. Suggestions are only as good as the sample: check the game
counts shown next to each pick.

### Older matches

The player page shows 10 matches at a time; **Older →** pages back through the
full match history (each new match costs one HenrikDev request, then it's cached).
**Older history** goes further back using HenrikDev's stored archive (one request
per 20 matches, may have gaps). Very old matches may no longer have round data,
so coaching them can fail.

### Accounts and workspaces

- Every user has a **private workspace**: their players, playbooks, notes, reports
  and uploaded VODs. Other users, admins included, can't see or open them (they get 404).
- **Admins** additionally manage users (create, reset password, disable, delete
  with their whole workspace) and the server settings (API key, Ollama, video
  analysis). There must always be at least one active admin.
- Each user's **recordings folder** is set by an admin, because it's a path on
  the server. Users without one upload their VODs.
- Drag the **⋮⋮** handle on a player card to set the order of your players (Home and the player picker in the menu).
  It's saved per account. On a phone drag the handle; with the keyboard, focus it and use the arrow keys.
- All coaching jobs share **one queue** (*Settings → Coaching jobs at the same
  time*, 1 is right for one Mac). Each user can have at most 3 reports queued or
  running (*Max reports per user at once*), and an uploaded VOD may be at most
  20 GB (*Max VOD upload size*); both are admin settings.
- Only round-based modes can be coached (Competitive, Premier, Unrated, Swiftplay,
  Custom). Deathmatch, Team Deathmatch and Gauntlet show as *not coachable*.
- Passwords have at least 8 characters. Changing a password logs out the other
  devices. 5 wrong logins lock that username from that address for 10 minutes.
- Forms are only accepted from the app's own pages (checked via the browser's
  `Origin` header). Behind a reverse proxy, keep the original `Host` header or
  set `X-Forwarded-Host`.
- Forgotten admin password: run
  `python -c "from valcoach.web.store import Store; s=Store('data'); s.set_password(s.user_by_name('user').id, 'new-password')"`
  in the project folder.

Only open the app on your LAN or behind your reverse proxy (with HTTPS). It
holds your API key(s) and serves the uploaded VODs.

### Where do the recordings come from?

The VOD is recorded on the gaming PC, but the app runs wherever. Either:

- **Upload** in the browser on PC (coach page → *Upload a file*). It
  shows a progress bar; a 3–5 GB VOD takes about a minute over gigabit LAN. The file
  goes up in 16 MB pieces (no request may be bigger than 17 MB), so a proxy in front of
  the app must allow at least that. Or:
- **Share the recordings folder** (SMB) from the PC or a NAS, mount it on the Server,
  and set it as the user's recordings folder under *Users*. The coach page then lists the
  files and pre-selects the one saved right after the match.

Record as **MP4 with H.264**, because browsers can't play every MKV.

### Run it permanently

**Option A: systemd** (simplest, uses your existing `.venv`)

```bash
sudo cp deploy/valcoach.service /etc/systemd/system/
sudo nano /etc/systemd/system/valcoach.service    # check User= and paths
sudo systemctl daemon-reload
sudo systemctl enable --now valcoach
journalctl -u valcoach -f                         # logs
```

After an update: `git pull`, `pip install -e .` in the venv, then `sudo systemctl restart valcoach`.
The service may only write to `data/`; if a recordings folder lives somewhere
else, it still works (read-only is enough).

**Option B: Docker Compose**

```bash
UID=$(id -u) GID=$(id -g) docker compose up -d --build
docker compose logs -f
```

- Uses host networking, so Ollama on the same host is reached at `127.0.0.1:11434`
  as before and the app stays on port 10070.
- `./data` is mounted at `/data`. Existing reports and uploads keep working:
  valcoach finds them in the new location automatically.
- Recordings folders: mount them at the **same path** as on the host
  (see the commented line in `docker-compose.yml`).
- Update: `git pull`, then the same `up -d --build`.

Use one or the other, not both (both want port 10070).

## 3. Recording settings (needed for the video part)

| Setting | Value |
|---|---|
| Recorder | OBS / Outplayed / Medal, **MP4 + H.264**, ≥1080p, ≥30 fps, full match in one file |
| Ultrawide monitor | fine: the black bars left/right of the 16:9 game are detected and left out |
| Minimap → Rotate | **Fixed** (orientation *Always the same* or *Based on side*, both work) |
| Minimap → Keep player centered | **Off** |
| Minimap size / zoom | anything, but **keep it the same** across recordings |
| Colour-blind mode / enemy highlight | default (otherwise adjust `COLOR_RANGES` in `valcoach/video/minimap.py`) |
| HUD | default kill-feed position (top right) |

The first time, check the minimap/kill-feed areas with the CLI (below). If
sync fails for a match, *Advanced options* on the coach page take a manual
anchor (the VOD time of one kill).

## 4. Command line (still works, same engine)

`config.toml` (copy from `config.example.toml`) is only used by the CLI, and
on the first start of the web app to pre-fill Settings and create your profile.

```bash
valcoach history                                   # last 10 matches
valcoach coach latest --vod match.mp4              # full run, writes output/*.html
valcoach coach <match_id> --no-llm                 # facts only
valcoach calibrate-minimap <match_id> match.mp4    # debug images in output/calibration/
valcoach notes-template <match_id>
```

`calibrate-minimap` draws the minimap area (orange), the kill-feed area
(magenta), the detected icons (circles) and the API positions (crosses). The
crosses must sit on the icons; if the boxes are off, change the areas in
Settings (web) or `[video]` (CLI).

## 5. How it works

| Module | Does |
|---|---|
| `henrik.py` | v4 client, `Authorization` header, 429 backoff, completed matches cached forever |
| `parse.py` | v4 JSON → models; attacking side per round (Red-attacks-first rule, verified against plants, OT alternates) |
| `maps.py` | valorant-api.com map transforms + callouts; world ↔ minimap UV; nearest callout |
| `analysis/` | team (economy, first contact, setups, player-count progression, trades, plants/retakes), player (kills, death context, KAST, clutches, utility, path) and view/duels (self-calibrating view directions, facing/side/behind, ranges) |
| `video/sync.py` | kill-feed onset detection → offset histogram vote → per-round refinement |
| `video/minimap.py` | HSV icon detection, ICP calibration against API positions, round tracking, rotations |
| `video/allies.py` | teammate identities from kill snapshots, forward/backward tracking, enemy sightings |
| `coach/` | YAML round facts → Ollama with JSON schema → match review from round digests |
| `pipeline.py` | the full run, shared by CLI and web |
| `web/` | Flask app: SQLite store (settings, users, profiles, jobs), accounts, job queue, templates |
| `coach/replay.py` | round replay data (positions, view angles, path) for the report |
| `report.py` | single-file HTML report incl. the SVG round replay |
| `stats/teamdata.py`, `stats/gameplans.py`, `stats/weekly.py`, `discord.py` | matches played together, teammate tips, map facts, game plans, weekly focus, Discord webhooks |
| `web/strats.py`, `web/static/strat.js` | strat book: storage, assets (map image, ability icons), the drag-and-drop editor |
| `web/ui.py`, `web/static/ui.js`, `web/static/styles/*.css` | styles per user, animation switches, Ctrl+K search |
| `web/lineups.py` | lineups library in the strat book |
| `stats/progress.py`, `stats/training.py`, `web/player_views.py` | Progress and Training tabs: weekly numbers, focus checks, aim, routine, learning paths |
| `stats/scouting.py` | scouting summaries of other teams, how to play them, the map veto |
| `web/premierjobs.py`, `web/premier_views.py` | Premier tab: division scouting, match reviews, this week's map, the brief |
| `web/drafts.py`, `web/static/drafts.js` | roster drafts: storage (typed fields only), player numbers per agent, the drag-and-drop editor |
| `web/abilityshapes.py` | every ability's shape and size in meters, and each agent's colour, for the strat board |
| `coach/teamreview.py` | whole-team review of one match (facts per teammate, trades, model write-up) |
| `stats/` | history import, per map / agent aggregates, findings, team comps with subs, pick helper, tips, playstyle + pro matching (`style.py`, `pros.yaml`), YouTube search, team roles (`teamroles.py`) |

Data of the web app lives in `data/`: `valcoach.db`, `cache/` (matches, maps,
minimap calibrations), `profiles/<id>/` (playbook, notes), `uploads/`,
`reports/<job>/`, `uploads/<user>/`, `profiles/<id>/stats/` (imported games, tips). Deleting a report also deletes its uploaded VOD.

## 6. Known limits

- Match data and coaching run on live HenrikDev data. The **video part** (sync,
  minimap) is tested automatically on synthetic recordings (sync within 0.05 s,
  calibration within 1–2 px) and has been fixed on a first real recording (2.16/2.17:
  ultrawide, minimap orientation, ally counts). Other recording setups (resolution,
  HUD scale, minimap settings) may still need the screen areas or `COLOR_RANGES` adjusted once.
- The live API has no per-round utility (ability casts are `null` per round), so
  round coaching leaves utility out; match totals are still used.
- Without a VOD, positions are only known at kills, plants and defuses; the round
  replay estimates everything in between.
- Ally counts from the minimap are approximate, because stacked icons merge.
- Teammate tracking is tuned on synthetic recordings (95 % coverage, ~1.7 m median error there).
  Real minimaps have agent portraits, utility icons and pings, so expect less on real recordings.
- After you die, the minimap shows your spectated teammate's view, so your own path ends at your death.
- Teams are shared (comps, game plans, notes, strats), but each player's coaching playbook
  is still a separate copy per profile.
