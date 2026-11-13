// Practice › Callouts: the minimap quiz. Learn: every callout on the map. Find it: a callout's name, click where it
// is (right when the nearest callout to your click is that one). Name it: a spot lights up, pick its name from four.
// The server sends the maps' callouts (u, v on the minimap, 0..1) and how often each one should come up (weights:
// more often the ones you get wrong); it keeps the results (stats/callouts.py).
(function () {
  'use strict';
  const C = window.NEXUS_CALLOUTS;
  if (!C) return;
  const $ = id => document.getElementById(id);
  const T = s => (window.vcT ? window.vcT(s) : s);
  const NS = 'http://www.w3.org/2000/svg', S = 1000, NEAR = 0.035;
  const svg = $('co-svg'), board = $('co-board'), play = $('co-play'), opts = $('co-opts'), res = $('co-res');
  const startBtn = $('co-start'), bar = $('co-bar');
  const M = C.maps[C.map];
  if (!M) return;
  let mode = 'learn', q = null;          // q: the running round

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function weak(label) { return (M.weak || []).includes(label); }
  // draw: dots for every callout; marks: {label: class}; labels: which names to write; extra: drawn after
  function draw(marks = {}, labels = null, extra = null) {
    svg.textContent = '';
    for (const pt of M.points) {
      const cls = marks[pt.label] || '';
      const c = el('circle', {cx: pt.u * S, cy: pt.v * S, r: cls ? 9 : 6, class: 'co-dot ' + cls}, svg);
      if (mode === 'learn') {
        if (weak(pt.label)) c.classList.add('weak');
        el('title', {}, c).textContent = pt.label;
      }
    }
    if (extra) extra();
    for (const pt of M.points) {
      if (labels && !labels.has(pt.label)) continue;
      const t = el('text', {x: pt.u * S, y: pt.v * S - 13, 'text-anchor': 'middle', class: 'co-lbl' + (labels ? '' : ' small')}, svg);
      t.textContent = pt.label;
    }
  }
  function learn() {
    mode = 'learn'; q = null;
    board.classList.remove('ask');
    opts.hidden = true; res.hidden = true; bar.hidden = true; startBtn.hidden = true;
    play.innerHTML = `<p class="co-sub">${esc(T('Every callout of this map. Red rings: the ones you get wrong most.'))}</p>`;
    draw({}, null);
  }
  function pick(n) {                     // n callouts, weighted, no repeats
    const pool = M.points.map(p => ({p, w: M.weights[p.label] || 1})), out = [];
    while (out.length < n && pool.length) {
      let r = Math.random() * pool.reduce((a, x) => a + x.w, 0), i = 0;
      while (i < pool.length - 1 && (r -= pool[i].w) > 0) i++;
      out.push(pool.splice(i, 1)[0].p);
    }
    return out;
  }
  function choices(target) {             // the answer and three others, close by or in the same area first
    const d = p => Math.hypot(p.u - target.u, p.v - target.v) - (p.area === target.area ? 0.15 : 0);
    const near = M.points.filter(p => p !== target).sort((a, b) => d(a) - d(b)).slice(0, 6);
    const three = [];
    while (three.length < 3 && near.length) three.push(near.splice(Math.floor(Math.random() * Math.min(near.length, 4)), 1)[0]);
    const all = [target, ...three];
    for (let i = all.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [all[i], all[j]] = [all[j], all[i]]; }
    return all;
  }
  function ready(m) {
    mode = m; q = null;
    board.classList.remove('ask');
    opts.hidden = true; res.hidden = true; bar.hidden = true; startBtn.hidden = false;
    play.innerHTML = `<p class="co-sub">${esc(m === 'find'
      ? T('A callout appears: click where it is on the map. Faster answers score more.')
      : T('A spot lights up: pick its name. Keys 1–4 work too. Faster answers score more.'))}</p>`;
    draw({}, new Set());
    startBtn.focus();
  }
  function start() {
    q = {list: pick(C.questions), i: -1, asked: [], busy: false};
    startBtn.hidden = true; res.hidden = true; bar.hidden = false;
    next();
  }
  function next() {
    q.i++;
    bar.firstElementChild.style.width = (100 * q.i / q.list.length) + '%';
    if (q.i >= q.list.length) { finish(); return; }
    const t = q.list[q.i];
    q.t0 = performance.now(); q.busy = false;
    if (mode === 'find') {
      board.classList.add('ask');
      play.innerHTML = `<div class="co-sub">${q.i + 1} / ${q.list.length} · ${esc(T('Where is'))}</div><p class="co-q" translate="no">${esc(t.label)}</p>`;
      draw({}, new Set());
    } else {
      board.classList.remove('ask');
      play.innerHTML = `<div class="co-sub">${q.i + 1} / ${q.list.length} · ${esc(T('What is this spot called?'))}</div>`;
      draw({[t.label]: 'hot'}, new Set(), () => el('circle', {cx: t.u * S, cy: t.v * S, r: 9, class: 'co-ring'}, svg));
      q.opts = choices(t);
      opts.innerHTML = '';
      q.opts.forEach((o, k) => {
        const b = document.createElement('button');
        b.type = 'button'; b.innerHTML = `<kbd>${k + 1}</kbd><span translate="no">${esc(o.label)}</span>`;
        b.addEventListener('click', () => answerName(k));
        opts.appendChild(b);
      });
      opts.hidden = false;
    }
  }
  function record(ok) {
    const t = q.list[q.i];
    q.asked.push({label: t.label, ok, ms: Math.round(performance.now() - q.t0)});
    q.busy = true;
    setTimeout(next, ok ? 750 : 1700);
  }
  function answerName(k) {
    if (!q || q.busy || mode !== 'name') return;
    const t = q.list[q.i], ok = q.opts[k] === t;
    [...opts.children].forEach((b, j) => { if (q.opts[j] === t) b.classList.add('ok'); else if (j === k) b.classList.add('bad'); });
    draw({[t.label]: 'ok'}, new Set([t.label]));
    record(ok);
  }
  function answerFind(u, v) {
    if (!q || q.busy || mode !== 'find') return;
    const t = q.list[q.i];
    let best = null, bd = Infinity;
    for (const p of M.points) { const d = Math.hypot(p.u - u, p.v - v); if (d < bd) { bd = d; best = p; } }
    const ok = best === t || Math.hypot(t.u - u, t.v - v) < NEAR;
    const marks = {[t.label]: 'ok'}, show = new Set([t.label]);
    if (!ok && best) { marks[best.label] = 'bad'; show.add(best.label); }
    draw(marks, show, () => {
      if (!ok) el('line', {x1: u * S, y1: v * S, x2: t.u * S, y2: t.v * S, class: 'co-line'}, svg);
      el('circle', {cx: u * S, cy: v * S, r: 4, fill: ok ? 'var(--win)' : 'var(--red)'}, svg);
    });
    record(ok);
  }
  async function finish() {
    board.classList.remove('ask'); opts.hidden = true; bar.hidden = true;
    const right = q.asked.filter(a => a.ok).length;
    const score = q.asked.reduce((s, a) => s + (a.ok ? 100 + Math.max(0, 50 - Math.floor(a.ms / 100)) : 0), 0);
    const times = q.asked.filter(a => a.ok).map(a => a.ms);
    const avg = times.length ? Math.round(times.reduce((a, b) => a + b, 0) / times.length) : null;
    const wrong = q.asked.filter(a => !a.ok).map(a => a.label);
    play.innerHTML = '';
    res.innerHTML = `<div class="co-big">${score}</div><div class="co-sub" id="co-best"></div>
      <dl><div><dt>${esc(T('Correct'))}</dt><dd>${right}/${q.asked.length}</dd></div>
      <div><dt>${esc(T('Avg time'))}</dt><dd>${avg !== null ? (avg / 1000).toFixed(1) + ' s' : '–'}</dd></div>
      <div><dt>${esc(T('Wrong'))}</dt><dd>${wrong.length}</dd></div></dl>
      ${wrong.length ? `<div class="co-sub">${esc(T('Look at these again:'))}</div><ul class="co-wrong">${wrong.map(w => `<li translate="no">${esc(w)}</li>`).join('')}</ul>` : ''}`;
    res.hidden = false;
    draw(Object.fromEntries(wrong.map(w => [w, 'bad'])), new Set(wrong));
    startBtn.hidden = false; startBtn.textContent = T('Again');
    const best = $('co-best');
    if (!C.can_save) { best.textContent = T('Not saved (only the player or their owner can).'); return; }
    try {
      const r = await fetch(C.save, {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
                                     body: JSON.stringify({map: C.map, mode, asked: q.asked})});
      const d = await r.json();
      if (!r.ok) { best.textContent = d.error || T('Not saved.'); return; }
      M.weights = d.weights || M.weights; M.weak = d.weak || M.weak;
      best.textContent = d.is_best ? (d.best_before === null ? T('Your first score here.') : T(`New best (before: ${d.best_before}).`))
                                   : T(`Callouts you know on this map: ${d.known} of ${d.n}.`);
    } catch (e) { best.textContent = T('Not saved.'); }
  }

  board.addEventListener('click', e => {
    if (mode !== 'find' || !q) return;
    const r = svg.getBoundingClientRect(), side = Math.min(r.width, r.height);
    const u = (e.clientX - r.left - (r.width - side) / 2) / side, v = (e.clientY - r.top - (r.height - side) / 2) / side;
    answerFind(u, v);
  });
  document.addEventListener('keydown', e => {
    if (mode === 'name' && q && /^[1-4]$/.test(e.key)) answerName(+e.key - 1);
    else if (e.key === 'Enter' && !startBtn.hidden && mode !== 'learn' && document.activeElement !== startBtn) start();
  });
  $('co-modes').addEventListener('click', e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    $('co-modes').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    startBtn.textContent = T(`Start · ${C.questions} questions`);
    if (b.dataset.m === 'learn') learn(); else ready(b.dataset.m);
  });
  startBtn.addEventListener('click', start);
  learn();
  window.nexusCallouts = {state: () => ({mode, q}), find: answerFind, name: answerName, start, points: () => M.points};   // for tests
})();
