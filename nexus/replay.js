// Nexus round replay: continuous playback on the minimap.
// Data per round (RD.rounds[n]): events (kills/plants/defuses with snapshots), tracks per player
// ([t, u, v, kind] with kind 1 = known position, 0 = estimated route, 2 = spawn), roster, end (ms),
// measured (ids tracked on the VOD minimap, or every player with a replay file: source 'replay file') and seen ([t, u, v] enemy icons spotted on the minimap).
// casts (4.16.2, replay file): [{t, id, buy}] ability uses, drawn as a pulse where the player stood.
// effects (4.16.3, replay file): [{t0, t1, id, agent, slot, type, p, r}] placed utility (smoke, wall, slow,
// damage, trap, recon, orb, flash, other) drawn at its spot while it lasts, with the ability's icon.
// Hooks (4.18, set by the page as window.NEXUS_RP, all optional): pins(round) -> [{id, t, text, by, strokes}],
// addPin(round, {t, text, strokes}) -> Promise, delPin(round, id) -> Promise, canDelete(pin) -> bool,
// toStrat(round, {t, side, items, notes}) -> Promise of the new strat board's URL. With them the playback gets
// notes at a moment with lines drawn on the map (shown around their time, the playback stops there) and
// "Strat board" (this moment's positions, utility and drawings on a new board). 4.20: toDiscord(round, png Blob,
// text) -> Promise posts the moment as a picture; "⤓ Picture" saves it (always there).
(function () {
  const NS = 'http://www.w3.org/2000/svg', S = 1000;
  const COL = {us: '#2dd4bf', them: '#ff4655', you: '#f6d24a', better: '#f2b84b', plant: '#ff4655', defuse: '#2dd4bf'};
  const KNOWN_MS = 1200;          // within this time of a known position the icon is drawn solid
  const CONE_MS = 1500;           // view cones are only shown close to a snapshot
  const TRAIL_MS = 6000;
  const KILL_FLASH_MS = 2000;
  const SEEN_MS = 900;            // a spotted enemy icon stays visible this long
  const CAST_MS = 1800;           // an ability pulse is shown this long after the cast
  const PIN_MS = 4000;            // a note and its drawing are shown this long from their time
  const AB_SLOT = {Q: 'Ability1', E: 'Ability2', C: 'Grenade', X: 'Ultimate'};
  const PIN_COL = '#f6d24a';

  const fmt = ms => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  const parseT = s => { const m = /(\d+):(\d{1,2})/.exec(s || ''); return m ? (+m[1] * 60 + +m[2]) * 1000 : null; };
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function h(tag, attrs, html) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  // position of a player at time t from their track
  function posAt(track, t) {
    const p = track.pts;
    if (!p.length) return null;
    if (t <= p[0][0]) return [p[0][1], p[0][2]];
    let lo = 0, hi = p.length - 1;
    if (t >= p[hi][0]) return [p[hi][1], p[hi][2]];
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (p[mid][0] <= t) lo = mid; else hi = mid; }
    const a = p[lo], b = p[hi], f = (t - a[0]) / Math.max(1, b[0] - a[0]);
    return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }
  function knownGap(track, t) {           // ms to the nearest known (or spawn) point
    let best = Infinity;
    for (const q of track.pts) if (q[3] !== 0) best = Math.min(best, Math.abs(q[0] - t));
    return best;
  }

  function build(box) {
    if (box.dataset.built) return;
    const RD = window.VALCOACH_REPLAY, n = box.dataset.round, R = RD.rounds[n];
    if (!R || !RD.map) return;
    box.dataset.built = '1';
    const M = RD.map, B = (RD.better || {})[n], icons = RD.agents || {};
    const who = id => R.roster[id] || {name: '?', agent: '?', us: false, you: false};
    const colorOf = id => who(id).you ? COL.you : (who(id).us ? COL.us : COL.them);
    const ids = Object.keys(R.roster);
    const vodStart = (window.VALCOACH_START || {})[n];
    const kills = R.events.filter(e => e.kind === 'kill');
    const plant = R.events.find(e => e.kind === 'plant'), defuse = R.events.find(e => e.kind === 'defuse');
    const bt = B ? parseT(B.time) : null;
    const casts = R.casts || [];
    const effects = R.effects || [];
    const FX = {smoke: ['#aab3c2', .5], slow: ['#7fc4ff', .28], damage: ['#ff8a3d', .32], orb: ['#c58cff', .3]};
    const FX_NAME = {smoke: 'smoke', wall: 'wall', slow: 'slow', damage: 'molly / damage', trap: 'trap', recon: 'recon',
                     orb: 'orb', flash: 'flash', other: 'ability'};
    const castsBefore = (id, t) => casts.reduce((n, c) => n + (c.id === id && c.t <= t ? 1 : 0), 0);
    const HK = window.NEXUS_RP || null;
    const pinsOf = () => (HK && HK.pins ? HK.pins(n) || [] : []);

    // ------------------------------------------------------------ layout
    box.innerHTML = '';
    const root = h('div', {class: 'rp'});
    const main = h('div', {class: 'rp-main'});
    const stage = h('div', {class: 'rp-stage'});
    const zoomBtns = h('div', {class: 'rp-zoom'},
      '<button data-z="in" title="Zoom in">+</button><button data-z="out" title="Zoom out">−</button>' +
      '<button data-z="fit" title="Fit map">⤢</button><button data-z="full" title="Fullscreen">⛶</button>');
    stage.appendChild(zoomBtns);
    const bar = h('div', {class: 'rp-bar'},
      `<button class="rp-play" title="Play / pause (space)">▶</button>
       <span class="rp-time">0:00 / ${fmt(R.end)}</span>
       <div class="rp-scrub"><div class="rp-ticks"></div><input type="range" min="0" max="${R.end}" step="100" value="0"></div>
       <select class="rp-speed" title="Speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select>
       ${vodStart != null ? '<button class="rp-vod" title="Show this moment in the VOD">🎬</button>' : ''}
       ${HK && HK.addPin ? '<button class="rp-pin" title="Draw on the map and leave a note at this moment">✎ Note</button>' : ''}
       ${HK && HK.toStrat ? '<button class="rp-strat" title="This moment (positions, utility, drawings) on a new strat board">⇢ Strat board</button>' : ''}
       <button class="rp-pic" title="Save this moment as a picture">⤓ Picture</button>
       ${HK && HK.toDiscord ? '<button class="rp-disc" title="Post this moment (map, players, utility, notes) to the team\'s Discord">📷 Discord</button>' : ''}
       <span class="rp-msg"></span>`);
    const comp = h('div', {class: 'rp-compose', hidden: ''},
      `<span class="rp-ctime"></span><input type="text" maxlength="300" placeholder="What should everyone see here?">
       <button class="rp-csave">Save note</button><button class="rp-cundo" title="Remove the last line">↶</button>
       <button class="rp-ccancel">Cancel</button><span class="rp-cmsg"></span>`);
    const opts = h('div', {class: 'rp-opts'},
      `<label><input type="checkbox" data-o="names" checked> names</label>
       <label><input type="checkbox" data-o="callouts" checked> callouts</label>
       <label><input type="checkbox" data-o="trails" checked> trails</label>
       ${R.view ? '<label><input type="checkbox" data-o="cones" checked> view cones</label>' : ''}
       ${(R.seen || []).length ? '<label><input type="checkbox" data-o="seen" checked> spotted enemies</label>' : ''}
       ${casts.length || effects.length ? '<label><input type="checkbox" data-o="util" checked> utility</label>' : ''}
       ${HK && HK.pins ? '<label><input type="checkbox" data-o="pins" checked> notes</label><label><input type="checkbox" data-o="stop" checked> stop at notes</label>' : ''}
       <span class="rp-note">solid = known position (kills${(R.measured || []).length ? (R.source === 'replay file' ? ', replay file' : ', your minimap') : ''}) · faded = estimated ${R.routes ? '(walkable route at running speed)' : '(straight line)'}${(R.seen || []).length ? ' · red rings = enemies seen on your minimap' : ''}${casts.length ? ' · ⚡ pulse = ability used (replay file)' : ''}${effects.length ? ' · grey circles = smokes, icons = placed utility while it lasts' : ''} · click a player to show their route · zoom: + / − or Ctrl + wheel</span>`);
    main.append(stage, bar, comp, opts);
    if (B) main.appendChild(h('div', {class: 'rp-better'}, `<b>Better position ${esc(B.time)}: ${esc(B.callout)}</b> — ${esc(B.why)}`));
    const side = h('aside', {class: 'rp-side'});
    const rosterEl = h('div', {class: 'rp-roster'});
    const feedEl = h('div', {class: 'rp-feed'});
    const colA = h('div', {class: 'rp-col'}), colB = h('div', {class: 'rp-col'});
    colA.append(h('div', {class: 'rp-h'}, 'Players'), rosterEl);
    colB.append(h('div', {class: 'rp-h'}, 'Round events'), feedEl);
    const pinsEl = h('div', {class: 'rp-feed rp-pins'});
    if (HK && HK.pins) colB.append(h('div', {class: 'rp-h'}, 'Notes'), pinsEl);
    side.append(colA, colB);
    root.append(main, side);
    box.appendChild(root);

    // ------------------------------------------------------------ svg
    const svg = el('svg', {viewBox: `0 0 ${S} ${S}`, class: 'rp-svg', role: 'img', 'aria-label': 'Round replay'}, stage);
    const defs = el('defs', {}, svg);
    const clip = el('clipPath', {id: `clip-${n}`, clipPathUnits: 'objectBoundingBox'}, defs);
    el('circle', {cx: .5, cy: .5, r: .5}, clip);
    const grey = el('filter', {id: `grey-${n}`}, defs);
    el('feColorMatrix', {type: 'saturate', values: 0}, grey);
    for (const [k, c] of Object.entries(COL)) {
      const m = el('marker', {id: `ar-${k}-${n}`, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse'}, defs);
      el('path', {d: 'M0,0 L10,5 L0,10 z', fill: c}, m);
    }
    const world = el('g', {}, svg);
    if (M.image) el('image', {href: M.image, x: 0, y: 0, width: S, height: S, opacity: .85, preserveAspectRatio: 'none'}, world);
    const gCall = el('g', {'font-size': 17, fill: '#dfe6f2', 'text-anchor': 'middle', opacity: .6, 'pointer-events': 'none'}, world);
    for (const c of M.callouts) { const t = el('text', {x: c.p[0] * S, y: c.p[1] * S}, gCall); t.textContent = c.label; }
    const g = el('g', {}, world);

    // ------------------------------------------------------------ state
    let T = 0, playing = false, speed = 1, last = null;
    const show = {names: true, callouts: true, trails: true, cones: !!R.view, seen: true, util: true, pins: true, stop: true};
    let drawing = false, pending = [], stroke = null, pinSig = '';
    const measured = new Set(R.measured || []);
    const selected = new Set();
    const youId = ids.find(id => who(id).you);
    let view = {x: 0, y: 0, w: S};

    // ------------------------------------------------------------ roster + feed
    const avatar = (id, cls = '') => {
      const ic = icons[who(id).agent];
      return ic ? `<img class="rp-av ${cls}" src="${ic}" style="border-color:${colorOf(id)}" alt="">`
                : `<span class="rp-av ${cls}" style="background:${colorOf(id)};border-color:${colorOf(id)}"></span>`;
    };
    const rows = {};
    for (const id of ids) {
      const r = h('button', {class: 'rp-row', 'data-id': id, title: 'Show / hide route'},
        `${avatar(id)}<span class="rp-nm">${esc(who(id).you ? 'You' : who(id).name)}<small>${esc(who(id).agent)}${measured.has(id) ? (R.source === 'replay file' ? ' · from replay file' : ' · tracked on video') : ''}</small></span>${casts.length ? '<span class="rp-ut" title="Abilities used so far this round">⚡0</span>' : ''}<span class="rp-st"></span>`);
      r.onclick = () => { selected.has(id) ? selected.delete(id) : selected.add(id); draw(); };
      rosterEl.appendChild(r); rows[id] = r;
    }
    const feedRows = [];
    const feedEvents = [...R.events, ...casts.filter(c => who(c.id).you).map(c => ({kind: 'cast', t: c.t, time: c.buy ? 'buy' : fmt(c.t), id: c.id}))]
      .sort((a, b) => a.t - b.t);
    for (const e of feedEvents) {
      let txt;
      if (e.kind === 'cast') {
        txt = `<span class="rp-cast">⚡</span><span>You used an ability</span>`;
      } else if (e.kind === 'kill') {
        txt = `${e.killer ? avatar(e.killer, 'sm') : ''}<span>${esc(e.killer ? (who(e.killer).you ? 'You' : who(e.killer).name) : 'Spike')}</span>
               <span class="rp-arrow" style="color:${e.ours ? COL.us : COL.them}">→</span>${avatar(e.victim, 'sm')}<span>${esc(who(e.victim).you ? 'you' : who(e.victim).name)}</span>`;
      } else {
        txt = `<span class="rp-spike" style="background:${e.kind === 'plant' ? COL.plant : COL.defuse}"></span><span>${esc(e.by ? (who(e.by).you ? 'You' : who(e.by).name) : '')} ${e.kind === 'plant' ? 'planted' : 'defused'} ${esc(e.site || '')}</span>`;
      }
      const r = h('button', {class: 'rp-ev'}, `<b>${e.time}</b>${txt}`);
      r.onclick = () => { pause(); seek(Math.max(0, e.t - 1500)); };
      feedEl.appendChild(r); feedRows.push([e, r]);
    }

    // scrub ticks
    const ticks = bar.querySelector('.rp-ticks');
    for (const e of R.events) {
      const c = e.kind === 'kill' ? (e.ours ? COL.us : COL.them) : (e.kind === 'plant' ? COL.plant : COL.defuse);
      const tk = h('span', {class: 'rp-tick' + (e.kind !== 'kill' ? ' spike' : ''), title: `${e.time} ${e.kind}`});
      tk.style.left = (100 * e.t / R.end) + '%'; tk.style.background = c; tk.dataset.t = e.t;
      ticks.appendChild(tk);
    }
    for (const c of casts) {                       // small ticks under the bar: who used utility when
      const tk = h('span', {class: 'rp-tick cast' + (who(c.id).you ? ' you' : ''), title: `${c.buy ? 'buy phase' : fmt(c.t)} ${who(c.id).you ? 'you' : who(c.id).name}: ability`});
      tk.style.left = (100 * c.t / R.end) + '%'; tk.style.background = colorOf(c.id); tk.dataset.t = c.t;
      ticks.appendChild(tk);
    }

    // notes: list + ticks, rebuilt when they change (another viewer's notes arrive with the page's polling)
    function renderPins() {
      const ps = pinsOf(), sig = ps.map(p => p.id + ':' + p.t).join(',');
      if (sig === pinSig) return;
      pinSig = sig;
      ticks.querySelectorAll('.rp-tick.pin').forEach(x => x.remove());
      pinsEl.innerHTML = ps.length ? '' : '<p class="rp-none">No notes yet. Pause at a moment, press ✎ Note, draw on the map and write a line.</p>';
      for (const p of ps) {
        const tk = h('span', {class: 'rp-tick pin', title: `${fmt(p.t)} note: ${p.text || 'drawing'}`});
        tk.style.left = (100 * p.t / R.end) + '%'; tk.style.background = PIN_COL;
        ticks.appendChild(tk);
        const r = h('button', {class: 'rp-ev rp-pinrow'}, `<b>${fmt(p.t)}</b><span>✎ ${esc(p.text || '(drawing)')} <small>${esc(String(p.by || '').split('#')[0])}</small></span>` +
          (HK.delPin && (!HK.canDelete || HK.canDelete(p)) ? '<span class="rp-pdel" title="Delete this note">✕</span>' : ''));
        r.onclick = ev => {
          if (ev.target.classList.contains('rp-pdel')) {
            ev.stopPropagation();
            HK.delPin(n, p.id).then(() => { pinSig = ''; draw(); }).catch(e => { msg(e.message || 'not deleted'); });
            return;
          }
          pause(); seek(p.t);
        };
        pinsEl.appendChild(r);
      }
    }
    // status line next to the buttons: always plain text; a link only to a page of this site
    const msg = (text, url) => {
      const box = bar.querySelector('.rp-msg');
      box.textContent = '';
      if (url && /^\/[^/\\]/.test(url)) {
        const a = document.createElement('a');
        a.href = url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = text;
        box.appendChild(a);
      } else box.textContent = text;
    };

    // ------------------------------------------------------------ drawing
    function cone(x, y, a, color, alpha) {
      const L = 95, w = Math.PI / 6;
      const x1 = x + L * Math.cos(a - w), y1 = y + L * Math.sin(a - w), x2 = x + L * Math.cos(a + w), y2 = y + L * Math.sin(a + w);
      el('path', {d: `M${x},${y} L${x1},${y1} A${L},${L} 0 0 1 ${x2},${y2} Z`, fill: color, opacity: .25 * alpha}, g);
    }
    function token(id, x, y, opt) {
      const c = colorOf(id), me = who(id).you, r = (me ? 30 : 24) * (opt.scale || 1), ic = icons[who(id).agent];
      const grp = el('g', {'data-id': id, class: 'rp-tok', opacity: opt.alpha}, g);
      el('circle', {cx: x, cy: y, r: r + 3, fill: '#0b0e13'}, grp);
      if (ic) el('image', {href: ic, x: x - r, y: y - r, width: 2 * r, height: 2 * r, 'clip-path': `url(#clip-${n})`,
                           filter: opt.dead ? `url(#grey-${n})` : null, opacity: opt.dead ? .5 : 1}, grp);
      else el('circle', {cx: x, cy: y, r, fill: c, opacity: opt.dead ? .45 : 1}, grp);
      el('circle', {cx: x, cy: y, r, fill: 'none', stroke: c, 'stroke-width': me ? 6 : 5,
                    'stroke-dasharray': opt.est ? '7 5' : null, opacity: opt.dead ? .6 : 1}, grp);
      if (opt.dead) {
        const t = el('text', {x, y: y + r * .45, 'font-size': r * 1.4, 'text-anchor': 'middle', fill: '#ff4655', 'font-weight': 700,
                              stroke: '#0b0e13', 'stroke-width': 3, 'paint-order': 'stroke'}, grp);
        t.textContent = '✕';
      }
      if (show.names && !opt.dead || selected.has(id)) {
        const t = el('text', {x, y: y - r - 8, 'font-size': me ? 23 : 19, 'text-anchor': 'middle', fill: '#fff', stroke: '#0b0e13',
                              'stroke-width': 5, 'paint-order': 'stroke', 'font-weight': me ? 700 : 500}, grp);
        t.textContent = me ? 'you' : who(id).name;
      }
    }
    function nearestSnapshotAngle(id, t) {
      let best = null, gap = Infinity;
      for (const e of R.events) {
        const d = Math.abs(e.t - t);
        if (d > CONE_MS || d >= gap) continue;
        const p = (e.players || []).find(q => q.id === id);
        if (p && p.a !== null && p.a !== undefined) { best = p.a; gap = d; }
      }
      return best === null ? null : [best, 1 - gap / CONE_MS];
    }

    function draw() {
      if (HK && HK.pins) renderPins();
      while (g.firstChild) g.removeChild(g.firstChild);
      gCall.style.display = show.callouts ? '' : 'none';
      // spike
      if (plant && T >= plant.t) {
        const [x, y] = [plant.spot[0] * S, plant.spot[1] * S], done = defuse && T >= defuse.t;
        el('rect', {x: x - 14, y: y - 14, width: 28, height: 28, transform: `rotate(45 ${x} ${y})`,
                    fill: done ? COL.defuse : COL.plant, stroke: '#fff', 'stroke-width': 3}, g);
      }
      // selected routes (whole round) with times at known points
      for (const id of selected) {
        const tr = R.tracks[id]; if (!tr) continue;
        const end = tr.death != null ? tr.death : R.end;
        const pts = tr.pts.filter(q => q[0] <= end);
        el('polyline', {points: pts.map(q => `${q[1] * S},${q[2] * S}`).join(' '), fill: 'none', stroke: colorOf(id),
                        'stroke-width': 4, 'stroke-dasharray': '3 9', 'stroke-linecap': 'round', opacity: .9}, g);
        // time labels on known positions, at least 4 s apart (your VOD path has a point every 0.5 s)
        const known = pts.filter(q => q[3] === 1), labelled = [];
        let lastT = -1e9;
        known.forEach((q, i) => {
          if (q[0] - lastT >= 4000 || i === known.length - 1) {
            if (i === known.length - 1 && labelled.length && q[0] - lastT < 1500) labelled.pop();
            labelled.push(q); lastT = q[0];
          }
        });
        for (const q of labelled) {
          el('circle', {cx: q[1] * S, cy: q[2] * S, r: 6, fill: colorOf(id), stroke: '#0b0e13', 'stroke-width': 2}, g);
          const t = el('text', {x: q[1] * S + 9, y: q[2] * S + 6, 'font-size': 16, fill: '#fff', stroke: '#0b0e13', 'stroke-width': 4,
                                'paint-order': 'stroke'}, g);
          t.textContent = fmt(q[0]);
        }
      }
      // trails (last few seconds)
      if (show.trails) for (const id of ids) {
        const tr = R.tracks[id]; if (!tr) continue;
        if (tr.death != null && T >= tr.death) continue;
        const pts = tr.pts.filter(q => q[0] > T - TRAIL_MS && q[0] < T).map(q => [q[1], q[2]]);
        const now = posAt(tr, T); if (!now) continue;
        const start = posAt(tr, Math.max(0, T - TRAIL_MS));
        const line = [start, ...pts, now].map(p => `${p[0] * S},${p[1] * S}`).join(' ');
        el('polyline', {points: line, fill: 'none', stroke: colorOf(id), 'stroke-width': 4, opacity: .45, 'stroke-linecap': 'round'}, g);
      }
      // cones
      if (show.cones) for (const id of ids) {
        const tr = R.tracks[id]; if (!tr || (tr.death != null && T >= tr.death)) continue;
        const a = nearestSnapshotAngle(id, T), p = posAt(tr, T);
        if (a && p) cone(p[0] * S, p[1] * S, a[0], colorOf(id), a[1]);
      }
      // enemies spotted on your minimap (no identity: the minimap only shows a red icon)
      if (show.seen) for (const q of R.seen || []) {
        if (q[0] > T || q[0] < T - SEEN_MS) continue;
        const f = 1 - (T - q[0]) / SEEN_MS;
        el('circle', {cx: q[1] * S, cy: q[2] * S, r: 17, fill: 'none', stroke: COL.them, 'stroke-width': 4, opacity: .25 + .6 * f}, g);
        el('circle', {cx: q[1] * S, cy: q[2] * S, r: 5, fill: COL.them, opacity: .25 + .6 * f}, g);
      }
      // placed utility while it lasts: smokes / slows / mollies as areas, the rest as icons (replay file)
      if (show.util) {
        const live = effects.filter(e => T >= e.t0 && (e.t1 == null ? true : T <= e.t1));
        const area = live.filter(e => FX[e.type] && e.r > 0), mark = live.filter(e => !(FX[e.type] && e.r > 0));
        for (const e of area) {
          const [c, a] = FX[e.type], x = e.p[0] * S, y = e.p[1] * S, rr = e.r * S;
          const fade = e.t1 != null ? Math.min(1, (e.t1 - T) / 1500) : 1, grow = Math.min(1, (T - e.t0) / 500);
          el('circle', {cx: x, cy: y, r: rr * (.35 + .65 * grow), fill: c, opacity: a * fade,
                        stroke: e.id ? colorOf(e.id) : '#d6dbe4', 'stroke-width': 3, 'stroke-opacity': .7 * fade}, g);
        }
        for (const e of [...area, ...mark]) {
          const x = e.p[0] * S, y = e.p[1] * S, ic = icons[`${e.agent}|${e.slot}`], c = e.id ? colorOf(e.id) : '#d6dbe4';
          const fade = e.t1 != null ? Math.max(.25, Math.min(1, (e.t1 - T) / 1500)) : 1;
          const grp = el('g', {opacity: fade}, g);
          if (e.type === 'recon') {                      // reveal: a slow ring
            const k = ((T - e.t0) % 1600) / 1600;
            el('circle', {cx: x, cy: y, r: 18 + 50 * k, fill: 'none', stroke: c, 'stroke-width': 3, opacity: 1 - k}, grp);
          }
          el('circle', {cx: x, cy: y, r: 15, fill: '#0b0e13', stroke: c, 'stroke-width': 3, opacity: .9}, grp);
          if (ic) el('image', {href: ic, x: x - 11, y: y - 11, width: 22, height: 22}, grp);
          else { const t = el('text', {x, y: y + 6, 'font-size': 16, 'text-anchor': 'middle', fill: '#fff'}, grp); t.textContent = e.slot || '•'; }
          const tt = el('title', {}, grp);
          tt.textContent = `${e.id ? (who(e.id).you ? 'You' : who(e.id).name) : e.agent || '?'}: ${e.agent} ${e.slot} (${FX_NAME[e.type] || 'ability'})`;
        }
      }
      // ability pulses: where a player stood when they used an ability (replay file)
      if (show.util) for (const c of casts) {
        if (T < c.t || T > c.t + CAST_MS) continue;
        const tr = R.tracks[c.id]; if (!tr) continue;
        const p = posAt(tr, c.t); if (!p) continue;
        const f = (T - c.t) / CAST_MS, x = p[0] * S, y = p[1] * S;
        el('circle', {cx: x, cy: y, r: 26 + 38 * f, fill: 'none', stroke: colorOf(c.id), 'stroke-width': 5 * (1 - f) + 1, opacity: 1 - f}, g);
        const t = el('text', {x: x + 24, y: y - 20, 'font-size': 24, fill: '#ffd84a', stroke: '#0b0e13', 'stroke-width': 4,
                              'paint-order': 'stroke', opacity: 1 - f * .7}, g);
        t.textContent = '⚡';
      }
      // kill lines just after each kill
      for (const e of kills) {
        if (!e.from || T < e.t || T > e.t + KILL_FLASH_MS) continue;
        const k = e.ours ? 'us' : 'them', f = 1 - (T - e.t) / KILL_FLASH_MS;
        el('line', {x1: e.from[0] * S, y1: e.from[1] * S, x2: e.to[0] * S, y2: e.to[1] * S, stroke: COL[k], 'stroke-width': 5,
                    opacity: .3 + .7 * f, 'marker-end': `url(#ar-${k}-${n})`}, g);
      }
      // the coach's better spot around its time
      if (B && bt !== null && Math.abs(T - bt) <= 4000) {
        const spot = (M.callouts.find(c => c.label === B.callout) || {}).p;
        const me = youId && R.tracks[youId] ? posAt(R.tracks[youId], T) : null;
        if (spot) {
          if (me) el('line', {x1: me[0] * S, y1: me[1] * S, x2: spot[0] * S, y2: spot[1] * S, stroke: COL.better, 'stroke-width': 4,
                              'stroke-dasharray': '12 8', 'marker-end': `url(#ar-better-${n})`}, g);
          el('circle', {cx: spot[0] * S, cy: spot[1] * S, r: 28, fill: 'none', stroke: COL.better, 'stroke-width': 5, 'stroke-dasharray': '8 6'}, g);
          el('circle', {cx: spot[0] * S, cy: spot[1] * S, r: 7, fill: COL.better}, g);
        }
      }
      // players: dead first, then alive (you on top)
      const order = [...ids].sort((a, b) => (who(a).you ? 1 : 0) - (who(b).you ? 1 : 0));
      for (const id of order) {
        const tr = R.tracks[id]; if (!tr) continue;
        if (tr.death != null && T >= tr.death) {
          const lp = tr.pts[tr.pts.length - 1];
          token(id, lp[1] * S, lp[2] * S, {dead: true, scale: .8, alpha: 1});
        }
      }
      for (const id of order) {
        const tr = R.tracks[id]; if (!tr || (tr.death != null && T >= tr.death)) continue;
        const p = posAt(tr, T); if (!p) continue;
        const est = knownGap(tr, T) > KNOWN_MS;
        token(id, p[0] * S, p[1] * S, {est, alpha: est ? .62 : 1});
      }
      // notes: their lines and text around their time, and what's being drawn now
      const line = (pts, op, dash) => el('polyline', {points: pts.map(q => `${q[0]},${q[1]}`).join(' '), fill: 'none', stroke: PIN_COL,
        'stroke-width': 7, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: op, 'stroke-dasharray': dash ? '14 8' : null}, g);
      if (show.pins) for (const p of pinsOf()) {
        if (T < p.t - 300 || T > p.t + PIN_MS) continue;
        const op = T < p.t ? .5 : Math.max(.25, 1 - (T - p.t) / PIN_MS * .75);
        for (const st of p.strokes || []) line(st, op);
        if (p.text) {
          const at = (p.strokes && p.strokes[0] && p.strokes[0][0]) || [40, 60];
          const right = at[0] > S / 2;       // on the right half the text runs to the left, so it stays on the map
          const tx = el('text', {x: right ? at[0] - 14 : at[0] + 14, y: Math.max(at[1] - 14, 30), 'text-anchor': right ? 'end' : 'start',
                                 'font-size': 26, 'font-weight': 700, fill: PIN_COL,
                                 stroke: '#0b0e13', 'stroke-width': 6, 'paint-order': 'stroke', opacity: Math.min(1, op + .2)}, g);
          tx.textContent = p.text.length > 60 ? p.text.slice(0, 58) + '…' : p.text;
        }
      }
      for (const st of pending) line(st, .95, true);
      // side panel state
      for (const id of ids) {
        const tr = R.tracks[id], dead = tr && tr.death != null && T >= tr.death;
        rows[id].classList.toggle('dead', !!dead);
        rows[id].classList.toggle('sel', selected.has(id));
        rows[id].querySelector('.rp-st').textContent = dead ? `✕ ${fmt(tr.death)}` : '';
        const ut = rows[id].querySelector('.rp-ut');
        if (ut) { const k = castsBefore(id, T); ut.textContent = `⚡${k}`; ut.classList.toggle('zero', k === 0); }
      }
      let cur = null;
      for (const [e, r] of feedRows) { r.classList.toggle('past', e.t <= T); if (e.t <= T && T - e.t < 2500) cur = r; }
      for (const [, r] of feedRows) r.classList.toggle('now', r === cur);
      bar.querySelector('.rp-time').textContent = LOCK == null ? `${fmt(T)} / ${fmt(R.end)}` : fmt(T);
      bar.querySelector('input').value = T;
    }

    // ------------------------------------------------------------ playback
    const playBtn = bar.querySelector('.rp-play');
    function frame(ts) {
      if (!playing) return;
      const before = T;
      if (last !== null) T += (ts - last) * speed;
      last = ts;
      if (show.stop && show.pins) {
        const p = pinsOf().find(q => q.t > before && q.t <= T);
        if (p) { T = p.t; pause(); draw(); return; }
      }
      if (LOCK != null && T >= LOCK) { T = LOCK; pause(); }
      if (T >= R.end) { T = R.end; pause(); }
      draw();
      if (playing) requestAnimationFrame(frame);
    }
    function play() { if (T >= R.end) T = 0; playing = true; last = null; playBtn.textContent = '❚❚'; requestAnimationFrame(frame); }
    function pause() { playing = false; playBtn.textContent = '▶'; }
    function seek(t) { T = Math.max(0, Math.min(LOCK == null ? R.end : LOCK, t)); draw(); }
    // 4.22 (quiz): the page can jump to a moment and lock the playback there: nothing after it is shown
    // (no later kills in the list or on the bar, no round length) until it's unlocked
    let LOCK = null;
    function lock(t) {
      LOCK = t == null ? null : Math.max(0, Math.min(R.end, t));
      for (const [e, r] of feedRows) r.hidden = LOCK != null && e.t > LOCK;
      for (const tk of ticks.querySelectorAll('.rp-tick')) if (tk.dataset.t) tk.hidden = LOCK != null && +tk.dataset.t > LOCK;
      if (LOCK != null && T > LOCK) T = LOCK;
      draw();
    }
    box._seek = t => { pause(); seek(t); };
    box._lock = lock;
    box._play = () => play();
    playBtn.onclick = () => playing ? pause() : play();
    bar.querySelector('input').oninput = ev => { pause(); seek(+ev.target.value); };
    bar.querySelector('.rp-speed').onchange = ev => { speed = +ev.target.value; };
    const vodBtn = bar.querySelector('.rp-vod');
    if (vodBtn) vodBtn.onclick = () => { pause(); if (window.seek) window.seek(vodStart + T / 1000); };
    const pinBtn = bar.querySelector('.rp-pin'), cin = comp.querySelector('input');
    const compose = on => {
      drawing = on; comp.hidden = !on; svg.style.cursor = on ? 'crosshair' : '';
      if (on) { pause(); comp.querySelector('.rp-ctime').textContent = `Note at ${fmt(T)}: draw on the map, then write a line`; comp.querySelector('.rp-cmsg').textContent = ''; cin.focus(); }
      else { pending = []; stroke = null; cin.value = ''; }
      if (pinBtn) pinBtn.classList.toggle('on', on);
      draw();
    };
    if (pinBtn) pinBtn.onclick = () => compose(!drawing);
    comp.querySelector('.rp-ccancel').onclick = () => compose(false);
    comp.querySelector('.rp-cundo').onclick = () => { pending.pop(); draw(); };
    const savePin = () => {
      const text = cin.value.trim();
      if (!text && !pending.length) { comp.querySelector('.rp-cmsg').textContent = 'Draw on the map or write something first.'; return; }
      comp.querySelector('.rp-cmsg').textContent = 'saving…';
      HK.addPin(n, {t: Math.round(T), text, strokes: pending}).then(() => { pinSig = ''; compose(false); })
        .catch(e => { comp.querySelector('.rp-cmsg').textContent = 'Not saved: ' + (e.message || e); });
    };
    comp.querySelector('.rp-csave').onclick = savePin;
    cin.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); savePin(); } else if (e.key === 'Escape') compose(false); });

    // this moment on a new strat board: everyone alive where they stand, the utility that's up, the drawings
    function moment() {
      const items = [];
      for (const id of ids) {
        const tr = R.tracks[id]; if (!tr || (tr.death != null && T >= tr.death)) continue;
        const p = posAt(tr, T); if (!p) continue;
        items.push({t: 'agent', a: who(id).agent, x: Math.round(p[0] * S), y: Math.round(p[1] * S), c: who(id).us ? 'us' : 'them', label: who(id).name});
      }
      for (const e of effects) {
        if (!(T >= e.t0 && (e.t1 == null || T <= e.t1))) continue;
        const x = Math.round(e.p[0] * S), y = Math.round(e.p[1] * S), c = e.id && !who(e.id).us ? 'them' : 'us';
        if (e.agent && AB_SLOT[e.slot]) items.push({t: 'ab', a: e.agent, s: AB_SLOT[e.slot], x, y, c});
        else items.push({t: e.type === 'smoke' ? 'smoke' : e.type === 'damage' ? 'molly' : 'zone', x, y, r: 4.5});
      }
      const near = pinsOf().filter(p => Math.abs(p.t - T) <= PIN_MS);
      for (const st of [...pending, ...near.flatMap(p => p.strokes || [])]) items.push({t: 'pen', pts: st, c: 'us'});
      return {t: Math.round(T), side: R.attack ? 'attack' : 'defense', items,
              notes: near.filter(p => p.text).map(p => `${fmt(p.t)} ${p.text}`).join('\n')};
    }
    // this moment as a picture: the map as it's shown now (zoom included), with the round and time on top
    async function dataUrl(href) {
      if (!href || href.startsWith('data:')) return href;
      try {
        const b = await (await fetch(href)).blob(); if (!b.type.startsWith('image')) return null;
        return await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); });
      } catch (e) { return null; }
    }
    const caption = () => {
      const near = pinsOf().filter(p => p.text && Math.abs(p.t - T) <= PIN_MS).map(p => p.text);
      return [`${M.name || ''} round ${n} · ${fmt(T)}`.trim(), ...near].join('\n');
    };
    async function picture() {
      const clone = svg.cloneNode(true), P = 1400;
      clone.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.w}`);
      clone.setAttribute('font-family', 'Inter, Segoe UI, Helvetica, Arial, sans-serif');
      for (const im of clone.querySelectorAll('image')) {
        const d = await dataUrl(im.getAttribute('href'));
        if (d) im.setAttribute('href', d); else im.remove();
      }
      const k = view.w / S;
      const title = el('text', {x: view.x + 16 * k, y: view.y + 38 * k, 'font-size': 30 * k, 'font-weight': 800, fill: '#fff',
                                stroke: '#0b0e13', 'stroke-width': 6 * k, 'paint-order': 'stroke'});
      title.textContent = caption().split('\n')[0];
      clone.appendChild(title);
      clone.setAttribute('width', P); clone.setAttribute('height', P);
      const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], {type: 'image/svg+xml'}));
      const img = new Image();
      await new Promise((ok, no) => { img.onload = ok; img.onerror = no; img.src = url; });
      const c = document.createElement('canvas'); c.width = P; c.height = P;
      const ctx = c.getContext('2d'); ctx.fillStyle = '#0b0e13'; ctx.fillRect(0, 0, P, P); ctx.drawImage(img, 0, 0, P, P);
      URL.revokeObjectURL(url);
      return await new Promise(res => c.toBlob(res, 'image/png'));
    }
    bar.querySelector('.rp-pic').onclick = async () => {
      pause();
      try {
        const b = await picture(), a = document.createElement('a');
        a.href = URL.createObjectURL(b); a.download = `${(M.name || 'round').replace(/[^\w-]+/g, '-')}-r${n}-${fmt(T).replace(':', 'm')}s.png`; a.click();
      } catch (e) { msg('No picture: ' + (e.message || e)); }
    };
    const discBtn = bar.querySelector('.rp-disc');
    if (discBtn) discBtn.onclick = async () => {
      pause(); discBtn.disabled = true; msg('posting…');
      try { await HK.toDiscord(n, await picture(), caption()); msg('Posted to Discord'); }
      catch (e) { msg('Discord: ' + (e.message || e)); }
      discBtn.disabled = false;
    };
    const stratBtn = bar.querySelector('.rp-strat');
    if (stratBtn) stratBtn.onclick = () => {
      pause(); msg('making the strat board…');
      HK.toStrat(n, moment()).then(url => msg('Open the strat board ↗', String(url || '')))
        .catch(e => msg('Not made: ' + (e.message || e)));
    };
    opts.querySelectorAll('input[type=checkbox]').forEach(cb => cb.onchange = () => { show[cb.dataset.o] = cb.checked; draw(); });
    root.tabIndex = 0;
    root.addEventListener('keydown', e => {
      if (e.target.closest && e.target.closest('input, textarea, select')) return;
      if (e.key === ' ') { e.preventDefault(); playing ? pause() : play(); }
      else if (e.key === 'ArrowRight') { pause(); seek(T + 1000); }
      else if (e.key === 'ArrowLeft') { pause(); seek(T - 1000); }
    });

    // ------------------------------------------------------------ zoom / pan / select
    const setView = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.w}`);
    function zoom(f, cx = view.x + view.w / 2, cy = view.y + view.w / 2) {
      const w = Math.max(180, Math.min(S, view.w * f));
      view = {x: Math.max(0, Math.min(S - w, cx - (cx - view.x) * w / view.w)),
              y: Math.max(0, Math.min(S - w, cy - (cy - view.y) * w / view.w)), w};
      setView();
    }
    const toSvg = (cx, cy) => { const r = svg.getBoundingClientRect(); return [view.x + (cx - r.left) / r.width * view.w, view.y + (cy - r.top) / r.height * view.w]; };
    // plain wheel scrolls the page; Ctrl / Cmd + wheel (or pinch on a touchpad) zooms
    svg.addEventListener('wheel', e => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault(); const [x, y] = toSvg(e.clientX, e.clientY); zoom(e.deltaY > 0 ? 1.18 : 1 / 1.18, x, y);
    }, {passive: false});
    let drag = null;
    svg.addEventListener('pointerdown', e => {
      if (!drawing) return;
      const [x, y] = toSvg(e.clientX, e.clientY);
      stroke = [[Math.round(x), Math.round(y)]]; pending.push(stroke);
      svg.setPointerCapture(e.pointerId); e.stopImmediatePropagation(); draw();
    });
    svg.addEventListener('pointermove', e => {
      if (!drawing || !stroke) return;
      const [x, y] = toSvg(e.clientX, e.clientY), l = stroke[stroke.length - 1];
      if (Math.hypot(l[0] - x, l[1] - y) > 5 && stroke.length < 300) { stroke.push([Math.round(x), Math.round(y)]); draw(); }
      e.stopImmediatePropagation();
    });
    svg.addEventListener('pointerup', e => {
      if (!drawing) return;
      if (stroke && stroke.length < 2) pending.pop();
      stroke = null; e.stopImmediatePropagation(); draw();
    });
    svg.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false}; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener('pointermove', e => {
      if (!drag) return;
      const r = svg.getBoundingClientRect(), dx = (e.clientX - drag.x) / r.width * view.w, dy = (e.clientY - drag.y) / r.height * view.w;
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) drag.moved = true;
      if (drag.moved && view.w < S) {
        view.x = Math.max(0, Math.min(S - view.w, drag.vx - dx)); view.y = Math.max(0, Math.min(S - view.w, drag.vy - dy)); setView();
      }
    });
    svg.addEventListener('pointerup', e => {
      if (drag && !drag.moved) {
        const tok = document.elementsFromPoint(e.clientX, e.clientY).map(x => x.closest && x.closest('.rp-tok')).find(Boolean);
        if (tok) { const id = tok.getAttribute('data-id'); selected.has(id) ? selected.delete(id) : selected.add(id); draw(); }
      }
      drag = null;
    });
    svg.addEventListener('dblclick', () => { view = {x: 0, y: 0, w: S}; setView(); });
    zoomBtns.onclick = e => {
      const z = e.target.dataset.z;
      if (z === 'in') zoom(1 / 1.35); else if (z === 'out') zoom(1.35);
      else if (z === 'fit') { view = {x: 0, y: 0, w: S}; setView(); }
      else if (z === 'full') { document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen && root.requestFullscreen(); }
    };

    box._destroy = () => { playing = false; if (document.fullscreenElement === root) document.exitFullscreen(); };
    box._redraw = () => { if (!playing) draw(); };      // the page got new notes (playing redraws anyway)
    draw();
  }

  window.nexusBuild = build;
  window.nexusInitReplays = scope => (scope || document).querySelectorAll('.replay').forEach(build);
})();
