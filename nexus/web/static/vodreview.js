// VOD review: a match recording with the team's comments. Pause, draw on the frame (pen, arrow, circle), comment
// at that moment; a comment's drawing shows from its time for a few seconds. Points are stored relative to the video
// picture (0..1), so drawings sit on the same spot at any window size. Data: stats/vodreview.py, web/vodreview.py.
(function () {
  'use strict';
  const B = window.NEXUS_VR;
  if (!B) return;
  const $ = id => document.getElementById(id);
  const T = s => (window.vcT ? window.vcT(s) : s);
  const video = $('vr-video'), canvas = $('vr-canvas'), stage = $('vr-stage'), tl = $('vr-tl'), list = $('vr-notes');
  const ctx = canvas.getContext('2d');
  const SHOW = 3;                         // seconds a comment's drawing stays on after its time
  let notes = B.notes || [], tool = 'pen', color = B.colors[0], strokes = [], cur = null, active = null;

  const fmt = t => { t = Math.max(0, t || 0); const m = Math.floor(t / 60), s = Math.floor(t % 60); return `${m}:${String(s).padStart(2, '0')}`; };
  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  // where the picture is inside the stage (object-fit: contain), in canvas pixels
  function box() {
    const W = canvas.width, H = canvas.height, vw = video.videoWidth || 16, vh = video.videoHeight || 9;
    const s = Math.min(W / vw, H / vh), w = vw * s, h = vh * s;
    return {x: (W - w) / 2, y: (H - h) / 2, w, h};
  }
  function size() {
    const r = stage.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
    paint();
  }
  function toPx(p) { const b = box(); return [b.x + p[0] * b.w, b.y + p[1] * b.h]; }
  function fromEvent(e) {
    const r = canvas.getBoundingClientRect(), dpr = canvas.width / r.width, b = box();
    return [+(((e.clientX - r.left) * dpr - b.x) / b.w).toFixed(4), +(((e.clientY - r.top) * dpr - b.y) / b.h).toFixed(4)];
  }
  function drawStroke(s, alpha = 1) {
    const pts = s.p.map(toPx), lw = Math.max(3, canvas.width / 320);
    ctx.save(); ctx.globalAlpha = alpha; ctx.strokeStyle = s.c; ctx.fillStyle = s.c; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.shadowColor = 'rgba(0,0,0,.7)'; ctx.shadowBlur = 4;
    if (s.k === 'circle' && pts.length >= 2) {
      const [a, b] = [pts[0], pts[pts.length - 1]];
      ctx.beginPath(); ctx.arc(a[0], a[1], Math.hypot(b[0] - a[0], b[1] - a[1]), 0, 2 * Math.PI); ctx.stroke();
    } else if (s.k === 'arrow' && pts.length >= 2) {
      const [a, b] = [pts[0], pts[pts.length - 1]], ang = Math.atan2(b[1] - a[1], b[0] - a[0]), h = lw * 4.5;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(b[0], b[1]);
      ctx.lineTo(b[0] - h * Math.cos(ang - 0.45), b[1] - h * Math.sin(ang - 0.45));
      ctx.lineTo(b[0] - h * Math.cos(ang + 0.45), b[1] - h * Math.sin(ang + 0.45)); ctx.closePath(); ctx.fill();
    } else {
      ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))); ctx.stroke();
    }
    ctx.restore();
  }
  function paint() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const t = video.currentTime;
    for (const n of notes) {                 // the team's drawings at their moment
      if (n.strokes && n.strokes.length && t >= n.t - 0.05 && t <= n.t + SHOW) for (const s of n.strokes) drawStroke(s, n === active ? 1 : 0.85);
    }
    for (const s of strokes) drawStroke(s);
    if (cur) drawStroke(cur);
  }
  // ---- timeline: rounds and comments
  function timeline() {
    const d = video.duration || 0;
    tl.querySelectorAll('.rd,.nt').forEach(x => x.remove());
    if (!d) return;
    for (const r of B.rounds) {
      const e = document.createElement('div'); e.className = 'rd ' + (r.won ? 'w' : 'l');
      e.style.left = (100 * r.t / d) + '%'; e.textContent = r.n; tl.appendChild(e);
    }
    for (const n of notes) { const e = document.createElement('div'); e.className = 'nt'; e.style.left = (100 * n.t / d) + '%'; tl.appendChild(e); }
  }
  function tick() {
    const d = video.duration || 0, t = video.currentTime;
    $('vr-time').textContent = `${fmt(t)} / ${fmt(d)}`;
    $('vr-at').textContent = fmt(t);
    $('vr-pos').style.left = d ? (100 * t / d) + '%' : '0';
    $('vr-play').textContent = video.paused ? T('Play') : T('Pause');
    paint();
  }
  // ---- comments
  function render() {
    $('vr-count').textContent = notes.length || '';
    list.innerHTML = notes.length ? '' : `<p class="muted small" style="margin:0">${esc(T('No comments yet. Pause where something happens, draw it and say what should have happened.'))}</p>`;
    for (const n of notes) {
      const el = document.createElement('div'); el.className = 'vr-note' + (n === active ? ' on' : '');
      const can = n.uid === B.uid || B.owner;
      el.innerHTML = `<div class="h"><b>${fmt(n.t)}</b>${n.round ? `<span>${esc(T('Round'))} ${n.round}</span>` : ''}<span translate="no">${esc(n.by)}</span>
        ${can ? `<button type="button" class="del" title="${esc(T('Remove'))}" aria-label="${esc(T('Remove'))}">×</button>` : ''}</div>
        ${n.text ? `<p>${esc(n.text)}</p>` : ''}${n.strokes && n.strokes.length ? `<div class="dr">${esc(T('with a drawing'))}</div>` : ''}`;
      el.addEventListener('click', e => {
        if (e.target.closest('.del')) { remove(n); return; }
        active = n; video.pause(); video.currentTime = n.t; render(); tick();
      });
      list.appendChild(el);
    }
    timeline();
  }
  async function api(url, body) {
    const r = await fetch(url, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin', body: JSON.stringify(body)}
                                    : {credentials: 'same-origin'});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
    return d;
  }
  async function save() {
    const text = $('vr-text').value.trim();
    if (!text && !strokes.length) { $('vr-text').focus(); return; }
    try {
      const d = await api(B.api, {t: video.currentTime, text, strokes});
      notes = d.notes; active = notes.find(x => x.id === d.note.id) || null;
      strokes = []; $('vr-text').value = '';
      render(); tick();
      window.nexusToast && window.nexusToast(T('Comment saved.'), 'ok');
    } catch (e) { window.nexusToast ? window.nexusToast(e.message, 'error') : alert(e.message); }
  }
  async function remove(n) {
    if (!confirm(T('Remove this comment?'))) return;
    try { const d = await api(`${B.api}/${n.id}/delete`, {}); notes = d.notes; if (active === n) active = null; render(); tick(); }
    catch (e) { window.nexusToast && window.nexusToast(e.message, 'error'); }
  }
  // ---- drawing
  canvas.addEventListener('pointerdown', e => {
    video.pause();
    canvas.setPointerCapture(e.pointerId);
    cur = {c: color, k: tool, p: [fromEvent(e)]};
    stage.classList.add('draw');
  });
  canvas.addEventListener('pointermove', e => {
    if (!cur) return;
    const p = fromEvent(e);
    if (tool === 'pen') { const q = cur.p[cur.p.length - 1]; if (Math.hypot(p[0] - q[0], p[1] - q[1]) > 0.003 && cur.p.length < 300) cur.p.push(p); }
    else cur.p = [cur.p[0], p];
    paint();
  });
  const end = () => { if (cur && cur.p.length >= 2) strokes.push(cur); cur = null; paint(); };
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
  document.querySelectorAll('.vr-tools .tool').forEach(b => b.addEventListener('click', () => {
    tool = b.dataset.k; document.querySelectorAll('.vr-tools .tool').forEach(x => x.classList.toggle('on', x === b));
  }));
  const cols = $('vr-cols');
  for (const c of B.colors) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'col' + (c === color ? ' on' : ''); b.style.background = c; b.title = c;
    b.addEventListener('click', () => { color = c; cols.querySelectorAll('.col').forEach(x => x.classList.toggle('on', x === b)); });
    cols.appendChild(b);
  }
  $('vr-undo').addEventListener('click', () => { strokes.pop(); paint(); });
  $('vr-clear').addEventListener('click', () => { strokes = []; paint(); });
  // ---- player
  video.src = B.video;
  $('vr-play').addEventListener('click', () => (video.paused ? video.play().catch(() => {}) : video.pause()));
  document.querySelectorAll('[data-skip]').forEach(b => b.addEventListener('click', () => { video.pause(); video.currentTime = Math.max(0, video.currentTime + +b.dataset.skip); }));
  $('vr-rate').addEventListener('change', e => { video.playbackRate = +e.target.value; });
  const rsel = $('vr-round');
  if (B.rounds.length) {
    rsel.hidden = false;
    for (const r of B.rounds) { const o = document.createElement('option'); o.value = r.t; o.textContent = `${T('Round')} ${r.n}${r.won ? ' ✓' : ''}`; rsel.appendChild(o); }
    rsel.addEventListener('change', () => { if (rsel.value !== '') { video.currentTime = +rsel.value; video.pause(); } rsel.value = ''; });
  }
  tl.addEventListener('click', e => {
    const r = tl.getBoundingClientRect();
    if (video.duration) { video.currentTime = video.duration * Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)); }
  });
  ['timeupdate', 'seeked', 'play', 'pause', 'loadedmetadata'].forEach(ev => video.addEventListener(ev, () => { if (ev === 'loadedmetadata') { size(); timeline(); } tick(); }));
  $('vr-save').addEventListener('click', save);
  $('vr-text').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  $('vr-text').addEventListener('focus', () => video.pause());
  document.addEventListener('keydown', e => {
    if (e.target.closest('input,textarea,select')) return;
    if (e.key === ' ') { e.preventDefault(); video.paused ? video.play().catch(() => {}) : video.pause(); }
    else if (e.key === 'ArrowLeft') video.currentTime = Math.max(0, video.currentTime - 5);
    else if (e.key === 'ArrowRight') video.currentTime += 5;
    else if (e.key === ',') { video.pause(); video.currentTime = Math.max(0, video.currentTime - 1 / 30); }
    else if (e.key === '.') { video.pause(); video.currentTime += 1 / 30; }
  });
  window.addEventListener('resize', size);
  setInterval(async () => {                 // teammates' comments come in while you watch
    if (document.hidden) return;
    try { const d = await api(B.api); if (JSON.stringify(d.notes.map(n => n.id)) !== JSON.stringify(notes.map(n => n.id))) { notes = d.notes; render(); paint(); } } catch (e) {}
  }, 15000);
  size(); render(); tick();
  window.nexusVR = {state: () => ({notes, strokes, tool, color}), save, draw: s => { strokes.push(s); paint(); }, video};   // for tests
})();
