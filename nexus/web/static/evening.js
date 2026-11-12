// Nexus review evening: rounds one by one, everyone marks his own, the host moves everyone along.
(function () {
  'use strict';
  const B = JSON.parse(document.getElementById('ev-boot').textContent);
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = a => B.agent_icon.replace('__A__', encodeURIComponent(a));
  const ai = (a, s = 20) => a ? `<img class="ai" src="${icon(a)}" width="${s}" height="${s}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : '';
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  };
  const SID = B.api.split('/').pop();
  const R = Object.fromEntries(B.rounds.map(r => [r.n, r]));
  const N = B.rounds.length;
  const KEY = new Set(B.key || []);
  const BUY = {pistol: 'pistol', eco: 'eco', force: 'force buy', full: 'full buy'};
  let S = B.state;
  let host = !!B.host;
  let follow = !host && store.get('vc-ev-follow', '1') === '1';
  let cur = S.current || 1;
  const hm = /^#r(\d+)$/.exec(location.hash);
  if (hm && R[+hm[1]]) { cur = +hm[1]; follow = false; }
  let me = store.get('vc-ev-me-' + SID, '') || B.me || (B.players[0] || {}).name || '';
  if (!B.players.some(p => p.name === me)) me = (B.players[0] || {}).name || '';
  let keyOnly = store.get('vc-ev-key', '0') === '1';

  // ------------------------------------------------------------------ server
  async function api(body) {
    const r = await fetch(B.api, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || 'not saved');
    return d;
  }
  async function poll() {
    try {
      const r = await fetch(B.api, {headers: {Accept: 'application/json'}});
      if (r.ok) apply(await r.json(), false);
    } catch (e) {}
    setTimeout(poll, document.hidden ? 8000 : 2500);
  }
  function apply(st, mine) {
    const wasFinished = S.finished;
    S = st;
    if (st.finished !== wasFinished && !mine) { location.reload(); return; }
    if (follow && !host && S.current !== cur) { cur = S.current; renderRound(); }
    renderStrip(); renderHere(); renderMarks();
    const rb = $('#rp-box'); if (replayOn && rb && rb._redraw) rb._redraw();       // notes from the others
    if (st.updated !== shownSummary) refreshSummary(st.updated);
  }
  let shownSummary = S.updated, sumTimer = null;
  function refreshSummary(stamp) {
    clearTimeout(sumTimer);
    sumTimer = setTimeout(async () => {
      try {
        const r = await fetch(B.summary);
        if (!r.ok) return;
        const box = document.getElementById('summary');
        const tmp = document.createElement('div'); tmp.innerHTML = await r.text();
        const fresh = tmp.querySelector('#summary');
        if (box && fresh) { box.replaceWith(fresh); bindGo(fresh); shownSummary = stamp; }
      } catch (e) {}
    }, 1200);
  }

  // ------------------------------------------------------------------ strip
  function marksOf(n) { return (S.marks || {})[String(n)] || {}; }
  function renderStrip() {
    const box = $('#strip');
    let html = '';
    B.rounds.forEach((r, i) => {
      if (i > 0 && r.side !== B.rounds[i - 1].side) html += '<span class="half" aria-hidden="true"></span>';
      const ms = Object.values(marksOf(r.n));
      let dot = '';
      if (ms.length) {
        const c = ms.some(m => m.m === 'fault') ? 'f' : ms.some(m => m.m === 'talk') ? 't' : 'g';
        dot = `<span class="dot ${c}">${ms.length}</span>`;
      }
      const cls = ['rn', r.won ? 'w' : 'l', r.n === cur ? 'on' : '', KEY.has(r.n) ? 'key' : '', keyOnly && !KEY.has(r.n) ? 'dim' : ''].join(' ');
      const title = `Round ${r.n}: ${r.won ? 'won' : 'lost'}, ${r.side}${KEY.has(r.n) ? ', key round' : ''}${ms.length ? `, ${ms.length} marked` : ''}`;
      html += `<button type="button" class="${cls}" data-n="${r.n}" role="tab" aria-selected="${r.n === cur}" title="${esc(title)}">${r.n}${dot}${S.current === r.n && S.current !== cur ? '<span class="hostmark" title="The host is here"></span>' : ''}</button>`;
    });
    box.innerHTML = html;
  }
  $('#strip').addEventListener('click', e => {
    const b = e.target.closest('.rn'); if (b) go(+b.dataset.n, true);
  });

  // ------------------------------------------------------------------ round
  function renderRound() {
    const r = R[cur]; if (!r) return;
    const buy = r.buy;
    const facts = [];
    if (buy) facts.push(['Buys', `${BUY[buy.us] || buy.us} (${buy.us_avg.toLocaleString()}) vs ${BUY[buy.them] || buy.them} (${buy.them_avg.toLocaleString()})`]);
    if (r.first) facts.push(['First kill', `${r.first.ours ? esc(r.first.k) : esc(r.first.k) + ' (them)'} on ${esc(r.first.v)} at ${r.first.t}`]);
    if (r.plant) facts.push([r.plant.ours ? 'You planted' : 'They planted', `${r.plant.site ? r.plant.site + ' site' : 'spike'} at ${r.plant.t}${r.defused ? ', defused' : ''}`]);
    facts.push(['Alive at the end', `${r.alive[0]} of you, ${r.alive[1]} of them`]);
    if (r.untraded.length) facts.push(['Not traded', r.untraded.map(esc).join(', ')]);
    $('#round').innerHTML = `
      <div class="rhead">
        <div class="rbig ${r.won ? 'w' : 'l'}" aria-label="Round ${r.n}">${r.n}</div>
        <div class="rres">${r.won ? 'Won' : 'Lost'}<small>${esc(r.result)}</small></div>
        <div class="rsub">${r.side === 'attack' ? 'Attack' : 'Defense'} · ${r.score} before the round${KEY.has(r.n) ? ' · key round' : ''} · round ${r.n} of ${N}</div>
      </div>
      ${r.why.length ? `<div class="tags">${r.why.map(w => `<span class="tag">${esc(w)}</span>`).join('')}</div>` : ''}
      <div class="facts">${facts.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>`;
    $('#kn').textContent = r.kills.length ? `${r.kills.length} kills` : '';
    $('#kills').innerHTML = r.kills.map(k => `<div class="${k.ours ? 'us' : 'them'}"><span class="t">${k.t}</span>
        <span class="n">${ai(k.ka)}${esc(k.k)}</span><span class="w">${esc(k.w)}</span><span class="n">${ai(k.va)}${esc(k.v)}</span></div>`).join('')
      || '<p class="muted small" style="margin:0">No kills in this round.</p>';
    const ps = Object.entries(r.players);
    $('#ours').innerHTML = '<tr><th>Player</th><th>Weapon</th><th class="x">Kills</th><th class="x">Damage</th><th class="x">Buy</th><th></th></tr>' +
      ps.map(([n, p]) => `<tr class="${p.died ? 'dead' : ''}"><td>${ai(p.agent)} ${esc(n)}</td><td>${esc(p.weapon || '–')}</td>
        <td class="x">${p.k}</td><td class="x">${p.dmg}</td><td class="x">${p.loadout.toLocaleString()}</td>
        <td><span class="st ${p.died ? '' : 'alive'}">${p.afk ? 'AFK' : p.died ? 'died' : 'alive'}</span></td></tr>`).join('');
    $('#prev').disabled = !step(-1);
    $('#next').disabled = !step(1);
    renderMarks();
    if (replayOn) showReplay();
  }

  // ------------------------------------------------------------------ marks
  function renderMarks() {
    const ms = marksOf(cur);
    const mine = ms[me] || {};
    document.querySelectorAll('#mk button').forEach(b => {
      b.classList.toggle('on', b.dataset.m === mine.m);
      b.setAttribute('aria-pressed', b.dataset.m === mine.m);
    });
    const note = $('#note');
    if (document.activeElement !== note && !note.dataset.dirty) note.value = mine.note || '';
    $('#all').innerHTML = B.players.map(p => {
      const m = ms[p.name] || {};
      return `<div><span>${ai(p.agent, 24)}</span><span class="nm">${esc(p.name)}${p.name === me ? '<span class="youtag">you</span>' : ''}</span>
        <span class="m ${m.m || ''}">${m.m ? esc(B.marks[m.m]) : 'not yet'}</span>
        ${m.note ? `<span class="nt">${esc(m.note)}${m.by && m.by.split('#')[0] !== p.name ? ` (${esc(m.by)})` : ''}</span>` : ''}</div>`;
    }).join('');
  }
  async function mark(m, note) {
    const ms = marksOf(cur), mine = ms[me] || {};
    if (m === undefined) m = mine.m;
    if (!m) { $('#saved').textContent = 'Pick a mark first, then save the note.'; return; }
    const off = note === undefined && mine.m === m;          // pressing your mark again takes it back
    const body = {action: 'mark', round: cur, player: me, mark: off ? 'none' : m, note: note !== undefined ? note : $('#note').value};
    $('#saved').textContent = 'saving…';
    try {
      const st = await api(body);
      $('#note').dataset.dirty = '';
      apply(st, true);
      $('#saved').textContent = off ? `Mark taken back for round ${cur}.` : `Saved for round ${cur}.`;
    } catch (e) { $('#saved').textContent = 'Not saved: ' + e.message; }
  }
  $('#mk').addEventListener('click', e => { const b = e.target.closest('button'); if (b) mark(b.dataset.m); });
  $('#notesave').addEventListener('click', () => mark(undefined, $('#note').value));
  $('#note').addEventListener('input', e => { e.target.dataset.dirty = '1'; });
  $('#note').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); mark(undefined, e.target.value); } });
  const meSel = $('#me');
  meSel.value = me;
  meSel.addEventListener('change', () => { me = meSel.value; store.set('vc-ev-me-' + SID, me); $('#note').dataset.dirty = ''; renderMarks(); if (replayOn) showReplay(); });

  // ------------------------------------------------------------------ moving
  function step(d) {
    for (let n = cur + d; n >= 1 && n <= N; n += d) if (!keyOnly || KEY.has(n)) return n;
    return null;
  }
  async function go(n, byHand) {
    if (!R[n]) return;
    cur = n;
    if (host) {
      api({action: 'goto', round: n}).then(st => apply(st, true)).catch(() => {});
    } else if (byHand && follow && n !== S.current) {
      follow = false; $('#follow').checked = false;          // looking around on your own
    }
    history.replaceState(null, '', '#r' + n);
    $('#note').dataset.dirty = '';
    renderStrip(); renderRound();
  }
  $('#prev').addEventListener('click', () => { const n = step(-1); if (n) go(n, true); });
  $('#next').addEventListener('click', () => { const n = step(1); if (n) go(n, true); });
  const ko = $('#keyonly');
  ko.checked = keyOnly;
  $('#keyn').textContent = KEY.size ? `(${KEY.size})` : '(none found)';
  ko.addEventListener('change', () => {
    keyOnly = ko.checked; store.set('vc-ev-key', keyOnly ? '1' : '0');
    if (keyOnly && !KEY.has(cur)) { const n = [...KEY].sort((a, b) => a - b).find(x => x > cur) || [...KEY][0]; if (n) { go(n, true); return; } }
    renderStrip(); renderRound();
  });
  const fo = $('#follow');
  fo.checked = follow;
  fo.addEventListener('change', () => {
    follow = fo.checked; store.set('vc-ev-follow', follow ? '1' : '0');
    if (follow && S.current !== cur) { cur = S.current; renderStrip(); renderRound(); }
  });
  function renderHere() {
    const here = S.here || [];
    $('#here').innerHTML = `<i></i>Here: ${here.map(n => `<b>${esc(n.split('#')[0])}</b>`).join(', ') || '–'} · host: <b>${esc((S.host || '').split('#')[0])}</b>`;
    $('#followl').hidden = host;
    $('#takehost').hidden = host || here.includes(S.host);
  }
  $('#takehost').addEventListener('click', async () => {
    try { await api({action: 'host'}); location.reload(); } catch (e) { alertLine(e.message); }
  });
  function alertLine(msg) { $('#saved').textContent = msg; }
  const fin = $('#finish');
  if (fin) fin.addEventListener('click', async () => {
    try { const ending = !S.finished; await api({action: ending ? 'finish' : 'reopen'}); location.hash = ending ? 'summary' : ''; location.reload(); }
    catch (e) { alertLine(e.message); }
  });
  function bindGo(scope) {
    scope.querySelectorAll('[data-go]').forEach(a => a.addEventListener('click', e => {
      e.preventDefault(); go(+a.dataset.go, true); window.scrollTo({top: 0, behavior: 'smooth'});
    }));
  }
  bindGo(document);
  document.addEventListener('keydown', e => {
    if (e.target.closest('input, textarea, select') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowRight') { const n = step(1); if (n) { e.preventDefault(); go(n, true); } }
    else if (e.key === 'ArrowLeft') { const n = step(-1); if (n) { e.preventDefault(); go(n, true); } }
    else if (['1', '2', '3'].includes(e.key)) { const k = Object.keys(B.marks)[+e.key - 1]; if (k) mark(k); }
  });

  // ------------------------------------------------------------------ replay (loaded the first time it's opened)
  let replayOn = false, replayData = null, loading = null;
  function loadReplay() {
    if (loading) return loading;
    loading = Promise.all([
      fetch(B.replay).then(r => { if (!r.ok) throw new Error('no replay'); return r.json(); }),
      window.nexusBuild ? Promise.resolve() : new Promise((ok, no) => {
        const s = document.createElement('script'); s.src = B.replay_js; s.onload = ok; s.onerror = no; document.head.appendChild(s);
      }),
    ]).then(([d]) => { replayData = d; });
    return loading;
  }
  // 4.18: notes with drawings on the playback (saved for everyone) and "this moment on a strat board"
  window.NEXUS_RP = {
    pins: n => ((S.pins || {})[String(n)] || []),
    addPin: (n, p) => api({action: 'pin', round: +n, t: p.t, text: p.text, strokes: p.strokes}).then(st => apply(st, true)),
    delPin: (n, id) => api({action: 'unpin', round: +n, id}).then(st => apply(st, true)),
    canDelete: p => host || p.by_id === B.uid,
    toStrat: async (n, m) => {
      const ts = `${Math.floor(m.t / 60000)}:${String(Math.floor(m.t / 1000) % 60).padStart(2, '0')}`;
      const name = `${B.map} R${n} ${ts} vs ${B.opponent || 'them'}`.slice(0, 80);
      const r = await fetch(B.to_strat, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({map: B.map, side: m.side, name, items: m.items,
                              notes: `From the review evening, round ${n} at ${ts}.` + (m.notes ? '\n' + m.notes : '')})});
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'not made');
      return d.url;
    },
  };
  async function showReplay() {
    const box = $('#rp-box'), note = $('#rpnote');
    try { await loadReplay(); } catch (e) { note.textContent = 'No replay for this match (the map or the round data is missing).'; return; }
    const rd = (replayData.rounds || {})[cur];
    if (box._destroy) box._destroy();
    box.innerHTML = ''; delete box.dataset.built; box.dataset.round = cur;
    if (!replayData.map || !rd || !rd.events || !rd.events.length) {
      box.hidden = true; note.hidden = false; note.textContent = 'No replay data for this round.'; return;
    }
    for (const id in rd.roster) rd.roster[id].you = rd.roster[id].us && rd.roster[id].name === me;
    window.VALCOACH_REPLAY = replayData;
    box.hidden = false; note.hidden = true;
    window.nexusBuild(box);
  }
  $('#rpbtn').addEventListener('click', () => {
    replayOn = !replayOn;
    $('#rpbtn').textContent = replayOn ? 'Hide the minimap' : 'Show the minimap';
    if (replayOn) showReplay();
    else { const box = $('#rp-box'); if (box._destroy) box._destroy(); box.innerHTML = ''; delete box.dataset.built; box.hidden = true; $('#rpnote').hidden = false; $('#rpnote').textContent = 'Where everyone was at every kill and at the plant, with the routes in between estimated.'; }
  });

  renderStrip(); renderRound(); renderHere();
  setTimeout(poll, 2500);
})();
