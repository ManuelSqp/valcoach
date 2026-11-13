/* Nexus aim trainer (Practice › Aim trainer). Plain WebGL, no libraries.
   Plays like Valorant: 0.07° per mouse count × sensitivity, vertical field of view 70.53° (103° horizontal at 16:9),
   raw mouse input through pointer lock where the browser has it (Chrome, Edge, the Nexus app).
   The scenarios match stats/trainer.py by id; the server stores what a run sends (POST …/trainer/runs). */
(function () {
  'use strict';
  const C = window.NEXUS_TRAINER;
  if (!C) return;
  const YAW = 0.07, VFOV = 70.53 * Math.PI / 180, EYE = 1.6;
  const $ = id => document.getElementById(id);
  const stage = $('tr-stage'), canvas = $('tr-canvas'), panel = $('tr-panel'), hud = $('tr-hud');
  const byId = Object.fromEntries(C.scenarios.map(s => [s.id, s]));
  byId.mix = {id: 'mix', name: 'Sens test', kind: 'click', seconds: 20,
              about: 'Flicks and small corrections, then a target to track. Shoot the targets, then stay on the moving one.'};
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  // ------------------------------------------------------------------ settings on the page
  const sensIn = $('tr-sens'), dpiIn = $('tr-dpi');
  let finder = null;            // the sens finder while it runs: {list, i, done, round2}
  const sens = () => finder ? finder.list[finder.i] : clamp(parseFloat(sensIn.value) || 0.4, 0.01, 20);
  function showNumbers(n) {
    $('tr-numbers').innerHTML = n && n.edpi ? `eDPI <b>${n.edpi}</b> · <b>${n.cm360}</b> cm per 360°` : '';
  }
  let saveT = null;
  function saveSetup() {
    clearTimeout(saveT);
    saveT = setTimeout(async () => {
      const dpi = parseInt(dpiIn.value, 10), s = parseFloat(sensIn.value);
      const local = s > 0 && dpi > 0 ? {edpi: Math.round(s * dpi), cm360: Math.round(360 / (YAW * s) / dpi * 25.4) / 10} : null;
      showNumbers(local);
      if (!C.can_save) return;
      try {
        await fetch(C.urls.setup, {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({sens: s, dpi: dpi})});
      } catch (e) {}
    }, 500);
  }
  sensIn.addEventListener('input', saveSetup);
  dpiIn.addEventListener('input', saveSetup);

  // ------------------------------------------------------------------ crosshair (like Valorant's primary crosshair)
  // Sizes in screen pixels like in Valorant. A Valorant crosshair code (Settings › Crosshair › Import/Export) can be
  // pasted: "0;P;c;5;h;0;0l;4;0o;2;0a;1;1b;0" — c colour, u custom colour, h/t/o outlines, d/z/a centre dot,
  // 0b/0t/0l/0v/0g/0o/0a inner lines, 1b/1t/1l/1v/1g/1o/1a outer lines.
  const XCOLORS = ['#ffffff', '#00ff00', '#7fff00', '#dfff00', '#ffff00', '#00ffff', '#ff00ff', '#ff0000'];
  const XDEF = {color: '#00ffff', outline: true, ot: 1, oo: 0.5, dot: false, dt: 2, da: 1,
                inner: true, it: 2, il: 4, iv: 4, ig: false, io: 3, ia: 1,
                outer: false, ot2: 2, ol: 2, ov: 2, og: false, oo2: 10, oa: 0.35};
  function xLoad() {
    let x = Object.assign({}, XDEF, C.crosshair || {});
    try { const s = localStorage.getItem('vc-crosshair'); if (s && !C.crosshair) Object.assign(x, JSON.parse(s)); } catch (e) {}
    return x;
  }
  let xh = xLoad();
  function xParse(code) {
    const p = String(code || '').trim().split(';');
    if (p.length < 3) return null;
    const x = Object.assign({}, XDEF, {outline: true, ot: 1, oo: 0.5, inner: true, it: 2, il: 6, iv: 6, io: 3, ia: 0.8,
                                       outer: true, ot2: 2, ol: 2, ov: 2, oo2: 10, oa: 0.35, color: '#ffffff'});
    let sec = '', ok = false;
    for (let i = 0; i < p.length; i++) {
      const k = p[i];
      if (k === 'P' || k === 'A' || k === 'S') { sec = k; continue; }
      if (sec !== 'P' || i + 1 >= p.length) continue;
      const v = p[++i], n = parseFloat(v);
      ok = true;
      switch (k) {
        case 'c': if (n >= 0 && n < 8) x.color = XCOLORS[n]; break;
        case 'u': if (/^[0-9a-fA-F]{6,8}$/.test(v)) x.color = '#' + v.slice(0, 6).toLowerCase(); break;
        case 'h': x.outline = v === '1'; break;
        case 't': x.ot = n; break;
        case 'o': x.oo = n; break;
        case 'd': x.dot = v === '1'; break;
        case 'z': x.dt = n; break;
        case 'a': x.da = n; break;
        case '0b': x.inner = v === '1'; break;
        case '0t': x.it = n; break;
        case '0l': x.il = n; if (!x.ig) x.iv = n; break;
        case '0v': x.iv = n; break;
        case '0g': x.ig = v === '1'; break;
        case '0o': x.io = n; break;
        case '0a': x.ia = n; break;
        case '1b': x.outer = v === '1'; break;
        case '1t': x.ot2 = n; break;
        case '1l': x.ol = n; if (!x.og) x.ov = n; break;
        case '1v': x.ov = n; break;
        case '1g': x.og = v === '1'; break;
        case '1o': x.oo2 = n; break;
        case '1a': x.oa = n; break;
        default: ok = ok && true;
      }
    }
    if (!ok) return null;
    for (const k of Object.keys(XDEF)) if (typeof XDEF[k] === 'number' && !isFinite(x[k])) x[k] = XDEF[k];
    return xClean(x);
  }
  function xClean(x) {
    const n = (v, lo, hi) => clamp(Math.round((+v || 0) * 1000) / 1000, lo, hi);
    return {color: /^#[0-9a-f]{6}$/i.test(x.color) ? x.color.toLowerCase() : XDEF.color, outline: !!x.outline, ot: n(x.ot, 1, 6), oo: n(x.oo, 0, 1),
            dot: !!x.dot, dt: n(x.dt, 1, 6), da: n(x.da, 0, 1), inner: !!x.inner, it: n(x.it, 0, 10), il: n(x.il, 0, 20), iv: n(x.iv, 0, 20),
            ig: !!x.ig, io: n(x.io, 0, 20), ia: n(x.ia, 0, 1), outer: !!x.outer, ot2: n(x.ot2, 0, 10), ol: n(x.ol, 0, 20), ov: n(x.ov, 0, 20),
            og: !!x.og, oo2: n(x.oo2, 0, 40), oa: n(x.oa, 0, 1)};
  }
  function xCode(x) {             // back to a code Valorant can import
    const i = XCOLORS.indexOf(x.color), b = v => v ? 1 : 0;
    return ['0', 'P', 'c', i >= 0 ? i : 8, ...(i < 0 ? ['u', x.color.slice(1).toUpperCase() + 'FF'] : []),
      'h', b(x.outline), 't', x.ot, 'o', x.oo, 'd', b(x.dot), 'z', x.dt, 'a', x.da,
      '0b', b(x.inner), '0t', x.it, '0l', x.il, ...(x.ig ? ['0v', x.iv, '0g', 1] : []), '0o', x.io, '0a', x.ia, '0m', 0, '0f', 0,
      '1b', b(x.outer), '1t', x.ot2, '1l', x.ol, ...(x.og ? ['1v', x.ov, '1g', 1] : []), '1o', x.oo2, '1a', x.oa, '1m', 0, '1f', 0].join(';');
  }
  function xDraw(ctx, x, cx, cy, s = 1) {       // s: screen pixels per crosshair pixel; (cx, cy): the centre pixel
    // Mirror-exact on all four sides. An odd thickness is centred on the centre pixel, an even one on the corner
    // between pixels; the gap is measured from that centre, the same on every side.
    const rects = [];                 // [x, y, w, h, alpha], whole pixels only
    const lines = (t, l, v, off, a) => {
      if (!t || (!l && !v)) return;
      const T = Math.round(t), odd = T % 2 === 1, u = s;
      const lo = c => (odd ? c - (T - 1) / 2 * u : c - T / 2 * u);                     // first pixel of the bar across
      const far = c => (odd ? c + u : c);                                               // first pixel after the centre
      const o = Math.round(off) * u, L = Math.round(l) * u, V = Math.round(v) * u, W = T * u;
      if (L) { rects.push([far(cx) + o, lo(cy), L, W, a]); rects.push([cx - o - L, lo(cy), L, W, a]); }
      if (V) { rects.push([lo(cx), far(cy) + o, W, V, a]); rects.push([lo(cx), cy - o - V, W, V, a]); }
    };
    if (x.inner) lines(x.it, x.il, x.ig ? x.iv : x.il, x.io, x.ia);
    if (x.outer) lines(x.ot2, x.ol, x.og ? x.ov : x.ol, x.oo2, x.oa);
    if (x.dot) {
      const D = Math.round(x.dt), st = D % 2 ? (D - 1) / 2 * s : D / 2 * s;
      rects.push([cx - st, cy - st, D * s, D * s, x.da]);
    }
    for (const r of rects) { r[0] = Math.round(r[0]); r[1] = Math.round(r[1]); }
    if (x.outline && x.oo > 0) {
      const w = Math.round(x.ot) * s;
      ctx.fillStyle = `rgba(0,0,0,${x.oo})`;
      for (const [rx, ry, rw, rh, a] of rects) if (a > 0) ctx.fillRect(rx - w, ry - w, rw + 2 * w, rh + 2 * w);
    }
    ctx.fillStyle = x.color;
    for (const [rx, ry, rw, rh, a] of rects) { ctx.globalAlpha = a; ctx.fillRect(rx, ry, rw, rh); }
    ctx.globalAlpha = 1;
  }
  // Canvases sized to the exact device pixels they cover (with Windows display scaling, e.g. 125%, a rounded size
  // makes the browser stretch the picture by a fraction of a pixel: smeared, uneven crosshair lines).
  const exact = new Map();             // canvas -> [w, h] in device pixels
  function devicePixels(cv) {
    const r = cv.getBoundingClientRect();
    const guess = [Math.round(r.width * devicePixelRatio), Math.round(r.height * devicePixelRatio)];
    const known = exact.get(cv);       // the browser's exact count, when it agrees with the guess (within a pixel)
    return known && Math.abs(known[0] - guess[0]) <= 1 && Math.abs(known[1] - guess[1]) <= 1 ? known : guess;
  }
  function watchPixels(cv, then) {
    if (!cv || !window.ResizeObserver) return;
    try {
      new ResizeObserver(es => {
        for (const e of es) {
          const b = e.devicePixelContentBoxSize && e.devicePixelContentBoxSize[0];
          if (b) exact.set(cv, [b.inlineSize, b.blockSize]);
          else exact.delete(cv);
        }
        then();
      }).observe(cv, {box: 'device-pixel-content-box'});
    } catch (e) {
      new ResizeObserver(() => { exact.delete(cv); then(); }).observe(cv);
    }
  }
  const xc = $('tr-xhair'), xctx = xc ? xc.getContext('2d') : null;
  function xPaint() {                  // the crosshair over the game, in device pixels like Valorant
    if (!xctx) return;
    const [w, h] = devicePixels(xc);
    if (xc.width !== w || xc.height !== h) { xc.width = w; xc.height = h; }
    xctx.clearRect(0, 0, w, h);
    xDraw(xctx, xh, Math.floor(w / 2), Math.floor(h / 2), 1);
  }
  watchPixels(xc, xPaint);
  watchPixels(canvas, () => {});
  window.addEventListener('resize', xPaint);

  // the settings on the page: a code, the main switches and sizes, a preview
  const xForm = $('tr-xform'), xPrev = $('tr-xprev');
  let xSaveT = null;
  function xShow() {
    if (!xForm) return;
    for (const el of xForm.querySelectorAll('[data-x]')) {
      const k = el.dataset.x;
      if (el.type === 'checkbox') el.checked = !!xh[k]; else el.value = xh[k];
    }
    const code = $('tr-xcode-out'); if (code) code.value = xCode(xh);
    if (xPrev) {
      const [w, h] = devicePixels(xPrev), z = Math.max(1, Math.round(4 * devicePixelRatio));
      if (xPrev.width !== w || xPrev.height !== h) { xPrev.width = w; xPrev.height = h; }
      const c = xPrev.getContext('2d');
      c.fillStyle = '#3a4252'; c.fillRect(0, 0, w, h);
      c.fillStyle = '#6b7488'; c.fillRect(0, h * 0.62, w, h * 0.38);
      c.imageSmoothingEnabled = false;
      xDraw(c, xh, Math.floor(w / 2), Math.floor(h / 2), z);
    }
    xPaint();
  }
  function xSave() {
    try { localStorage.setItem('vc-crosshair', JSON.stringify(xh)); } catch (e) {}
    clearTimeout(xSaveT);
    if (!C.can_save) return;
    xSaveT = setTimeout(() => fetch(C.urls.setup, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({crosshair: xh})}).catch(() => {}), 600);
  }
  if (xForm) {
    xForm.addEventListener('input', e => {
      const el = e.target.closest('[data-x]');
      if (!el) return;
      xh[el.dataset.x] = el.type === 'checkbox' ? el.checked : (el.type === 'color' ? el.value : parseFloat(el.value));
      xh = xClean(xh); xShow(); xSave();
    });
    $('tr-xcode-use').addEventListener('click', () => {
      const x = xParse($('tr-xcode').value), msg = $('tr-xcode-msg');
      if (!x) { msg.textContent = 'That doesn\'t look like a Valorant crosshair code.'; return; }
      xh = x; xShow(); xSave(); msg.textContent = 'Crosshair taken over.';
    });
    $('tr-xreset').addEventListener('click', () => { xh = Object.assign({}, XDEF); xShow(); xSave(); });
    $('tr-xcode-copy').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(xCode(xh)); $('tr-xcode-msg').textContent = 'Copied.'; } catch (e) { $('tr-xcode-out').select(); }
    });
  }
  watchPixels(xPrev, xShow);
  xShow();

  // ------------------------------------------------------------------ WebGL
  const gl = canvas.getContext('webgl', {antialias: true, alpha: false, desynchronized: true, powerPreference: 'high-performance'});
  const VS = `attribute vec3 p;attribute vec3 n;uniform mat4 vp;uniform mat4 m;varying vec3 wp;varying vec3 wn;
    void main(){vec4 w=m*vec4(p,1.0);wp=w.xyz;wn=mat3(m)*n;gl_Position=vp*w;}`;
  const FS = `precision mediump float;varying vec3 wp;varying vec3 wn;uniform vec3 col;uniform float grid;uniform vec3 eye;uniform float glow;
    void main(){vec3 nn=normalize(wn);float l=0.58+0.42*max(dot(nn,normalize(vec3(0.35,0.9,0.4))),0.0);vec3 c=col*l;
      if(grid>0.0){vec3 f=abs(fract(wp+0.5)-0.5);float d=min(min(abs(nn.x)>0.5?9.0:f.x,abs(nn.y)>0.5?9.0:f.y),abs(nn.z)>0.5?9.0:f.z);
        c=mix(c+vec3(0.06),c,smoothstep(0.0,0.025*grid,d));}
      c+=col*glow;float fog=clamp((distance(wp,eye)-20.0)/60.0,0.0,0.6);gl_FragColor=vec4(mix(c,vec3(0.043,0.06,0.085),fog),1.0);}`;
  let prog = null, loc = {}, meshes = {};
  function shader(type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  function mesh(data) {
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
    return {b, n: data.length / 6};
  }
  function sphereData(seg = 20, ring = 14) {
    const out = [];
    const pt = (i, j) => { const th = j / ring * Math.PI, ph = i / seg * 2 * Math.PI;
      const x = Math.sin(th) * Math.cos(ph), y = Math.cos(th), z = Math.sin(th) * Math.sin(ph); return [x, y, z, x, y, z]; };
    for (let j = 0; j < ring; j++) for (let i = 0; i < seg; i++) {
      const a = pt(i, j), b = pt(i + 1, j), c = pt(i + 1, j + 1), d = pt(i, j + 1);
      out.push(...a, ...c, ...b, ...a, ...d, ...c);
    }
    return out;
  }
  function boxData() {        // unit cube 0..1 on every axis, normals outward
    const f = (n, a, b, c, d) => [...a, ...n, ...b, ...n, ...c, ...n, ...a, ...n, ...c, ...n, ...d, ...n];
    return [
      ...f([0, 0, 1], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]), ...f([0, 0, -1], [1, 0, 0], [0, 0, 0], [0, 1, 0], [1, 1, 0]),
      ...f([1, 0, 0], [1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]), ...f([-1, 0, 0], [0, 0, 0], [0, 0, 1], [0, 1, 1], [0, 1, 0]),
      ...f([0, 1, 0], [0, 1, 1], [1, 1, 1], [1, 1, 0], [0, 1, 0]), ...f([0, -1, 0], [0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1])];
  }
  function initGL() {
    if (prog || !gl) return !!gl;
    prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog); gl.useProgram(prog);
    for (const k of ['p', 'n']) loc[k] = gl.getAttribLocation(prog, k);
    for (const k of ['vp', 'm', 'col', 'grid', 'eye', 'glow']) loc[k] = gl.getUniformLocation(prog, k);
    meshes = {sphere: mesh(sphereData()), box: mesh(boxData())};
    gl.enable(gl.DEPTH_TEST);
    return true;
  }
  // column-major 4×4 matrices
  function perspective(fy, asp, n, f) {
    const t = 1 / Math.tan(fy / 2);
    return [t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0];
  }
  function mul(a, b) {
    const o = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s;
    }
    return o;
  }
  function view(yaw, pitch) {      // camera at (0, EYE, 0): rotate the world by -pitch, -yaw
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const ry = [cy, 0, -sy, 0, 0, 1, 0, 0, sy, 0, cy, 0, 0, 0, 0, 1];
    const rx = [1, 0, 0, 0, 0, cp, -sp, 0, 0, sp, cp, 0, 0, 0, 0, 1];
    const tr = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -EYE, 0, 1];
    return mul(rx, mul(ry, tr));
  }
  const model = (x, y, z, sx, sy, sz) => [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, x, y, z, 1];
  function draw(m, mat, col, grid = 0, glow = 0) {
    gl.bindBuffer(gl.ARRAY_BUFFER, m.b);
    gl.enableVertexAttribArray(loc.p); gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(loc.n); gl.vertexAttribPointer(loc.n, 3, gl.FLOAT, false, 24, 12);
    gl.uniformMatrix4fv(loc.m, false, mat); gl.uniform3fv(loc.col, col);
    gl.uniform1f(loc.grid, grid); gl.uniform1f(loc.glow, glow);
    gl.drawArrays(gl.TRIANGLES, 0, m.n);
  }

  // ------------------------------------------------------------------ the world
  const ROOM = {x0: -34, x1: 34, z0: -36, z1: 8, h: 14};
  const WALL = [0.2, 0.235, 0.29], FLOOR = [0.16, 0.185, 0.22], COVER = [0.32, 0.35, 0.4];
  const TARGET = [0.95, 0.33, 0.3], TARGET_ON = [1.0, 0.62, 0.35];
  const AGENT = [0.78, 0.26, 0.26], AGENT_HEAD = [0.95, 0.45, 0.38];
  function drawRoom() {
    const {x0, x1, z0, z1, h} = ROOM, t = 0.2;
    draw(meshes.box, model(x0, -t, z0, x1 - x0, t, z1 - z0), FLOOR, 1);
    draw(meshes.box, model(x0, 0, z0 - t, x1 - x0, h, t), WALL, 1);
    draw(meshes.box, model(x0 - t, 0, z0, t, h, z1 - z0), WALL, 1);
    draw(meshes.box, model(x1, 0, z0, t, h, z1 - z0), WALL, 1);
    draw(meshes.box, model(x0, 0, z1, x1 - x0, h, t), WALL, 1);
    draw(meshes.box, model(x0, h, z0, x1 - x0, t, z1 - z0), [0.13, 0.15, 0.18], 1);
  }
  function hitSphere(o, d, c, r) {
    const ox = o[0] - c[0], oy = o[1] - c[1], oz = o[2] - c[2];
    const b = ox * d[0] + oy * d[1] + oz * d[2], q = ox * ox + oy * oy + oz * oz - r * r, disc = b * b - q;
    if (disc < 0) return Infinity;
    const t = -b - Math.sqrt(disc);
    return t > 0 ? t : Infinity;
  }
  function hitBox(o, d, b) {
    let tmin = 0, tmax = Infinity;
    for (let i = 0; i < 3; i++) {
      const lo = b.min[i], hi = b.max[i];
      if (Math.abs(d[i]) < 1e-9) { if (o[i] < lo || o[i] > hi) return Infinity; continue; }
      let t1 = (lo - o[i]) / d[i], t2 = (hi - o[i]) / d[i];
      if (t1 > t2) [t1, t2] = [t2, t1];
      tmin = Math.max(tmin, t1); tmax = Math.min(tmax, t2);
      if (tmin > tmax) return Infinity;
    }
    return tmin;
  }
  const atAngle = (deg, dist, y) => [Math.sin(deg * Math.PI / 180) * dist, y, -Math.cos(deg * Math.PI / 180) * dist];

  // ------------------------------------------------------------------ scenarios (ids as in stats/trainer.py)
  // Each: setup(st), update(st, dt), hit(st, tg, head); the targets in st.targets ({c:[x,y,z], r, born} spheres,
  // or {agent: true, c: feet} enemy models) and walls in st.covers. Targets never go into the floor or ceiling.
  const D2R = Math.PI / 180;
  // a point at (yaw, pitch, distance) from the eye, kept between the floor and the ceiling
  function place(ty, tp, d, r) {
    const lo = Math.atan2(r + 0.25 - EYE, d), hi = Math.atan2(ROOM.h - 1.5 - EYE, d);
    tp = clamp(tp, lo, hi);
    return [Math.sin(ty) * Math.cos(tp) * d, EYE + Math.sin(tp) * d, -Math.cos(ty) * Math.cos(tp) * d];
  }
  // how a flick went (sens finder and flick scenarios): progress along the line to the target, the first stop
  function pathStart(st, ty, tp, r, d, flick) {
    const len = Math.hypot(ty - yaw, tp - pitch);
    st.path = {y0: yaw, p0: pitch, vy: ty - yaw, vp: tp - pitch, len, tol: Math.atan(r / d), flick, max: 0, peak: 0, stop: null, py: yaw, pp: pitch};
  }
  function pathUpdate(st, dt) {
    const p = st.path;
    if (!p || !dt || !p.len) return;
    const prog = ((yaw - p.y0) * p.vy + (pitch - p.p0) * p.vp) / (p.len * p.len);
    const speed = Math.hypot(yaw - p.py, pitch - p.pp) / dt;
    p.py = yaw; p.pp = pitch;
    p.max = Math.max(p.max, prog);
    p.peak = Math.max(p.peak, speed);
    if (p.stop === null && p.peak > p.len * 2 && speed < p.peak * 0.15) p.stop = prog;    // the first stop after the flick
  }
  function pathHit(st) {
    const p = st.path;
    if (p && p.flick && p.len > 8 * D2R) {
      const tol = p.tol / p.len;
      (st.over = st.over || []).push(Math.max(0, p.max - 1 - tol));
      (st.under = st.under || []).push(p.stop === null ? 0 : Math.max(0, 1 - tol - p.stop));
    }
  }
  // one target at a time, somewhere between amin and amax degrees away from the crosshair
  function flicks(o) {
    return {
      kind: 'click',
      setup(st) { st.targets = []; this.spawn(st); },
      spawn(st) {
        const a = rand(o.amin, o.amax) * D2R, side = Math.random() < 0.5 ? -1 : 1, up = rand(-1, 1) * (o.vert || 0.35);
        let ty = yaw + side * a * Math.sqrt(1 - Math.min(0.9, up * up)), tp = clamp(pitch + up * a, (o.pmin || -6) * D2R, (o.pmax || 10) * D2R);
        if (!o.back && Math.abs(ty) > 70 * D2R) ty = yaw - side * a;                  // keep it in front, not behind you
        const d = rand(o.dmin, o.dmax), c = place(ty, tp, d, o.r);
        st.targets = [{c, r: o.r, born: st.t}];
      },
      hit(st) { pathHit(st); this.spawn(st); },
    };
  }
  // one target that strafes left and right; stops: chance to stand still for a moment (counter-strafe)
  function tracker(o) {
    return {
      kind: 'track',
      setup(st, here) {
        let x = 0, y = o.y;
        if (here) {                                 // in the sens test: start right where the crosshair is
          x = clamp(Math.tan(yaw) * o.d, -o.bound, o.bound);
          y = clamp(EYE + Math.tan(pitch) * o.d, 0.9, 2.6);
        }
        st.targets = [{c: [x, y, -o.d], r: o.r, born: st.t, y0: y}];
        const dir = Math.random() < 0.5 ? -1 : 1;
        st.mv = {v: here ? dir * o.vmin : 0, goal: dir * rand(o.vmin, o.vmax), flip: st.t + rand(o.fmin, o.fmax)};
      },
      update(st, dt) {
        const tg = st.targets[0], m = st.mv;
        if (!tg) return;
        if (st.t >= m.flip || Math.abs(tg.c[0]) > o.bound) {
          if (Math.abs(tg.c[0]) > o.bound) m.goal = -Math.sign(tg.c[0]) * rand(o.vmin, o.vmax);
          else if (o.stop && m.goal && Math.random() < o.stop) m.goal = 0;               // stands for a moment
          else m.goal = (m.goal ? -Math.sign(m.goal) : (Math.random() < 0.5 ? -1 : 1)) * rand(o.vmin, o.vmax);
          m.flip = st.t + (m.goal === 0 ? rand(0.12, 0.35) : rand(o.fmin, o.fmax));
        }
        const acc = (o.acc || 26) * dt;
        m.v += clamp(m.goal - m.v, -acc, acc);
        tg.c[0] += m.v * dt;
        tg.c[1] = tg.y0 + (o.bob ? Math.sin(st.t * 2.1) * o.bob : 0);
      },
    };
  }
  // ---- 4.23: builders for the scenario library
  // several targets at once in a box of yaw (±w°) x pitch (pmin..pmax°) x distance; each hit puts one back
  // somewhere else, at least sep° from the others. hp: hits a target needs (points only for the last one).
  // head: all at head height (pitch ~0).
  function multi(o) {
    return {
      kind: 'click',
      setup(st) { st.targets = []; for (let i = 0; i < o.n; i++) this.spawn(st); },
      spawn(st) {
        let a, b, k = 0;
        do {
          a = rand(-o.w, o.w); b = o.head ? rand(-0.4, 0.4) : rand(o.pmin, o.pmax); k++;
        } while (k < 40 && st.targets.some(t => Math.hypot(t.a - a, t.b - b) < (o.sep || 6)));
        const d = rand(o.dmin, o.dmax);
        st.targets.push({c: place(a * D2R, b * D2R, d, o.r), r: o.r, born: st.t, a, b, hp: o.hp || 1});
      },
      hit(st, tg) {
        if (--tg.hp > 0) { tg.r *= 0.85; return 'hp'; }             // not down yet: smaller, shoot again
        st.targets.splice(st.targets.indexOf(tg), 1); this.spawn(st);
      },
    };
  }
  // one target at a time that is only there for `life` seconds (shorter after each hit, longer after a miss)
  function timed(o) {
    const base = flicks(o);
    return {
      kind: 'click',
      setup(st) { st.life = o.life; st.escaped = 0; st.targets = []; st.next = st.t + 0.3; },
      update(st) {
        const tg = st.targets[0];
        if (!tg && st.t >= st.next) { base.spawn(st); return; }
        if (tg && st.t - tg.born > st.life) {
          st.targets = []; st.escaped++; st.life = Math.min(o.life, st.life + 0.05); st.next = st.t + rand(0.15, 0.45);
        }
      },
      hit(st) { pathHit(st); st.targets = []; st.life = Math.max(o.min, st.life - 0.02); st.next = st.t + rand(0.15, 0.45); },
    };
  }
  // spider: a target in the middle, then one around it, back to the middle, and so on
  function spider(o) {
    return {
      kind: 'click',
      setup(st) { st.out = false; st.targets = []; this.spawn(st); },
      spawn(st) {
        st.out = !st.out;
        const d = rand(o.dmin, o.dmax);
        if (!st.out) { st.targets = [{c: place(0, 0, d, o.r), r: o.r, born: st.t}]; return; }
        const ang = Math.random() * 2 * Math.PI, a = rand(o.amin, o.amax);
        st.targets = [{c: place(Math.cos(ang) * a * D2R, Math.sin(ang) * a * (o.flat || 0.55) * D2R, d, o.r), r: o.r, born: st.t}];
      },
      hit(st) { pathHit(st); this.spawn(st); },
    };
  }
  // a target circling around you at distance d (wide tracking): angular speed changes, sometimes reverses;
  // jump: hops now and then; vy: also moves up and down
  function orbit(o) {
    return {
      kind: 'track',
      setup(st, here) {
        const a0 = here ? yaw : rand(-0.3, 0.3);
        st.targets = [{c: [0, o.y, -o.d], r: o.r, born: st.t, a: a0, h: o.y}];
        st.mv = {w: (Math.random() < 0.5 ? -1 : 1) * rand(o.wmin, o.wmax), flip: st.t + rand(o.fmin, o.fmax), vy: 0, jump: st.t + rand(1, 2.5), jv: 0};
        this.put(st.targets[0]);
      },
      put(tg) { tg.c = [Math.sin(tg.a) * o.d, tg.h, -Math.cos(tg.a) * o.d]; },
      update(st, dt) {
        const tg = st.targets[0], m = st.mv;
        if (!tg) return;
        if (st.t >= m.flip) {
          m.w = (Math.random() < (o.rev || 0.5) ? -Math.sign(m.w) : Math.sign(m.w)) * rand(o.wmin, o.wmax);
          m.flip = st.t + rand(o.fmin, o.fmax);
          if (o.vy) m.vy = rand(-o.vy, o.vy);
        }
        tg.a += m.w * D2R * dt;
        if (Math.abs(tg.a) > (o.span || 75) * D2R) { tg.a = Math.sign(tg.a) * (o.span || 75) * D2R; m.w = -m.w; }
        if (o.vy) { tg.h = clamp(tg.h + m.vy * dt, o.y - 0.9, o.y + 1.4); if (tg.h <= o.y - 0.9 || tg.h >= o.y + 1.4) m.vy = -m.vy; }
        if (o.jump) {                                // a hop: up and down again (about 0.6 s)
          if (!m.jv && tg.h <= o.y + 0.001 && st.t >= m.jump) { m.jv = 4.2; m.jump = st.t + rand(0.9, 2.2); }
          if (m.jv || tg.h > o.y) { tg.h += m.jv * dt; m.jv -= 13 * dt; if (tg.h <= o.y) { tg.h = o.y; m.jv = 0; } }
        }
        this.put(tg);
      },
    };
  }
  // a strafing target (tracker) that also hops (jump) or crouches (duck) now and then
  function strafer(o) {
    const base = tracker(o);
    return {
      kind: 'track',
      setup(st, here) { base.setup(st, here); st.hop = {v: 0, off: 0, next: st.t + rand(0.8, 2), duck: 0}; },
      update(st, dt) {
        base.update(st, dt);
        const tg = st.targets[0], h = st.hop;
        if (!tg) return;
        if (o.jump) {
          if (!h.v && h.off <= 0 && st.t >= h.next) { h.v = 4.0; h.next = st.t + rand(0.9, 2.4); }
          if (h.v || h.off > 0) { h.off += h.v * dt; h.v -= 12.5 * dt; if (h.off <= 0) { h.off = 0; h.v = 0; } }
          tg.c[1] += h.off;
        }
        if (o.duck) {
          if (st.t >= h.next && !h.duck) { h.duck = st.t + rand(0.35, 0.8); h.next = st.t + rand(1.2, 2.6); }
          if (h.duck && st.t > h.duck) h.duck = 0;
          if (h.duck) tg.c[1] -= 0.45;
        }
      },
    };
  }
  function peeks(o) {
    o = Object.assign({z: 14, spread: 4.5, r: 0.26, win: 0.9, min: 0.38, out: 0.12}, o);
    return {
      kind: 'click',
      setup(st) {
        st.covers = [-o.spread, 0, o.spread].map(x => ({min: [x - 0.8, 0, -o.z - 0.5], max: [x + 0.8, 3.2, -o.z + 0.5]}));
        st.window = o.win; st.targets = []; st.next = st.t + 0.6; st.escaped = 0;
      },
      update(st) {
        const tg = st.targets[0];
        if (!tg && st.t >= st.next) {
          const cv = st.covers[Math.floor(Math.random() * 3)], side = Math.random() < 0.5 ? -1 : 1;
          const x0 = side < 0 ? cv.min[0] + 0.35 : cv.max[0] - 0.35;
          st.targets = [{c: [x0, EYE - 0.05, -o.z - 0.35], r: o.r, born: st.t, x0, x1: x0 + side * 1.0, phase: 'out', t0: st.t}];
          return;
        }
        if (!tg) return;
        const k = (st.t - tg.t0) / o.out;
        if (tg.phase === 'out') {
          tg.c[0] = tg.x0 + (tg.x1 - tg.x0) * Math.min(1, k);
          if (k >= 1) { tg.phase = 'stay'; tg.t0 = st.t; tg.born = st.t; }
        } else if (tg.phase === 'stay' && st.t - tg.t0 >= st.window) {
          tg.phase = 'in'; tg.t0 = st.t;
        } else if (tg.phase === 'in') {
          tg.c[0] = tg.x1 + (tg.x0 - tg.x1) * Math.min(1, k);
          if (k >= 1) {               // got away
            st.targets = []; st.escaped++; st.window = Math.min(o.win, st.window + 0.04); st.next = st.t + rand(0.35, 0.9);
          }
        }
      },
      hit(st) { st.targets = []; st.window = Math.max(o.min, st.window - 0.025); st.next = st.t + rand(0.35, 0.9); },
    };
  }
    // Hold the angle: a doorway in front of you, an enemy model comes out of the left or right side: a wide swing
    // (stops in the opening for a moment), a jiggle (shows a shoulder and the head, goes straight back) or a run
    // through the opening. Only the head kills; a body shot is counted but the enemy keeps going.
  function angle(o) {
    o = Object.assign({dmin: 10, dmax: 17, wmin: 2.6, wmax: 4.2, swing: 0.5, jiggle: 0.25, win: 0.8, min: 0.42, fast: 1}, o);
    return {
      kind: 'click', heads: true,
      setup(st) {
        const D = rand(o.dmin, o.dmax), W = rand(o.wmin, o.wmax), x0 = rand(-1.2, 1.2);
        st.door = {D, W, x0, l: x0 - W / 2, r: x0 + W / 2, z: -D - 1.4};
        st.covers = [{min: [x0 - W / 2 - 7, 0, -D - 0.5], max: [x0 - W / 2, 3.6, -D + 0.5]},
                     {min: [x0 + W / 2, 0, -D - 0.5], max: [x0 + W / 2 + 7, 3.6, -D + 0.5]},
                     {min: [x0 - W / 2 - 7, 3.6, -D - 0.5], max: [x0 + W / 2 + 7, 4.2, -D + 0.5]}];
        st.window = o.win; st.targets = []; st.next = st.t + rand(0.5, 1.1); st.escaped = 0; st.body = 0;
      },
      update(st, dt) {
        const dr = st.door;
        let tg = st.targets[0];
        if (!tg && st.t >= st.next) {
          const side = Math.random() < 0.5 ? -1 : 1;                   // -1: from the left wall
          const edge = side < 0 ? dr.l : dr.r, hidden = edge + side * 0.9, roll = Math.random();
          const type = roll < o.swing ? 'swing' : roll < o.swing + o.jiggle ? 'jiggle' : 'cross';
          const stopAt = type === 'swing' ? edge - side * rand(0.7, Math.max(0.9, dr.W * 0.55))
                       : type === 'jiggle' ? edge - side * 0.42 : (side < 0 ? dr.r : dr.l) + side * -0.9;
          tg = {agent: true, c: [hidden, 0, dr.z], born: Infinity, type, side, edge, stopAt, phase: 'out', t0: st.t,
                speed: (type === 'jiggle' ? 4.2 : 5.4) * o.fast};
          st.targets = [tg];
          return;
        }
        if (!tg) return;
        const dir = Math.sign(tg.stopAt - tg.c[0]);
        // visible from the moment the head clears the wall edge: that's when the reaction time starts
        if (tg.born === Infinity && (tg.c[0] - tg.edge) * -tg.side > 0.05) tg.born = st.t;
        if (tg.phase === 'out') {
          tg.c[0] += dir * tg.speed * dt;
          if (Math.sign(tg.stopAt - tg.c[0]) !== dir) {
            tg.c[0] = tg.stopAt;
            if (tg.type === 'cross') { this.gone(st); return; }
            tg.phase = 'stay'; tg.t0 = st.t;
          }
        } else if (tg.phase === 'stay' && st.t - tg.t0 >= (tg.type === 'jiggle' ? 0.06 : st.window)) {
          tg.phase = 'in';
        } else if (tg.phase === 'in') {
          const home = tg.edge + tg.side * 0.9;
          tg.c[0] += Math.sign(home - tg.c[0]) * tg.speed * dt;
          if ((tg.c[0] - home) * tg.side >= 0) this.gone(st);
        }
      },
      gone(st) { st.targets = []; st.escaped++; st.window = Math.min(o.win + 0.1, st.window + 0.03); st.next = st.t + rand(0.5, 1.3); },
      hit(st, tg, head) {
        if (!head) { st.body++; return false; }                    // keeps going
        st.targets = []; st.window = Math.max(o.min, st.window - 0.02); st.next = st.t + rand(0.5, 1.3);
        return true;
      },
    };
  }
  // ---- 4.24: the drill types the big aim trainers are known for, in our own versions
  // a wall of space in front of you at distance d: x within ±tan(w°)·d, y between pitch pmin° and pmax°
  function wallBox(o, r) {
    const X = Math.tan(o.w * D2R) * o.d;
    const lo = Math.max(r + 0.25, EYE + Math.tan(o.pmin * D2R) * o.d), hi = Math.min(ROOM.h - 1.5 - r, EYE + Math.tan(o.pmax * D2R) * o.d);
    return {X, lo, hi: Math.max(hi, lo + 0.2)};
  }
  // moving targets to click: n at a time, each flying at smin..smax m/s and bouncing off the edges of the box.
  // jink: changes direction every jink[0]..jink[1] s. grav: falls and hops up again. horiz: only sideways.
  // toward: comes at you and is gone (got away) once it's closer than `near` m. life: shrinks to r·shrink, then gone.
  function bounce(o) {
    return {
      kind: 'click',
      setup(st) { st.targets = []; st.escaped = 0; for (let i = 0; i < o.n; i++) this.spawn(st); },
      spawn(st) {
        const B = wallBox(o, o.r);
        let x, y, k = 0;
        do { x = rand(-B.X, B.X); y = rand(B.lo, B.hi); k++; }
        while (k < 30 && st.targets.some(t => Math.hypot(t.c[0] - x, t.c[1] - y) < o.r * 5));
        const ang = Math.random() * 2 * Math.PI, s = rand(o.smin, o.smax);
        const v = [Math.cos(ang) * s, o.horiz || o.toward ? 0 : Math.sin(ang) * s, o.toward ? s : 0];
        if (o.horiz || o.toward) v[0] = (Math.random() < 0.5 ? -1 : 1) * s * (o.toward ? 0.3 : 1);
        if (o.grav) v[1] = rand(o.hop * 0.6, o.hop);
        st.targets.push({c: [x, y, -o.d], r: o.r, born: st.t, v, turn: st.t + (o.jink ? rand(...o.jink) : 1e9)});
      },
      update(st, dt) {
        for (const tg of [...st.targets]) {
          const B = wallBox(o, tg.r), v = tg.v;
          if (st.t >= tg.turn) {
            const s = Math.hypot(v[0], v[1]), ang = Math.random() * 2 * Math.PI;
            v[0] = Math.cos(ang) * s; v[1] = Math.sin(ang) * s; tg.turn = st.t + rand(...o.jink);
          }
          if (o.grav) v[1] -= o.grav * dt;
          tg.c[0] += v[0] * dt; tg.c[1] += v[1] * dt; tg.c[2] += v[2] * dt;
          const X = o.toward ? B.X * -tg.c[2] / o.d : B.X;
          if (Math.abs(tg.c[0]) > X) { tg.c[0] = Math.sign(tg.c[0]) * X; v[0] = -v[0]; }
          if (tg.c[1] < B.lo) { tg.c[1] = B.lo; v[1] = o.grav ? rand(o.hop * 0.6, o.hop) : Math.abs(v[1]); }
          if (tg.c[1] > B.hi) { tg.c[1] = B.hi; v[1] = -Math.abs(v[1]); }
          let gone = o.toward && tg.c[2] > -o.near;
          if (o.life) {
            const k = (st.t - tg.born) / o.life;
            tg.r = o.r * (1 - (1 - o.shrink) * Math.min(1, k));
            gone = gone || k >= 1;
          }
          if (gone) { st.targets.splice(st.targets.indexOf(tg), 1); st.escaped++; this.spawn(st); }
        }
      },
      hit(st, tg) { st.targets.splice(st.targets.indexOf(tg), 1); this.spawn(st); },
    };
  }
  // a group of k targets close together (spread°), amin..amax° away from the last group: flick there, clear it
  function burst(o) {
    return {
      kind: 'click',
      setup(st) { st.at = {a: 0, b: 0}; st.targets = []; this.spawn(st); },
      spawn(st) {
        const ang = Math.random() * 2 * Math.PI, a = rand(o.amin, o.amax);
        let ya = st.at.a + Math.cos(ang) * a, pa = clamp(st.at.b + Math.sin(ang) * a * 0.35, -4, 12);
        if (Math.abs(ya) > 60) ya = st.at.a - Math.cos(ang) * a;
        st.at = {a: clamp(ya, -65, 65), b: pa};
        for (let i = 0; i < o.k; i++) {
          let a2, b2, n = 0;
          do { a2 = st.at.a + rand(-o.spread, o.spread); b2 = st.at.b + rand(-o.spread, o.spread) * 0.7; n++; }
          while (n < 30 && st.targets.some(t => Math.hypot(t.a - a2, t.b - b2) < o.spread * 0.6));
          st.targets.push({c: place(a2 * D2R, b2 * D2R, o.d, o.r), r: o.r, born: st.t, a: a2, b: b2});
        }
      },
      hit(st, tg) { st.targets.splice(st.targets.indexOf(tg), 1); if (!st.targets.length) this.spawn(st); },
      since(st) { return st.lastHit; },
    };
  }
  // targets pop up on their own every every[0]..every[1] s, anywhere in ±w° x pmin..pmax°, and stay for `life` s.
  // bad: share of them in blue, which you must not shoot (a hit on one costs points).
  const BAD = [0.3, 0.62, 0.95];
  function popups(o) {
    return {
      kind: 'click',
      setup(st) { st.targets = []; st.escaped = 0; st.next = st.t + 0.4; },
      update(st) {
        for (const tg of [...st.targets]) {
          if (st.t - tg.born > o.life) { st.targets.splice(st.targets.indexOf(tg), 1); if (!tg.bad) st.escaped++; }
        }
        if (st.t >= st.next && st.targets.length < (o.max || 4)) {
          let a, b, k = 0;
          do { a = rand(-o.w, o.w); b = rand(o.pmin, o.pmax); k++; }
          while (k < 30 && st.targets.some(t => Math.hypot(t.a - a, t.b - b) < 8));
          const bad = Math.random() < (o.bad || 0), d = rand(o.dmin, o.dmax);
          st.targets.push({c: place(a * D2R, b * D2R, d, o.r), r: o.r, born: st.t, a, b, bad, col: bad ? BAD : null});
          st.next = st.t + rand(...o.every);
        }
      },
      hit(st, tg) { st.targets.splice(st.targets.indexOf(tg), 1); },
    };
  }
  // one target gliding over a wall (tracking). path: line (straight lines between random points), arc (curves that
  // bend one way, then the other), star (out from the middle and back), circle (circles around a point that drifts).
  // blink: jumps somewhere else every blink[0]..blink[1] s: find it again.
  function glide(o) {
    return {
      kind: 'track',
      setup(st, here) {
        const B = wallBox(o, o.r), mid = [0, (B.lo + B.hi) / 2];
        let p = here ? [clamp(Math.tan(yaw) * o.d, -B.X, B.X), clamp(EYE + Math.tan(pitch) * o.d, B.lo, B.hi)] : mid.slice();
        st.targets = [{c: [p[0], p[1], -o.d], r: o.r, born: st.t}];
        st.g = {B, mid, to: null, dir: Math.random() * 2 * Math.PI, bend: 0, flip: st.t, out: true, ang: 0, cw: 1,
                blink: st.t + (o.blink ? rand(...o.blink) : 1e9), s: rand(o.smin, o.smax)};
        st.mv = {v: 0, goal: 0};
      },
      update(st, dt) {
        const tg = st.targets[0], g = st.g, B = g.B;
        if (!tg) return;
        const x0 = tg.c[0];
        if (st.t >= g.blink) {
          tg.c[0] = rand(-B.X, B.X) * 0.8; tg.c[1] = rand(B.lo, B.hi); g.to = null; g.blink = st.t + rand(...o.blink);
        }
        if (o.path === 'circle') {
          if (!g.c || st.t >= g.flip) { g.c = g.c || [tg.c[0] - o.R, tg.c[1]]; g.cw = Math.random() < 0.5 ? -1 : 1; g.flip = st.t + rand(1.5, 3); g.s = rand(o.smin, o.smax); }
          g.c[0] = clamp(g.c[0] + Math.sin(st.t * 0.7) * 0.6 * dt, -B.X + o.R, B.X - o.R);
          g.c[1] = clamp(g.c[1] + Math.cos(st.t * 0.5) * 0.3 * dt, B.lo + o.R, Math.max(B.lo + o.R, B.hi - o.R));
          g.ang += g.cw * g.s / o.R * dt;
          tg.c[0] = g.c[0] + Math.cos(g.ang) * o.R; tg.c[1] = g.c[1] + Math.sin(g.ang) * o.R;
        } else if (o.path === 'arc') {
          if (st.t >= g.flip) { g.bend = (Math.random() < 0.5 ? -1 : 1) * rand(o.bmin, o.bmax) * D2R; g.flip = st.t + rand(0.5, 1.3); g.s = rand(o.smin, o.smax); }
          g.dir += g.bend * dt;
          tg.c[0] += Math.cos(g.dir) * g.s * dt; tg.c[1] += Math.sin(g.dir) * g.s * dt;
          if (Math.abs(tg.c[0]) > B.X) { tg.c[0] = Math.sign(tg.c[0]) * B.X; g.dir = Math.PI - g.dir; }
          if (tg.c[1] < B.lo || tg.c[1] > B.hi) { tg.c[1] = clamp(tg.c[1], B.lo, B.hi); g.dir = -g.dir; }
        } else {                                 // line and star: straight to the next point
          if (!g.to) {
            if (o.path === 'star') { g.out = !g.out; g.to = g.out ? g.mid.slice() : [rand(-B.X, B.X), rand(B.lo, B.hi)]; }
            else g.to = [rand(-B.X, B.X), rand(B.lo, B.hi)];
            if (o.path === 'star' && !g.out) {
              const a = Math.random() * 2 * Math.PI, R = Math.min(B.X, (B.hi - B.lo) / 2) * rand(0.7, 1);
              g.to = [g.mid[0] + Math.cos(a) * R * (B.X / Math.min(B.X, (B.hi - B.lo) / 2)) * 0.9, g.mid[1] + Math.sin(a) * R];
            }
            g.s = rand(o.smin, o.smax);
          }
          const dx = g.to[0] - tg.c[0], dy = g.to[1] - tg.c[1], dist = Math.hypot(dx, dy), stepLen = g.s * dt;
          if (dist <= stepLen) { tg.c[0] = g.to[0]; tg.c[1] = g.to[1]; g.to = null; }
          else { tg.c[0] += dx / dist * stepLen; tg.c[1] += dy / dist * stepLen; }
        }
        const v = dt ? (tg.c[0] - x0) / dt : 0;                // for Aim insights: which way it's going
        st.mv.v = Math.abs(v) < 20 ? v : 0; st.mv.goal = Math.abs(v) > 0.8 ? Math.sign(v) : st.mv.goal;
      },
    };
  }
  // switch tracking: n targets moving on a wall, each needs hp seconds of fire on it; then the next one comes.
  // vy: also up and down. evade: dodges (turns around) while you're on it.
  function tswitch(o) {
    return {
      kind: 'track',
      setup(st) { st.targets = []; st.kills = 0; for (let i = 0; i < o.n; i++) this.spawn(st); },
      spawn(st) {
        const B = wallBox(o, o.r);
        let x, y, k = 0;
        do { x = rand(-B.X, B.X); y = rand(B.lo, B.hi); k++; }
        while (k < 30 && st.targets.some(t => Math.hypot(t.c[0] - x, t.c[1] - y) < 2));
        st.targets.push({c: [x, y, -o.d], r: o.r, born: st.t, hp: o.hp, v: this.vel(), flip: st.t + rand(o.fmin, o.fmax)});
      },
      vel() { return [(Math.random() < 0.5 ? -1 : 1) * rand(o.smin, o.smax), o.vy ? rand(-o.vy, o.vy) : 0]; },
      update(st, dt) {
        const on = firing ? aimed() : null;
        for (const tg of [...st.targets]) {
          const B = wallBox(o, tg.r);
          if (st.t >= tg.flip) { const v = this.vel(); tg.v = [-Math.sign(tg.v[0]) * Math.abs(v[0]), v[1]]; tg.flip = st.t + rand(o.fmin, o.fmax); }
          if (o.evade && tg === on && Math.random() < o.evade * dt) { tg.v[0] = -tg.v[0]; tg.flip = st.t + rand(o.fmin, o.fmax); }
          tg.c[0] += tg.v[0] * dt; tg.c[1] += tg.v[1] * dt;
          if (Math.abs(tg.c[0]) > B.X) { tg.c[0] = Math.sign(tg.c[0]) * B.X; tg.v[0] = -tg.v[0]; }
          if (tg.c[1] < B.lo || tg.c[1] > B.hi) { tg.c[1] = clamp(tg.c[1], B.lo, B.hi); tg.v[1] = -tg.v[1]; }
          tg.r = o.r * (0.75 + 0.25 * tg.hp / o.hp);              // smaller while it takes damage
        }
        if (on) {
          on.hp -= dt;
          if (on.hp <= 0) { st.targets.splice(st.targets.indexOf(on), 1); st.kills++; this.spawn(st); tick(900); }
        }
      },
    };
  }
  // ---- 4.28: map angles. You stand where C.angles.current says (a callout of a real site), looking at another
  // callout; enemies peek out from behind cover at the other callouts in front of you, at their real direction
  // (yaw, right positive) and distance (stats/mapangles.py). The callout's name shows when one appears.
  // Only the head kills; a body shot counts but the enemy keeps going.
  function mapspots(o) {
    o = Object.assign({win: 0.85, min: 0.45, out: 0.16}, o);
    return {
      kind: 'click', heads: true,
      setup(st) {
        let cur = (C.angles && C.angles.current) || null;
        if (!cur && C.angles) {                       // played from the library card: the first map and spot
          const m = Object.keys(C.angles)[0];
          if (m) cur = C.angles.current = Object.assign({map: m}, C.angles[m][0]);
        }
        if (!cur) setTimeout(() => cue('No map data yet'), 50);
        st.where = cur ? `${cur.map} · ${cur.name}` : '';
        st.spots = (cur ? cur.spots : []).map(s => {
          const a = s.yaw * D2R, d = clamp(s.d, 3, 33);
          const f = [Math.sin(a), -Math.cos(a)], side = [Math.cos(a), Math.sin(a)];        // forward, to the right
          const c = [f[0] * d, f[1] * d], sgn = Math.random() < 0.5 ? -1 : 1;             // which side it peeks from
          const box = [c[0] + side[0] * sgn * 0.75, c[1] + side[1] * sgn * 0.75];
          return {label: s.label, sgn, hide: [box[0], 0, box[1]], show: [c[0] - side[0] * sgn * 0.35, 0, c[1] - side[1] * sgn * 0.35],
                  cover: {min: [box[0] - 0.7, 0, box[1] - 0.7], max: [box[0] + 0.7, 2.3, box[1] + 0.7]}};
        });
        st.covers = st.spots.map(s => s.cover);
        st.window = o.win; st.targets = []; st.next = st.t + rand(0.6, 1.2); st.escaped = 0; st.body = 0; st.lastSpot = -1;
      },
      update(st, dt) {
        let tg = st.targets[0];
        if (!tg && st.t >= st.next && st.spots.length) {
          let i; do { i = Math.floor(Math.random() * st.spots.length); } while (st.spots.length > 1 && i === st.lastSpot);
          st.lastSpot = i;
          const s = st.spots[i];
          tg = {agent: true, c: s.hide.slice(), born: Infinity, side: s.sgn, spot: s, phase: 'out', t0: st.t};
          st.targets = [tg];
          return;
        }
        if (!tg) return;
        const s = tg.spot, k = Math.min(1, (st.t - tg.t0) / o.out);
        const lerp = (a, b, x) => [a[0] + (b[0] - a[0]) * x, 0, a[2] + (b[2] - a[2]) * x];
        if (tg.phase === 'out') {
          tg.c = lerp(s.hide, s.show, k);
          if (tg.born === Infinity && k > 0.55) { tg.born = st.t; cue(s.label); }        // the head is out: the clock starts
          if (k >= 1) { tg.phase = 'stay'; tg.t0 = st.t; }
        } else if (tg.phase === 'stay') {
          if (st.t - tg.t0 >= st.window) { tg.phase = 'in'; tg.t0 = st.t; }
        } else {
          tg.c = lerp(s.show, s.hide, k);
          if (k >= 1) { st.targets = []; st.escaped++; st.window = Math.min(o.win + 0.1, st.window + 0.03); st.next = st.t + rand(0.5, 1.3); }
        }
      },
      hit(st, tg, head) {
        if (!head) { st.body++; return false; }
        st.targets = []; st.window = Math.max(o.min, st.window - 0.02); st.next = st.t + rand(0.5, 1.3);
        return true;
      },
    };
  }
  const GRID_X = [-2.4, -1.2, 0, 1.2, 2.4], GRID_Y = [0.75, 1.65, 2.55, 3.45];
  const SC = {
    grid: {
      kind: 'click',
      setup(st) { st.cells = new Set(); st.targets = []; for (let i = 0; i < 3; i++) this.spawn(st); },
      spawn(st) {
        let k; do { k = Math.floor(Math.random() * 20); } while (st.cells.has(k));
        st.cells.add(k);
        st.targets.push({c: [GRID_X[k % 5], GRID_Y[Math.floor(k / 5)], -10], r: 0.36, born: st.t, cell: k});
      },
      hit(st, tg) { st.cells.delete(tg.cell); st.targets.splice(st.targets.indexOf(tg), 1); this.spawn(st); },
      since(st) { return st.lastHit; },
    },
    headline: {
      kind: 'click',
      setup(st) { st.prev = 0; st.targets = []; this.spawn(st); },
      spawn(st) {
        let a; do { a = rand(-45, 45); } while (Math.abs(a - st.prev) < 12);
        st.prev = a;
        st.targets = [{c: atAngle(a, 12, EYE + rand(-0.04, 0.04)), r: 0.21, born: st.t}];
      },
      hit(st) { this.spawn(st); },
    },
    micro: {
      kind: 'click',
      setup(st) { st.ya = 0; st.pa = 0; st.targets = []; this.spawn(st); },
      spawn(st) {
        const step = rand(1.4, 4.5), dir = Math.random() * 2 * Math.PI;
        st.ya = clamp(st.ya + Math.cos(dir) * step, -28, 28); st.pa = clamp(st.pa + Math.sin(dir) * step * 0.5, -3, 4);
        const d = 18, c = atAngle(st.ya, d * Math.cos(st.pa * D2R), EYE + Math.tan(st.pa * D2R) * d);
        st.targets = [{c, r: 0.11, born: st.t}];
      },
      hit(st) { this.spawn(st); },
    },
    // close: big targets 6–8 m away, far around you (an enemy in your face). far: small ones 22–30 m away
    flick_close: flicks({dmin: 6, dmax: 8, r: 0.32, amin: 35, amax: 85, pmin: -8, pmax: 12, vert: 0.3}),
    flick_far: flicks({dmin: 22, dmax: 30, r: 0.2, amin: 6, amax: 28, pmin: -3, pmax: 5, vert: 0.25}),
    peek: peeks({}),
    holdangle: angle({}),
    track: tracker({d: 9, r: 0.38, y: 1.35, bob: 0.06, vmin: 2.4, vmax: 5.2, fmin: 0.25, fmax: 1.1, bound: 5}),
    // close: an enemy 4.5 m away, fast across the screen. far: small, 20 m away. reactive: short ADAD strafes
    // with sudden stops, like a player dodging
    track_close: tracker({d: 4.5, r: 0.34, y: 1.4, bob: 0.05, vmin: 3.4, vmax: 6.2, fmin: 0.25, fmax: 0.8, bound: 2.8, acc: 32}),
    track_far: tracker({d: 20, r: 0.24, y: 1.45, bob: 0.04, vmin: 2.0, vmax: 4.2, fmin: 0.5, fmax: 1.5, bound: 9}),
    track_react: tracker({d: 9, r: 0.36, y: 1.4, vmin: 4.2, vmax: 6.2, fmin: 0.12, fmax: 0.45, bound: 4.5, acc: 60, stop: 0.3}),
    // ---- 4.23: the library (names and texts in stats/trainer.py)
    flick_mid: flicks({dmin: 12, dmax: 16, r: 0.26, amin: 15, amax: 45}),
    flick_wide: flicks({dmin: 8, dmax: 11, r: 0.3, amin: 50, amax: 70, vert: 0.2}),
    flick_vert: flicks({dmin: 10, dmax: 14, r: 0.26, amin: 10, amax: 28, vert: 0.95, pmin: -8, pmax: 16}),
    flick_tiny: flicks({dmin: 14, dmax: 18, r: 0.12, amin: 8, amax: 30, pmin: -3, pmax: 6}),
    spider: spider({dmin: 8, dmax: 9, r: 0.3, amin: 20, amax: 45}),
    spider_far: spider({dmin: 18, dmax: 22, r: 0.16, amin: 6, amax: 18}),
    six_shot: multi({n: 6, w: 20, pmin: -4, pmax: 12, dmin: 12, dmax: 12, r: 0.28, sep: 6}),
    head_switch: multi({n: 4, w: 35, head: true, dmin: 13, dmax: 16, r: 0.2, sep: 9}),
    close_switch: multi({n: 3, w: 65, pmin: -6, pmax: 10, dmin: 5, dmax: 7, r: 0.32, sep: 25}),
    tiny_switch: multi({n: 5, w: 15, pmin: -3, pmax: 6, dmin: 18, dmax: 20, r: 0.13, sep: 4}),
    double_tap: multi({n: 3, w: 25, pmin: -3, pmax: 8, dmin: 10, dmax: 14, r: 0.3, hp: 2, sep: 8}),
    reflex: timed({dmin: 10, dmax: 13, r: 0.3, amin: 10, amax: 40, life: 1.1, min: 0.45}),
    reflex_small: timed({dmin: 14, dmax: 18, r: 0.17, amin: 5, amax: 25, life: 1.0, min: 0.5}),
    reflex_wide: timed({dmin: 7, dmax: 9, r: 0.3, amin: 40, amax: 70, life: 1.2, min: 0.55, vert: 0.2}),
    pinpoint: multi({n: 1, w: 10, pmin: -2, pmax: 3, dmin: 24, dmax: 28, r: 0.1, sep: 2}),
    headline_far: flicks({dmin: 24, dmax: 30, r: 0.16, amin: 4, amax: 20, vert: 0.03, pmin: -0.5, pmax: 0.5}),
    micro_spider: spider({dmin: 16, dmax: 18, r: 0.12, amin: 1.5, amax: 5}),
    peek_far: peeks({z: 28, spread: 7, r: 0.2, win: 0.9, min: 0.45}),
    peek_fast: peeks({win: 0.6, min: 0.25, out: 0.08}),
    angle_close: angle({dmin: 5, dmax: 8, wmin: 2.2, wmax: 3}),
    angle_long: angle({dmin: 24, dmax: 32, wmin: 2, wmax: 3, win: 0.7}),
    angle_jiggle: angle({swing: 0.15, jiggle: 0.7}),
    angle_wide: angle({swing: 1, jiggle: 0, win: 0.75, wmin: 3.5, wmax: 5}),
    angle_runners: angle({swing: 0, jiggle: 0, fast: 1.25}),
    track_smooth: tracker({d: 11, r: 0.4, y: 1.4, bob: 0.04, vmin: 1.5, vmax: 2.8, fmin: 0.8, fmax: 2, bound: 5}),
    track_fast: tracker({d: 7, r: 0.32, y: 1.4, vmin: 5.5, vmax: 7.5, fmin: 0.2, fmax: 0.6, bound: 3.8, acc: 45}),
    track_tiny: tracker({d: 14, r: 0.18, y: 1.45, bob: 0.03, vmin: 2, vmax: 4, fmin: 0.4, fmax: 1.2, bound: 6}),
    track_jump: strafer({d: 8, r: 0.34, y: 1.4, vmin: 3, vmax: 5, fmin: 0.3, fmax: 0.9, bound: 4, jump: true}),
    track_crouch: strafer({d: 8, r: 0.34, y: 1.45, vmin: 3, vmax: 5, fmin: 0.3, fmax: 0.9, bound: 4, duck: true}),
    orbit: orbit({d: 7, r: 0.36, y: 1.4, wmin: 25, wmax: 60, fmin: 0.6, fmax: 1.6, span: 75}),
    orbit_air: orbit({d: 9, r: 0.34, y: 1.4, wmin: 20, wmax: 45, fmin: 0.5, fmax: 1.4, jump: true}),
    orbit_vert: orbit({d: 8, r: 0.34, y: 1.6, wmin: 10, wmax: 30, fmin: 0.5, fmax: 1.2, vy: 2.2}),
    // ---- 4.24: the drill types from the big aim trainers, our own versions (names and texts in stats/trainer.py)
    bounce_shot: bounce({n: 3, w: 28, pmin: -4, pmax: 14, d: 12, r: 0.3, smin: 2, smax: 4}),
    bounce_fast: bounce({n: 3, w: 28, pmin: -4, pmax: 14, d: 12, r: 0.26, smin: 4.5, smax: 7}),
    bounce_close: bounce({n: 2, w: 55, pmin: -8, pmax: 16, d: 6, r: 0.32, smin: 3, smax: 5}),
    bounce_tiny: bounce({n: 4, w: 20, pmin: -3, pmax: 10, d: 14, r: 0.15, smin: 1.5, smax: 3}),
    jink: bounce({n: 1, w: 25, pmin: -3, pmax: 14, d: 10, r: 0.28, smin: 4, smax: 6, jink: [0.35, 0.9]}),
    jink_small: bounce({n: 1, w: 22, pmin: -3, pmax: 12, d: 13, r: 0.16, smin: 3.5, smax: 5.5, jink: [0.3, 0.8]}),
    hops: bounce({n: 2, w: 25, pmin: -6, pmax: 16, d: 10, r: 0.3, smin: 1, smax: 2.5, grav: 9, hop: 7}),
    hops_small: bounce({n: 2, w: 25, pmin: -6, pmax: 16, d: 12, r: 0.17, smin: 1.5, smax: 3, grav: 11, hop: 8}),
    motion_shot: bounce({n: 1, w: 30, pmin: -4, pmax: 14, d: 10, r: 0.32, smin: 2, smax: 3.5}),
    motion_far: bounce({n: 1, w: 18, pmin: -2, pmax: 8, d: 22, r: 0.22, smin: 2, smax: 3.5}),
    strafe_shot: bounce({n: 3, w: 30, pmin: -3, pmax: 12, d: 11, r: 0.28, smin: 2.5, smax: 5, horiz: true}),
    strafe_heads: bounce({n: 2, w: 30, pmin: -0.4, pmax: 0.4, d: 13, r: 0.19, smin: 3, smax: 5, horiz: true}),
    horde: bounce({n: 6, w: 35, pmin: -3, pmax: 8, d: 28, r: 0.3, smin: 2.5, smax: 4, toward: true, near: 5}),
    horde_fast: bounce({n: 8, w: 40, pmin: -3, pmax: 8, d: 28, r: 0.28, smin: 4, smax: 6.5, toward: true, near: 5}),
    shrinking: bounce({n: 3, w: 25, pmin: -3, pmax: 12, d: 12, r: 0.36, smin: 0.6, smax: 1.4, life: 1.8, shrink: 0.3}),
    flick_180: flicks({dmin: 7, dmax: 9, r: 0.34, amin: 90, amax: 175, vert: 0.12, back: true}),
    spider_180: spider({dmin: 8, dmax: 9, r: 0.34, amin: 60, amax: 170, flat: 0.08}),
    flick_speed: flicks({dmin: 9, dmax: 11, r: 0.42, amin: 10, amax: 40}),
    flick_precise: flicks({dmin: 12, dmax: 14, r: 0.14, amin: 10, amax: 40}),
    flick_low: flicks({dmin: 9, dmax: 13, r: 0.26, amin: 10, amax: 40, vert: 0.2, pmin: -14, pmax: -4}),
    flick_high: flicks({dmin: 9, dmax: 13, r: 0.26, amin: 10, amax: 40, vert: 0.2, pmin: 10, pmax: 22}),
    grid_speed: multi({n: 4, w: 14, pmin: -2, pmax: 10, dmin: 10, dmax: 10, r: 0.42, sep: 7}),
    grid_precise: multi({n: 3, w: 14, pmin: -2, pmax: 10, dmin: 10, dmax: 10, r: 0.17, sep: 6}),
    six_precise: multi({n: 6, w: 20, pmin: -4, pmax: 12, dmin: 12, dmax: 12, r: 0.16, sep: 6}),
    wide_three: multi({n: 3, w: 55, pmin: -4, pmax: 12, dmin: 10, dmax: 10, r: 0.28, sep: 30}),
    wide_five: multi({n: 5, w: 60, pmin: -4, pmax: 12, dmin: 10, dmax: 10, r: 0.24, sep: 20}),
    heads_range: multi({n: 3, w: 40, head: true, dmin: 8, dmax: 26, r: 0.16, sep: 8}),
    triple_tap: multi({n: 2, w: 25, pmin: -3, pmax: 8, dmin: 10, dmax: 14, r: 0.32, hp: 3, sep: 10}),
    burst: burst({k: 3, spread: 3, amin: 20, amax: 50, d: 12, r: 0.24}),
    burst_wide: burst({k: 4, spread: 5, amin: 40, amax: 80, d: 9, r: 0.28}),
    burst_micro: burst({k: 3, spread: 1.5, amin: 8, amax: 25, d: 18, r: 0.12}),
    side_vision: popups({w: 75, pmin: -5, pmax: 15, dmin: 8, dmax: 12, r: 0.3, every: [0.5, 1.0], life: 1.5, max: 3}),
    friend_foe: popups({w: 30, pmin: -3, pmax: 12, dmin: 10, dmax: 13, r: 0.28, every: [0.35, 0.7], life: 1.3, bad: 0.4}),
    friend_foe_fast: popups({w: 35, pmin: -3, pmax: 12, dmin: 11, dmax: 14, r: 0.24, every: [0.25, 0.5], life: 0.8, bad: 0.5, max: 5}),
    popups: popups({w: 35, pmin: -3, pmax: 12, dmin: 10, dmax: 13, r: 0.3, every: [0.35, 0.7], life: 1.1}),
    reflex_close: timed({dmin: 5, dmax: 6, r: 0.34, amin: 30, amax: 90, life: 1.0, min: 0.45, vert: 0.25}),
    reflex_head: timed({dmin: 12, dmax: 16, r: 0.18, amin: 6, amax: 35, life: 0.9, min: 0.45, vert: 0.03, pmin: -0.5, pmax: 0.5}),
    line_trace: glide({path: 'line', w: 25, pmin: -2, pmax: 14, d: 10, r: 0.32, smin: 2.5, smax: 4}),
    line_trace_small: glide({path: 'line', w: 20, pmin: -2, pmax: 12, d: 14, r: 0.18, smin: 2.5, smax: 4}),
    arc_track: glide({path: 'arc', w: 25, pmin: -2, pmax: 14, d: 10, r: 0.32, smin: 3, smax: 4.5, bmin: 90, bmax: 200}),
    star_track: glide({path: 'star', w: 18, pmin: -3, pmax: 14, d: 10, r: 0.3, smin: 3.5, smax: 5}),
    star_micro: glide({path: 'star', w: 5, pmin: -2, pmax: 3, d: 16, r: 0.14, smin: 1.2, smax: 1.8}),
    circle_track: glide({path: 'circle', w: 22, pmin: -2, pmax: 14, d: 10, r: 0.3, smin: 3, smax: 4.5, R: 1.5}),
    circle_small: glide({path: 'circle', w: 18, pmin: -2, pmax: 10, d: 13, r: 0.18, smin: 2, smax: 3, R: 0.7}),
    blink_track: glide({path: 'line', w: 30, pmin: -3, pmax: 14, d: 10, r: 0.3, smin: 2.5, smax: 4, blink: [1.1, 2]}),
    track_above: tracker({d: 9, r: 0.34, y: 4.2, bob: 0.08, vmin: 2.4, vmax: 5, fmin: 0.3, fmax: 1.1, bound: 5}),
    track_below: tracker({d: 7, r: 0.34, y: 0.6, bob: 0.04, vmin: 2.4, vmax: 5, fmin: 0.3, fmax: 1.1, bound: 4}),
    track_long: tracker({d: 10, r: 0.36, y: 1.4, bob: 0.04, vmin: 3, vmax: 5, fmin: 1.4, fmax: 3, bound: 7}),
    track_close_long: tracker({d: 5, r: 0.34, y: 1.4, bob: 0.04, vmin: 3.5, vmax: 5.5, fmin: 1.2, fmax: 2.5, bound: 4.5}),
    track_zigzag: tracker({d: 9, r: 0.32, y: 1.4, vmin: 4, vmax: 6, fmin: 0.12, fmax: 0.28, bound: 3, acc: 70}),
    orbit_fast: orbit({d: 7, r: 0.34, y: 1.4, wmin: 50, wmax: 90, fmin: 0.4, fmax: 1.2, span: 80}),
    tswitch: tswitch({n: 3, w: 25, pmin: -3, pmax: 12, d: 10, r: 0.34, hp: 0.6, smin: 1.5, smax: 3, fmin: 0.6, fmax: 1.6}),
    tswitch_fast: tswitch({n: 3, w: 25, pmin: -3, pmax: 12, d: 10, r: 0.32, hp: 0.4, smin: 3, smax: 5, fmin: 0.4, fmax: 1.1}),
    tswitch_evasive: tswitch({n: 3, w: 25, pmin: -3, pmax: 12, d: 10, r: 0.32, hp: 0.6, smin: 3, smax: 5, fmin: 0.5, fmax: 1.3, evade: 3}),
    tswitch_wide: tswitch({n: 3, w: 60, pmin: -4, pmax: 14, d: 7, r: 0.34, hp: 0.5, smin: 2, smax: 4, fmin: 0.6, fmax: 1.5}),
    tswitch_small: tswitch({n: 3, w: 20, pmin: -2, pmax: 10, d: 14, r: 0.2, hp: 0.6, smin: 1.5, smax: 3, fmin: 0.6, fmax: 1.6}),
    tswitch_float: tswitch({n: 3, w: 25, pmin: -4, pmax: 16, d: 10, r: 0.32, hp: 0.5, smin: 1.5, smax: 3.5, vy: 2.5, fmin: 0.5, fmax: 1.3}),
    map_angles: mapspots({}),
  };
  // The sens finder's test: parts of the same scenarios back to back, without breaks (switching seamlessly, the
  // trackers starting at the crosshair). quick: flicks (close and far in turn), then tracking. 15 and 30 minutes:
  // close flicks, far flicks, close tracking, far tracking, reactive tracking.
  const PART = {
    flick: {flick: true, h: {
      kind: 'click',
      near: flicks({dmin: 10, dmax: 12, r: 0.3, amin: 15, amax: 50}),
      far: flicks({dmin: 18, dmax: 20, r: 0.12, amin: 2, amax: 5, vert: 0.6}),
      setup(st) { st.flickN = 0; st.targets = []; this.spawn(st); },
      spawn(st) { st.flickN++; (st.flickN % 2 ? this.near : this.far).spawn(st); },
      hit(st) { pathHit(st); this.spawn(st); },
    }},
    fc: {flick: true, h: SC.flick_close}, ff: {flick: true, h: SC.flick_far},
    tm: {h: SC.track}, tc: {h: SC.track_close}, tf: {h: SC.track_far}, tr: {h: SC.track_react},
  };
  const PART_LABEL = {fc: 'Close flicks', ff: 'Far flicks', tc: 'Close tracking', tf: 'Far tracking', tr: 'Reactive tracking', flick: 'Flicks', tm: 'Tracking'};
  const PART_NAME = {flick: 'Flicks', fc: 'Close flicks', ff: 'Far flicks', tm: 'Track it', tc: 'Close tracking: stay on it',
                     tf: 'Far tracking: stay on it', tr: 'Reactive tracking: stay on it'};
  SC.mix = {
    kind: 'click',
    setup(st) {
      st.parts = {}; st.over = []; st.under = []; st.trackOn = 0; st.trackT = 0; st.segI = -1;
      this.next(st);
    },
    next(st) {                       // the next part of the round, at the crosshair
      st.segI++;
      const [type, secs] = st.segs[st.segI], p = PART[type];
      st.seg = {type, until: (st.segI ? st.seg.until : 0) + secs, h: p.h, flick: !!p.flick};
      st.tracking = !p.flick; st.path = null;
      st.parts[type] = st.parts[type] || {points: 0, hits: 0, shots: 0, on: 0, t: 0};
      p.h.setup(st, true);
      if (st.segI > 0 || st.started) cue(PART_NAME[type]);
    },
    update(st, dt) {
      while (st.t >= st.seg.until && st.segI < st.segs.length - 1) this.next(st);
      const part = st.parts[st.seg.type];
      if (st.seg.h.update) st.seg.h.update(st, dt);
      if (st.tracking) {
        const on = !!aimed();
        st.trackT += dt; part.t += dt;
        if (on) { st.trackOn += dt; part.on += dt; }
      }
    },
    hit(st, tg) { st.seg.h.hit(st, tg); },
  };
  for (const [id, sc] of Object.entries(SC)) if (!byId[id]) byId[id] = {id, name: id, kind: sc.kind, seconds: 45, about: ''};

  // ------------------------------------------------------------------ what Aim insights needs from each run
  // Compact sums, no raw samples (stats/trainer.py clean_detail checks the shape):
  //   f.d[8]: flicks by direction (0 right, 2 up, 4 left, 6 down): [count, ms, overshoot, stop-short, measured]
  //   f.s[3]: flicks by size (under 10°, 10–30°, over 30°): [count, ms]
  //   f.m: misses near a target: count, left/right/high/low of it, g: where (0.5° cells, ±3°, "col,row": count)
  //   t: tracking while the target moves left / right: [seconds, seconds on it]; lead: [sum, n] (° ahead of it,
  //      negative = behind); re: [ms, n] to be back on it after it changes direction
  //   p: enemies peeking from the left / right: [kills, ms, headshots]; place: [° above the head, ° to the side,
  //      n] where the crosshair was when one showed up; body: body shots
  const angOf = c => [Math.atan2(c[0], -c[2]), Math.atan2(c[1] - EYE, Math.hypot(c[0], c[2]))];
  const DEG = 180 / Math.PI;
  function ixNew() {
    return {f: {d: Array.from({length: 8}, () => [0, 0, 0, 0, 0]), s: [[0, 0], [0, 0], [0, 0]], m: {n: 0, l: 0, r: 0, h: 0, lo: 0, g: {}}},
            t: {L: [0, 0], R: [0, 0], lead: [0, 0], re: [0, 0]}, p: {L: [0, 0, 0], R: [0, 0, 0], place: [0, 0, 0], body: 0}};
  }
  function headOf(tg) { return tg.agent ? [tg.c[0], tg.c[1] + HEAD_Y, tg.c[2]] : tg.c; }
  function ixFlick(st, tg, ms) {          // a hit on a single target: direction, size, time, how the path went
    if (tg.agent || !st.ix) return;
    const from = st.from || {y: 0, p: 0};
    const [ty, tp] = angOf(tg.c), vy = ty - from.y, vp = tp - from.p, len = Math.hypot(vy, vp) * DEG;
    if (len < 2) return;
    const k = ((Math.round(Math.atan2(vp, vy) / (Math.PI / 4)) % 8) + 8) % 8, d = st.ix.f.d[k];
    d[0]++; d[1] += ms;
    const p = st.path;
    if (p && st.pathFor === tg && p.len > 4 / DEG) {
      const tol = p.tol / p.len;
      d[2] += Math.max(0, p.max - 1 - tol); d[3] += p.stop === null ? 0 : Math.max(0, 1 - tol - p.stop); d[4]++;
    }
    const s = st.ix.f.s[len < 10 ? 0 : len < 30 ? 1 : 2];
    s[0]++; s[1] += ms;
  }
  function ixMiss(st) {                   // a shot that missed: where, relative to the nearest target
    if (!st.ix || !st.targets.length) return;
    let best = null, bd = Infinity;
    for (const tg of st.targets) {
      const [ty, tp] = angOf(headOf(tg)), dx = (yaw - ty) * DEG, dy = (pitch - tp) * DEG, dd = Math.hypot(dx, dy);
      if (dd < bd) { bd = dd; best = {dx, dy, r: Math.atan((tg.agent ? HEAD_R : tg.r) / Math.hypot(...headOf(tg).map((v, i) => v - [0, EYE, 0][i]))) * DEG}; }
    }
    if (!best || bd > 8) return;
    const m = st.ix.f.m;
    m.n++;
    if (Math.abs(best.dx) > best.r) best.dx < 0 ? m.l++ : m.r++;
    if (Math.abs(best.dy) > best.r) best.dy > 0 ? m.h++ : m.lo++;
    const cx = Math.round(best.dx * 2), cy = Math.round(best.dy * 2);
    if (Math.abs(cx) <= 6 && Math.abs(cy) <= 6) { const key = cx + ',' + cy; m.g[key] = (m.g[key] || 0) + 1; }
  }
  function ixTrack(st, dt, on) {          // tracking: direction, on target, ahead or behind, catching up after a turn
    const tg = st.targets[0], m = st.mv;
    if (!st.ix || !tg || !m) return;
    const v = m.v, side = v < 0 ? 'L' : 'R';
    if (Math.abs(v) > 0.8) {
      st.ix.t[side][0] += dt; if (on) st.ix.t[side][1] += dt;
      const err = (yaw - angOf(tg.c)[0]) * DEG * Math.sign(v);
      if (Math.abs(err) < 6) { st.ix.t.lead[0] += err * dt; st.ix.t.lead[1] += dt; }
    }
    const sg = Math.sign(m.goal || 0);
    if (st.trackSign && sg && sg !== st.trackSign) { st.turnAt = st.t; }
    if (sg) st.trackSign = sg;
    if (st.turnAt !== undefined && on) {
      const ms = (st.t - st.turnAt) * 1000;
      if (ms < 1500) { st.ix.t.re[0] += ms; st.ix.t.re[1]++; }
      st.turnAt = undefined;
    }
  }
  function ixPeek(st) {                   // an enemy just showed up: where was the crosshair?
    if (!st.ix) return;
    for (const tg of st.targets) {
      if (tg.placed || tg.born === Infinity || (tg.phase && tg.phase === 'out' && !tg.agent)) continue;
      if (!(tg.agent || st.id === 'peek')) continue;
      tg.placed = true;
      const [hy, hp] = angOf(headOf(tg));
      st.ix.p.place[0] += (pitch - hp) * DEG; st.ix.p.place[1] += Math.abs(yaw - hy) * DEG; st.ix.p.place[2]++;
      tg.from = tg.agent ? (tg.side < 0 ? 'L' : 'R') : (tg.x1 < tg.x0 ? 'L' : 'R');
    }
  }

  // ------------------------------------------------------------------ one run
  let st = null, yaw = 0, pitch = 0, raf = 0, last = 0, plan = null, raw = null, firing = false, audio = null;
  const scale = () => clamp(+C.scale || 1, 0.25, 4);
  function tick(hz = 1250) {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = hz; g.gain.setValueAtTime(0.06, audio.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.06);
      o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + 0.07);
    } catch (e) {}
  }
  function aimDir() {
    return [Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch)];
  }
  // the enemy model (feet at c): boxes for legs, body and arms, a sphere for the head at eye height (1.6 m)
  const HEAD_Y = 1.6, HEAD_R = 0.13;
  function agentBoxes(c) {
    const [x, y, z] = c, b = (x0, y0, z0, x1, y1, z1) => ({min: [x + x0, y + y0, z + z0], max: [x + x1, y + y1, z + z1]});
    return [b(-0.19, 0, -0.12, 0.19, 0.86, 0.12), b(-0.25, 0.86, -0.15, 0.25, 1.42, 0.15),
            b(-0.37, 0.92, -0.1, -0.25, 1.4, 0.1), b(0.25, 0.92, -0.1, 0.37, 1.4, 0.1), b(-0.06, 1.42, -0.06, 0.06, 1.5, 0.06)];
  }
  function aimedHit() {     // {tg, head} under the crosshair (not behind cover), or null
    if (!st) return null;
    const o = [0, EYE, 0], d = aimDir();
    let best = null, bt = Infinity, head = true;
    for (const tg of st.targets) {
      if (tg.agent) {
        const th = hitSphere(o, d, [tg.c[0], tg.c[1] + HEAD_Y, tg.c[2]], HEAD_R);
        if (th < bt) { bt = th; best = tg; head = true; }
        for (const b of agentBoxes(tg.c)) { const tb = hitBox(o, d, b); if (tb < bt) { bt = tb; best = tg; head = false; } }
      } else {
        const t = hitSphere(o, d, tg.c, tg.r);
        if (t < bt) { bt = t; best = tg; head = true; }
      }
    }
    if (best) for (const b of st.covers || []) if (hitBox(o, d, b) < bt) return null;
    return best ? {tg: best, head} : null;
  }
  function aimed() { const h = aimedHit(); return h ? h.tg : null; }
  function newRun(id) {
    const sc = byId[id], seconds = plan ? plan.items[plan.i].seconds : finder ? finder.mode.secs : sc.seconds;
    firing = false;
    st = {id, kind: SC[id].kind || sc.kind, seconds, t: 0, phase: 'ready', targets: [], covers: null, hits: 0, shots: 0,
          points: 0, times: [], lastHit: 0, on: 0, stalls: [], ix: finder ? null : ixNew(), from: {y: 0, p: 0}};
    yaw = 0; pitch = 0;
    if (finder) st.segs = finder.mode.segs;
    SC[id].setup(st);
  }
  function score() {
    if (!st) return 0;
    if (st.kind === 'track') return Math.round(1000 * st.on / st.seconds);
    if (st.id === 'mix') return Math.round(st.points * (st.shots ? st.hits / st.shots : 0) + 1000 * st.trackOn / Math.max(1, st.trackT));
    const acc = st.shots ? st.hits / st.shots : 0;
    return Math.round(st.points * acc);
  }
  function shoot() {
    if (!st || st.phase !== 'run' || st.kind === 'track' || st.tracking) return;
    const part = st.seg ? st.parts[st.seg.type] : null;
    st.shots++; if (part) part.shots++;
    const h = aimedHit();
    if (!h) { ixMiss(st); return; }
    const {tg, head} = h;
    if (tg.bad) {                                  // a blue one: shouldn't have shot it
      SC[st.id].hit(st, tg, head); st.wrong = (st.wrong || 0) + 1; st.points = Math.max(0, st.points - 150); tick(300); return;
    }
    const since = SC[st.id].since ? Math.max(tg.born, SC[st.id].since(st)) : tg.born;
    const ms = Math.max(0, (st.t - (isFinite(since) ? since : st.t)) * 1000);
    if (!head && tg.agent) { if (st.ix) st.ix.p.body++; }
    else if (st.ix && tg.from) { const pk = st.ix.p[tg.from]; pk[0]++; pk[1] += ms; pk[2]++; }
    else ixFlick(st, tg, ms);
    const res = SC[st.id].hit(st, tg, head);
    if (res === false) { tick(520); return; }                                // a body shot: counted, not a kill
    if (res === 'hp') { st.hits++; if (part) part.hits++; tick(900); return; } // a hit that doesn't kill yet (double tap)
    st.from = {y: yaw, p: pitch};
    const pts = 100 + clamp(100 * (1 - (ms - 250) / 750), 0, 100);
    st.hits++; st.times.push(ms); st.lastHit = st.t; st.points += pts;
    if (part) { part.hits++; part.points += pts; }
    tick();
  }
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const gap = now - (last || now), dt = Math.min(0.05, gap / 1000); last = now;
    if (st && st.phase === 'run' && gap > 120) st.stalls.push(Math.round(gap));     // the browser stood still
    const [w, h] = devicePixels(canvas);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    if (st && st.phase === 'count') {
      st.count -= dt;
      $('tr-count').textContent = Math.max(1, Math.ceil(st.count));
      if (st.count <= 0) {
        st.phase = 'run'; $('tr-count').hidden = true;
        if (!st.started) { st.started = true; for (const t of st.targets) t.born = 0; st.lastHit = 0; }
      }
    }
    let onTarget = null;
    if (st && st.phase === 'run') {
      st.t += dt;
      if (SC[st.id].update) SC[st.id].update(st, dt);
      if (st.kind === 'track') { onTarget = aimed(); if (firing && onTarget) st.on += dt; if (firing) st.fire = (st.fire || 0) + dt; }
      else if (st.tracking) onTarget = aimed();
      if (st.kind === 'track' || st.tracking) ixTrack(st, dt, !!onTarget);
      else if (st.targets.length === 1 && !st.targets[0].agent) {      // a single target: follow the flick to it
        const tg = st.targets[0];
        if (st.pathFor !== tg) { const [ty, tp] = angOf(tg.c); pathStart(st, ty, tp, tg.r, Math.hypot(tg.c[0], tg.c[1] - EYE, tg.c[2]), true); st.pathFor = tg; }
        else pathUpdate(st, dt);
      }
      ixPeek(st);
      if (st.t >= st.seconds) finish();
      updateHud();
    }
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.043, 0.06, 0.085, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.uniformMatrix4fv(loc.vp, false, mul(perspective(VFOV, w / h, 0.05, 200), view(yaw, pitch)));
    gl.uniform3fv(loc.eye, [0, EYE, 0]);
    drawRoom();
    if (!st) return;
    for (const b of st.covers || []) draw(meshes.box, model(b.min[0], b.min[1], b.min[2], b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]), COVER, 1);
    for (const tg of st.targets) {
      if (tg.agent) {
        for (const b of agentBoxes(tg.c)) draw(meshes.box, model(b.min[0], b.min[1], b.min[2], b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]), AGENT, 0, 0.1);
        draw(meshes.sphere, model(tg.c[0], tg.c[1] + HEAD_Y, tg.c[2], HEAD_R, HEAD_R * 1.1, HEAD_R), AGENT_HEAD, 0, 0.15);
        continue;
      }
      const on = tg === onTarget && (firing || st.tracking);
      draw(meshes.sphere, model(tg.c[0], tg.c[1], tg.c[2], tg.r, tg.r, tg.r), on && !tg.col ? TARGET_ON : tg.col || TARGET, 0, on ? 0.25 : 0.12);
    }
  }
  let cueT = null;
  function cue(text) {                       // a short line in the middle, e.g. when tracking starts
    const w = $('tr-cue');
    if (!w) return;
    w.textContent = text; w.hidden = false;
    clearTimeout(cueT); cueT = setTimeout(() => { w.hidden = true; }, 1300);
  }
  function updateHud() {
    $('tr-time').textContent = Math.max(0, Math.ceil(st.seconds - st.t));
    $('tr-score').textContent = score();
    if (st.tracking) { $('tr-l3').textContent = 'On target'; $('tr-acc').textContent = st.trackT ? Math.round(100 * st.trackOn / st.trackT) + '%' : '–'; }
    else if (st.kind === 'track') { $('tr-l3').textContent = 'On target'; $('tr-acc').textContent = st.t ? Math.round(100 * st.on / Math.max(st.t, 0.01)) + '%' : '–'; }
    else { $('tr-l3').textContent = SC[st.id].heads ? 'Headshots' : 'Accuracy'; $('tr-acc').textContent = st.shots ? Math.round(100 * st.hits / st.shots) + '%' : '–'; }
  }

  // ------------------------------------------------------------------ mouse and pointer lock
  document.addEventListener('mousemove', e => {
    if (document.pointerLockElement !== canvas || !st || st.phase === 'done') return;
    const k = YAW * sens() / scale() * Math.PI / 180;
    yaw += e.movementX * k;
    pitch = clamp(pitch - e.movementY * k, -1.55, 1.55);
  });
  canvas.addEventListener('mousedown', e => {
    if (document.pointerLockElement !== canvas) return;
    if (e.button === 0) { firing = true; shoot(); }
  });
  document.addEventListener('mouseup', e => { if (e.button === 0) firing = false; });
  async function lock() {
    try {
      const p = canvas.requestPointerLock({unadjustedMovement: true});
      raw = !!(p && p.then);                  // browsers that ignore the option return nothing
      await p;
    } catch (e) {
      try { await canvas.requestPointerLock(); } catch (e2) { canvas.requestPointerLock && canvas.requestPointerLock(); }
      raw = false;
    }
    const chip = $('tr-raw');
    chip.className = 'tr-raw ' + (raw ? 'ok' : 'warn');
    chip.textContent = raw ? 'Raw mouse input: on' : 'Raw mouse input: not in this browser';
    const w = $('tr-warn');
    w.hidden = raw;
    w.textContent = raw ? '' : 'This browser can\'t read the mouse raw: Windows\' "Enhance pointer precision" and pointer speed apply. Chrome, Edge or the Nexus app can.';
  }
  let unlockedAt = 0;
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement === canvas || !st) return;
    firing = false; unlockedAt = performance.now();
    if (st.phase === 'run' || st.phase === 'count') {
      st.phase = 'paused'; $('tr-count').hidden = true;
      showPaused();
    }
  });

  // ------------------------------------------------------------------ panels
  function setPanel(html) { panel.innerHTML = html; panel.hidden = !html; }
  function planStep() { return plan ? `<div class="tr-step">${esc(plan.name)} · round ${plan.i + 1} of ${plan.items.length}</div>` : ''; }
  function showReady() {
    const sc = byId[st.id];
    if (finder) {
      hud.hidden = true;
      const m = finder.mode, n = finderRounds(m);
      const how = m.segs.length > 2 ? 'Each round: close flicks, far flicks, then close, far and reactive tracking, without breaks. The text in the middle says what comes next. Shoot the targets; on the moving ones, just stay on them.'
        : 'Each round: shoot the targets, and when the moving one comes, just stay on it.';
      setPanel(`<div class="tr-step">Sens finder · ${esc(m.name)} · ${finder.i < m.warm ? 'warm-up' : `test ${finder.i - m.warm + 1} of ${n - m.warm}`}</div><h2>Find your sens</h2>
        <p>${m.warm === 1 ? 'One warm-up round' : 'Two warm-up rounds'} at your sens, then ${n - m.warm} rounds of ${m.secs} seconds at other sensitivities, blind and in random order.
        ${how} Don't think about the sens, aim like in a match.</p>
        <p>About ${m.minutes} minutes · Esc pauses · F fullscreen</p>
        <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Click to start</button><button type="button" class="btn ghost" data-a="quit">Back</button>${xhBtn()}</div>`);
      return;
    }
    hud.hidden = true;
    setPanel(`${planStep()}<h2>${esc(sc.name)}</h2><p>${esc(sc.about)}</p><p>${st.seconds} seconds · ${sc.kind === 'track' ? 'hold the left mouse button on the target' : 'left click to shoot'} · Esc pauses · F fullscreen</p>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Click to start</button><button type="button" class="btn ghost" data-a="quit">Back</button>${xhBtn()}</div>`);
  }
  function showPaused(again) {
    // the browser won't lock the mouse again right after Esc: Continue unlocks after a moment
    const where = finder ? `<div class="tr-step">Sens finder · ${esc(finder.mode.name)} · ${finder.i < finder.mode.warm ? 'warm-up' : `test ${finder.i - finder.mode.warm + 1}`}</div>` : planStep();
    setPanel(`${where}<h2>Paused</h2><p>${again ? 'The browser needs a moment after Esc: click Continue once more.' : `${Math.ceil(st.seconds - st.t)} seconds left in this round.`}</p>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="resume" id="tr-resume" disabled>Continue</button>
      ${finder ? '' : '<button type="button" class="btn ghost" data-a="restart">Start over</button>'}
      <button type="button" class="btn ghost" data-a="quit">${finder ? 'Stop the sens finder' : 'Quit'}</button>${xhBtn()}</div>
      <p style="margin:12px 0 0;font-size:12.5px">Enter or Space also continues.</p>`);
    const b = $('tr-resume'), wait = Math.max(0, 900 - (performance.now() - unlockedAt));
    setTimeout(() => { if (b.isConnected) { b.disabled = false; b.focus(); } }, wait);
  }
  // fullscreen while playing (switch on the page, F while playing). In the Nexus app the whole window goes
  // fullscreen through the app (WebView2 can't do it from the page alone).
  const fsBox = $('tr-fs');
  const wantFs = () => (fsBox ? fsBox.checked : true);
  try { const v = localStorage.getItem('vc-trainer-fs'); if (fsBox && v !== null) fsBox.checked = v === '1'; } catch (e) {}
  if (fsBox) fsBox.addEventListener('change', () => { try { localStorage.setItem('vc-trainer-fs', fsBox.checked ? '1' : '0'); } catch (e) {} });
  const appApi = () => (window.pywebview && window.pywebview.api && window.pywebview.api.fullscreen ? window.pywebview.api : null);
  let appFs = false;
  function isFs() { return appFs || !!document.fullscreenElement; }
  function enterFs() {
    if (isFs()) return;
    const api = appApi();
    if (api) { appFs = true; api.fullscreen(true).catch(() => { appFs = false; }); return; }
    if (stage.requestFullscreen) stage.requestFullscreen({navigationUI: 'hide'}).catch(() => {});
  }
  function exitFs() {
    const api = appApi();
    if (appFs && api) { appFs = false; api.fullscreen(false).catch(() => {}); }
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  function toggleFs() { if (isFs()) exitFs(); else enterFs(); }

  async function go(resume) {
    if (xPanel) xPanel.hidden = true;
    setPanel('');
    initAudio();
    if (wantFs()) enterFs();           // in the same click as the mouse lock
    await lock();
    if (document.pointerLockElement !== canvas) { resume ? showPaused(true) : showReady(); return; }   // the browser said no: try again
    hud.hidden = false;
    // back in: a short countdown, then on where it stopped (a round that hadn't started yet gets the full one)
    st.phase = 'count'; st.count = resume && st.started ? 1.5 : (finder && finder.i > 0 ? 2 : 3); $('tr-count').hidden = false;
    updateHud();
  }
  function initAudio() { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); } catch (e) {} }

  function ixRound(x) {                   // smaller numbers to send
    const r = v => Math.round(v * 1000) / 1000;
    return {f: {d: x.f.d.map(a => a.map(r)), s: x.f.s.map(a => a.map(r)), m: x.f.m},
            t: {L: x.t.L.map(r), R: x.t.R.map(r), lead: x.t.lead.map(r), re: x.t.re.map(r)},
            p: {L: x.p.L.map(r), R: x.p.R.map(r), place: x.p.place.map(r), body: x.p.body}};
  }
  function stallNote(stalls) {
    if (!stalls || !stalls.length) return '';
    return `<p class="tr-stall">The browser stood still ${stalls.length}× (up to ${Math.max(...stalls)} ms) during this, not the trainer: usually
      another program or a browser tab working in the background. Closing those helps.</p>`;
  }
  const xhBtn = () => '<button type="button" class="btn ghost" data-a="xh">Crosshair</button>';

  async function finish() {
    if (finder) { finderNext(); return; }
    st.phase = 'done'; firing = false;
    if (document.pointerLockElement) document.exitPointerLock();
    const sc = byId[st.id], s = score();
    const avg = st.times.length ? Math.round(st.times.reduce((a, b) => a + b, 0) / st.times.length) : null;
    const body = {scenario: st.id, score: s, seconds: st.seconds};
    if (st.kind === 'track') body.on_target = Math.round(1000 * st.on / st.seconds) / 1000;
    else Object.assign(body, {hits: st.hits, shots: st.shots, ms: avg || 0});
    if (SC[st.id].heads) Object.assign(body, {body: st.body || 0, escaped: st.escaped || 0});
    if (st.where) body.where = st.where;
    if (st.ix) body.detail = ixRound(st.ix);
    if (plan) { plan.total += s; if (plan.i === plan.items.length - 1) Object.assign(body, {plan_done: plan.kind, plan_score: plan.total}); }
    const cells = SC[st.id].heads
      ? `<div><dt>Headshots</dt><dd>${st.hits}/${st.shots}</dd></div><div><dt>Body shots · got away</dt><dd>${st.body || 0} · ${st.escaped || 0}</dd></div><div><dt>Reaction</dt><dd>${avg !== null ? avg + ' ms' : '–'}</dd></div>`
      : st.kind === 'track'
      ? `<div><dt>On target</dt><dd>${Math.round(100 * st.on / st.seconds)}%</dd></div><div><dt>While firing</dt><dd>${st.fire ? Math.round(100 * st.on / st.fire) : 0}%</dd></div>${st.kills !== undefined ? `<div><dt>Targets down</dt><dd>${st.kills}</dd></div>` : `<div><dt>Seconds</dt><dd>${st.seconds}</dd></div>`}`
      : `<div><dt>Hits</dt><dd>${st.hits}/${st.shots}</dd></div><div><dt>Accuracy</dt><dd>${st.shots ? Math.round(100 * st.hits / st.shots) : 0}%</dd></div><div><dt>Avg time</dt><dd>${avg !== null ? avg + ' ms' : '–'}</dd></div>${st.wrong ? `<div><dt>Blue ones hit</dt><dd>${st.wrong}</dd></div>` : ''}`;
    const more = plan && plan.i < plan.items.length - 1;
    const nextName = more ? byId[plan.items[plan.i + 1].id].name : '';
    setPanel(`${planStep()}<h2>${esc(sc.name)}</h2><div class="tr-big">${s}</div><div class="tr-best" id="tr-best"></div><dl>${cells}</dl>${stallNote(st.stalls)}
      <div class="tr-btns">${more ? `<button type="button" class="btn primary" data-a="next">Next: ${esc(nextName)}</button>`
        : (plan ? `<button type="button" class="btn primary" data-a="quit">Done · ${plan.total} points</button>` : `<button type="button" class="btn primary" data-a="restart">Again</button>`)}
      ${plan ? '' : '<button type="button" class="btn ghost" data-a="quit">Back</button>'}${xhBtn()}</div>`);
    if (!C.can_save) { $('tr-best').textContent = 'Not saved (only the player or their owner can).'; return; }
    try {
      const r = await fetch(C.urls.run, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const d = await r.json();
      const b = $('tr-best');
      if (!r.ok) { b.textContent = d.error || 'Not saved.'; return; }
      b.textContent = d.is_best ? (d.best_before === null ? 'Your first score here.' : `New best (before: ${Math.round(d.best_before)}).`) : `Your best: ${Math.round(d.best)}.`;
      if (body.plan_done) b.textContent += ' Ticked off on the Aim page.';
      C.dirty = true;
    } catch (e) { $('tr-best').textContent = 'Not saved: Nexus didn\'t answer.'; }
  }

  // ------------------------------------------------------------------ sens finder
  const shuffle = a => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const r4 = v => Math.round(v * 10000) / 10000;
  const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;
  // Three lengths. quick (about 5 min): 1 warm-up, 5 wide, 5 close, 20 s rounds of flicks then tracking.
  // 15 min: 2 warm-ups, your sens counted at the start and the end (to see how much you tire; stats/trainer.py
  // corrects for it), 7 wide, 6 close played twice, 35 s rounds of close and far flicks, close, far and reactive
  // tracking. 30 min: the same parts in 45 s rounds, 9 wide, 7 close played three times, your sens also in the
  // middle, and a minute's break halfway.
  const FIVE = [['fc', 9], ['ff', 9], ['tc', 6], ['tf', 5], ['tr', 6]];
  const MODES = {
    quick: {name: 'quick', minutes: 5, secs: 20, segs: [['flick', 13], ['tm', 7]], warm: 1, control: 0, rep: 1,
            r1: [0.7, 0.85, 1, 1.15, 1.3], r2: [0.9, 0.95, 1, 1.05, 1.1]},
    standard: {name: '15 min', minutes: 15, secs: 35, segs: FIVE, warm: 2, control: 2, rep: 2,
               r1: [0.65, 0.75, 0.87, 1, 1.15, 1.3, 1.5], r2: [0.88, 0.93, 0.97, 1.03, 1.07, 1.12]},
    full: {name: '30 min', minutes: 30, secs: 45, segs: FIVE.map(([k, s]) => [k, Math.round(s * 45 / 35)]), warm: 2, control: 3, rep: 3, pause: 60,
           r1: [0.6, 0.7, 0.8, 0.9, 1, 1.12, 1.25, 1.4, 1.6], r2: [0.86, 0.91, 0.96, 1, 1.04, 1.09, 1.14]},
  };
  MODES.full.segs[MODES.full.segs.length - 1][1] += 45 - MODES.full.segs.reduce((a, s) => a + s[1], 0);
  function finderRounds(m) { return m.warm + m.control + m.r1.length + m.r2.length * m.rep; }
  function startFinder(kind) {
    const m = MODES[kind] || MODES.quick, base = clamp(+C.sens_rec || sens(), 0.02, 15);
    const list = [...Array(m.warm).fill(r4(base)), ...(m.control ? [r4(base)] : []), ...shuffle(m.r1.map(f => r4(base * f)))];
    finder = {kind, mode: m, base, list, i: 0, done: [], round2: false, stalls: [], paused: false};
    plan = null;
    open('mix');
  }
  function partsOf(s) {             // per part: flicks as points × accuracy, tracking as the share of time on target
    const out = {};
    for (const [k, p] of Object.entries(s.parts || {})) {
      out[k] = PART[k].flick ? Math.round(p.points * (p.shots ? p.hits / p.shots : 0) * 10) / 10 : Math.round(1000 * p.on / Math.max(p.t, 0.01)) / 1000;
    }
    return out;
  }
  function finderNext() {
    const cur = finder.list[finder.i], m = finder.mode;
    finder.stalls.push(...st.stalls);
    if (finder.i >= m.warm) {
      finder.done.push({sens: cur, i: finder.done.length, click: Math.round(st.points * (st.shots ? st.hits / st.shots : 0) * 10) / 10,
                        track: Math.round(1000 * st.trackOn / Math.max(st.trackT, 0.01)) / 1000,
                        over: Math.round(mean(st.over) * 1000) / 1000, under: Math.round(mean(st.under) * 1000) / 1000,
                        acc: st.shots ? Math.round(1000 * st.hits / st.shots) / 1000 : 0,
                        ms: st.times.length ? Math.round(mean(st.times)) : 0, parts: partsOf(st)});
    }
    finder.i++;
    if (finder.i === finder.list.length && !finder.round2) {        // round 2: close around round 1's best
      finder.round2 = true;
      const r1 = finder.done.slice(m.control ? 1 : 0);
      const cmax = Math.max(...r1.map(t => t.click), 1e-9), tmax = Math.max(...r1.map(t => t.track), 1e-9);
      const best = r1.reduce((b, t) => ((t.click / cmax + t.track / tmax) > (b.click / cmax + b.track / tmax) ? t : b)).sens;
      const r2 = [];
      for (let k = 0; k < m.rep; k++) r2.push(...shuffle(m.r2.map(f => r4(best * f))));
      if (m.control >= 3) r2.splice(Math.floor(r2.length / 2), 0, r4(finder.base));   // your sens in the middle too
      finder.list.push(...r2);
      if (m.control >= 2) finder.list.push(r4(finder.base));             // and at the end
      if (m.pause) finder.pauseAt = finder.i + Math.floor(r2.length / 2);
    }
    if (finder.i >= finder.list.length) { finderEnd(); return; }
    newRun('mix');
    if (finder.pauseAt === finder.i) { finderBreak(); return; }
    if (document.pointerLockElement === canvas) {                   // straight on to the next one
      st.phase = 'count'; st.count = 2; $('tr-count').hidden = false; updateHud();
      cue(`Test ${finder.i - m.warm + 1} of ${finderRounds(m) - m.warm}`);
    } else showReady();
  }
  function finderBreak() {           // the 30-minute finder: a minute to shake out the hand
    if (document.pointerLockElement) document.exitPointerLock();
    st.phase = 'ready'; hud.hidden = true;
    let left = finder.mode.pause;
    setPanel(`<div class="tr-step">Sens finder · ${esc(finder.mode.name)} · halfway</div><h2>Break</h2>
      <p>Take your hand off the mouse, shake it out, drink something. Continue when you're ready.</p><div class="tr-big" id="tr-break">${left}</div>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Continue</button>${xhBtn()}</div>`);
    const tmr = setInterval(() => {
      const el = $('tr-break');
      if (!el) { clearInterval(tmr); return; }
      left--; el.textContent = Math.max(0, left);
      if (left <= 0) clearInterval(tmr);
    }, 1000);
  }
  async function finderEnd() {
    const tests = finder.done, base = finder.base;
    st.phase = 'done'; firing = false;
    if (document.pointerLockElement) document.exitPointerLock();
    hud.hidden = true;
    setPanel('<h2>Working out your sens…</h2>');
    let d = null;
    if (C.can_save) {
      try {
        const r = await fetch(C.urls.sens, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({base, tests, mode: finder.kind})});
        d = await r.json();
        if (!r.ok) throw new Error(d.error || r.status);
      } catch (e) { d = {error: String(e.message || e)}; }
    }
    const best = tests.reduce((b, t) => t.click + 1000 * t.track > b.click + 1000 * b.track ? t : b, tests[0]);
    const fmt = v => (+v).toFixed(3);
    let body;
    if (d && !d.error) {
      const parts = d.parts && Object.keys(d.parts).length ? `<p class="tr-parts">${Object.entries(d.parts).map(([k, v]) => `${esc(PART_LABEL[k] || k)} <b>${fmt(v)}</b>`).join(' · ')}</p>` : '';
      body = `<div class="tr-step">Sens finder · ${esc(finder.mode.name)}</div><h2>This test says</h2><div class="tr-big">${fmt(d.this || best.sens)}</div>${parts}
        <p>${d.sessions > 1 ? `With your ${d.sessions} tests together: <b>${fmt(d.sens)}</b> (${fmt(d.low)}–${fmt(d.high)}).` : 'One test is a first hint: test again on another day and Nexus combines them.'}
        ${d.edge ? ` The best was at the ${d.edge === 'higher' ? 'top' : 'bottom'} of what was tested: test again, it starts from there.` : ''}</p>`;
    } else {
      body = `<div class="tr-step">Sens finder</div><h2>Best in this test</h2><div class="tr-big">${fmt(best.sens)}</div>
        <p>${d && d.error ? 'Not saved: ' + esc(d.error) : 'Not saved (only the player or their owner can).'}</p>`;
    }
    body += stallNote(finder.stalls);
    finder = null; C.dirty = !!(d && !d.error); C.goSens = true;
    setPanel(body + '<div class="tr-btns"><button type="button" class="btn primary" data-a="quit">See the chart</button></div>');
  }

  function open(id) {
    if (!initGL()) { window.nexusToast && window.nexusToast('This browser has no WebGL: the trainer can\'t run here.', 'error'); return; }
    stage.classList.add('on'); document.body.style.overflow = 'hidden';
    newRun(id); showReady(); requestAnimationFrame(xPaint);
    last = 0; cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }
  function close() {
    cancelAnimationFrame(raf); st = null; plan = null;
    if (document.pointerLockElement) document.exitPointerLock();
    stage.classList.remove('on'); document.body.style.overflow = '';
    exitFs();
    finder = null;
    if (C.dirty) { if (C.goSens) location.hash = 'sens'; location.reload(); }
  }
  panel.addEventListener('click', e => {
    const a = e.target.closest('[data-a]');
    if (!a) return;
    const act = a.dataset.a;
    if (act === 'go') go(false);
    else if (act === 'resume') go(true);
    else if (act === 'restart') { if (finder) { finder.i = Math.max(0, finder.i); } newRun(st.id); go(false); }
    else if (act === 'next') { plan.i++; newRun(plan.items[plan.i].id); showReady(); }
    else if (act === 'quit') close();
    else if (act === 'xh') openXh();
  });
  // the crosshair settings inside the trainer: your real crosshair stays on the game behind them
  const xPanel = $('tr-xpanel');
  function openXh() { if (!xPanel) return; panel.hidden = true; xPanel.hidden = false; xShow(); const f = xPanel.querySelector('input,button'); if (f) f.focus(); }
  function closeXh() { if (!xPanel || xPanel.hidden) return false; xPanel.hidden = true; panel.hidden = !panel.innerHTML; return true; }
  if (xPanel) xPanel.addEventListener('click', e => { if (e.target.closest('[data-a="xdone"]')) closeXh(); });
  document.addEventListener('keydown', e => {
    if (!stage.classList.contains('on')) return;
    if (e.key === 'Escape' && xPanel && !xPanel.hidden) { closeXh(); return; }
    if (e.target && e.target.closest && e.target.closest('input')) return;          // typing a value in the crosshair panel
    if (e.key === 'Escape' && st && (st.phase === 'ready' || st.phase === 'done') && !document.pointerLockElement
        && performance.now() - unlockedAt > 600) close();
    if ((e.key === 'f' || e.key === 'F') && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); toggleFs(); }
    if ((e.key === 'Enter' || e.key === ' ') && st && st.phase === 'paused' && !document.pointerLockElement) {
      const b = $('tr-resume');
      if (b && !b.disabled) { e.preventDefault(); go(true); }
    }
  });
  document.querySelectorAll('[data-play]').forEach(b => b.addEventListener('click', () => { plan = null; open(b.dataset.play); }));
  document.querySelectorAll('[data-plan]').forEach(b => b.addEventListener('click', () => {
    const p = C.plans[b.dataset.plan];
    plan = {kind: p.kind, name: p.name, items: p.items, i: 0, total: 0};
    open(p.items[0].id);
  }));
  document.querySelectorAll('[data-finder]').forEach(b => b.addEventListener('click', () => startFinder(b.dataset.finder)));
  if (C.start && C.plans[C.start]) {
    const b = document.querySelector(`[data-plan="${C.start}"]`);
    if (b) b.scrollIntoView({block: 'center'});
  }
  if (C.play && C.scenarios.some(s => s.id === C.play)) {                 // from Aim insights: "Play …"
    try { const u = new URL(location.href); u.searchParams.delete('play'); history.replaceState(null, '', u); } catch (e) { /* only the address bar */ }
    open(C.play);
  }

  // the sens finder's chart: hover (or tap) a dot to see which sens that round was
  const tip = $('tr-tip');
  if (tip) {
    const box = tip.parentElement, lang = document.documentElement.lang || 'en';
    let on = null;
    const show = g => {
      if (on) on.classList.remove('on');
      on = g; g.classList.add('on');
      const s = +g.dataset.sens, q = +g.dataset.q, dpi = +C.dpi || +dpiIn.value || 0;
      const day = g.dataset.d ? new Date(g.dataset.d + 'T12:00').toLocaleDateString(lang, {day: 'numeric', month: 'short'}) : '';
      tip.innerHTML = `<b>${s.toFixed(3)}</b>${dpi ? ` · ${(360 / (YAW * s) / dpi * 2.54).toFixed(1)} cm per 360°` : ''}<br>`
        + `${Math.round(q * 100)}% of that test's best${day || g.dataset.mode ? ` · ${esc(day)}${g.dataset.mode ? ` (${esc(g.dataset.mode)})` : ''}` : ''}`;
      const c = g.querySelector('.dot').getBoundingClientRect(), b = box.getBoundingClientRect();
      tip.style.left = clamp(c.left + c.width / 2 - b.left, 90, b.width - 90) + 'px';
      const below = c.top - b.top < 64;                 // near the top: below the dot instead of above
      tip.style.top = (below ? c.bottom - b.top : c.top - b.top) + 'px';
      tip.classList.toggle('below', below);
      tip.hidden = false;
    };
    const hide = () => { tip.hidden = true; if (on) on.classList.remove('on'); on = null; };
    // the dot nearest the pointer (within 16 px): dots close together can each still be reached
    const dots = [...box.querySelectorAll('.tr-dot')];
    const nearest = e => {
      let best = null, bd = 16;
      for (const g of dots) {
        const c = g.querySelector('.dot').getBoundingClientRect();
        const d = Math.hypot(e.clientX - (c.left + c.width / 2), e.clientY - (c.top + c.height / 2));
        if (d < bd) { bd = d; best = g; }
      }
      return best;
    };
    const svg = box.querySelector('svg');
    svg.addEventListener('pointermove', e => { const g = nearest(e); if (g) { if (g !== on) show(g); } else hide(); });
    svg.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') hide(); });
    svg.addEventListener('click', e => { const g = nearest(e); if (g) show(g); else hide(); });     // touch screens
  }
  // step: advance a run by dt seconds without the screen (tests): the scenario moves, tracking counts while fire
  function step(dt, fire) {
    if (!st) return;
    st.t += dt; firing = !!fire;
    if (SC[st.id].update) SC[st.id].update(st, dt);
    if (st.kind === 'track' && fire && aimed()) st.on += dt;
  }
  // ---- 4.28: the Map angles card above the library: pick a map and where you stand, then play "map_angles"
  (function () {
    const A = C.angles, mapSel = $('tr-ang-map'), posSel = $('tr-ang-pos'), list = $('tr-ang-spots');
    if (!A || !mapSel) return;
    const T = s => (window.vcT ? window.vcT(s) : s);
    const choose = () => {
      const m = mapSel.value, ps = A[m] || [], p = ps.find(x => x.id === posSel.value) || ps[0];
      A.current = p ? Object.assign({map: m}, p) : null;
      if (list) list.textContent = p ? T('Spots in front of you:') + ' ' + p.spots.map(s => `${s.label} (${Math.round(s.d)} m)`).join(', ') : '';
    };
    const fill = () => {
      posSel.innerHTML = '';
      for (const p of A[mapSel.value] || []) { const o = document.createElement('option'); o.value = p.id; o.textContent = T(p.name); posSel.appendChild(o); }
      choose();
    };
    mapSel.addEventListener('change', fill); posSel.addEventListener('change', choose);
    $('tr-ang-play').addEventListener('click', () => { choose(); open('map_angles'); });
    fill();
  })();
  window.nexusTrainer = {open, startFinder, xParse, xCode, crosshair: () => xh, finder: () => finder, state: () => st, aim: (y, p) => { yaw = y; pitch = p; }, shoot, score, step};   // for tests
})();
