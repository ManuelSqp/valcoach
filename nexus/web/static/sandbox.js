// The aim trainer's sandbox (4.33): make your own scenarios from the trainer's builders. Pick a type, set its numbers,
// try it, save it for yourself or a team, share it as a code (NX1-…). The server checks every save (stats/sandbox.py)
// and turns the settings into the builder's options, so what you try is exactly what gets saved.
(function () {
  'use strict';
  const C = window.NEXUS_TRAINER, S = C && C.sandbox, TR = window.nexusTrainer;
  const $ = id => document.getElementById(id);
  const box = $('sb-form');
  if (!S || !TR || !box) return;
  const T = s => (window.vcT ? window.vcT(s) : s);
  const esc = s => { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; };
  const toast = (m, k) => (window.nexusToast ? window.nexusToast(m, k) : null);
  let editing = null;                       // the saved scenario being changed: {id, scope}

  // ---- the editor
  const typeSel = $('sb-type'), params = $('sb-params');
  for (const k of S.order) {
    const t = S.types[k], o = document.createElement('option'); o.value = k; o.textContent = T(t.label) + (t.kind === 'track' ? ' · ' + T('tracking') : ''); typeSel.appendChild(o);
  }
  const skillSel = $('sb-skill');
  for (const [k, v] of S.skills) { const o = document.createElement('option'); o.value = k; o.textContent = T(v); skillSel.appendChild(o); }
  const scopeSel = $('sb-scope');
  for (const t of S.teams) { const o = document.createElement('option'); o.value = 'team:' + t.id; o.textContent = T('Team') + ' ' + t.name; scopeSel.appendChild(o); }

  function controls(type, values) {
    const t = S.types[type];
    $('sb-about-type').textContent = T(t.about);
    params.innerHTML = '';
    for (const [k, ...spec] of t.params) {
      const v = values && k in values ? values[k] : (spec[1] === 'bool' ? spec[2] : spec[1] === 'choice' ? spec[3] : spec[4]);
      const row = document.createElement('label');
      if (spec[1] === 'bool') {
        row.className = 'sb-bool';
        row.innerHTML = `<input type="checkbox" data-k="${k}" ${v ? 'checked' : ''}> <span>${esc(T(spec[0]))}</span>`;
      } else if (spec[1] === 'choice') {
        row.innerHTML = `<span>${esc(T(spec[0]))}</span><select data-k="${k}">${spec[2].map(c => `<option ${c === v ? 'selected' : ''} value="${c}">${esc(T(c))}</option>`).join('')}</select>`;
      } else {
        row.innerHTML = `<span>${esc(T(spec[0]))} <b data-out="${k}">${v}</b></span>
          <input type="range" data-k="${k}" min="${spec[1]}" max="${spec[2]}" step="${spec[3]}" value="${v}">`;
      }
      params.appendChild(row);
    }
    params.querySelectorAll('input[type=range]').forEach(r => r.addEventListener('input', () => { params.querySelector(`[data-out="${r.dataset.k}"]`).textContent = r.value; }));
  }
  function read() {
    const p = {};
    params.querySelectorAll('[data-k]').forEach(el => { p[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.tagName === 'SELECT' ? el.value : +el.value; });
    return {type: typeSel.value, name: $('sb-name').value, about: $('sb-about').value, seconds: +$('sb-seconds').value,
            skill: skillSel.value, level: +$('sb-level').value, scope: scopeSel.value, params: p};
  }
  function fill(c) {
    typeSel.value = c.type; controls(c.type, c.params);
    $('sb-name').value = c.name || ''; $('sb-about').value = c.about || ''; $('sb-seconds').value = c.seconds || 45;
    skillSel.value = c.skill || ''; $('sb-level').value = c.level || 2; scopeSel.value = c.scope || 'me';
  }
  async function post(url, body) {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin', body: JSON.stringify(body)});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || T('That didn\'t work.'));
    return d;
  }
  typeSel.addEventListener('change', () => controls(typeSel.value));
  $('sb-try').addEventListener('click', async () => {
    try {
      const d = await post(S.save, Object.assign(read(), {dry: true, name: $('sb-name').value || T('Try')}));
      TR.addCustom(d.item); TR.play(d.item.id);
    } catch (e) { toast(e.message, 'error'); }
  });
  $('sb-save').addEventListener('click', async () => {
    try {
      const body = read();
      if (editing) Object.assign(body, {id: editing.id, from: editing.scope});
      const d = await post(S.save, body);
      toast(T('Saved.'), 'ok');
      setTimeout(() => location.reload(), 400);           // the list, the library and the skill sessions pick it up
      return d;
    } catch (e) { toast(e.message, 'error'); }
  });
  $('sb-new').addEventListener('click', () => { editing = null; $('sb-save').textContent = T('Save'); fill({type: typeSel.value}); $('sb-form').open = true; });
  $('sb-import').addEventListener('click', async () => {
    const code = $('sb-code').value.trim();
    if (!code) { $('sb-code').focus(); return; }
    try { await post(S.save, {code, scope: scopeSel.value}); toast(T('Added.'), 'ok'); setTimeout(() => location.reload(), 400); }
    catch (e) { toast(e.message, 'error'); }
  });

  // ---- the list
  const list = $('sb-list');
  const byIdx = Object.fromEntries(S.items.map(c => [c.id, c]));
  list.addEventListener('click', async e => {
    const b = e.target.closest('button[data-a]'); if (!b) return;
    const c = byIdx[b.closest('[data-id]').dataset.id];
    if (b.dataset.a === 'play') TR.play(c.id);
    else if (b.dataset.a === 'edit') {
      editing = {id: c.id, scope: c.scope}; fill(c); $('sb-save').textContent = T('Save changes');
      $('sb-form').open = true; $('sb-form').scrollIntoView({block: 'start', behavior: 'smooth'});
    } else if (b.dataset.a === 'code') {
      try { await navigator.clipboard.writeText(c.code); b.textContent = T('Copied'); } catch (err) { prompt(T('The code:'), c.code); }
      setTimeout(() => { b.textContent = T('Copy code'); }, 1600);
    } else if (b.dataset.a === 'del') {
      if (!confirm(T('Remove this scenario?'))) return;
      try { await post(S.save + '/' + c.id + '/delete', {scope: c.scope}); location.reload(); } catch (err) { toast(err.message, 'error'); }
    }
  });
  fill({type: S.order[0]});
})();
