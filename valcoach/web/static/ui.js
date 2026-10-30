// valcoach UI extras: count-up numbers, progress bars for jobs, toasts, Ctrl+K quick search.
// Each part is switched on by a class on <body> (a-count, a-loaders, a-toasts); the search is always there.
(function () {
  'use strict';
  const body = document.body;
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const on = k => body.classList.contains('a-' + k) && !reduced;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  // ---------------------------------------------------------------- toasts
  let box = document.getElementById('toasts');
  function toast(msg, kind) {
    if (!box) return;
    const t = document.createElement('div');
    t.className = 'vtoast ' + (kind || 'ok');
    t.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    t.textContent = msg;
    box.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, kind === 'error' ? 7000 : 3500);
  }
  window.valcoachToast = toast;
  if (body.classList.contains('a-toasts')) {
    document.querySelectorAll('main .flash.ok').forEach(f => {
      if (f.querySelector('a, form, button')) return;           // keep boxes with links (e.g. "see what's new")
      toast(f.textContent.trim(), 'ok'); f.remove();
    });
  }

  // ---------------------------------------------------------------- count-up
  const COUNT = '.mc .val, .big3 b, .nums b, .cl b, .val, .procard .pct, .wkmap .big, [data-count]';
  if (on('count')) {
    const els = [...document.querySelectorAll(COUNT)].filter(e => e.children.length === 0 && /^\s*-?\d+([.,]\d+)?\s*(%|s)?\s*$/.test(e.textContent));
    const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { io.unobserve(x.target); run(x.target); } })) : null;
    function run(e) {
      const txt = e.textContent.trim(), m = txt.match(/^(-?\d+)([.,](\d+))?\s*(%|s)?$/);
      if (!m) return;
      const dec = m[3] ? m[3].length : 0, target = parseFloat(txt.replace(',', '.')), suffix = m[4] || '', sep = m[2] ? m[2][0] : '.';
      const t0 = performance.now(), dur = 650;
      const step = now => {
        const p = Math.min(1, (now - t0) / dur), v = target * (1 - Math.pow(1 - p, 3));
        e.textContent = v.toFixed(dec).replace('.', sep) + suffix;
        if (p < 1) requestAnimationFrame(step); else e.textContent = txt;
      };
      requestAnimationFrame(step);
    }
    els.forEach(e => io ? io.observe(e) : run(e));
  }

  // ---------------------------------------------------------------- progress bars for running jobs
  if (body.classList.contains('a-loaders')) {
    const blocks = document.querySelectorAll('[data-key][data-state="queued"], [data-key][data-state="running"]');
    blocks.forEach(b => {
      const pre = b.querySelector('pre.log');
      const bar = document.createElement('div');
      bar.className = 'jobbar';
      bar.innerHTML = '<div class="jb-track"><i></i></div><div class="jb-step small"></div>';
      const fill = bar.querySelector('i'), stepEl = bar.querySelector('.jb-step');
      const logLine = b.querySelector('.log:not(pre)');
      (pre || logLine || b.lastChild).parentNode.insertBefore(bar, pre || logLine || null);
      if (pre) {                                   // the raw log goes behind "show log"
        const d = document.createElement('details'); d.className = 'jb-log';
        d.innerHTML = '<summary class="small">show log</summary>';
        pre.parentNode.insertBefore(d, pre); d.appendChild(pre);
      }
      const update = () => {
        const src = pre ? pre.textContent : (logLine ? logLine.textContent : '');
        const lines = src.split('\n').map(x => x.trim()).filter(Boolean);
        const last = lines[lines.length - 1] || 'Waiting for a free worker …';
        let frac = null;
        for (let i = lines.length - 1; i >= 0; i--) {
          const m = lines[i].match(/\((\d+)\s*\/\s*(\d+)\)/) || lines[i].match(/(\d+)\s*\/\s*(\d+)/);
          if (m && +m[2] > 0) { frac = Math.min(1, (+m[1] - 0.5) / +m[2]); break; }
        }
        bar.classList.toggle('indet', frac === null);
        if (frac !== null) fill.style.width = (frac * 100).toFixed(0) + '%';
        stepEl.textContent = last.replace(/^[·•✓]\s*/, '');
      };
      update();
      if (pre || logLine) new MutationObserver(update).observe(pre || logLine, {childList: true, characterData: true, subtree: true});
    });
  }

  // ---------------------------------------------------------------- Ctrl+K quick search
  let pal = null, items = null, sel = 0, shown = [];
  async function load() {
    if (items) return items;
    try { const r = await fetch(body.dataset.search, {headers: {'Accept': 'application/json'}}); items = r.ok ? await r.json() : []; }
    catch (e) { items = []; }
    return items;
  }
  function score(it, q) {
    const hay = (it.label + ' ' + (it.sub || '') + ' ' + (it.kind || '')).toLowerCase();
    let s = 0;
    for (const w of q.toLowerCase().split(/\s+/).filter(Boolean)) {
      const i = hay.indexOf(w);
      if (i < 0) return -1;
      s += i === 0 ? 3 : (hay[i - 1] === ' ' ? 2 : 1);
    }
    return s;
  }
  function render(q) {
    const list = pal.querySelector('ul');
    shown = (q ? items.map(it => [score(it, q), it]).filter(x => x[0] >= 0).sort((a, b) => b[0] - a[0]).map(x => x[1]) : items).slice(0, 40);
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    list.innerHTML = shown.map((it, i) => `<li role="option" id="cmdk-${i}" aria-selected="${i === sel}" data-i="${i}"><span class="k">${esc(it.kind)}</span><span class="l">${esc(it.label)}</span><span class="s">${esc(it.sub || '')}</span></li>`).join('')
      || '<li class="none">Nothing found</li>';
    pal.querySelector('input').setAttribute('aria-activedescendant', shown.length ? 'cmdk-' + sel : '');
    const cur = list.querySelector('[aria-selected="true"]'); if (cur) cur.scrollIntoView({block: 'nearest'});
  }
  function go(i) { const it = shown[i]; if (it) location.href = it.url; }
  async function open() {
    if (!body.dataset.search) return;
    if (!pal) {
      pal = document.createElement('div');
      pal.className = 'cmdk'; pal.hidden = true;
      pal.innerHTML = '<div class="cmdk-box" role="dialog" aria-modal="true" aria-label="Quick search"><input type="text" role="combobox" aria-expanded="true" aria-controls="cmdk-list" placeholder="Jump to a player, team, map, draft, strat …" autocomplete="off"><ul id="cmdk-list" role="listbox"></ul><div class="cmdk-foot small">↑↓ choose · Enter open · Esc close</div></div>';
      document.body.appendChild(pal);
      const inp = pal.querySelector('input');
      inp.addEventListener('input', () => { sel = 0; render(inp.value); });
      inp.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(shown.length - 1, sel + 1); render(inp.value); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); render(inp.value); }
        else if (e.key === 'Enter') { e.preventDefault(); go(sel); }
        else if (e.key === 'Escape') { close(); }
      });
      pal.addEventListener('click', e => { const li = e.target.closest('li[data-i]'); if (li) go(+li.dataset.i); else if (e.target === pal) close(); });
    }
    pal.hidden = false;
    await load();
    const inp = pal.querySelector('input'); inp.value = ''; sel = 0; render(''); inp.focus();
  }
  function close() { if (pal) pal.hidden = true; }
  window.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); pal && !pal.hidden ? close() : open(); }
    else if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !document.activeElement.isContentEditable) {
      if (document.getElementById('strat') || document.getElementById('dr-slots')) return;    // editors use their own keys
      e.preventDefault(); open();
    }
  });
  document.querySelectorAll('[data-cmdk]').forEach(b => b.addEventListener('click', open));
})();
