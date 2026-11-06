// Nexus report, opened from the web app: 👍 / 👎 on the coach's lines (liked lines become examples
// for the next coaching runs, disliked ones what to avoid) and 🎯 to make a line your focus this week.
(function () {
  'use strict';
  const C = window.VALCOACH_FB; if (!C) return;
  const css = document.createElement('style');
  css.textContent = '.vfb{display:inline-flex;gap:2px;margin-left:6px;vertical-align:middle;opacity:.45;transition:opacity .15s}' +
    '[data-fb]:hover .vfb,.vfb.set{opacity:1}' +
    '.vfb button{border:1px solid transparent;background:none;cursor:pointer;font-size:12px;padding:0 4px;border-radius:5px;line-height:18px;filter:grayscale(1)}' +
    '.vfb button:hover{border-color:rgba(255,255,255,.2)}.vfb button.on{filter:none;border-color:rgba(255,255,255,.35);background:rgba(255,255,255,.08)}';
  document.head.appendChild(css);
  const key = (r, t) => r + '|' + t;
  const post = (url, body) => fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  function toast(m) {
    const d = document.createElement('div');
    d.textContent = m; d.style.cssText = 'position:fixed;right:16px;bottom:16px;background:#222a36;color:#fff;padding:9px 14px;border-radius:9px;font:13px system-ui;z-index:99;box-shadow:0 6px 24px rgba(0,0,0,.4)';
    document.body.appendChild(d); setTimeout(() => d.remove(), 2200);
  }
  document.querySelectorAll('[data-fb]').forEach(el => {
    const round = +el.dataset.fb, who = el.dataset.who, text = el.textContent.trim().replace(/\s+/g, ' ');
    const box = document.createElement('span'); box.className = 'vfb';
    const cur = C.votes[key(round, text)] || '';
    const mk = (v, label, title) => {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.title = title; b.dataset.v = v;
      if (cur === v) { b.classList.add('on'); box.classList.add('set'); }
      return b;
    };
    box.append(mk('up', '👍', 'Good feedback: use lines like this as an example'), mk('down', '👎', "Not helpful: the coach avoids lines like this"));
    if (who === 'you' && C.focus_url) {
      const f = document.createElement('button'); f.type = 'button'; f.textContent = '🎯'; f.title = 'Make this my focus this week';
      f.onclick = async e => { e.stopPropagation(); const r = await post(C.focus_url, {focus: text.slice(0, 160), why: `From round ${round} of ${C.match}`, source: 'report', ref: C.match + ' R' + round});
        if (r.ok) { f.classList.add('on'); toast('Set as your focus for this week'); } };
      box.append(f);
    }
    box.addEventListener('click', async e => {
      const b = e.target.closest('button[data-v]'); if (!b) return;
      e.stopPropagation();
      const v = b.classList.contains('on') ? 'none' : b.dataset.v;
      const r = await post(C.vote_url, {round, who, text, vote: v});
      if (!r.ok) { toast('Not saved'); return; }
      box.querySelectorAll('button[data-v]').forEach(x => x.classList.toggle('on', x.dataset.v === v));
      box.classList.toggle('set', v !== 'none');
      if (v !== 'none') toast(v === 'up' ? 'Thanks: the coach uses lines like this as examples' : 'Got it: the coach avoids lines like this');
    });
    el.appendChild(box);
  });
})();
