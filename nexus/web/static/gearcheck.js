/* Practice › Mouse & monitor: the real DPI (counts over a measured distance), the polling rate (time between the
   mouse's reports), the screen's refresh rate (time between frames), worn buttons (two clicks for one press) and
   the Valorant numbers that follow. Everything is measured here in the browser; "Save" sends the results
   (POST …/trainer/setup). Pointer lock with unadjustedMovement gives the mouse's raw counts (Chrome, Edge, the
   Nexus app); without it Windows' pointer speed and acceleration would be in the numbers. */
(function () {
  'use strict';
  const C = window.NEXUS_GEAR;
  if (!C) return;
  const $ = id => document.getElementById(id);
  const median = a => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const nearest = (v, list) => list.reduce((b, x) => Math.abs(x - v) < Math.abs(b - v) ? x : b, list[0]);
  const res = {measured_dpi: C.setup.measured_dpi || null, polling_hz: C.setup.polling_hz || null,
               refresh_hz: C.setup.refresh_hz || null, raw: null};
  let lockFor = null;            // which pad has the pointer lock

  async function lock(el) {
    lockFor = el;
    try {
      const p = el.requestPointerLock({unadjustedMovement: true});
      res.raw = !!(p && p.then);
      await p;
    } catch (e) {
      res.raw = false;
      try { await el.requestPointerLock(); } catch (e2) {}
    }
    return document.pointerLockElement === el;
  }
  function unlock() { if (document.pointerLockElement) document.exitPointerLock(); }
  const rawNote = () => res.raw === false
    ? '<div class="warn" style="flex-basis:100%">This browser doesn\'t give raw mouse input: Windows\' pointer speed and "Enhance pointer precision" are in this number. Use Chrome, Edge or the Nexus app.</div>' : '';

  // ------------------------------------------------------------------ DPI
  const dpiPad = $('gc-dpi-pad'), dpiIn = $('gc-dpi'), cmIn = $('gc-cm');
  let dpi = null;                // {dx, dy} while measuring
  const tries = [];
  cmIn.addEventListener('input', () => { $('gc-cm-l').textContent = cmIn.value; });
  dpiPad.addEventListener('mousedown', async e => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (dpi && document.pointerLockElement === dpiPad) { stopDpi(); return; }
    if (!await lock(dpiPad)) return;
    dpi = {dx: 0, dy: 0};
    dpiPad.classList.add('live');
    $('gc-dpi-text').innerHTML = '<b class="big">0</b>counts · move exactly ' + (+cmIn.value || 10) + ' cm to the right, then click';
  });
  function stopDpi() {
    const cm = +cmIn.value || 10, d = dpi;
    dpi = null; unlock(); dpiPad.classList.remove('live');
    if (!d || Math.abs(d.dx) < 50) { $('gc-dpi-text').textContent = 'That was too short. Click to try again.'; return; }
    const cpi = Math.abs(d.dx) / (cm / 2.54), bent = Math.abs(d.dy) > Math.abs(d.dx) * 0.08;
    tries.push({cpi, bent});
    $('gc-dpi-text').textContent = bent ? 'That one wasn\'t straight (it went up or down too): try a straighter line. Click for another try.'
      : 'Got it. Click for another try: three or more give a good average.';
    showDpi();
  }
  function showDpi() {
    $('gc-dpi-tries').innerHTML = tries.map(t => `<li title="${t.bent ? 'not straight' : ''}">${Math.round(t.cpi)}${t.bent ? ' ⚠' : ''}</li>`).join('');
    const good = tries.filter(t => !t.bent).map(t => t.cpi), use = good.length ? good : tries.map(t => t.cpi);
    if (!use.length) return;
    const avg = use.reduce((a, b) => a + b, 0) / use.length, set = +dpiIn.value || 0;
    const spread = use.length > 1 ? (Math.max(...use) - Math.min(...use)) / avg : null;
    res.measured_dpi = Math.round(avg);
    const off = set ? (avg - set) / set : null, cls = off === null ? '' : Math.abs(off) < 0.03 ? 'ok' : Math.abs(off) < 0.08 ? 'warn' : 'bad';
    const dpr = window.devicePixelRatio || 1;
    const scaled = set && dpr !== 1 && Math.abs(avg / (set * dpr) - 1) < 0.03 || set && dpr !== 1 && Math.abs(avg * dpr / set - 1) < 0.03;
    const r = $('gc-dpi-res');
    r.hidden = false;
    r.innerHTML = `<div>Measured<b>${Math.round(avg)} DPI</b></div>`
      + (off !== null ? `<div>Compared to ${set}<b class="${cls}">${off >= 0 ? '+' : ''}${(off * 100).toFixed(1)}%</b></div>` : '')
      + `<div>Tries<b>${use.length}</b></div>` + (spread !== null ? `<div>Spread<b class="${spread < 0.04 ? 'ok' : 'warn'}">${(spread * 100).toFixed(1)}%</b></div>` : '')
      + rawNote()
      + (scaled ? `<div class="warn" style="flex-basis:100%">That's off by exactly your Windows display scaling (${Math.round(dpr * 100)}%): this browser scales the mouse's counts. Your mouse is most likely fine.</div>` : '');
    showValorant();
  }
  document.addEventListener('mousemove', e => {
    if (dpi && document.pointerLockElement === dpiPad) {
      dpi.dx += e.movementX; dpi.dy += e.movementY;
      const b = dpiPad.querySelector('b.big');
      if (b) b.textContent = Math.abs(dpi.dx);
    }
  });
  dpiIn.addEventListener('input', () => { if (tries.length) showDpi(); else showValorant(); });

  // ------------------------------------------------------------------ polling rate
  const hzPad = $('gc-hz-pad');
  let hz = null;                 // {times: [], start}
  const RATES = [125, 250, 500, 1000, 2000, 4000, 8000];
  function hzFrom(times) {
    const iv = [];
    for (let i = 1; i < times.length; i++) { const d = times[i] - times[i - 1]; if (d > 0 && d < 25) iv.push(d); }
    return iv.length > 20 ? 1000 / median(iv) : 0;
  }
  function onRaw(e) {
    if (!hz || document.pointerLockElement !== hzPad) return;
    if (e.type === 'pointermove' && e.getCoalescedEvents) for (const c of e.getCoalescedEvents()) hz.times.push(c.timeStamp);
    else hz.times.push(e.timeStamp);
    const now = performance.now();
    if (now - hz.shown > 200) {
      hz.shown = now;
      const live = hzFrom(hz.times.slice(-400));
      $('gc-hz-text').innerHTML = `<b class="big">${live ? Math.round(live) : '…'}</b>Hz · keep moving (${Math.max(0, Math.ceil(5 - (now - hz.start) / 1000))} s), click to stop`;
      if (now - hz.start > 5000) stopHz();
    }
  }
  const RAW_EVT = 'onpointerrawupdate' in window ? 'pointerrawupdate' : 'pointermove';
  document.addEventListener(RAW_EVT, onRaw);
  hzPad.addEventListener('mousedown', async e => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (hz && document.pointerLockElement === hzPad) { stopHz(); return; }
    if (!await lock(hzPad)) return;
    hz = {times: [], start: performance.now(), shown: 0};
    hzPad.classList.add('live');
    $('gc-hz-text').innerHTML = '<b class="big">…</b>Hz · move the mouse in circles';
  });
  function stopHz() {
    const h = hz;
    hz = null; unlock(); hzPad.classList.remove('live');
    const v = h ? hzFrom(h.times) : 0;
    if (!v) { $('gc-hz-text').textContent = 'Not enough movement. Click and move the mouse in fast circles.'; return; }
    const near = nearest(v, RATES), close = Math.abs(v - near) / near < 0.15;
    res.polling_hz = Math.round(close ? near : v);
    $('gc-hz-text').textContent = 'Click to measure again.';
    const r = $('gc-hz-res');
    r.hidden = false;
    r.innerHTML = `<div>Measured<b>${Math.round(v)} Hz</b></div><div>That's<b class="${near >= 1000 ? 'ok' : near >= 500 ? 'warn' : 'bad'}">${close ? near + ' Hz' : 'between rates'}</b></div>`
      + `<div>Reports<b>${h.times.length}</b></div>`
      + (near < 1000 ? '<div class="warn" style="flex-basis:100%">Under 1000 Hz: set the polling rate to 1000 Hz (or more) in your mouse\'s software, if it has that.</div>' : '')
      + (v > 1500 ? '<div style="flex-basis:100%">Over 1000 Hz a browser can miss reports: the mouse may well send more than this.</div>' : '')
      + (RAW_EVT === 'pointermove' ? '<div style="flex-basis:100%">This browser groups reports, so the number may be low. Chrome, Edge or the Nexus app measure it better.</div>' : '');
  }
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement) return;
    if (dpi) { dpi = null; dpiPad.classList.remove('live'); $('gc-dpi-text').textContent = 'Stopped. Click to try again.'; }
    if (hz) stopHz();
  });

  // ------------------------------------------------------------------ refresh rate and the moving square
  const SCREENS = [50, 60, 75, 90, 100, 120, 144, 165, 170, 180, 200, 240, 280, 300, 360, 390, 480, 500, 540];
  const strip = $('gc-strip'), ctx = strip.getContext('2d');
  let frames = [], measuring = true, lastT = 0, x = 0;
  function loop(t) {
    requestAnimationFrame(loop);
    const dt = lastT ? t - lastT : 0; lastT = t;
    if (measuring && dt) {
      frames.push(dt);
      if (frames.length >= 240 || frames.reduce((a, b) => a + b, 0) > 2500) { measuring = false; showFps(); }
    }
    const w = strip.clientWidth * devicePixelRatio, h = strip.clientHeight * devicePixelRatio;
    if (strip.width !== w || strip.height !== h) { strip.width = w; strip.height = h; }
    x = (x + dt / 1000 * w * 0.45) % (w + h);
    ctx.fillStyle = '#0b0f15'; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#263142'; for (let i = 0; i < w; i += 40 * devicePixelRatio) ctx.fillRect(i, 0, 1, h);
    ctx.fillStyle = '#f4b740'; ctx.fillRect(x - h, h * 0.2, h * 0.6, h * 0.6);
  }
  function showFps() {
    const m = median(frames), v = m ? 1000 / m : 0, near = nearest(v, SCREENS), drop = frames.filter(f => f > m * 1.6).length / frames.length;
    res.refresh_hz = Math.round(Math.abs(v - near) / near < 0.04 ? near : v);
    $('gc-fps-res').innerHTML = `<div>Measured<b>${v.toFixed(1)} Hz</b></div><div>That's a<b>${near} Hz screen</b></div>`
      + `<div>Late frames<b class="${drop < 0.02 ? 'ok' : drop < 0.08 ? 'warn' : 'bad'}">${(drop * 100).toFixed(1)}%</b></div>`
      + (near <= 75 ? '<div class="warn" style="flex-basis:100%">Only 60–75 Hz: if your monitor can do more, Windows or the cable is holding it back.</div>' : '');
  }
  $('gc-fps-again').addEventListener('click', () => { frames = []; measuring = true; $('gc-fps-res').innerHTML = '<div>Measuring…<b>–</b></div>'; });
  requestAnimationFrame(loop);

  // ------------------------------------------------------------------ buttons
  const NAMES = ['Left', 'Middle', 'Right', 'Back', 'Forward'], btnPad = $('gc-btn-pad');
  const btn = NAMES.map(() => ({n: 0, dbl: 0, up: 0, down: false}));
  let wheel = {up: 0, down: 0};
  function showBtns() {
    $('gc-btns').innerHTML = btn.map((b, i) => `<div class="${b.dbl ? 'flag' : ''} ${b.down ? 'down' : ''}">${NAMES[i]}<b>${b.n}</b>${b.dbl ? b.dbl + '× double' : ''}</div>`).join('');
    const bad = btn.map((b, i) => b.dbl ? NAMES[i] : null).filter(Boolean);
    $('gc-btn-res').innerHTML = `<div>Wheel<b>${wheel.up} up · ${wheel.down} down</b></div>`
      + (bad.length ? `<div class="bad" style="flex-basis:100%">${bad.join(', ')}: registered two clicks within 60 ms, faster than a finger clicks. If that happens again, the switch is wearing out.</div>`
        : (btn.some(b => b.n) ? '<div class="ok" style="flex-basis:100%">No double clicks so far.</div>' : ''));
  }
  btnPad.addEventListener('mousedown', e => {
    const b = btn[e.button]; if (!b) return;
    e.preventDefault();
    const now = performance.now();
    if (b.up && now - b.up < 60) b.dbl++;
    b.n++; b.down = true; showBtns();
  });
  btnPad.addEventListener('mouseup', e => { const b = btn[e.button]; if (!b) return; e.preventDefault(); b.up = performance.now(); b.down = false; showBtns(); });
  btnPad.addEventListener('auxclick', e => e.preventDefault());
  btnPad.addEventListener('contextmenu', e => e.preventDefault());
  btnPad.addEventListener('wheel', e => { e.preventDefault(); if (e.deltaY < 0) wheel.up++; else if (e.deltaY > 0) wheel.down++; showBtns(); }, {passive: false});
  showBtns();

  // ------------------------------------------------------------------ Valorant numbers and saving
  const sensIn = $('gc-sens');
  function showValorant() {
    const s = +sensIn.value, set = +dpiIn.value, real = res.measured_dpi;
    const cm = d => (360 / (C.yaw * s) / d * 2.54).toFixed(1);
    let h = '';
    if (s > 0 && set > 0) h += `<div>eDPI<b>${Math.round(s * set)}</b></div><div>cm per 360° (set DPI)<b>${cm(set)}</b></div>`;
    if (s > 0 && real) h += `<div>cm per 360° (measured)<b>${cm(real)}</b></div>`;
    $('gc-val-res').innerHTML = h || '<div>Enter your sensitivity.</div>';
  }
  sensIn.addEventListener('input', showValorant);
  showValorant();
  const save = $('gc-save');
  if (save) save.addEventListener('click', async () => {
    const body = {sens: +sensIn.value, dpi: +dpiIn.value};
    for (const k of ['measured_dpi', 'polling_hz', 'refresh_hz']) if (res[k]) body[k] = res[k];
    if (res.raw !== null) body.raw = res.raw;
    try {
      const r = await fetch(C.url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || r.status);
      $('gc-saved').textContent = `Saved: ${d.setup.measured_dpi || '–'} DPI measured, ${d.setup.polling_hz || '–'} Hz polling, ${d.setup.refresh_hz || '–'} Hz screen.`;
      window.nexusToast && window.nexusToast('Saved.', 'ok');
    } catch (e) { window.nexusToast && window.nexusToast('Not saved: ' + e.message, 'error'); }
  });
})();
