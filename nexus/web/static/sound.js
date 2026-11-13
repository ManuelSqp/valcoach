// Practice › Sound: a sound plays once from somewhere around you (WebAudio, HRTF panner: needs headphones), you
// click on the radar where it came from. Direction: just that. Distance: also near or far. Height: also above, same
// floor or below. The sounds are made here (noise and tones shaped like footsteps, a reload, a beep), not Valorant's.
// Angles: 0 = in front (top of the radar), clockwise in degrees. Results go to stats/sound.py.
(function () {
  'use strict';
  const C = window.NEXUS_SOUND;
  if (!C) return;
  const $ = id => document.getElementById(id);
  const T = s => (window.vcT ? window.vcT(s) : s);
  const NS = 'http://www.w3.org/2000/svg', R = 400;
  const svg = $('so-svg'), radar = $('so-radar'), play = $('so-play'), res = $('so-res'), bar = $('so-bar');
  const startBtn = $('so-start'), distBox = $('so-dist'), heightBox = $('so-height');
  let mode = 'dir', q = null, ctx = null, noise = null;
  const KINDS = ['steps', 'steps', 'reload', 'beep'];        // footsteps most of the time, like in a game

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  const wrap = a => ((a + 180) % 360 + 360) % 360 - 180;
  const rad = a => a * Math.PI / 180;
  const at = (a, r) => [Math.sin(rad(a)) * r, -Math.cos(rad(a)) * r];
  // the radar: rings, ticks, you in the middle looking up
  function base() {
    svg.textContent = '';
    el('circle', {r: R, class: 'so-ring'}, svg);
    el('circle', {r: R * 0.45, class: 'so-ring mid'}, svg);
    for (let a = 0; a < 360; a += 45) { const [x1, y1] = at(a, R - 22), [x2, y2] = at(a, R); el('line', {x1, y1, x2, y2, class: 'so-tick'}, svg); }
    el('path', {d: `M0,0 L${at(-35, 170).join(',')} A170,170 0 0 1 ${at(35, 170).join(',')} Z`, class: 'so-look'}, svg);
    el('circle', {r: 16, class: 'so-me'}, svg);
    const t = el('text', {x: 0, y: -R + 50, 'text-anchor': 'middle', class: 'so-txt'}, svg); t.textContent = T('in front');
  }
  // ---- sounds
  function audio() {
    if (!ctx) {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const d = noise.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    if (ctx.state === 'suspended') ctx.resume();
    return ctx;
  }
  function panner(a, r, y) {
    const p = ctx.createPanner();
    Object.assign(p, {panningModel: 'HRTF', distanceModel: 'inverse', refDistance: 1.5, rolloffFactor: 1, maxDistance: 100});
    const x = Math.sin(rad(a)) * r, z = -Math.cos(rad(a)) * r;
    if (p.positionX) { p.positionX.value = x; p.positionY.value = y; p.positionZ.value = z; } else p.setPosition(x, y, z);
    p.connect(ctx.destination);
    return p;
  }
  function burst(out, t, f, q, dur, gain, type = 'bandpass') {
    const s = ctx.createBufferSource(), fl = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noise; fl.type = type; fl.frequency.value = f; fl.Q.value = q;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.004); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(fl).connect(g).connect(out); s.start(t, Math.random() * 0.5); s.stop(t + dur + 0.02);
  }
  function tone(out, t, f, dur, gain, type = 'sine') {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.005); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(out); o.start(t); o.stop(t + dur + 0.02);
  }
  function sound(kind, a, r, y) {             // -> seconds it lasts
    audio();
    const out = panner(a, r, y), t = ctx.currentTime + 0.05;
    if (kind === 'steps') {
      const f = 350 + Math.random() * 350;
      for (let i = 0; i < 4; i++) { const ti = t + i * 0.34; burst(out, ti, f, 1.1, 0.11, 1.4); burst(out, ti, 3200, 0.8, 0.05, 0.35, 'highpass'); tone(out, ti, 80, 0.08, 0.6); }
      return 1.5;
    }
    if (kind === 'reload') {
      burst(out, t, 2600, 1.5, 0.04, 1.2, 'highpass'); tone(out, t + 0.02, 1900, 0.05, 0.25, 'triangle');
      burst(out, t + 0.42, 1800, 2, 0.06, 1.2); burst(out, t + 0.5, 3500, 1, 0.04, 0.9, 'highpass');
      return 0.8;
    }
    for (let i = 0; i < 3; i++) tone(out, t + i * 0.28, 1150, 0.11, 0.5, 'square');          // a beep, three times
    return 1.0;
  }
  // ---- a round
  function ready(m) {
    mode = m; q = null; radar.classList.remove('ask');
    distBox.hidden = true; heightBox.hidden = true; res.hidden = true; bar.hidden = true; startBtn.hidden = false;
    play.innerHTML = `<p class="so-sub">${esc(m === 'dir' ? T('Each sound plays once from somewhere around you: click on the circle where it came from.')
      : m === 'dist' ? T('Click where it came from, then say if it was near or far.')
      : T('Click where it came from, then say if it was above you, on your floor or below.'))}</p>`;
    base();
  }
  function start() {
    audio();
    q = {i: -1, list: [], sounds: []};
    for (let i = 0; i < C.sounds; i++) {
      const s = {a: Math.round(Math.random() * 359), kind: KINDS[Math.floor(Math.random() * KINDS.length)]};
      if (mode === 'dist') { s.dist = Math.random() < 0.5 ? 'near' : 'far'; s.r = s.dist === 'near' ? 2.5 + Math.random() * 2 : 11 + Math.random() * 6; }
      else s.r = 3 + Math.random() * 7;
      s.h = mode === 'height' ? ['up', 'level', 'down'][Math.floor(Math.random() * 3)] : 'level';
      s.y = s.h === 'up' ? 3.2 : s.h === 'down' ? -3.2 : 0;
      q.list.push(s);
    }
    startBtn.hidden = true; res.hidden = true; bar.hidden = false;
    next();
  }
  function next() {
    q.i++; q.cur = null;
    bar.firstElementChild.style.width = (100 * q.i / q.list.length) + '%';
    distBox.hidden = true; heightBox.hidden = true;
    if (q.i >= q.list.length) { finish(); return; }
    base();
    play.innerHTML = `<div class="so-sub">${q.i + 1} / ${q.list.length}</div><p class="so-q">${esc(T('Listen…'))}</p>`;
    radar.classList.remove('ask');
    setTimeout(() => {
      if (!q) return;
      const s = q.list[q.i];
      el('circle', {r: 30, class: 'so-wave'}, svg);
      try { sound(s.kind, s.a, s.r, s.y); } catch (e) {}
      q.t0 = performance.now(); q.cur = {a: s.a, kind: s.kind, dist: s.dist, h: s.h};
      radar.classList.add('ask');
      play.innerHTML = `<div class="so-sub">${q.i + 1} / ${q.list.length}</div><p class="so-q">${esc(T('Where did it come from?'))}</p>`;
    }, 700);
  }
  function answer(guess) {
    if (!q || !q.cur || q.cur.guess !== undefined) return;
    const c = q.cur;
    c.guess = ((Math.round(guess) % 360) + 360) % 360; c.ms = Math.round(performance.now() - q.t0);
    radar.classList.remove('ask');
    const err = Math.abs(wrap(c.guess - c.a));
    base();
    el('line', {x1: 0, y1: 0, x2: at(c.a, R - 10)[0], y2: at(c.a, R - 10)[1], class: 'so-ok'}, svg);
    if (err > 4) el('line', {x1: 0, y1: 0, x2: at(c.guess, R - 10)[0], y2: at(c.guess, R - 10)[1], class: 'so-bad'}, svg);
    play.innerHTML = `<div class="so-sub">${q.i + 1} / ${q.list.length}</div><p class="so-q">${esc(err <= 15 ? T('Spot on') : T(`Off by ${Math.round(err)}°`))}</p>`;
    if (mode === 'dist') { distBox.hidden = false; return; }
    if (mode === 'height') { heightBox.hidden = false; return; }
    done();
  }
  function pick(v) {
    if (!q || !q.cur || q.cur.guess === undefined) return;
    const c = q.cur;
    if (mode === 'dist' && !c.dist_guess) c.dist_guess = v;
    else if (mode === 'height' && !c.h_guess) c.h_guess = v;
    else return;
    const right = mode === 'dist' ? c.dist === v : c.h === v;
    const name = {near: T('near'), far: T('far'), up: T('above'), level: T('on your floor'), down: T('below')};
    play.insertAdjacentHTML('beforeend', `<p class="so-sub">${esc((right ? T('Correct:') : T('No:')) + ' ')}${esc(name[mode === 'dist' ? c.dist : c.h])}</p>`);
    done();
  }
  function done() {
    const c = q.cur;
    q.sounds.push({a: c.a, guess: c.guess, kind: c.kind, ms: c.ms, dist: c.dist, dist_guess: c.dist_guess, h: c.h, h_guess: c.h_guess});
    q.cur = Object.assign(c, {done: true});
    setTimeout(next, 1300);
  }
  async function finish() {
    radar.classList.remove('ask'); bar.hidden = true;
    const errs = q.sounds.map(s => Math.abs(wrap(s.guess - s.a)));
    const avg = Math.round(errs.reduce((a, b) => a + b, 0) / errs.length);
    const fb = q.sounds.filter((s, i) => errs[i] > 90 && Math.abs(wrap(s.guess - (180 - s.a))) <= 30).length;
    const extra = mode === 'dist' ? q.sounds.filter(s => s.dist === s.dist_guess).length : mode === 'height' ? q.sounds.filter(s => s.h === s.h_guess).length : null;
    const score = Math.round(q.sounds.reduce((t, s, i) => t + Math.max(0, 100 - 1.5 * errs[i]) + (mode === 'dist' ? (s.dist === s.dist_guess ? 50 : 0) : mode === 'height' ? (s.h === s.h_guess ? 50 : 0) : 0), 0));
    base();
    for (const s of q.sounds) {                         // every sound: where it was (green) and where you clicked
      el('circle', {cx: at(s.a, R - 30)[0], cy: at(s.a, R - 30)[1], r: 10, fill: 'var(--win)'}, svg);
      el('circle', {cx: at(s.guess, R - 70)[0], cy: at(s.guess, R - 70)[1], r: 8, fill: 'var(--red)', opacity: 0.8}, svg);
    }
    play.innerHTML = '';
    res.innerHTML = `<div class="so-big">${score}</div><div class="so-sub" id="so-best"></div>
      <dl><div><dt>${esc(T('Off by'))}</dt><dd>${avg}°</dd></div>
      <div><dt>${esc(T('Front/back mixed up'))}</dt><dd>${fb}</dd></div>
      <div><dt>${esc(mode === 'dist' ? T('Near/far right') : mode === 'height' ? T('Height right') : T('Within 15°'))}</dt>
        <dd>${extra !== null ? extra : errs.filter(e => e <= 15).length}/${q.sounds.length}</dd></div></dl>`;
    res.hidden = false; startBtn.hidden = false; startBtn.textContent = T('Again');
    const best = $('so-best');
    if (!C.can_save) { best.textContent = T('Not saved (only the player or their owner can).'); return; }
    try {
      const r = await fetch(C.save, {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
                                     body: JSON.stringify({mode, sounds: q.sounds})});
      const d = await r.json();
      if (!r.ok) { best.textContent = d.error || T('Not saved.'); return; }
      best.textContent = d.is_best ? (d.best_before === null ? T('Your first score here.') : T(`New best (before: ${d.best_before}).`))
                                   : (d.worst ? T(`Hardest for you so far: ${d.worst}.`) : T('Saved.'));
    } catch (e) { best.textContent = T('Not saved.'); }
  }

  radar.addEventListener('click', e => {
    if (!q || !q.cur || q.cur.guess !== undefined) return;
    const r = radar.getBoundingClientRect(), x = e.clientX - (r.left + r.width / 2), y = e.clientY - (r.top + r.height / 2);
    answer(Math.atan2(x, -y) * 180 / Math.PI);
  });
  distBox.addEventListener('click', e => { const b = e.target.closest('button[data-v]'); if (b) pick(b.dataset.v); });
  heightBox.addEventListener('click', e => { const b = e.target.closest('button[data-v]'); if (b) pick(b.dataset.v); });
  $('so-modes').addEventListener('click', e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    $('so-modes').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    startBtn.textContent = T(`Start · ${C.sounds} sounds`);
    ready(b.dataset.m);
  });
  startBtn.addEventListener('click', start);
  $('so-test').addEventListener('click', () => {        // left, then right: are the headphones the right way round?
    try { sound('steps', 270, 3, 0); setTimeout(() => sound('steps', 90, 3, 0), 1700); } catch (e) {}
    play.innerHTML = `<p class="so-sub">${esc(T('Footsteps on your left, then on your right. If it\'s the other way round, your headphones are on backwards.'))}</p>`;
  });
  base();
  window.nexusSound = {state: () => ({mode, q}), start, answer, pick, ready};   // for tests
})();
