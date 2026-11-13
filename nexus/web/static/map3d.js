// Practice › 3D maps: walk around a map rebuilt from replay files (stats/map3d.py). Plain WebGL, no libraries.
// The map is a grid of half-metre cells with one or more floor heights each; floors are drawn per cell, walls where a
// neighbour is missing or much higher. Frame: metres, x right and z down on the minimap, y up; yaw 0 looks "up" the
// minimap. Keys: WASD move, Shift walk, Ctrl crouch, Space jump, F fly, C callouts, R radar, H help, Esc stop.
(function () {
  'use strict';
  const C = window.NEXUS_MAP3D;
  if (!C) return;
  const $ = id => document.getElementById(id);
  const T = s => (window.vcT ? window.vcT(s) : s);
  const canvas = $('m3-canvas'), over = $('m3-over'), radar = $('m3-radar'), stage = $('m3-stage');
  const D2R = Math.PI / 180, EYE = 1.6, EYE_CROUCH = 1.15, STEP = 0.6, WALL_H = 3.6, R = 0.3;
  const SPEED = {run: 6.75, walk: 3.6, crouch: 2.4}, GRAV = 20, JUMP = 5.5;
  let gl = null, prog = null, loc = {}, mesh = null, M = null, grid = null, raf = 0, last = 0;
  const keys = new Set();
  const me = {x: 0, y: 0, z: 0, vy: 0, yaw: 0, pitch: 0, ground: true, fly: false, crouch: false};
  const opt = {labels: false, radar: true, help: true};
  try { Object.assign(opt, JSON.parse(localStorage.getItem('nexus.map3d') || '{}')); } catch (e) {}
  const saveOpt = () => { try { localStorage.setItem('nexus.map3d', JSON.stringify(opt)); } catch (e) {} };

  // ---------------------------------------------------------------- the grid
  function buildGrid(d) {
    const g = new Map();
    for (const [i, j, h, k] of d.cells) {
      const key = i + ',' + j;
      if (!g.has(key)) g.set(key, []);
      g.get(key).push({h, k});
    }
    for (const v of g.values()) v.sort((a, b) => a.h - b.h);
    return g;
  }
  const cellOf = (x, z) => [Math.floor(x / M.cell), Math.floor(z / M.cell)];
  const levels = (i, j) => grid.get(i + ',' + j) || null;
  // the floor you stand on at (x, z) from feet height y: the highest level not more than a step above you
  function floorAt(x, z, y) {
    const lv = levels(...cellOf(x, z));
    if (!lv) return null;
    let best = null;
    for (const l of lv) if (l.h <= y + STEP && (best === null || l.h > best)) best = l.h;
    return best;
  }
  // can't go there: no floor within a step at the centre, or at the edge of your body within a bit more (on a ramp
  // the cells beside you are already higher; a wall or a box has no floor near your height at all)
  function blocked(x, z, y) {
    if (floorAt(x, z, y) === null) return true;
    for (const [dx, dz] of [[R, 0], [-R, 0], [0, R], [0, -R]]) if (floorAt(x + dx, z + dz, y + 0.45) === null) return true;
    return false;
  }

  // ---------------------------------------------------------------- meshes
  const VS = `attribute vec3 p; attribute vec3 n; attribute vec3 c; uniform mat4 vp; uniform vec3 eye;
    varying vec3 vc; varying vec3 vn; varying vec3 wp; varying float fog;
    void main(){ gl_Position = vp * vec4(p, 1.0); vc = c; vn = n; wp = p; fog = clamp(length(p - eye) / 140.0, 0.0, 1.0); }`;
  const FS = `precision mediump float; varying vec3 vc; varying vec3 vn; varying vec3 wp; varying float fog;
    void main(){
      vec3 L = normalize(vec3(0.35, 0.9, 0.25));
      float d = 0.55 + 0.45 * max(dot(normalize(vn), L), 0.0);
      vec2 g = abs(fract((abs(vn.y) > 0.5 ? wp.xz : (abs(vn.x) > 0.5 ? wp.zy : wp.xy)) / 2.0) - 0.5);
      float line = 1.0 - 0.07 * step(0.47, max(g.x, g.y));
      vec3 col = vc * d * line;
      gl_FragColor = vec4(mix(col, vec3(0.55, 0.62, 0.72), fog * 0.6), 1.0);
    }`;
  function initGL() {
    if (gl) return true;
    gl = canvas.getContext('webgl', {antialias: true});
    if (!gl) return false;
    const sh = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
    gl.useProgram(prog);
    loc = {p: gl.getAttribLocation(prog, 'p'), n: gl.getAttribLocation(prog, 'n'), c: gl.getAttribLocation(prog, 'c'),
           vp: gl.getUniformLocation(prog, 'vp'), eye: gl.getUniformLocation(prog, 'eye')};
    gl.enable(gl.DEPTH_TEST);
    return true;
  }
  function shade(k, i, j, h) {                    // the area's colour, a little different per cell, darker low down
    const base = M.palette[k] || M.palette[0];
    const n = (((i * 73856093) ^ (j * 19349663)) >>> 0) % 1000 / 1000;
    const f = 0.92 + 0.12 * n;
    return [base[0] * f, base[1] * f, base[2] * f];
  }
  function buildMesh() {
    const v = [];
    const quad = (a, b, c2, d, n, col) => { for (const q of [a, b, c2, a, c2, d]) v.push(q[0], q[1], q[2], n[0], n[1], n[2], col[0], col[1], col[2]); };
    const s = M.cell;
    for (const [key, lv] of grid) {
      const [i, j] = key.split(',').map(Number), x0 = i * s, z0 = j * s, x1 = x0 + s, z1 = z0 + s;
      for (const l of lv) {
        const col = shade(l.k, i, j, l.h);
        quad([x0, l.h, z0], [x0, l.h, z1], [x1, l.h, z1], [x1, l.h, z0], [0, 1, 0], col);
        // walls on the four sides: up to the next floor, or a full wall where there's nothing to stand on
        for (const [di, dj, a, b, n] of [[1, 0, [x1, z0], [x1, z1], [1, 0, 0]], [-1, 0, [x0, z1], [x0, z0], [-1, 0, 0]],
                                          [0, 1, [x1, z1], [x0, z1], [0, 0, 1]], [0, -1, [x0, z0], [x1, z0], [0, 0, -1]]]) {
          const nb = levels(i + di, j + dj);
          let top = null;
          if (!nb) top = l.h + WALL_H;
          else if (nb.some(o => Math.abs(o.h - l.h) <= STEP)) continue;
          else {
            const up = nb.filter(o => o.h > l.h + STEP && o.h <= l.h + WALL_H);
            const down = nb.some(o => o.h < l.h - STEP && o.h >= l.h - WALL_H);
            if (up.length) top = Math.min(...up.map(o => o.h));
            else if (down) continue;                  // the lower cell draws this face
            else top = l.h + WALL_H;
          }
          const wc = col.map(c => c * 0.82);
          quad([a[0], l.h, a[1]], [a[0], top, a[1]], [b[0], top, b[1]], [b[0], l.h, b[1]], [-n[0], 0, -n[2]], wc);
        }
      }
    }
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW);
    return {buf, n: v.length / 9};
  }
  function persp(fy, asp, n, f) { const t = 1 / Math.tan(fy / 2); return [t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0]; }
  function mul(a, b) { const o = new Array(16).fill(0); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k]; return o; }
  function viewM() {
    const e = eyePos(), cy = Math.cos(me.yaw), sy = Math.sin(me.yaw), cp = Math.cos(me.pitch), sp = Math.sin(me.pitch);
    const f = [sy * cp, sp, -cy * cp], r = [cy, 0, sy], u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    return [r[0], u[0], -f[0], 0, r[1], u[1], -f[1], 0, r[2], u[2], -f[2], 0,
            -(r[0] * e[0] + r[1] * e[1] + r[2] * e[2]), -(u[0] * e[0] + u[1] * e[1] + u[2] * e[2]), f[0] * e[0] + f[1] * e[1] + f[2] * e[2], 1];
  }
  const eyePos = () => [me.x, me.y + (me.fly ? EYE : me.crouch ? EYE_CROUCH : EYE), me.z];
  let VP = null;
  function draw() {
    const dpr = window.devicePixelRatio || 1, w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; over.width = w; over.height = h; }
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.55, 0.62, 0.72, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!mesh) return;
    VP = mul(persp(71 * D2R, w / h, 0.05, 400), viewM());
    gl.uniformMatrix4fv(loc.vp, false, VP); gl.uniform3fv(loc.eye, eyePos());
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buf);
    gl.enableVertexAttribArray(loc.p); gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 36, 0);
    gl.enableVertexAttribArray(loc.n); gl.vertexAttribPointer(loc.n, 3, gl.FLOAT, false, 36, 12);
    gl.enableVertexAttribArray(loc.c); gl.vertexAttribPointer(loc.c, 3, gl.FLOAT, false, 36, 24);
    gl.drawArrays(gl.TRIANGLES, 0, mesh.n);
    overlay(w, h, dpr);
  }
  // ---------------------------------------------------------------- overlays: callout names, radar
  function overlay(w, h, dpr) {
    const g = over.getContext('2d');
    g.clearRect(0, 0, w, h);
    if (opt.labels && VP) {
      g.textAlign = 'center'; g.font = `600 ${Math.round(13 * dpr)}px system-ui, sans-serif`;
      for (const c of M.callouts) {
        if (c.y === null) continue;
        const p = [c.x, c.y + 1.4, c.z, 1], q = [0, 0, 0, 0];
        for (let i = 0; i < 4; i++) q[i] = VP[i] * p[0] + VP[4 + i] * p[1] + VP[8 + i] * p[2] + VP[12 + i];
        if (q[3] <= 0.1) continue;
        const d = Math.hypot(c.x - me.x, c.z - me.z);
        if (d > 70) continue;
        const sx = (q[0] / q[3] * 0.5 + 0.5) * w, sy = (1 - (q[1] / q[3] * 0.5 + 0.5)) * h;
        g.globalAlpha = Math.max(0.35, 1 - d / 80);
        g.lineWidth = 3 * dpr; g.strokeStyle = 'rgba(0,0,0,.75)'; g.strokeText(c.label, sx, sy);
        g.fillStyle = '#fff'; g.fillText(c.label, sx, sy);
      }
      g.globalAlpha = 1;
    }
    radar.hidden = !opt.radar;
    if (opt.radar) drawRadar();
  }
  function drawRadar() {
    const g = radar.getContext('2d'), S = radar.width, k = S / 70;          // 35 m around you
    g.clearRect(0, 0, S, S);
    g.fillStyle = 'rgba(10,14,20,.72)'; g.fillRect(0, 0, S, S);
    g.save(); g.translate(S / 2, S / 2); g.rotate(-me.yaw);                 // you always look up
    const [ci, cj] = cellOf(me.x, me.z), span = Math.ceil(36 / M.cell);
    for (let i = ci - span; i <= ci + span; i++) for (let j = cj - span; j <= cj + span; j++) {
      const lv = levels(i, j); if (!lv) continue;
      const near = lv.reduce((a, l) => (Math.abs(l.h - me.y) < Math.abs(a.h - me.y) ? l : a));
      const c = M.palette[near.k] || M.palette[0], up = near.h - me.y;
      const f = up > 1.5 ? 0.55 : up < -1.5 ? 0.45 : 0.85;
      g.fillStyle = `rgb(${c[0] * 255 * f | 0},${c[1] * 255 * f | 0},${c[2] * 255 * f | 0})`;
      g.fillRect(((i + 0.5) * M.cell - me.x) * k - M.cell * k / 2, ((j + 0.5) * M.cell - me.z) * k - M.cell * k / 2, M.cell * k + 0.6, M.cell * k + 0.6);
    }
    if (opt.labels) {
      g.fillStyle = '#fff'; g.font = '10px system-ui, sans-serif'; g.textAlign = 'center';
      for (const c of M.callouts) {
        const x = (c.x - me.x) * k, y = (c.z - me.z) * k;
        if (Math.abs(x) > S / 2 || Math.abs(y) > S / 2) continue;
        g.save(); g.translate(x, y); g.rotate(me.yaw); g.fillText(c.label, 0, 0); g.restore();
      }
    }
    g.restore();
    g.fillStyle = 'rgba(255, 209, 102, .25)';
    g.beginPath(); g.moveTo(S / 2, S / 2); g.arc(S / 2, S / 2, S * 0.3, -Math.PI / 2 - 0.62, -Math.PI / 2 + 0.62); g.fill();
    g.fillStyle = '#ffd166'; g.beginPath(); g.moveTo(S / 2, S / 2 - 7); g.lineTo(S / 2 - 5, S / 2 + 5); g.lineTo(S / 2 + 5, S / 2 + 5); g.fill();
  }
  // ---------------------------------------------------------------- moving
  function step(dt, k = keys) {
    if (!M) return;
    me.crouch = k.has('ControlLeft') || k.has('ControlRight') || k.has('KeyX');
    const sp = me.fly ? 14 : me.crouch ? SPEED.crouch : (k.has('ShiftLeft') || k.has('ShiftRight')) ? SPEED.walk : SPEED.run;
    let fx = 0, fz = 0;
    const f = [Math.sin(me.yaw), -Math.cos(me.yaw)], r = [Math.cos(me.yaw), Math.sin(me.yaw)];
    if (k.has('KeyW')) { fx += f[0]; fz += f[1]; }
    if (k.has('KeyS')) { fx -= f[0]; fz -= f[1]; }
    if (k.has('KeyD')) { fx += r[0]; fz += r[1]; }
    if (k.has('KeyA')) { fx -= r[0]; fz -= r[1]; }
    const len = Math.hypot(fx, fz);
    if (len) { fx = fx / len * sp * dt; fz = fz / len * sp * dt; }
    if (me.fly) {
      me.x += fx; me.z += fz;
      if (k.has('Space')) me.y += sp * dt;
      if (me.crouch) me.y -= sp * dt;
      return;
    }
    if (len) {                                        // move, or slide along the wall
      if (!blocked(me.x + fx, me.z + fz, me.y)) { me.x += fx; me.z += fz; }
      else if (!blocked(me.x + fx, me.z, me.y)) me.x += fx;
      else if (!blocked(me.x, me.z + fz, me.y)) me.z += fz;
    }
    const fl = floorAt(me.x, me.z, me.y);
    if (k.has('Space') && me.ground) { me.vy = JUMP; me.ground = false; }
    if (fl === null) { me.vy = 0; return; }
    if (me.ground && me.y - fl > 0 && me.y - fl <= STEP) { me.y = fl; }        // walking down a step or a ramp
    else if (me.y > fl || me.vy > 0) {
      me.vy -= GRAV * dt; me.y += me.vy * dt; me.ground = false;
      if (me.y <= fl) { me.y = fl; me.vy = 0; me.ground = true; }
    } else { me.y = fl; me.ground = true; }
  }
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - (last || now)) / 1000); last = now;
    if (document.pointerLockElement === canvas) step(dt);
    draw();
    $('m3-pos').textContent = M ? `${nearest()}${me.fly ? ' · ' + T('flying') : ''}` : '';
  }
  function nearest() {
    let b = null, bd = Infinity;
    for (const c of M.callouts) { const d = Math.hypot(c.x - me.x, c.z - me.z) + (c.y === null ? 0 : Math.abs(c.y - me.y) * 2); if (d < bd) { bd = d; b = c; } }
    return b ? b.label : '';
  }
  // ---------------------------------------------------------------- load a map
  async function load(name) {
    $('m3-msg').textContent = T('Loading…'); $('m3-msg').hidden = false;
    try {
      const r = await fetch(C.api + encodeURIComponent(name), {credentials: 'same-origin'});
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
      use(d);
      $('m3-msg').hidden = true;
      $('m3-info').textContent = T(`${d.matches} replay${d.matches === 1 ? '' : 's'} · ${Math.round(d.cells.length * d.cell * d.cell)} m² of floor`);
    } catch (e) { $('m3-msg').textContent = e.message; }
  }
  function use(d) {
    M = d; grid = buildGrid(d);
    if (!initGL()) { $('m3-msg').textContent = T('This browser has no WebGL.'); $('m3-msg').hidden = false; return; }
    mesh = buildMesh();
    [me.x, me.y, me.z] = d.start; me.vy = 0; me.ground = true; me.yaw = 0; me.pitch = 0;
    const fl = floorAt(me.x, me.z, me.y + 2); if (fl !== null) me.y = fl;
    if (!raf) raf = requestAnimationFrame(frame);
  }
  // ---------------------------------------------------------------- input
  canvas.addEventListener('click', () => { if (M && document.pointerLockElement !== canvas) canvas.requestPointerLock(); });
  document.addEventListener('pointerlockchange', () => { $('m3-start').hidden = document.pointerLockElement === canvas; if (document.pointerLockElement !== canvas) keys.clear(); });
  document.addEventListener('mousemove', e => {
    if (document.pointerLockElement !== canvas) return;
    const k = 0.07 * (+C.sens || 0.4) * D2R;
    me.yaw += e.movementX * k; me.pitch = Math.max(-1.5, Math.min(1.5, me.pitch - e.movementY * k));
  });
  document.addEventListener('keydown', e => {
    if (document.pointerLockElement !== canvas) return;
    keys.add(e.code);
    if (['Space', 'ControlLeft', 'KeyW', 'KeyA', 'KeyS', 'KeyD'].includes(e.code)) e.preventDefault();
    if (e.code === 'KeyC') { opt.labels = !opt.labels; saveOpt(); }
    else if (e.code === 'KeyR') { opt.radar = !opt.radar; saveOpt(); }
    else if (e.code === 'KeyH') { opt.help = !opt.help; $('m3-help').hidden = !opt.help; saveOpt(); }
    else if (e.code === 'KeyF') { me.fly = !me.fly; if (!me.fly) { const fl = floorAt(me.x, me.z, me.y + 50); if (fl !== null && fl <= me.y + STEP) { me.ground = false; } } }
  });
  document.addEventListener('keyup', e => keys.delete(e.code));
  document.querySelectorAll('[data-map]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-map]').forEach(x => x.classList.toggle('on', x === b));
    load(b.dataset.map);
  }));
  $('m3-labels').addEventListener('change', e => { opt.labels = e.target.checked; saveOpt(); });
  $('m3-radar-t').addEventListener('change', e => { opt.radar = e.target.checked; saveOpt(); });
  $('m3-labels').checked = opt.labels; $('m3-radar-t').checked = opt.radar; $('m3-help').hidden = !opt.help;
  $('m3-full').addEventListener('click', () => { if (stage.requestFullscreen) stage.requestFullscreen().catch(() => {}); });
  const first = document.querySelector('[data-map]:not([disabled])');
  if (first) first.click();
  window.nexusMap3D = {state: () => ({me, opt, loaded: !!M, cells: M ? M.cells.length : 0, mesh: mesh ? mesh.n : 0}), use, step: (dt, ks) => step(dt, new Set(ks)), draw, floorAt};   // for tests
})();
