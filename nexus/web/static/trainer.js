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
  // Each: setup(st), update(st, dt), and the targets in st.targets [{c:[x,y,z], r, born, on}] + st.covers.
  const GRID_X = [-2.4, -1.2, 0, 1.2, 2.4], GRID_Y = [0.75, 1.65, 2.55, 3.45];
  const SC = {
    grid: {
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
      setup(st) { st.prev = 0; st.targets = []; this.spawn(st); },
      spawn(st) {
        let a; do { a = rand(-45, 45); } while (Math.abs(a - st.prev) < 12);
        st.prev = a;
        st.targets = [{c: atAngle(a, 12, EYE + rand(-0.04, 0.04)), r: 0.21, born: st.t}];
      },
      hit(st) { this.spawn(st); },
    },
    micro: {
      setup(st) { st.ya = 0; st.pa = 0; st.targets = []; this.spawn(st); },
      spawn(st) {
        const step = rand(1.4, 4.5), dir = Math.random() * 2 * Math.PI;
        st.ya = clamp(st.ya + Math.cos(dir) * step, -28, 28); st.pa = clamp(st.pa + Math.sin(dir) * step * 0.5, -3, 4);
        const d = 18, c = atAngle(st.ya, d * Math.cos(st.pa * Math.PI / 180), EYE + Math.tan(st.pa * Math.PI / 180) * d);
        st.targets = [{c, r: 0.11, born: st.t}];
      },
      hit(st) { this.spawn(st); },
    },
    peek: {
      setup(st) {
        st.covers = [-4.5, 0, 4.5].map(x => ({min: [x - 0.8, 0, -14.5], max: [x + 0.8, 3.2, -13.5]}));
        st.window = 0.9; st.targets = []; st.next = st.t + 0.6; st.escaped = 0;
      },
      update(st) {
        const tg = st.targets[0];
        if (!tg && st.t >= st.next) {
          const cv = st.covers[Math.floor(Math.random() * 3)], side = Math.random() < 0.5 ? -1 : 1;
          const x0 = side < 0 ? cv.min[0] + 0.35 : cv.max[0] - 0.35;
          st.targets = [{c: [x0, EYE - 0.05, -14.35], r: 0.26, born: st.t, x0, x1: x0 + side * 1.0, phase: 'out', t0: st.t}];
          return;
        }
        if (!tg) return;
        const k = (st.t - tg.t0) / 0.12;
        if (tg.phase === 'out') {
          tg.c[0] = tg.x0 + (tg.x1 - tg.x0) * Math.min(1, k);
          if (k >= 1) { tg.phase = 'stay'; tg.t0 = st.t; tg.born = st.t; }
        } else if (tg.phase === 'stay' && st.t - tg.t0 >= st.window) {
          tg.phase = 'in'; tg.t0 = st.t;
        } else if (tg.phase === 'in') {
          tg.c[0] = tg.x1 + (tg.x0 - tg.x1) * Math.min(1, k);
          if (k >= 1) {               // got away
            st.targets = []; st.escaped++; st.window = Math.min(0.9, st.window + 0.04); st.next = st.t + rand(0.35, 0.9);
          }
        }
      },
      hit(st) { st.targets = []; st.window = Math.max(0.38, st.window - 0.025); st.next = st.t + rand(0.35, 0.9); },
    },
    // the sens finder's test: flicks and micro corrections (with how each flick went), then tracking (st.split:
    // where tracking starts; 13 of 20 s in the quick finder, 16 of 25 s in the thorough one)
    mix: {
      setup(st) { st.n = 0; st.over = []; st.under = []; st.trackOn = 0; st.trackT = 0; st.tracking = false; st.targets = []; this.spawn(st); },
      spawn(st) {
        st.n++;
        const flick = st.n % 2 === 1, D = Math.PI / 180;
        let ty, tp, d, r;
        if (flick) {
          ty = clamp(yaw + (Math.random() < 0.5 ? -1 : 1) * rand(15, 50) * D, -60 * D, 60 * D);
          if (Math.abs(ty - yaw) < 12 * D) ty = yaw + (ty > 0 ? -1 : 1) * rand(20, 45) * D;
          tp = clamp(pitch + rand(-6, 6) * D, -8 * D, 12 * D); d = 12; r = 0.3;
        } else {
          const a = Math.random() * 2 * Math.PI, s = rand(2, 5) * D;
          ty = yaw + Math.cos(a) * s; tp = clamp(pitch + Math.sin(a) * s * 0.6, -8 * D, 12 * D); d = 18; r = 0.12;
        }
        st.targets = [{c: [Math.sin(ty) * Math.cos(tp) * d, EYE + Math.sin(tp) * d, -Math.cos(ty) * Math.cos(tp) * d], r, born: st.t}];
        const len = Math.hypot(ty - yaw, tp - pitch);
        st.path = {y0: yaw, p0: pitch, vy: ty - yaw, vp: tp - pitch, len, tol: Math.atan(r / d), flick, max: 0, peak: 0, stop: null, py: yaw, pp: pitch};
      },
      hit(st) {
        const p = st.path;
        if (p && p.flick && p.len > 8 * Math.PI / 180) {
          const tol = p.tol / p.len;
          st.over.push(Math.max(0, p.max - 1 - tol));
          st.under.push(p.stop === null ? 0 : Math.max(0, 1 - tol - p.stop));
        }
        this.spawn(st);
      },
      update(st, dt) {
        if (!st.tracking && st.t >= (st.split || 13)) {                  // second part: tracking
          st.tracking = true; st.path = null;
          // right where the crosshair is, already moving: no searching, no waiting
          const x = clamp(Math.sin(yaw) * 9, -4.5, 4.5), y = clamp(EYE + Math.tan(pitch) * 9, 0.9, 2.6);
          st.targets = [{c: [x, y, -Math.sqrt(Math.max(16, 81 - x * x))], r: 0.38, born: st.t, y0: y}];
          const dir = Math.random() < 0.5 ? -1 : 1;
          st.v = dir * 2.5; st.goal = dir * rand(2.8, 4.5); st.flip = st.t + rand(0.4, 0.9);
          cue('Track it: stay on the target');
        }
        if (st.tracking) {
          SC.track.update(st, dt);
          st.trackT += dt;
          if (aimed()) st.trackOn += dt;
          return;
        }
        const p = st.path;
        if (!p || !dt) return;
        const prog = ((yaw - p.y0) * p.vy + (pitch - p.p0) * p.vp) / (p.len * p.len);
        const speed = Math.hypot(yaw - p.py, pitch - p.pp) / dt;
        p.py = yaw; p.pp = pitch;
        p.max = Math.max(p.max, prog);
        p.peak = Math.max(p.peak, speed);
        if (p.stop === null && p.peak > p.len * 2 && speed < p.peak * 0.15) p.stop = prog;    // the first stop after the flick
      },
    },
    track: {
      setup(st) {
        st.targets = [{c: [0, 1.35, -9], r: 0.38, born: st.t}];
        st.v = 0; st.goal = 3.5; st.flip = st.t + 0.6; st.on = 0;
      },
      update(st, dt) {
        const tg = st.targets[0];
        if (!tg) return;
        if (st.t >= st.flip || Math.abs(tg.c[0]) > 5) {
          const dir = Math.abs(tg.c[0]) > 5 ? -Math.sign(tg.c[0]) : -Math.sign(st.goal || 1);
          st.goal = dir * rand(2.4, 5.2); st.flip = st.t + rand(0.25, 1.1);
        }
        const acc = 26 * dt;
        st.v += clamp(st.goal - st.v, -acc, acc);
        tg.c[0] += st.v * dt;
        tg.c[1] = (tg.y0 || 1.35) + Math.sin(st.t * 2.1) * 0.06;
      },
    },
  };

  // ------------------------------------------------------------------ one run
  let st = null, yaw = 0, pitch = 0, raf = 0, last = 0, plan = null, raw = null, firing = false, audio = null;
  const scale = () => clamp(+C.scale || 1, 0.25, 4);
  function tick() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = 1250; g.gain.setValueAtTime(0.06, audio.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.06);
      o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + 0.07);
    } catch (e) {}
  }
  function aimDir() {
    return [Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch)];
  }
  function aimed() {        // the target under the crosshair (not behind cover), or null
    if (!st) return null;
    const o = [0, EYE, 0], d = aimDir();
    let best = null, bt = Infinity;
    for (const tg of st.targets) { const t = hitSphere(o, d, tg.c, tg.r); if (t < bt) { bt = t; best = tg; } }
    if (best) for (const b of st.covers || []) if (hitBox(o, d, b) < bt) return null;
    return best;
  }
  function newRun(id) {
    const sc = byId[id], seconds = plan ? plan.items[plan.i].seconds : finder ? finder.mode.secs : sc.seconds;
    firing = false;
    st = {id, kind: sc.kind, seconds, t: 0, phase: 'ready', targets: [], covers: null, hits: 0, shots: 0, points: 0,
          times: [], lastHit: 0, on: 0};
    yaw = 0; pitch = 0;
    if (finder) st.split = finder.mode.split;
    SC[id].setup(st);
  }
  function score() {
    if (!st) return 0;
    if (st.kind === 'track') return Math.round(1000 * st.on / st.seconds);
    if (st.id === 'mix') return Math.round(st.points * (st.shots ? st.hits / st.shots : 0) + 1000 * st.trackOn / Math.max(1, st.seconds - (st.split || 13)));
    const acc = st.shots ? st.hits / st.shots : 0;
    return Math.round(st.points * acc);
  }
  function shoot() {
    if (!st || st.phase !== 'run' || st.kind === 'track' || st.tracking) return;
    st.shots++;
    const tg = aimed();
    if (!tg) return;
    const since = SC[st.id].since ? Math.max(tg.born, SC[st.id].since(st)) : tg.born;
    const ms = (st.t - since) * 1000;
    st.hits++; st.times.push(ms); st.lastHit = st.t;
    st.points += 100 + clamp(100 * (1 - (ms - 250) / 750), 0, 100);
    SC[st.id].hit(st, tg);
    tick();
  }
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - (last || now)) / 1000); last = now;
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
      const on = tg === onTarget && (firing || st.tracking);
      draw(meshes.sphere, model(tg.c[0], tg.c[1], tg.c[2], tg.r, tg.r, tg.r), on ? TARGET_ON : TARGET, 0, on ? 0.25 : 0.12);
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
    else { $('tr-l3').textContent = 'Accuracy'; $('tr-acc').textContent = st.shots ? Math.round(100 * st.hits / st.shots) + '%' : '–'; }
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
      const m = finder.mode, n = m.warm + m.r1.length + m.r2.length * m.rep + (m.control ? 2 : 0);
      setPanel(`<div class="tr-step">Sens finder · ${m.name} · ${finder.i < m.warm ? 'warm-up' : `test ${finder.i - m.warm + 1} of ${n - m.warm}`}</div><h2>Find your sens</h2>
        <p>${m.warm === 1 ? 'One warm-up round' : 'Two warm-up rounds'} at your sens, then ${n - m.warm} rounds of ${m.secs} seconds at other sensitivities, blind and in random order.
        Each round: shoot the targets, and when the moving one comes, just stay on it. Don't think about the sens, aim like in a match.</p>
        <p>About ${m.minutes} minutes · Esc pauses · F fullscreen</p>
        <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Click to start</button><button type="button" class="btn ghost" data-a="quit">Back</button></div>`);
      return;
    }
    hud.hidden = true;
    setPanel(`${planStep()}<h2>${esc(sc.name)}</h2><p>${esc(sc.about)}</p><p>${st.seconds} seconds · ${sc.kind === 'track' ? 'hold the left mouse button on the target' : 'left click to shoot'} · Esc pauses · F fullscreen</p>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Click to start</button><button type="button" class="btn ghost" data-a="quit">Back</button></div>`);
  }
  function showPaused(again) {
    // the browser won't lock the mouse again right after Esc: Continue unlocks after a moment
    const where = finder ? `<div class="tr-step">Sens finder · ${finder.mode.name} · ${finder.i < finder.mode.warm ? 'warm-up' : `test ${finder.i - finder.mode.warm + 1}`}</div>` : planStep();
    setPanel(`${where}<h2>Paused</h2><p>${again ? 'The browser needs a moment after Esc: click Continue once more.' : `${Math.ceil(st.seconds - st.t)} seconds left in this round.`}</p>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="resume" id="tr-resume" disabled>Continue</button>
      ${finder ? '' : '<button type="button" class="btn ghost" data-a="restart">Start over</button>'}
      <button type="button" class="btn ghost" data-a="quit">${finder ? 'Stop the sens finder' : 'Quit'}</button></div>
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

  async function finish() {
    if (finder) { finderNext(); return; }
    st.phase = 'done'; firing = false;
    if (document.pointerLockElement) document.exitPointerLock();
    const sc = byId[st.id], s = score();
    const avg = st.times.length ? Math.round(st.times.reduce((a, b) => a + b, 0) / st.times.length) : null;
    const body = {scenario: st.id, score: s, seconds: st.seconds};
    if (st.kind === 'track') body.on_target = Math.round(1000 * st.on / st.seconds) / 1000;
    else Object.assign(body, {hits: st.hits, shots: st.shots, ms: avg || 0});
    if (plan) { plan.total += s; if (plan.i === plan.items.length - 1) Object.assign(body, {plan_done: plan.kind, plan_score: plan.total}); }
    const cells = st.kind === 'track'
      ? `<div><dt>On target</dt><dd>${Math.round(100 * st.on / st.seconds)}%</dd></div><div><dt>While firing</dt><dd>${st.fire ? Math.round(100 * st.on / st.fire) : 0}%</dd></div><div><dt>Seconds</dt><dd>${st.seconds}</dd></div>`
      : `<div><dt>Hits</dt><dd>${st.hits}/${st.shots}</dd></div><div><dt>Accuracy</dt><dd>${st.shots ? Math.round(100 * st.hits / st.shots) : 0}%</dd></div><div><dt>Avg time</dt><dd>${avg !== null ? avg + ' ms' : '–'}</dd></div>`;
    const more = plan && plan.i < plan.items.length - 1;
    const nextName = more ? byId[plan.items[plan.i + 1].id].name : '';
    setPanel(`${planStep()}<h2>${esc(sc.name)}</h2><div class="tr-big">${s}</div><div class="tr-best" id="tr-best"></div><dl>${cells}</dl>
      <div class="tr-btns">${more ? `<button type="button" class="btn primary" data-a="next">Next: ${esc(nextName)}</button>`
        : (plan ? `<button type="button" class="btn primary" data-a="quit">Done · ${plan.total} points</button>` : `<button type="button" class="btn primary" data-a="restart">Again</button>`)}
      ${plan ? '' : '<button type="button" class="btn ghost" data-a="quit">Back</button>'}</div>`);
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
  // quick: 1 warm-up, 5 wide, 5 close (20 s each). thorough: 2 warm-ups, your sens counted at the start and the end
  // (to see how much you tire, stats/trainer.py corrects for it), 7 wide, 6 close played twice each (25 s each).
  const MODES = {
    quick: {name: 'quick', secs: 20, split: 13, warm: 1, minutes: 5, control: false, rep: 1,
            r1: [0.7, 0.85, 1, 1.15, 1.3], r2: [0.9, 0.95, 1, 1.05, 1.1]},
    thorough: {name: 'thorough', secs: 25, split: 16, warm: 2, minutes: 11, control: true, rep: 2,
               r1: [0.65, 0.75, 0.87, 1, 1.15, 1.3, 1.5], r2: [0.88, 0.93, 0.97, 1.03, 1.07, 1.12]},
  };
  function startFinder(kind) {
    const m = MODES[kind] || MODES.quick, base = clamp(+C.sens_rec || sens(), 0.02, 15);
    const list = [...Array(m.warm).fill(r4(base)), ...(m.control ? [r4(base)] : []), ...shuffle(m.r1.map(f => r4(base * f)))];
    finder = {mode: m, base, list, i: 0, done: [], round2: false};
    plan = null;
    open('mix');
  }
  function finderNext() {
    const cur = finder.list[finder.i], m = finder.mode;
    if (finder.i >= m.warm) {
      finder.done.push({sens: cur, i: finder.done.length, click: Math.round(st.points * (st.shots ? st.hits / st.shots : 0) * 10) / 10,
                        track: Math.round(1000 * st.trackOn / Math.max(st.trackT, 0.01)) / 1000,
                        over: Math.round(mean(st.over) * 1000) / 1000, under: Math.round(mean(st.under) * 1000) / 1000,
                        acc: st.shots ? Math.round(1000 * st.hits / st.shots) / 1000 : 0,
                        ms: st.times.length ? Math.round(mean(st.times)) : 0});
    }
    finder.i++;
    if (finder.i === finder.list.length && !finder.round2) {        // round 2: close around round 1's best
      finder.round2 = true;
      const r1 = finder.done.slice(m.control ? 1 : 0);
      const cmax = Math.max(...r1.map(t => t.click), 1e-9), tmax = Math.max(...r1.map(t => t.track), 1e-9);
      const best = r1.reduce((b, t) => ((t.click / cmax + t.track / tmax) > (b.click / cmax + b.track / tmax) ? t : b)).sens;
      for (let k = 0; k < m.rep; k++) finder.list.push(...shuffle(m.r2.map(f => r4(best * f))));
      if (m.control) finder.list.push(r4(finder.base));             // your sens once more at the end
    }
    if (finder.i >= finder.list.length) { finderEnd(); return; }
    newRun('mix');
    if (document.pointerLockElement === canvas) {                   // straight on to the next one
      st.phase = 'count'; st.count = 2; $('tr-count').hidden = false; updateHud();
    } else showReady();
  }
  async function finderEnd() {
    const tests = finder.done, base = finder.base, mode = finder.mode.name;
    st.phase = 'done'; firing = false;
    if (document.pointerLockElement) document.exitPointerLock();
    hud.hidden = true;
    setPanel('<h2>Working out your sens…</h2>');
    let d = null;
    if (C.can_save) {
      try {
        const r = await fetch(C.urls.sens, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({base, tests, mode})});
        d = await r.json();
        if (!r.ok) throw new Error(d.error || r.status);
      } catch (e) { d = {error: String(e.message || e)}; }
    }
    const best = tests.reduce((b, t) => t.click + 1000 * t.track > b.click + 1000 * b.track ? t : b, tests[0]);
    const fmt = v => (+v).toFixed(3);
    let body;
    if (d && !d.error) {
      body = `<div class="tr-step">Sens finder</div><h2>This test says</h2><div class="tr-big">${fmt(d.this || best.sens)}</div>
        <p>${d.sessions > 1 ? `With your ${d.sessions} tests together: <b>${fmt(d.sens)}</b> (${fmt(d.low)}–${fmt(d.high)}).` : 'One test is a first hint: test again on another day and Nexus combines them.'}
        ${d.edge ? ` The best was at the ${d.edge === 'higher' ? 'top' : 'bottom'} of what was tested: test again, it starts from there.` : ''}</p>`;
    } else {
      body = `<div class="tr-step">Sens finder</div><h2>Best in this test</h2><div class="tr-big">${fmt(best.sens)}</div>
        <p>${d && d.error ? 'Not saved: ' + esc(d.error) : 'Not saved (only the player or their owner can).'}</p>`;
    }
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
  });
  document.addEventListener('keydown', e => {
    if (!stage.classList.contains('on')) return;
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
  window.nexusTrainer = {open, startFinder, xParse, xCode, crosshair: () => xh, finder: () => finder, state: () => st, aim: (y, p) => { yaw = y; pitch = p; }, shoot, score};   // for tests
})();
