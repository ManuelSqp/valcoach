// Nexus report, opened from the web app: "Ask the coach" under every round, and clips from the VOD
// next to the jump buttons (download, or post to the team's Discord).
(function () {
  'use strict';
  const C = window.VALCOACH_FB; if (!C || !C.ask_url) return;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const css = document.createElement('style');
  css.textContent = `
.vask{margin-top:12px;border-top:1px dashed rgba(255,255,255,.12);padding-top:10px}
.vask h4{margin:0 0 6px;font-size:13px;font-weight:650;opacity:.75}
.vask .qa{margin:6px 0 8px;font-size:13.5px}.vask .qa .q{font-weight:700}.vask .qa .a{margin-top:3px;line-height:1.45}
.vask .qa .m{font-size:11px;opacity:.55}
.vask form{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.vask input[type=text]{flex:1;min-width:200px;padding:7px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.15);background:rgba(0,0,0,.25);color:inherit;font:inherit;font-size:13.5px}
.vask select,.vask button,.vclip button,.vclip a{font:inherit;font-size:12.5px;padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.06);color:inherit;cursor:pointer;text-decoration:none}
.vask button[type=submit]{background:var(--accent,#f4b740);border-color:var(--accent,#f4b740);color:#1b1305;font-weight:700}
.vask .wait{font-size:12.5px;opacity:.75}.vask .err{font-size:12.5px;color:#ff6b77}
.vclip{display:inline-flex;gap:3px;margin:0 8px 0 2px;vertical-align:middle}
.vclip button,.vclip a{padding:3px 7px;font-size:11.5px}`;
  document.head.appendChild(css);
  const post = (url, body) => fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  function toast(m) {
    const d = document.createElement('div');
    d.textContent = m; d.style.cssText = 'position:fixed;right:16px;bottom:16px;background:#212b3a;color:#fff;padding:9px 14px;border-radius:9px;font:13px Archivo,system-ui;z-index:99;box-shadow:0 6px 24px rgba(0,0,0,.4)';
    document.body.appendChild(d); setTimeout(() => d.remove(), 2600);
  }

  // ------------------------------------------------------------- ask the coach
  const srcHtml = x => (x.sources && x.sources.length) ? `<div class="m">${x.sources.map((s, i) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer nofollow" title="${esc(s.url)}">[${i + 1}] ${esc(s.title)}</a>`).join(' · ')}</div>` : '';
  const qaHtml = x => `<div class="qa"><div class="q">${esc(x.q)}</div><div class="a">${esc(x.a)}</div>${srcHtml(x)}${x.model ? `<div class="m">${esc(x.model)}</div>` : ''}</div>`;
  const pick = () => C.llm && C.llm.length > 1 ? `<select name="llm" title="Which model answers">${C.llm.map(c => `<option value="${esc(c.value)}" ${c.value === C.llm_last ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}</select>` : '';
  fetch(C.ask_url).then(r => r.json()).then(all => {
    document.querySelectorAll('.round[id^="r"]').forEach(el => {
      const n = +el.id.slice(1), body = el.querySelector('.rbody'); if (!n || !body) return;
      const box = document.createElement('div'); box.className = 'vask';
      box.innerHTML = `<h4>Ask the coach about round ${n}</h4><div class="list">${((all.items || {})[n] || []).map(qaHtml).join('')}</div>
        <form><input type="text" maxlength="400" placeholder="e.g. Should I have saved here? What if I'd waited for the flash?" aria-label="Your question">${pick()}<button type="submit">Ask</button></form>
        <div class="state"></div>`;
      body.appendChild(box);
      const form = box.querySelector('form'), state = box.querySelector('.state'), list = box.querySelector('.list');
      form.addEventListener('click', e => e.stopPropagation());
      form.addEventListener('submit', async e => {
        e.preventDefault(); e.stopPropagation();
        const q = form.querySelector('input').value.trim(); if (!q) return;
        const sel = form.querySelector('select');
        const btn = form.querySelector('button'); btn.disabled = true;
        state.innerHTML = '<span class="wait">The coach is thinking… (a local model can take a minute)</span>';
        const r = await post(C.ask_url, {round: n, question: q, llm: sel ? sel.value : undefined});
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { state.innerHTML = `<span class="err">${esc(j.error || 'Not sent')}</span>`; btn.disabled = false; return; }
        if (sel) C.llm_last = sel.value;
        const seen = list.children.length;
        const poll = async () => {
          const s = await (await fetch(C.ask_url + '?round=' + n)).json().catch(() => null);
          if (s && s.error) { state.innerHTML = `<span class="err">${esc(s.error)}</span>`; btn.disabled = false; return; }
          if (s && !s.pending && s.items.length > seen) {
            list.innerHTML = s.items.map(qaHtml).join(''); state.innerHTML = ''; form.querySelector('input').value = ''; btn.disabled = false; return;
          }
          setTimeout(poll, 2000);
        };
        setTimeout(poll, 1500);
      });
    });
  }).catch(() => {});

  // ------------------------------------------------------------- playback: notes, strat board, picture (4.20)
  // The report keeps the playback script of the version it was made with; the current one is loaded so older
  // reports get the notes too. Notes here are the owner's own (only he opens this report).
  if (C.pins_url && C.replay_js) {
    const pcss = document.createElement('style');
    pcss.textContent = `
.rp-tick.pin{top:-3px;width:9px;height:9px;border-radius:50%;transform:translateX(-4px);border:2px solid #0b0e13}
.rp-bar .rp-pin.on{border-color:#f6d24a;color:#f6d24a}
.rp-msg{font-size:12.5px;opacity:.75}.rp-msg a{color:var(--accent,#f4b740)}
.rp-compose{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:6px;padding:8px;border:1px solid #f6d24a;border-radius:8px;background:rgba(255,255,255,.04)}
.rp-compose[hidden]{display:none}
.rp-compose input{flex:1;min-width:180px;padding:6px 9px;border-radius:7px;border:1px solid rgba(255,255,255,.15);background:rgba(0,0,0,.25);color:inherit;font:inherit;font-size:13px}
.rp-compose button{font:inherit;font-size:12.5px;padding:5px 10px;border-radius:7px;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.06);color:inherit;cursor:pointer}
.rp-compose .rp-csave{border-color:#f6d24a}
.rp-ctime,.rp-cmsg{font-size:12.5px;opacity:.75}
.rp-pins .rp-pinrow{opacity:1}.rp-pinrow span{flex:1}.rp-pinrow small{opacity:.6}
.rp-pdel{flex:none!important;opacity:.6;padding:0 4px}.rp-pdel:hover{color:#ff4655;opacity:1}
.rp-none{font-size:12.5px;opacity:.7;margin:0}`;
    document.head.appendChild(pcss);
    let PINS = {};
    const pinApi = async body => {
      const r = await post(C.pins_url, body); const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'not saved');
      PINS = d.pins || {};
    };
    window.NEXUS_RP = {
      pins: n => PINS[String(n)] || [],
      addPin: (n, p) => pinApi({action: 'pin', round: +n, t: p.t, text: p.text, strokes: p.strokes}),
      delPin: (n, id) => pinApi({action: 'unpin', round: +n, id}),
      canDelete: () => true,
    };
    if (C.strat) window.NEXUS_RP.toStrat = async (n, m) => {
      const ts = `${Math.floor(m.t / 60000)}:${String(Math.floor(m.t / 1000) % 60).padStart(2, '0')}`;
      const r = await post(C.strat.url, {map: C.map, side: m.side, name: `${C.map} R${n} ${ts} (${C.match || 'report'})`.slice(0, 80), items: m.items,
                                         notes: `From the coaching report, round ${n} at ${ts}.` + (m.notes ? '\n' + m.notes : '')});
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'not made');
      return d.url;
    };
    if (C.moment_url) window.NEXUS_RP.toDiscord = async (n, png, text) => {
      const fd = new FormData(); fd.append('png', png, 'moment.png'); fd.append('text', text);
      const r = await fetch(C.moment_url, {method: 'POST', body: fd}); const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'not posted');
    };
    const s = document.createElement('script');
    s.src = C.replay_js;
    s.onload = () => fetch(C.pins_url).then(r => r.json()).then(d => { PINS = d.pins || {}; }).catch(() => {}).then(() => {
      const box = document.getElementById('rp-box');            // rebuild the round shown with the new playback
      if (box && box.dataset.round && typeof window.showReplay === 'function') window.showReplay(box.dataset.round);
    });
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------- clips
  if (!C.clip_url) return;
  document.querySelectorAll('button.jump').forEach(b => {
    const m = /seek\(([-\d.]+)\)/.exec(b.getAttribute('onclick') || ''); if (!m) return;
    const start = Math.max(0, +m[1] - 2), label = b.textContent.trim();
    const g = document.createElement('span'); g.className = 'vclip';
    const a = document.createElement('a'); a.textContent = '⬇ clip'; a.title = `15 s clip from here (${label})`;
    a.href = `${C.clip_url}?t=${start.toFixed(1)}&len=15&dl=1`;
    a.addEventListener('click', () => toast('Cutting the clip… the download starts when it’s ready'));
    g.appendChild(a);
    if (C.discord_url) {
      const d = document.createElement('button'); d.type = 'button'; d.textContent = '→ Discord'; d.title = 'Post this clip to the team’s Discord';
      d.onclick = async e => {
        e.stopPropagation(); d.disabled = true; toast('Cutting the clip and posting it…');
        const round = (b.closest('.round') || {}).id || '';
        const r = await fetch(`${C.discord_url}?t=${start.toFixed(1)}&len=15&label=${encodeURIComponent((round ? 'R' + round.slice(1) + ' · ' : '') + label)}`, {method: 'POST'});
        const j = await r.json().catch(() => ({}));
        toast(r.ok ? 'Posted to Discord' : (j.error || 'Not posted')); d.disabled = false;
      };
      g.appendChild(d);
    }
    b.after(g);
  });
})();
