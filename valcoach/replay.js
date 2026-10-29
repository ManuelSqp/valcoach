// valcoach round replay: continuous playback on the minimap.
// Data per round (RD.rounds[n]): events (kills/plants/defuses with snapshots), tracks per player
// ([t, u, v, kind] with kind 1 = known position, 0 = estimated route, 2 = spawn), roster, end (ms),
// measured (ids tracked on the VOD minimap) and seen ([t, u, v] enemy icons spotted on the minimap).
(function () {
  const NS = 'http://www.w3.org/2000/svg', S = 1000;
  const COL = {us: '#2dd4bf', them: '#ff4655', you: '#f6d24a', better: '#f2b84b', plant: '#ff4655', defuse: '#2dd4bf'};
  const KNOWN_MS = 1200;          // within this time of a known position the icon is drawn solid
  const CONE_MS = 1500;           // view cones are only shown close to a snapshot
  const TRAIL_MS = 6000;
  const KILL_FLASH_MS = 2000;
  const SEEN_MS = 900;            // a spotted enemy icon stays visible this long

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
       ${vodStart != null ? '<button class="rp-vod" title="Show this moment in the VOD">🎬</button>' : ''}`);
    const opts = h('div', {class: 'rp-opts'},
      `<label><input type="checkbox" data-o="names" checked> names</label>
       <label><input type="checkbox" data-o="callouts" checked> callouts</label>
       <label><input type="checkbox" data-o="trails" checked> trails</label>
       ${R.view ? '<label><input type="checkbox" data-o="cones" checked> view cones</label>' : ''}
       ${(R.seen || []).length ? '<label><input type="checkbox" data-o="seen" checked> spotted enemies</label>' : ''}
       <span class="rp-note">solid = known position (kills${(R.measured || []).length ? ', your minimap' : ''}) · faded = estimated ${R.routes ? '(walkable route at running speed)' : '(straight line)'}${(R.seen || []).length ? ' · red rings = enemies seen on your minimap' : ''} · click a player to show their route · zoom: + / − or Ctrl + wheel</span>`);
    main.append(stage, bar, opts);
    if (B) main.appendChild(h('div', {class: 'rp-better'}, `<b>Better position ${esc(B.time)}: ${esc(B.callout)}</b> — ${esc(B.why)}`));
    const side = h('aside', {class: 'rp-side'});
    const rosterEl = h('div', {class: 'rp-roster'});
    const feedEl = h('div', {class: 'rp-feed'});
    const colA = h('div', {class: 'rp-col'}), colB = h('div', {class: 'rp-col'});
    colA.append(h('div', {class: 'rp-h'}, 'Players'), rosterEl);
    colB.append(h('div', {class: 'rp-h'}, 'Round events'), feedEl);
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
    const show = {names: true, callouts: true, trails: true, cones: !!R.view, seen: true};
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
        `${avatar(id)}<span class="rp-nm">${esc(who(id).you ? 'You' : who(id).name)}<small>${esc(who(id).agent)}${measured.has(id) ? ' · tracked on video' : ''}</small></span><span class="rp-st"></span>`);
      r.onclick = () => { selected.has(id) ? selected.delete(id) : selected.add(id); draw(); };
      rosterEl.appendChild(r); rows[id] = r;
    }
    const feedRows = [];
    for (const e of R.events) {
      let txt;
      if (e.kind === 'kill') {
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
      tk.style.left = (100 * e.t / R.end) + '%'; tk.style.background = c;
      ticks.appendChild(tk);
    }

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
      // side panel state
      for (const id of ids) {
        const tr = R.tracks[id], dead = tr && tr.death != null && T >= tr.death;
        rows[id].classList.toggle('dead', !!dead);
        rows[id].classList.toggle('sel', selected.has(id));
        rows[id].querySelector('.rp-st').textContent = dead ? `✕ ${fmt(tr.death)}` : '';
      }
      let cur = null;
      for (const [e, r] of feedRows) { r.classList.toggle('past', e.t <= T); if (e.t <= T && T - e.t < 2500) cur = r; }
      for (const [, r] of feedRows) r.classList.toggle('now', r === cur);
      bar.querySelector('.rp-time').textContent = `${fmt(T)} / ${fmt(R.end)}`;
      bar.querySelector('input').value = T;
    }

    // ------------------------------------------------------------ playback
    const playBtn = bar.querySelector('.rp-play');
    function frame(ts) {
      if (!playing) return;
      if (last !== null) T += (ts - last) * speed;
      last = ts;
      if (T >= R.end) { T = R.end; pause(); }
      draw();
      if (playing) requestAnimationFrame(frame);
    }
    function play() { if (T >= R.end) T = 0; playing = true; last = null; playBtn.textContent = '❚❚'; requestAnimationFrame(frame); }
    function pause() { playing = false; playBtn.textContent = '▶'; }
    function seek(t) { T = Math.max(0, Math.min(R.end, t)); draw(); }
    playBtn.onclick = () => playing ? pause() : play();
    bar.querySelector('input').oninput = ev => { pause(); seek(+ev.target.value); };
    bar.querySelector('.rp-speed').onchange = ev => { speed = +ev.target.value; };
    const vodBtn = bar.querySelector('.rp-vod');
    if (vodBtn) vodBtn.onclick = () => { pause(); if (window.seek) window.seek(vodStart + T / 1000); };
    opts.querySelectorAll('input[type=checkbox]').forEach(cb => cb.onchange = () => { show[cb.dataset.o] = cb.checked; draw(); });
    root.tabIndex = 0;
    root.addEventListener('keydown', e => {
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
    draw();
  }

  window.valcoachBuild = build;
  window.valcoachInitReplays = scope => (scope || document).querySelectorAll('.replay').forEach(build);
})();
