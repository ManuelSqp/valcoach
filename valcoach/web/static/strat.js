// valcoach strat board: the minimap with agents, abilities, smokes, walls, arrows, lines and text,
// in steps. Board coordinates are 0..1000 on the map image (same as the round replay).
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg', S = 1000;
  const COL = {us: '#2dd4bf', them: '#ff4655', you: '#f6d24a', smoke: '#c8d0dc', molly: '#ff8a3d', zone: '#a78bfa', wall: '#7dd3fc', mark: '#f2b84b', text: '#ffffff'};
  const TOOLS = [
    ['select', '↖', 'Select / move (V)'], ['arrow', '➜', 'Arrow (A)'], ['pen', '✎', 'Draw a path (P)'], ['wall', '▬', 'Wall (W)'],
    ['text', 'T', 'Text (T)'],
  ];
  const SHAPES = [   // dropped like icons (smokes, mollies etc. come from the agents' abilities now, at their real size)
    ['zone', 'Generic zone', 5], ['mark', 'Marker'], ['num', 'Number'],
  ];
  const B = JSON.parse(document.getElementById('strat-boot').textContent);
  const M = B.assets.map, PER_M = M.m || 7;
  const $ = s => document.querySelector(s);
  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const h = (tag, attrs, html) => { const e = document.createElement(tag); for (const k in attrs || {}) e.setAttribute(k, attrs[k]); if (html !== undefined) e.innerHTML = html; return e; };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const agentIcon = a => B.agent_icon.replace('__A__', encodeURIComponent(a));
  const abilityIcon = (a, s) => B.ability_icon.replace('__A__', encodeURIComponent(a)).replace('__S__', encodeURIComponent(s));
  const uid = () => Math.random().toString(36).slice(2, 9);
  const AG = Object.fromEntries(B.assets.agents.map(a => [a.name, a]));
  const abInfo = i => ((AG[i.a] || {}).abilities || []).find(x => x.slot === i.s) || null;
  const shapeOf = i => { const a = abInfo(i); return a && a.shape ? a.shape : null; };
  const agCol = a => (AG[a] && AG[a].color) || '#9aa4b2';
  const R2D = 180 / Math.PI;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  // the size an ability is drawn at: the item's own value, else the catalog's
  // board data comes from any team member: numbers that end up in HTML are forced to be numbers
  const num = (v, d) => { const x = Number(v); return Number.isFinite(x) ? x : d; };
  const abR = (i, sh) => i.r !== undefined && i.r !== null ? num(i.r, 0) : (sh && sh.r) || 0;
  const abLen = (i, sh) => i.len !== undefined && i.len !== null ? num(i.len, 10) : (sh && sh.len) || 10;
  const abEnd = (i, sh) => { const d = ((sh.off || 0) + abLen(i, sh)) * PER_M, a = (i.ang || 0) / R2D; return [i.x + Math.cos(a) * d, i.y + Math.sin(a) * d]; };

  // ------------------------------------------------------------------ state
  const st = B.strat;
  const data = st.data && st.data.steps && st.data.steps.length ? st.data : {steps: [{name: 'Setup', items: []}], notes: ''};
  data.notes = data.notes || '';
  let step = 0, tool = 'select', team = st.side === 'defense' ? 'us' : 'us', sel = null;
  let showPrev = true, showCallouts = true, activeAgent = null, dirty = false, saveTimer = null;
  const undo = [], redo = [];
  const items = () => data.steps[step].items;
  const find = id => items().find(i => i.id === id);
  function snapshot() { undo.push(JSON.stringify({data, step})); if (undo.length > 120) undo.shift(); redo.length = 0; }
  function changed() { dirty = true; setStatus('unsaved'); clearTimeout(saveTimer); saveTimer = setTimeout(save, 1500); }

  // ------------------------------------------------------------------ layout
  const root = $('#strat');
  const svg = el('svg', {viewBox: `0 0 ${S} ${S}`, class: 'sb-svg', role: 'img', 'aria-label': 'Strat board',
                         'font-family': 'ui-sans-serif, system-ui, Segoe UI, Helvetica, Arial, sans-serif'}, $('#sb-stage'));
  const defs = el('defs', {}, svg);
  el('circle', {cx: .5, cy: .5, r: .5}, el('clipPath', {id: 'sb-clip', clipPathUnits: 'objectBoundingBox'}, defs));
  for (const [k, c] of Object.entries({us: COL.us, them: COL.them, mark: COL.mark, text: COL.text})) {
    const m = el('marker', {id: `sb-ar-${k}`, viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse'}, defs);
    el('path', {d: 'M0,0 L10,5 L0,10 z', fill: c}, m);
  }
  // smoke texture (valoplant-like clouds): fractal noise, used as a light overlay inside each smoke
  const fN = el('filter', {id: 'sb-noise', x: '-5%', y: '-5%', width: '110%', height: '110%'}, defs);
  el('feTurbulence', {type: 'fractalNoise', baseFrequency: '0.035', numOctaves: 3, seed: 7}, fN);
  el('feColorMatrix', {type: 'matrix', values: '0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  1.8 0 0 0 -0.75'}, fN);
  el('feComposite', {in2: 'SourceGraphic', operator: 'in'}, fN);
  const grads = {};
  function shade(hex, f) {            // f > 0 lighter, f < 0 darker
    const n = parseInt(hex.slice(1), 16), ch = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.round(f > 0 ? v + (255 - v) * f : v * (1 + f)));
    return '#' + ch.map(v => v.toString(16).padStart(2, '0')).join('');
  }
  function grad(c) {
    const id = 'sb-gr-' + c.slice(1);
    if (!grads[id]) {
      const rg = el('radialGradient', {id, cx: '42%', cy: '38%', r: '62%'}, defs);
      el('stop', {offset: '0%', 'stop-color': shade(c, .45)}, rg);
      el('stop', {offset: '60%', 'stop-color': c}, rg);
      el('stop', {offset: '100%', 'stop-color': shade(c, -.45)}, rg);
      grads[id] = 1;
    }
    return `url(#${id})`;
  }
  const world = el('g', {}, svg);
  const mapImg = el('image', {href: B.map_image, x: 0, y: 0, width: S, height: S, preserveAspectRatio: 'none', opacity: .9}, world);
  mapImg.addEventListener('error', () => { mapImg.remove(); $('#sb-nomap').hidden = false; });
  const gCall = el('g', {'font-size': 15, fill: '#dfe6f2', 'text-anchor': 'middle', opacity: .55, 'pointer-events': 'none'}, world);
  for (const c of M.callouts || []) { const t = el('text', {x: c.u * S, y: c.v * S, stroke: '#0b0e13', 'stroke-width': 3, 'paint-order': 'stroke'}, gCall); t.textContent = c.label; }
  const gPrev = el('g', {opacity: .28, 'pointer-events': 'none', class: 'sb-prev'}, world);
  const g = el('g', {}, world);
  const gHandles = el('g', {}, world);
  let view = {x: 0, y: 0, w: S};
  const setView = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.w}`);

  function pt(evt) {
    const p = svg.createSVGPoint(); p.x = evt.clientX; p.y = evt.clientY;
    const r = p.matrixTransform(world.getScreenCTM().inverse());
    return [Math.max(0, Math.min(S, r.x)), Math.max(0, Math.min(S, r.y))];
  }

  // ------------------------------------------------------------------ drawing
  function color(i) { return COL[i.c] || COL.us; }
  function token(parent, i, isPrev) {
    const grp = el('g', {'data-id': i.id, class: 'sb-item' + (sel === i.id && !isPrev ? ' sel' : '')}, parent);
    const c = color(i);
    if (i.t === 'agent') {
      const r = 22;
      el('circle', {cx: i.x, cy: i.y, r: r + 3, fill: '#0b0e13'}, grp);
      const t = el('text', {x: i.x, y: i.y + 7, 'text-anchor': 'middle', 'font-size': 20, 'font-weight': 700, fill: '#fff'}, grp);
      t.textContent = (i.a || '?')[0];
      const im = el('image', {href: agentIcon(i.a), x: i.x - r, y: i.y - r, width: 2 * r, height: 2 * r, 'clip-path': 'url(#sb-clip)'}, grp);
      im.addEventListener('error', () => im.remove());
      el('circle', {cx: i.x, cy: i.y, r, fill: 'none', stroke: c, 'stroke-width': 5}, grp);
      if (i.label) {
        const lt = el('text', {x: i.x, y: i.y + r + 20, 'text-anchor': 'middle', 'font-size': 16, 'font-weight': 700, fill: '#fff',
                               stroke: '#0b0e13', 'stroke-width': 4, 'paint-order': 'stroke'}, grp);
        lt.textContent = i.label;
      }
    } else if (i.t === 'ab') {
      drawAbility(grp, i, c);
    } else if (i.t === 'smoke' || i.t === 'molly' || i.t === 'zone') {
      const cc = COL[i.t];
      el('circle', {cx: i.x, cy: i.y, r: (i.r || 4.5) * PER_M, fill: cc, opacity: i.t === 'smoke' ? .55 : .35, stroke: cc, 'stroke-width': 3}, grp);
      if (i.t !== 'smoke') el('circle', {cx: i.x, cy: i.y, r: 3, fill: cc}, grp);
    } else if (i.t === 'wall') {
      el('line', {x1: i.x, y1: i.y, x2: i.x2, y2: i.y2, stroke: COL.wall, 'stroke-width': 9, 'stroke-linecap': 'round', opacity: .85}, grp);
    } else if (i.t === 'arrow') {
      el('line', {x1: i.x, y1: i.y, x2: i.x2, y2: i.y2, stroke: c, 'stroke-width': 6, 'stroke-linecap': 'round',
                  'stroke-dasharray': i.dash ? '14 10' : null, 'marker-end': `url(#sb-ar-${i.c === 'them' ? 'them' : 'us'})`}, grp);
    } else if (i.t === 'pen') {
      el('polyline', {points: i.pts.map(p => p.join(',')).join(' '), fill: 'none', stroke: c, 'stroke-width': 5,
                      'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-dasharray': i.dash ? '12 9' : null}, grp);
    } else if (i.t === 'text') {
      const t = el('text', {x: i.x, y: i.y, 'text-anchor': 'middle', 'font-size': i.size || 22, 'font-weight': 700, fill: c === COL.us ? '#fff' : c,
                            stroke: '#0b0e13', 'stroke-width': 5, 'paint-order': 'stroke'}, grp);
      t.textContent = i.s || 'Text';
    } else if (i.t === 'mark' || i.t === 'num') {
      el('circle', {cx: i.x, cy: i.y, r: 15, fill: i.t === 'num' ? c : COL.mark, stroke: '#0b0e13', 'stroke-width': 3}, grp);
      const t = el('text', {x: i.x, y: i.y + 6, 'text-anchor': 'middle', 'font-size': 17, 'font-weight': 800, fill: '#0b0e13'}, grp);
      t.textContent = i.t === 'num' ? (i.n || 1) : (i.s || '!');
    }
    return grp;
  }
  function abIcon(grp, i, x, y, r, ring) {
    if (ring) el('circle', {cx: x, cy: y, r: r + 2, fill: '#0b0e13', stroke: ring, 'stroke-width': 3}, grp);
    const im = el('image', {href: abilityIcon(i.a, i.s), x: x - r + 4, y: y - r + 4, width: 2 * r - 8, height: 2 * r - 8}, grp);
    im.addEventListener('error', () => { im.remove(); const t = el('text', {x, y: y + 5, 'text-anchor': 'middle', 'font-size': 13, fill: '#fff', 'font-weight': 700}, grp); t.textContent = (i.s || '?').replace('Ability', '').slice(0, 2); });
  }
  // c = team colour (outline), ac = agent colour (fill): you see whose smoke it is and whose side
  function drawAbility(grp, i, c) {
    const sh = shapeOf(i), ac = agCol(i.a), k = sh ? sh.k : (i.r ? 'old' : null);
    if (k === 'smoke') {
      const r = abR(i, sh) * PER_M;
      if (r > 0) {
        el('circle', {cx: i.x, cy: i.y, r, fill: grad(ac), opacity: .9}, grp);
        el('circle', {cx: i.x, cy: i.y, r, fill: '#fff', opacity: .22, filter: 'url(#sb-noise)'}, grp);
        el('circle', {cx: i.x, cy: i.y, r, fill: 'none', stroke: c, 'stroke-width': 2.5, opacity: .95}, grp);
        abIcon(grp, i, i.x, i.y, Math.min(13, r * .55), null);
        return;
      }
    } else if (k === 'area' || k === 'old') {
      const r = abR(i, sh) * PER_M, col = k === 'old' ? c : ac;
      if (r > 0) {
        el('circle', {cx: i.x, cy: i.y, r, fill: col, opacity: .24}, grp);
        el('circle', {cx: i.x, cy: i.y, r, fill: 'none', stroke: col, 'stroke-width': 3, 'stroke-dasharray': k === 'old' ? '6 5' : null, opacity: .9}, grp);
      }
    } else if (k === 'strip' || k === 'wall' || k === 'lane') {
      const len = abLen(i, sh) * PER_M, off = (sh.off || 0) * PER_M, w = (sh.w || 1) * PER_M;
      const rg = el('g', {transform: `translate(${i.x} ${i.y}) rotate(${i.ang || 0})`}, grp);
      if (k === 'strip') {
        el('rect', {x: off, y: -w / 2, width: len, height: w, rx: Math.min(w / 2, 10), fill: ac, opacity: .3}, rg);
        el('rect', {x: off, y: -w / 2, width: len, height: w, rx: Math.min(w / 2, 10), fill: 'none', stroke: ac, 'stroke-width': 3, opacity: .95}, rg);
        for (let d = off + 40; d < off + len - 10; d += 55)        // chevrons: which way it travels
          el('path', {d: `M${d - 9},${-Math.min(w / 3, 14)} L${d + 3},0 L${d - 9},${Math.min(w / 3, 14)}`, fill: 'none', stroke: '#fff', 'stroke-width': 2.5, opacity: .55, 'stroke-linecap': 'round'}, rg);
      } else if (k === 'wall') {
        const ww = Math.max(6, w);
        el('line', {x1: 0, y1: 0, x2: len, y2: 0, stroke: '#0b0e13', 'stroke-width': ww + 5, 'stroke-linecap': 'round', opacity: .6}, rg);
        el('line', {x1: 0, y1: 0, x2: len, y2: 0, stroke: ac, 'stroke-width': ww, 'stroke-linecap': 'round', opacity: .95}, rg);
      } else {
        el('rect', {x: 0, y: -w / 2, width: len, height: w, fill: ac, opacity: .14}, rg);
        for (const yy of [-w / 2, w / 2]) el('line', {x1: 0, y1: yy, x2: len, y2: yy, stroke: ac, 'stroke-width': 6, 'stroke-linecap': 'round', opacity: .95}, rg);
      }
    }
    abIcon(grp, i, i.x, i.y, k === 'area' || k === 'old' ? 15 : 16, c);
  }
  function handles(i) {
    while (gHandles.firstChild) gHandles.removeChild(gHandles.firstChild);
    if (!i) return;
    const hh = (x, y, k, cur) => el('circle', {cx: x, cy: y, r: 9, class: 'sb-h', 'data-h': k, fill: '#fff', stroke: '#0b0e13', 'stroke-width': 3, style: `cursor:${cur}`}, gHandles);
    if (i.t === 'arrow' || i.t === 'wall') { hh(i.x, i.y, 'p1', 'move'); hh(i.x2, i.y2, 'p2', 'move'); }
    if (i.t === 'smoke' || i.t === 'molly' || i.t === 'zone') hh(i.x + (i.r || 4.5) * PER_M, i.y, 'r', 'ew-resize');
    if (i.t === 'ab') {
      const sh = shapeOf(i), k = sh ? sh.k : (i.r ? 'old' : null);
      if (k === 'smoke' || k === 'area' || k === 'old') { if (abR(i, sh) > 0) hh(i.x + abR(i, sh) * PER_M, i.y, 'r', 'ew-resize'); }
      else if (k) { const [ex, ey] = abEnd(i, sh); hh(ex, ey, 'e', sh.min === sh.max ? 'grab' : 'crosshair').setAttribute('fill', '#ffe08a'); }
    }
  }
  function draw() {
    while (g.firstChild) g.removeChild(g.firstChild);
    while (gPrev.firstChild) gPrev.removeChild(gPrev.firstChild);
    gCall.style.display = showCallouts ? '' : 'none';
    if (showPrev && step > 0) for (const i of data.steps[step - 1].items) token(gPrev, i, true);
    // areas and lines first, icons on top
    const order = i => ({smoke: 0, molly: 0, zone: 0, wall: 1, pen: 1, arrow: 2, ab: 3, agent: 4, mark: 5, num: 5, text: 6}[i.t] ?? 3);
    for (const i of [...items()].sort((a, b) => order(a) - order(b))) token(g, i, false);
    handles(find(sel));
    renderSteps(); renderProps();
  }

  // ------------------------------------------------------------------ palette
  function renderPalette() {
    const pal = $('#sb-agents');
    pal.innerHTML = '';
    let role = null;
    for (const a of B.assets.agents) {
      if (a.role !== role) { role = a.role; pal.appendChild(h('div', {class: 'sb-role'}, esc(role || 'Other'))); }
      const b = h('button', {class: 'sb-pal agent' + (activeAgent === a.name ? ' on' : ''), 'data-kind': 'agent', 'data-a': a.name, title: `${a.name}: drag onto the map, click for abilities`},
                  `<span class="ini">${esc(a.name[0])}</span><img src="${agentIcon(a.name)}" alt="" onerror="this.remove()">`);
      pal.appendChild(b);
    }
    const abl = $('#sb-abilities');
    const ag = B.assets.agents.find(a => a.name === activeAgent);
    abl.innerHTML = ag ? `<div class="sb-role">${esc(ag.name)} abilities</div>` : '<div class="muted small">Click an agent to see its abilities.</div>';
    if (ag && !ag.abilities.length) abl.innerHTML += '<div class="muted small">No ability data (offline). Use the shapes below.</div>';
    if (ag) abl.appendChild(abilityBar(ag));
  }
  const KIND = {smoke: 'smoke', area: 'area', strip: 'aim + stretch', wall: 'wall', lane: 'walls'};
  function abilityBar(ag) {
    const box = h('div', {class: 'sb-abar'});
    for (const ab of ag.abilities) {
      const sh = ab.shape, size = sh ? (sh.r ? `${sh.r} m` : `${sh.min === sh.max ? sh.len : sh.min + '–' + sh.max} m`) : '';
      const b = h('button', {class: 'sb-pal ab', 'data-kind': 'ab', 'data-a': ag.name, 'data-s': ab.slot, style: `border-color:${ag.color || '#333b4a'}`,
                             title: `${ab.name}${sh ? ` · ${KIND[sh.k]} ${size}${sh.approx ? ' (approx.)' : ''}` : ''}: drag onto the map, or click to place it at ${ag.name}`},
        `<span class="ini">${esc(ab.slot.replace('Ability', '').slice(0, 2))}</span><img src="${abilityIcon(ag.name, ab.slot)}" alt="" onerror="this.remove()"><small>${esc(ab.name)}</small>`);
      box.appendChild(b);
    }
    return box;
  }
  // a click on an ability (no drag): strips and walls start at that agent on the board, smokes/areas a bit in front
  function placeAbility(ds) {
    const ag = items().filter(i => i.t === 'agent' && i.a === ds.a).pop();
    let x = view.x + view.w / 2, y = view.y + view.w / 2;
    if (ag) { x = ag.x; y = ag.y; }
    const it = newItem('ab', x, y, ds), sh = shapeOf(it);
    if (ag && (!sh || !('len' in sh))) {
      const a = Math.atan2(S / 2 - y, S / 2 - x), d = sh ? Math.max(70, abR(it, sh) * PER_M + 40) : 50;
      it.x = Math.round(clamp(x + Math.cos(a) * d, 0, S)); it.y = Math.round(clamp(y + Math.sin(a) * d, 0, S));
    }
    snapshot(); items().push(it); sel = it.id; changed(); draw();
  }
  function renderShapes() {
    const sh = $('#sb-shapes');
    sh.innerHTML = '';
    for (const [k, label] of SHAPES) sh.appendChild(h('button', {class: 'sb-pal shape ' + k, 'data-kind': k, title: `${label}: drag onto the map`}, `<i></i><small>${label.split(' ')[0]}</small>`));
    const tl = $('#sb-tools');
    tl.innerHTML = '';
    for (const [k, icon, label] of TOOLS) {
      const b = h('button', {class: 'sb-tool' + (tool === k ? ' on' : ''), 'data-tool': k, title: label}, icon);
      b.onclick = () => setTool(k);
      tl.appendChild(b);
    }
  }
  function setTool(k) { tool = k; renderShapes(); svg.style.cursor = k === 'select' ? 'default' : 'crosshair'; }
  document.querySelectorAll('[data-team]').forEach(b => b.onclick = () => {
    team = b.dataset.team; document.querySelectorAll('[data-team]').forEach(x => x.classList.toggle('on', x === b));
    const i = find(sel); if (i && 'c' in i) { snapshot(); i.c = team; changed(); draw(); }
  });

  function newItem(kind, x, y, dataset) {
    const base = {id: uid(), x: Math.round(x), y: Math.round(y)};
    if (kind === 'agent') return {...base, t: 'agent', a: dataset.a, c: team};
    if (kind === 'ab') {
      const it = {...base, t: 'ab', a: dataset.a, s: dataset.s, c: team}, sh = shapeOf(it);
      if (sh && 'len' in sh) { it.len = sh.len; it.ang = Math.round(Math.atan2(S / 2 - y, S / 2 - x) * R2D); }
      return it;
    }
    if (kind === 'zone') return {...base, t: 'zone', r: 5};
    if (kind === 'mark') return {...base, t: 'mark', s: '!'};
    if (kind === 'num') return {...base, t: 'num', c: team, n: items().filter(i => i.t === 'num').length + 1};
    return null;
  }

  // drag from the palette onto the board (pointer events: mouse, pen and touch)
  let pdrag = null;
  document.addEventListener('pointerdown', e => {
    const b = e.target.closest('.sb-pal'); if (!b) return;
    e.preventDefault();
    const ghost = b.cloneNode(true); ghost.classList.add('sb-ghost'); document.body.appendChild(ghost);
    pdrag = {b, ghost, moved: false, x0: e.clientX, y0: e.clientY};
    moveGhost(e);
  });
  function moveGhost(e) { if (pdrag) { pdrag.ghost.style.left = e.clientX + 'px'; pdrag.ghost.style.top = e.clientY + 'px'; } }
  window.addEventListener('pointermove', e => { if (!pdrag) return; if (Math.abs(e.clientX - pdrag.x0) + Math.abs(e.clientY - pdrag.y0) > 4) pdrag.moved = true; moveGhost(e); });
  window.addEventListener('pointerup', e => {
    if (!pdrag) return;
    const {b, ghost, moved} = pdrag; pdrag = null; ghost.remove();
    if (!moved) {                                   // a click: agents show their abilities
      if (b.dataset.kind === 'agent') { activeAgent = b.dataset.a; renderPalette(); }
      else if (b.dataset.kind === 'ab') placeAbility({a: b.dataset.a, s: b.dataset.s});
      return;
    }
    const r = svg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return;
    const [x, y] = pt(e);
    const it = newItem(b.dataset.kind, x, y, b.dataset);
    if (!it) return;
    if (b.dataset.kind === 'agent') { activeAgent = b.dataset.a; renderPalette(); }
    snapshot(); items().push(it); sel = it.id; changed(); draw();
  });

  // ------------------------------------------------------------------ board interaction
  let drag = null;
  svg.addEventListener('dragstart', e => e.preventDefault());   // no native image drag (it cancels the pointer)
  svg.addEventListener('pointerdown', e => {
    if (e.button === 1) return;
    e.preventDefault();                            // (this also stops the focus from moving, so do it by hand)
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    const [x, y] = pt(e);
    const hEl = e.target.closest('.sb-h');
    if (hEl) { snapshot(); drag = {mode: 'handle', k: hEl.dataset.h, id: sel}; svg.setPointerCapture(e.pointerId); return; }
    const itEl = e.target.closest('.sb-item');
    if (tool === 'select') {
      if (itEl && itEl.parentNode === g) {
        sel = itEl.dataset.id; snapshot();
        drag = {mode: 'move', id: sel, x0: x, y0: y, orig: JSON.parse(JSON.stringify(find(sel))), moved: false};
      } else {
        sel = null;
        drag = view.w < S ? {mode: 'pan', cx: e.clientX, cy: e.clientY, vx: view.x, vy: view.y} : null;
      }
      svg.setPointerCapture(e.pointerId); draw(); return;
    }
    snapshot();
    let it = null;
    const rx = Math.round(x), ry = Math.round(y);
    if (tool === 'arrow') it = {id: uid(), t: 'arrow', x: rx, y: ry, x2: rx, y2: ry, c: team};
    else if (tool === 'wall') it = {id: uid(), t: 'wall', x: rx, y: ry, x2: rx, y2: ry};
    else if (tool === 'pen') it = {id: uid(), t: 'pen', pts: [[Math.round(x), Math.round(y)]], c: team};
    else if (tool === 'text') { it = {id: uid(), t: 'text', x: Math.round(x), y: Math.round(y), s: 'Text', c: team}; items().push(it); sel = it.id; changed(); setTool('select'); draw(); focusText(); return; }
    if (it) { items().push(it); sel = it.id; drag = {mode: 'draw', id: it.id}; svg.setPointerCapture(e.pointerId); draw(); }
  });
  svg.addEventListener('pointermove', e => {
    if (!drag) return;
    if (drag.mode === 'pan') {
      const r = svg.getBoundingClientRect();
      view.x = Math.max(0, Math.min(S - view.w, drag.vx - (e.clientX - drag.cx) / r.width * view.w));
      view.y = Math.max(0, Math.min(S - view.w, drag.vy - (e.clientY - drag.cy) / r.height * view.w));
      setView(); return;
    }
    const [x, y] = pt(e), i = find(drag.id); if (!i) return;
    if (drag.mode === 'move') {
      const dx = x - drag.x0, dy = y - drag.y0, o = drag.orig; drag.moved = true;
      if (i.t === 'pen') i.pts = o.pts.map(p => [Math.round(p[0] + dx), Math.round(p[1] + dy)]);
      else { i.x = Math.round(o.x + dx); i.y = Math.round(o.y + dy); if ('x2' in o) { i.x2 = Math.round(o.x2 + dx); i.y2 = Math.round(o.y2 + dy); } }
    } else if (drag.mode === 'draw') {
      if (i.t === 'pen') { const l = i.pts[i.pts.length - 1]; if (Math.hypot(l[0] - x, l[1] - y) > 6) i.pts.push([Math.round(x), Math.round(y)]); }
      else { i.x2 = Math.round(x); i.y2 = Math.round(y); }
    } else if (drag.mode === 'handle') {
      if (drag.k === 'p1') { i.x = Math.round(x); i.y = Math.round(y); }
      else if (drag.k === 'p2') { i.x2 = Math.round(x); i.y2 = Math.round(y); }
      else if (drag.k === 'r') i.r = Math.max(1, Math.round(Math.hypot(x - i.x, y - i.y) / PER_M * 10) / 10);
      else if (drag.k === 'e') {                 // aim (and stretch, where the ability can) from where it's cast
        const sh = shapeOf(i) || {};
        i.ang = Math.round(Math.atan2(y - i.y, x - i.x) * R2D);
        if (sh.min !== sh.max) i.len = Math.round(clamp(Math.hypot(x - i.x, y - i.y) / PER_M - (sh.off || 0), sh.min || 1, sh.max || 200) * 2) / 2;
      }
    }
    draw();
  });
  const endDrag = () => {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.mode === 'draw') {
      const i = find(d.id);
      const tiny = i && ((i.t === 'pen' && i.pts.length < 2) || (i.t !== 'pen' && Math.hypot(i.x2 - i.x, i.y2 - i.y) < 12));
      if (tiny) { undo.pop(); data.steps[step].items = items().filter(x => x.id !== d.id); sel = null; draw(); return; }
      changed();
    } else if (d.mode === 'move' && !d.moved) undo.pop();
    else if (d.mode !== 'pan') changed();
  };
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('wheel', e => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault(); const [x, y] = pt(e); zoom(e.deltaY > 0 ? 1.2 : 1 / 1.2, x, y);
  }, {passive: false});
  function zoom(f, cx = view.x + view.w / 2, cy = view.y + view.w / 2) {
    const w = Math.max(200, Math.min(S, view.w * f));
    view = {x: Math.max(0, Math.min(S - w, cx - (cx - view.x) * w / view.w)), y: Math.max(0, Math.min(S - w, cy - (cy - view.y) * w / view.w)), w};
    setView();
  }
  $('#sb-zin').onclick = () => zoom(1 / 1.35); $('#sb-zout').onclick = () => zoom(1.35);
  $('#sb-zfit').onclick = () => { view = {x: 0, y: 0, w: S}; setView(); };

  // ------------------------------------------------------------------ properties
  function renderProps() {
    const p = $('#sb-props'), i = find(sel);
    if (!i) { p.innerHTML = '<div class="muted small">Select something on the map to change it. Delete with <kbd>Del</kbd>, copy with <kbd>Ctrl</kbd>+<kbd>D</kbd>.</div>'; return; }
    const ai = i.t === 'ab' ? abInfo(i) : null, sh = i.t === 'ab' ? shapeOf(i) : null;
    const name = {agent: i.a, ab: `${i.a} · ${ai ? ai.name : i.s}`, smoke: 'Smoke', molly: 'Molly', zone: 'Zone', wall: 'Wall', arrow: 'Arrow', pen: 'Path', text: 'Text', mark: 'Marker', num: 'Number'}[i.t];
    let html = `<div class="sb-ph"><b>${esc(name)}</b><button class="btn sm ghost danger" id="sb-del" title="Delete (Del)">Delete</button></div>`;
    if (i.t === 'agent') html += `<label>Player</label><select id="sb-label"><option value="">—</option>${B.lineup.map(n => `<option ${n === i.label ? 'selected' : ''}>${esc(n)}</option>`).join('')}<option value="__custom" ${i.label && !B.lineup.includes(i.label) ? 'selected' : ''}>other…</option></select>
                                 <input type="text" id="sb-label-custom" placeholder="name" value="${esc(i.label && !B.lineup.includes(i.label) ? i.label : '')}" ${i.label && !B.lineup.includes(i.label) ? '' : 'hidden'} maxlength="20">`;
    if (i.t === 'text') html += `<label>Text</label><input type="text" id="sb-text" value="${esc(i.s)}" maxlength="60">`;
    if (i.t === 'mark') html += `<label>Symbol</label><select id="sb-mark">${['!', '?', 'X', '★', '👁'].map(s => `<option ${s === i.s ? 'selected' : ''}>${s}</option>`).join('')}</select>`;
    if (i.t === 'num') html += `<label>Number</label><input type="number" id="sb-num" value="${num(i.n, 1) || 1}" min="1" max="99">`;
    if (['smoke', 'molly', 'zone'].includes(i.t) || (i.t === 'ab' && (!sh || sh.k === 'smoke' || sh.k === 'area')))
      html += `<label>${i.t === 'ab' && !sh ? 'Show area (radius m, 0 = icon only)' : 'Radius (m)'}</label><div class="row" style="gap:4px;flex-wrap:nowrap"><input type="number" id="sb-r" value="${i.t === 'ab' ? abR(i, sh) : num(i.r, 0)}" step="0.1" min="0" max="60">${sh && i.r != null && i.r !== sh.r ? `<button class="btn sm ghost" id="sb-reset" title="Back to ${sh.r} m">↺ ${sh.r} m</button>` : ''}</div>`;
    if (sh && 'len' in sh) {
      html += `<label>${sh.min === sh.max ? 'Length' : `Length (${sh.min}–${sh.max} m)`}</label><input type="number" id="sb-len" value="${abLen(i, sh)}" step="0.5" min="${sh.min}" max="${sh.max}" ${sh.min === sh.max ? 'disabled' : ''}>
               <label>Direction (°)</label><input type="number" id="sb-ang" value="${num(i.ang, 0)}" step="5">
               <div class="muted small" style="margin-top:4px">Drag the yellow handle to aim${sh.min === sh.max ? '' : ' and stretch'} it.</div>`;
    }
    if (i.t === 'ab') html += `<div class="muted small" style="margin-top:6px">${sh ? `${KIND[sh.k]}${sh.w ? `, ${sh.w} m wide` : ''}${sh.off ? `, starts ${sh.off} m ahead` : ''} · ${sh.approx ? 'size ≈ estimated, adjust if needed' : 'size from the Valorant wiki'}` : 'no size data: icon only'}</div>`;
    if (i.t === 'ab' && B.lineups) {               // lineups from the library for this ability on this map
      const ls = B.lineups.filter(l => l.agent === i.a && (!l.ability || !ai || l.ability === ai.name));
      html += `<label>Lineups (${ls.length})</label>` + (ls.length
        ? ls.slice(0, 6).map(l => /^https?:\/\//.test(l.url) ? `<a class="small" style="display:block" href="${esc(l.url)}" target="_blank" rel="noopener">▶ ${esc(l.title)}</a>`
                                                               : `<span class="small" style="display:block">${esc(l.title)}</span>`).join('')
        : `<a class="small" href="${esc(B.lineups_url)}" target="_blank" rel="noopener">add one to the library</a>`);
    }
    const barAgent = i.t === 'agent' ? AG[i.a] : i.t === 'ab' ? AG[i.a] : null;
    if (barAgent && barAgent.abilities.length) html += `<label>${esc(barAgent.name)}'s abilities: drag or click</label><div id="sb-propbar"></div>`;
    if (i.t === 'arrow' || i.t === 'pen') html += `<label class="sb-check"><input type="checkbox" id="sb-dash" ${i.dash ? 'checked' : ''}> dashed (e.g. a rotate or a lurk)</label>`;
    if ('c' in i) html += `<label>Team</label><div class="row" style="gap:4px"><button class="btn sm ${i.c === 'us' ? 'primary' : 'ghost'}" data-setc="us">Us</button><button class="btn sm ${i.c === 'them' ? 'primary' : 'ghost'}" data-setc="them">Enemy</button></div>`;
    p.innerHTML = html;
    const on = (id, ev, fn) => { const x = document.getElementById(id); if (x) x.addEventListener(ev, fn); };
    on('sb-del', 'click', del);
    on('sb-label', 'change', e => { const c = document.getElementById('sb-label-custom'); if (e.target.value === '__custom') { c.hidden = false; c.focus(); } else { set('label', e.target.value); } });
    on('sb-label-custom', 'change', e => set('label', e.target.value.trim()));
    on('sb-text', 'input', e => set('s', e.target.value, true));
    on('sb-mark', 'change', e => set('s', e.target.value));
    on('sb-num', 'change', e => set('n', Math.max(1, +e.target.value || 1)));
    on('sb-r', 'change', e => set('r', Math.max(0, +e.target.value || 0)));
    on('sb-reset', 'click', () => set('r', sh.r));
    on('sb-len', 'change', e => set('len', clamp(+e.target.value || sh.len, sh.min, sh.max)));
    on('sb-ang', 'change', e => set('ang', ((Math.round(+e.target.value || 0) % 360) + 540) % 360 - 180));
    if (barAgent && document.getElementById('sb-propbar')) document.getElementById('sb-propbar').appendChild(abilityBar(barAgent));
    on('sb-dash', 'change', e => set('dash', e.target.checked));
    p.querySelectorAll('[data-setc]').forEach(b => b.onclick = () => set('c', b.dataset.setc));
  }
  let typing = null;
  function set(k, v, keepFocus) {
    const i = find(sel); if (!i) return;
    if (!keepFocus || typing !== sel) { snapshot(); typing = keepFocus ? sel : null; }
    i[k] = v; changed();
    if (keepFocus) { while (g.firstChild) g.removeChild(g.firstChild); for (const it of items()) token(g, it, false); handles(i); } else draw();
  }
  function focusText() { const t = document.getElementById('sb-text'); if (t) { t.focus(); t.select(); } }
  function del() { if (!sel) return; snapshot(); data.steps[step].items = items().filter(i => i.id !== sel); sel = null; changed(); draw(); }
  function dup() {
    const i = find(sel); if (!i) return; snapshot();
    const c = JSON.parse(JSON.stringify(i)); c.id = uid();
    if (c.pts) c.pts = c.pts.map(p => [p[0] + 25, p[1] + 25]); else { c.x += 25; c.y += 25; if ('x2' in c) { c.x2 += 25; c.y2 += 25; } }
    items().push(c); sel = c.id; changed(); draw();
  }

  // ------------------------------------------------------------------ steps
  function renderSteps() {
    const box = $('#sb-steps');
    box.innerHTML = '';
    data.steps.forEach((s, n) => {
      const b = h('button', {class: 'sb-step' + (n === step ? ' on' : ''), title: 'Open this step'}, `<b>${n + 1}</b> ${esc(s.name || 'Step ' + (n + 1))} <span class="muted">${s.items.length}</span>`);
      b.onclick = () => { step = n; sel = null; draw(); };
      box.appendChild(b);
    });
    $('#sb-stepname').value = data.steps[step].name || '';
    $('#sb-stepdel').disabled = data.steps.length < 2;
    $('#sb-left').disabled = step === 0; $('#sb-right').disabled = step === data.steps.length - 1;
  }
  $('#sb-stepadd').onclick = () => {        // a new step starts as a copy of this one: move what changes
    snapshot();
    const copy = JSON.parse(JSON.stringify(items())).map(i => ({...i, id: uid(), k: i.k || i.id}));   // k: playback moves it
    data.steps.splice(step + 1, 0, {name: `Step ${data.steps.length + 1}`, items: copy});
    step += 1; sel = null; changed(); draw();
    $('#sb-stepname').focus(); $('#sb-stepname').select();
  };
  $('#sb-stepdel').onclick = () => { if (data.steps.length < 2) return; snapshot(); data.steps.splice(step, 1); step = Math.max(0, step - 1); sel = null; changed(); draw(); };
  $('#sb-stepname').addEventListener('change', e => { snapshot(); data.steps[step].name = e.target.value.slice(0, 40); changed(); renderSteps(); });
  $('#sb-left').onclick = () => { if (step > 0) { snapshot(); [data.steps[step - 1], data.steps[step]] = [data.steps[step], data.steps[step - 1]]; step -= 1; changed(); draw(); } };
  $('#sb-right').onclick = () => { if (step < data.steps.length - 1) { snapshot(); [data.steps[step + 1], data.steps[step]] = [data.steps[step], data.steps[step + 1]]; step += 1; changed(); draw(); } };
  $('#sb-prev').onchange = e => { showPrev = e.target.checked; draw(); };
  $('#sb-callouts').onchange = e => { showCallouts = e.target.checked; draw(); };
  $('#sb-clear').onclick = () => { if (!items().length) return; snapshot(); data.steps[step].items = []; sel = null; changed(); draw(); };

  // ------------------------------------------------------------------ playback
  // Steps play as an animation: things that are in both steps move (agents walk, smokes slide),
  // new things fade in, removed things fade out. Same thing = same k (set when a step is copied),
  // else the same agent / ability / colour closest by.
  const MOVE_MS = 1300, HOLD_MS = 1100;
  let playing = null, speed = 1;
  const keyOf = i => i.k || i.id;
  function pairUp(a, b) {
    const used = new Set(), pairs = [], born = [];
    const byKey = new Map(a.map(i => [keyOf(i), i]));
    for (const i of b) {
      let m = byKey.get(i.k) || byKey.get(keyOf(i));
      if (m && (used.has(m.id) || m.t !== i.t)) m = null;
      if (!m && (i.t === 'agent' || i.t === 'ab')) {
        let best = null, bd = Infinity;
        for (const o of a) {
          if (used.has(o.id) || o.t !== i.t || o.a !== i.a || (o.s || '') !== (i.s || '') || (o.c || 'us') !== (i.c || 'us')) continue;
          const d = Math.hypot(o.x - i.x, o.y - i.y);
          if (d < bd) { bd = d; best = o; }
        }
        m = best;
      }
      if (m) { used.add(m.id); pairs.push([m, i]); } else born.push(i);
    }
    return {pairs, born, gone: a.filter(o => !used.has(o.id))};
  }
  const lerp = (p, q, t) => p + (q - p) * t;
  function tween(a, b, t) {
    const o = {...b};
    for (const k of ['x', 'y', 'x2', 'y2', 'r', 'len']) if (typeof a[k] === 'number' && typeof b[k] === 'number') o[k] = lerp(a[k], b[k], t);
    if (typeof a.ang === 'number' && typeof b.ang === 'number') { let d = ((b.ang - a.ang + 540) % 360) - 180; o.ang = a.ang + d * t; }
    if (a.pts && b.pts && a.pts.length === b.pts.length) o.pts = a.pts.map((p, n) => [lerp(p[0], b.pts[n][0], t), lerp(p[1], b.pts[n][1], t)]);
    return o;
  }
  const order = i => ({smoke: 0, molly: 0, zone: 0, wall: 1, pen: 1, arrow: 2, ab: 3, agent: 4, mark: 5, num: 5, text: 6}[i.t] ?? 3);
  function frame(list) {           // list: [[item, opacity]]
    while (g.firstChild) g.removeChild(g.firstChild);
    for (const [i, op] of list.sort((p, q) => order(p[0]) - order(q[0]))) {
      const grp = token(g, i, true);
      if (op < 1) grp.setAttribute('opacity', Math.max(0, op).toFixed(3));
    }
  }
  const ease = t => t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  const cap = $('#sb-caption'), pbtn = $('#sb-play');
  function caption(n) { cap.hidden = false; cap.textContent = `${n + 1}/${data.steps.length} · ${data.steps[n].name || 'Step ' + (n + 1)}`; }
  function stopPlay(at) {
    if (!playing) return;
    cancelAnimationFrame(playing.raf); playing = null;
    root.classList.remove('sb-playing'); cap.hidden = true; pbtn.textContent = '▶ Play'; pbtn.classList.remove('primary');
    if (at !== undefined) step = at;
    draw();
  }
  function startPlay() {
    if (data.steps.length < 2) { setStatus('add a second step to play'); return; }
    sel = null; handles(null);
    while (gPrev.firstChild) gPrev.removeChild(gPrev.firstChild);
    root.classList.add('sb-playing'); pbtn.textContent = '■ Stop'; pbtn.classList.add('primary');
    const from = step >= data.steps.length - 1 ? 0 : step;
    const seg = [];                 // [{kind: 'hold'|'move', n, ms}]
    seg.push({kind: 'hold', n: from, ms: HOLD_MS});
    for (let n = from; n < data.steps.length - 1; n++) { seg.push({kind: 'move', n, ms: MOVE_MS, pu: pairUp(data.steps[n].items, data.steps[n + 1].items)}); seg.push({kind: 'hold', n: n + 1, ms: HOLD_MS}); }
    let si = 0, t0 = performance.now(), shown = -1;
    playing = {raf: 0};
    const tick = now => {
      if (!playing) return;
      let s = seg[si], el2 = (now - t0) * speed;
      while (el2 >= s.ms) { si += 1; t0 = now; el2 = 0; if (si >= seg.length) { stopPlay(data.steps.length - 1); return; } s = seg[si]; }
      const t = el2 / s.ms;
      if (s.kind === 'hold') {
        if (shown !== s.n) { frame(data.steps[s.n].items.map(i => [i, 1])); caption(s.n); shown = s.n; step = s.n; renderSteps(); }
      } else {
        const e = ease(t);
        if (shown !== -2 - s.n) { caption(s.n + 1); shown = -2 - s.n; }
        frame([...s.pu.pairs.map(([a, b]) => [tween(a, b, e), 1]), ...s.pu.born.map(i => [i, Math.min(1, t * 1.6 - .4)]),
               ...s.pu.gone.map(i => [i, 1 - Math.min(1, t * 1.6)])]);
      }
      playing.raf = requestAnimationFrame(tick);
    };
    playing.raf = requestAnimationFrame(tick);
  }
  pbtn.onclick = () => playing ? stopPlay(step) : startPlay();
  $('#sb-speed').onchange = e => { speed = Number(e.target.value) || 1; };

  // ------------------------------------------------------------------ name, side, notes
  $('#sb-name').addEventListener('change', e => { st.name = e.target.value.trim() || 'Untitled'; document.title = st.name + ' · valcoach'; changed(); });
  $('#sb-side').addEventListener('change', e => { st.side = e.target.value; changed(); });
  $('#sb-notes').value = data.notes;
  $('#sb-notes').addEventListener('input', e => { data.notes = e.target.value.slice(0, 4000); changed(); });

  // ------------------------------------------------------------------ undo / keys
  function restore(from, to) {
    if (!from.length) return;
    to.push(JSON.stringify({data, step}));
    const s = JSON.parse(from.pop());
    data.steps = s.data.steps; data.notes = s.data.notes; step = Math.min(s.step, data.steps.length - 1); sel = null; changed(); draw();
  }
  $('#sb-undo').onclick = () => restore(undo, redo); $('#sb-redo').onclick = () => restore(redo, undo);
  window.addEventListener('keydown', e => {
    const typingNow = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if (playing && !typingNow && (e.key === 'Escape' || e.key === ' ' || e.key.startsWith('Arrow'))) { e.preventDefault(); stopPlay(step); return; }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
    if (typingNow) return;
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? restore(redo, undo) : restore(undo, redo); }
    else if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); restore(redo, undo); }
    else if (mod && e.key.toLowerCase() === 'd') { e.preventDefault(); dup(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { if (sel) { e.preventDefault(); del(); } }
    else if (e.key === 'Escape') { sel = null; setTool('select'); draw(); }
    else if (!mod) {
      const k = {v: 'select', a: 'arrow', p: 'pen', w: 'wall', t: 'text'}[e.key.toLowerCase()];
      if (k) setTool(k);
      if (e.key === 'ArrowRight' && step < data.steps.length - 1) { step += 1; sel = null; draw(); }
      if (e.key === 'ArrowLeft' && step > 0) { step -= 1; sel = null; draw(); }
    }
  });

  // ------------------------------------------------------------------ save
  function setStatus(s) { const x = $('#sb-status'); x.textContent = s; x.className = 'sb-status ' + s.split(' ')[0]; }
  async function save() {
    clearTimeout(saveTimer);
    if (!dirty) return;
    dirty = false; setStatus('saving…');
    try {
      const r = await fetch(B.save_url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                         body: JSON.stringify({name: st.name, side: st.side, data})});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      setStatus('saved ' + j.saved_at);
    } catch (err) { dirty = true; setStatus('not saved: ' + err.message); }
  }
  window.addEventListener('beforeunload', e => { if (dirty) { save(); e.preventDefault(); e.returnValue = ''; } });

  // ------------------------------------------------------------------ export (PNG) + Discord
  async function toDataUrl(href) {
    try { const b = await (await fetch(href)).blob(); if (!b.type.startsWith('image')) return null;
      return await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); }); }
    catch (e) { return null; }
  }
  async function png() {
    const clone = svg.cloneNode(true);
    clone.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.w}`);
    clone.querySelectorAll('.sb-h, .sb-prev').forEach(x => x.remove());
    clone.setAttribute('font-family', 'Inter, Segoe UI, Helvetica, Arial, sans-serif');
    clone.querySelectorAll('.sb-item.sel').forEach(x => x.classList.remove('sel'));
    for (const im of clone.querySelectorAll('image')) {
      const d = await toDataUrl(im.getAttribute('href'));
      if (d) im.setAttribute('href', d); else im.remove();
    }
    const title = el('text', {x: view.x + 14, y: view.y + 34 * view.w / S, 'font-size': 26 * view.w / S, 'font-weight': 800, fill: '#fff', stroke: '#0b0e13', 'stroke-width': 5 * view.w / S, 'paint-order': 'stroke', 'font-family': 'sans-serif'});
    title.textContent = `${st.name} · ${data.steps[step].name || 'Step ' + (step + 1)}`;
    clone.appendChild(title);
    clone.setAttribute('width', 1400); clone.setAttribute('height', 1400);
    clone.style.background = '#11151c';
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], {type: 'image/svg+xml'}));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
    const c = document.createElement('canvas'); c.width = 1400; c.height = 1400;
    const ctx = c.getContext('2d'); ctx.fillStyle = '#11151c'; ctx.fillRect(0, 0, 1400, 1400); ctx.drawImage(img, 0, 0, 1400, 1400);
    URL.revokeObjectURL(url);
    return await new Promise(res => c.toBlob(res, 'image/png'));
  }
  $('#sb-png').onclick = async () => {
    const b = await png(); const a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = `${st.name.replace(/[^\w-]+/g, '-')}-${step + 1}.png`; a.click();
  };
  const dbtn = $('#sb-discord');
  if (dbtn) dbtn.onclick = async () => {
    dbtn.disabled = true; setStatus('posting…');
    try {
      await save();
      const fd = new FormData(); fd.append('png', await png(), 'board.png'); fd.append('step', data.steps[step].name || '');
      const r = await fetch(B.discord_url, {method: 'POST', body: fd}); const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      setStatus('posted to Discord');
    } catch (err) { setStatus('Discord: ' + err.message); }
    dbtn.disabled = false;
  };

  // ------------------------------------------------------------------ go
  $('#sb-name').value = st.name; $('#sb-side').value = st.side;
  renderPalette(); renderShapes(); setTool('select'); draw(); setStatus('saved');
  if (new URLSearchParams(location.search).get('play')) { step = 0; draw(); startPlay(); }
  window.valcoachStrat = {data, save, get step() { return step; }, play: startPlay, stop: stopPlay, pairUp, get playing() { return !!playing; }};     // for tests / debugging
})();
