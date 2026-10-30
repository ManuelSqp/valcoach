// valcoach roster drafts: 5 player slots, drag agents in (pointer events: mouse, pen and touch).
(function () {
  'use strict';
  const B = JSON.parse(document.getElementById('draft-boot').textContent);
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = a => B.agent_icon.replace('__A__', encodeURIComponent(a));
  const pct = v => v == null ? '–' : Math.round(v * 100) + '%';
  const ROLE = Object.fromEntries(B.agents.map(a => [a.name, a.role]));
  const AGENTS = new Set(B.agents.map(a => a.name));
  const PLAYER = Object.fromEntries(B.players.map(p => [p.pid, p]));
  const ROLES = ['Duelist', 'Initiator', 'Controller', 'Sentinel'];

  const d = B.draft, data = d.data;
  while (data.slots.length < 5) data.slots.push({pid: null, agent: '', alt: '', note: ''});
  let selSlot = null, dirty = false, timer = null;

  // ------------------------------------------------------------------ save
  function setStatus(s) { const x = $('#dr-status'); x.textContent = s; x.className = 'savest ' + s.split(' ')[0]; }
  function changed() { dirty = true; setStatus('unsaved'); clearTimeout(timer); timer = setTimeout(save, 800); }
  async function save() {
    clearTimeout(timer);
    if (!dirty) return;
    dirty = false; setStatus('saving…');
    try {
      const r = await fetch(B.save_url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                         body: JSON.stringify({name: d.name, data})});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      setStatus('saved ' + j.saved_at);
      updateListItem();
    } catch (err) { dirty = true; setStatus('not saved: ' + err.message); }
  }
  window.addEventListener('beforeunload', e => { if (dirty) { save(); e.preventDefault(); e.returnValue = ''; } });
  // leaving through a link or a form (other draft, Post to Discord): save first
  document.addEventListener('click', async e => {
    const a = e.target.closest('a[href]');
    if (a && dirty && !e.ctrlKey && !e.metaKey) { e.preventDefault(); await save(); location.href = a.href; }
  });
  document.querySelectorAll('form[data-flush]').forEach(f => f.addEventListener('submit', async e => {
    if (!dirty) return; e.preventDefault(); await save(); f.submit();
  }));
  function updateListItem() {
    const it = document.querySelector(`.ditem[data-did="${d.id}"]`); if (!it) return;
    it.querySelector('.nm span').textContent = d.name;
    const st = it.querySelector('.st'); st.className = 'st ' + data.status; st.textContent = {idea: 'idea', try: 'trying', main: 'our comp'}[data.status];
    it.querySelector('.icons').innerHTML = data.slots.map(s => s.agent ? `<img class="ai" src="${icon(s.agent)}" width="22" height="22" alt="${esc(s.agent)}" title="${esc(s.agent)}">` : '<i></i>').join('');
  }

  // ------------------------------------------------------------------ numbers
  function statOf(pid, agent) { return ((B.stats[String(pid)] || {})[agent]) || null; }
  function statLine(s) {
    if (!s.agent) return '';
    if (s.pid == null) return '<span class="warn">no player yet</span>';
    const st = statOf(s.pid, s.agent), who = esc(PLAYER[s.pid] ? PLAYER[s.pid].name : '');
    if (!st || !st.n_all) return `<span class="warn">${who} hasn't played ${esc(s.agent)} (in the imported games)</span>`;
    const map = st.n_map ? `<b>${st.n_map}</b> on ${esc(B.map)}, ${pct(st.wr_map)} won` : `<span class="warn">never on ${esc(B.map)}</span>`;
    return `${map}<br>${st.n_all} games overall, ${pct(st.wr_all)} won`;
  }
  function bestPicks(pid) {
    const per = B.stats[String(pid)] || {};
    return Object.entries(per).filter(([a, v]) => AGENTS.has(a) && v.n_all).sort((x, y) => y[1].score - x[1].score).slice(0, 4).map(([a]) => a);
  }

  // ------------------------------------------------------------------ render
  function renderSlots() {
    const box = $('#dr-slots');
    box.innerHTML = data.slots.map((s, i) => {
      const players = `<option value="">— player —</option>` + B.players.map(p =>
        `<option value="${p.pid}" ${p.pid === s.pid ? 'selected' : ''}>${esc(p.name)}${p.kind === 'sub' ? ' (sub)' : ''}</option>`).join('');
      const main = s.agent
        ? `<div class="drop main full" data-drop="agent" data-slot="${i}" data-has="${esc(s.agent)}"><button type="button" class="x" data-clear="agent" data-slot="${i}" title="Remove" aria-label="Remove ${esc(s.agent)}">×</button>
             <span class="pf big"><b>${esc(s.agent[0])}</b><img src="${icon(s.agent)}" alt="" onerror="this.remove()"></span><span class="an">${esc(s.agent)}</span><span class="ar">${esc(ROLE[s.agent] || '')}</span></div>`
        : `<div class="drop main" data-drop="agent" data-slot="${i}">Drop an agent</div>`;
      const alt = s.alt
        ? `<div class="drop alt full" data-drop="alt" data-slot="${i}" data-has="${esc(s.alt)}"><span class="pf"><b>${esc(s.alt[0])}</b><img src="${icon(s.alt)}" alt="" onerror="this.remove()"></span><span>or <b>${esc(s.alt)}</b></span><button type="button" class="x" data-clear="alt" data-slot="${i}" title="Remove" aria-label="Remove backup ${esc(s.alt)}">×</button></div>`
        : `<div class="drop alt" data-drop="alt" data-slot="${i}">backup pick</div>`;
      const picks = s.pid != null ? bestPicks(s.pid) : [];
      const qp = picks.length ? `<div class="qp">best:${picks.map(a => `<button type="button" data-pick="${esc(a)}" data-slot="${i}" title="${esc(a)}: ${esc(PLAYER[s.pid].name)}'s pick">` +
        `<span class="pf"><b>${esc(a[0])}</b><img src="${icon(a)}" alt="${esc(a)}" onerror="this.remove()"></span></button>`).join('')}</div>` : '';
      return `<div class="slot ${selSlot === i ? 'sel' : ''}" data-slotcard="${i}">
        <select data-player="${i}" aria-label="Player ${i + 1}">${players}</select>
        ${main}${alt}
        <div class="sstat">${statLine(s)}</div>${qp}
        <input type="text" data-note="${i}" maxlength="60" placeholder="role / job, e.g. IGL, lurk B" value="${esc(s.note)}">
      </div>`;
    }).join('');
  }
  function renderPalette() {
    const used = new Set(data.slots.map(s => s.agent).filter(Boolean));
    let html = '';
    for (const r of [...ROLES, 'Other']) {
      const list = B.agents.filter(a => (ROLES.includes(a.role) ? a.role : 'Other') === r);
      if (!list.length) continue;
      html += `<div class="prole">${esc(r)}</div><div class="pgrid">` + list.map(a =>
        `<button type="button" class="pa ${used.has(a.name) ? 'used' : ''}" data-agent="${esc(a.name)}" title="${esc(a.name)}${used.has(a.name) ? ' (in this draft)' : ''}" aria-label="${esc(a.name)}">` +
        `${esc(a.name[0])}<img src="${icon(a.name)}" alt="" onerror="this.remove()"></button>`).join('') + '</div>';
    }
    $('#dr-pal').innerHTML = html;
  }
  function renderChecks() {
    const agents = data.slots.map(s => s.agent).filter(Boolean);
    const n = Object.fromEntries(ROLES.map(r => [r, agents.filter(a => ROLE[a] === r).length]));
    $('#dr-mix').innerHTML = ROLES.map(r => `<span class="${n[r] ? '' : 'zero'}">${n[r]} ${r}${n[r] === 1 ? '' : 's'}</span>`).join('');
    const w = [];
    const dupA = agents.filter((a, i) => agents.indexOf(a) !== i);
    for (const a of new Set(dupA)) w.push(['bad', `${a} is picked twice: only one of each agent per team.`]);
    const pids = data.slots.map(s => s.pid).filter(p => p != null);
    for (const p of new Set(pids.filter((p, i) => pids.indexOf(p) !== i))) w.push(['bad', `${PLAYER[p] ? PLAYER[p].name : 'A player'} is in two slots.`]);
    if (agents.length && !n.Controller) w.push(['warn', 'No controller: nobody smokes.']);
    if (agents.length >= 4 && !n.Initiator) w.push(['warn', 'No initiator: no info or flashes for the entry.']);
    if (agents.length >= 4 && !n.Sentinel) w.push(['', 'No sentinel: think about who watches the flank.']);
    if (n.Duelist >= 3) w.push(['warn', `${n.Duelist} duelists: little utility for the team.`]);
    for (const s of data.slots) {
      if (!s.agent || s.pid == null) continue;
      const st = statOf(s.pid, s.agent), who = PLAYER[s.pid] ? PLAYER[s.pid].name : '';
      if (!st || !st.n_all) w.push(['warn', `${who} has no games on ${s.agent}: practice first, or add a backup pick.`]);
      else if (st.n_all < 5) w.push(['', `${who} has only ${st.n_all} games on ${s.agent}.`]);
    }
    const empty = data.slots.filter(s => !s.agent).length;
    if (empty) w.push(['', `${empty} slot${empty === 1 ? '' : 's'} without an agent.`]);
    if (!w.length) w.push(['ok', 'Looks complete: one of each role or close, and everyone has played their agent.']);
    $('#dr-warns').innerHTML = w.map(([k, t]) => `<li class="${k}">${esc(t)}</li>`).join('');
  }
  function render() { renderSlots(); renderPalette(); renderChecks(); }

  // ------------------------------------------------------------------ edits
  function setAgent(i, kind, a) {
    const s = data.slots[i]; if (!s || (a && !AGENTS.has(a))) return;
    s[kind] = a || '';
    if (kind === 'agent' && a && s.alt === a) s.alt = '';
    changed(); render();
  }
  const slotsBox = $('#dr-slots');
  slotsBox.addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.player !== undefined) { data.slots[+t.dataset.player].pid = t.value ? +t.value : null; changed(); render(); }
  });
  slotsBox.addEventListener('input', e => {
    const t = e.target;
    if (t.dataset.note !== undefined) { data.slots[+t.dataset.note].note = t.value.slice(0, 60); changed(); }
  });
  slotsBox.addEventListener('click', e => {
    const x = e.target.closest('[data-clear]');
    if (x) { setAgent(+x.dataset.slot, x.dataset.clear, ''); return; }
    const qp = e.target.closest('[data-pick]');
    if (qp) { setAgent(+qp.dataset.slot, 'agent', qp.dataset.pick); return; }
    const card = e.target.closest('[data-slotcard]');
    if (card && !e.target.closest('select, input')) { const i = +card.dataset.slotcard; selSlot = selSlot === i ? null : i; renderSlots(); }
  });
  function clickAgent(a) {          // palette click: the selected slot, else the first one without an agent
    let i = selSlot != null ? selSlot : data.slots.findIndex(s => !s.agent);
    if (i < 0) return;
    setAgent(i, 'agent', a);
    if (selSlot != null) { const nxt = data.slots.findIndex(s => !s.agent); selSlot = nxt >= 0 ? nxt : null; renderSlots(); }
  }

  // ------------------------------------------------------------------ drag and drop
  let drag = null;
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const pa = e.target.closest('.pa');
    const full = e.target.closest('.drop.full');
    if (!pa && !(full && !e.target.closest('.x'))) return;
    e.preventDefault();
    const agent = pa ? pa.dataset.agent : full.dataset.has;
    drag = {agent, from: pa ? null : {slot: +full.dataset.slot, kind: full.dataset.drop}, x0: e.clientX, y0: e.clientY, moved: false, ghost: null, hot: null};
  });
  window.addEventListener('pointermove', e => {
    if (!drag) return;
    if (!drag.moved && Math.abs(e.clientX - drag.x0) + Math.abs(e.clientY - drag.y0) < 5) return;
    if (!drag.moved) {
      drag.moved = true;
      const g = document.createElement('img'); g.className = 'dr-ghost'; g.src = icon(drag.agent); g.alt = '';
      document.body.appendChild(g); drag.ghost = g;
    }
    drag.ghost.style.left = e.clientX + 'px'; drag.ghost.style.top = e.clientY + 'px';
    const t = document.elementFromPoint(e.clientX, e.clientY), zone = t && t.closest('[data-drop]');
    if (zone !== drag.hot) { if (drag.hot) drag.hot.classList.remove('hot'); if (zone) zone.classList.add('hot'); drag.hot = zone; }
  });
  function endDrag(e, cancel) {
    if (!drag) return;
    const dr = drag; drag = null;
    if (dr.ghost) dr.ghost.remove();
    if (dr.hot) dr.hot.classList.remove('hot');
    if (cancel) return;
    if (!dr.moved) { if (!dr.from) clickAgent(dr.agent); return; }
    const zone = dr.hot;
    if (zone) {
      const i = +zone.dataset.slot, kind = zone.dataset.drop;
      if (dr.from) {                              // slot -> slot: swap
        const a = data.slots[dr.from.slot], b = data.slots[i];
        const va = a[dr.from.kind], vb = b[kind];
        b[kind] = va; a[dr.from.kind] = vb || '';
        for (const s of [a, b]) if (s.agent && s.alt === s.agent) s.alt = '';
        changed(); render();
      } else setAgent(i, kind, dr.agent);
    } else if (dr.from) setAgent(dr.from.slot, dr.from.kind, '');     // dragged out of a slot: remove it
  }
  // keyboard: Enter / Space on an agent in the list fills a slot like a click
  $('#dr-pal').addEventListener('click', e => { const pa = e.target.closest('.pa'); if (pa && e.detail === 0) clickAgent(pa.dataset.agent); });
  window.addEventListener('pointerup', e => endDrag(e, false));
  window.addEventListener('pointercancel', e => endDrag(e, true));
  document.addEventListener('dragstart', e => { if (e.target.closest && e.target.closest('.drop, .pa, .qp')) e.preventDefault(); });

  // ------------------------------------------------------------------ name, status, notes
  const nameEl = $('#dr-name'); nameEl.value = d.name;
  nameEl.addEventListener('input', () => { d.name = nameEl.value.slice(0, 80) || 'Untitled'; changed(); });
  function renderStatus() { document.querySelectorAll('.seg button').forEach(b => { b.classList.toggle('on', b.dataset.st === data.status); b.setAttribute('aria-pressed', b.dataset.st === data.status); }); }
  document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => { data.status = b.dataset.st; renderStatus(); changed(); }));
  const notes = $('#dr-notes'); notes.value = data.notes || '';
  notes.addEventListener('input', () => { data.notes = notes.value.slice(0, 3000); changed(); });
  window.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); } });

  renderStatus(); render();
  window.valcoachDraft = {data, save};
})();
