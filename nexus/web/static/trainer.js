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
    // the sens finder's test: 13 s flicks and micro corrections (with how each flick went), 7 s tracking
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
        if (!st.tracking && st.t >= 13) {                  // second part: tracking
          st.tracking = true; st.path = null;
          st.targets = [{c: [Math.sin(yaw) * 9, 1.4, -Math.max(4, Math.cos(yaw) * 9)], r: 0.38, born: st.t}];
          st.v = 0; st.goal = 3.5; st.flip = st.t + 0.5;
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
        tg.c[1] = 1.35 + Math.sin(st.t * 2.1) * 0.06;
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
    const sc = byId[id], seconds = plan ? plan.items[plan.i].seconds : sc.seconds;
    firing = false;
    st = {id, kind: sc.kind, seconds, t: 0, phase: 'ready', targets: [], covers: null, hits: 0, shots: 0, points: 0,
          times: [], lastHit: 0, on: 0};
    yaw = 0; pitch = 0;
    SC[id].setup(st);
  }
  function score() {
    if (!st) return 0;
    if (st.kind === 'track') return Math.round(1000 * st.on / st.seconds);
    if (st.id === 'mix') return Math.round(st.points * (st.shots ? st.hits / st.shots : 0) + 1000 * st.trackOn / 7);
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
    const w = Math.round(canvas.clientWidth * devicePixelRatio), h = Math.round(canvas.clientHeight * devicePixelRatio);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    if (st && st.phase === 'count') {
      st.count -= dt;
      $('tr-count').textContent = Math.max(1, Math.ceil(st.count));
      if (st.count <= 0) { st.phase = 'run'; $('tr-count').hidden = true; for (const t of st.targets) t.born = 0; st.lastHit = 0; }
    }
    let onTarget = null;
    if (st && st.phase === 'run') {
      st.t += dt;
      if (SC[st.id].update) SC[st.id].update(st, dt);
      if (st.kind === 'track') { onTarget = aimed(); if (firing && onTarget) st.on += dt; if (firing) st.fire = (st.fire || 0) + dt; }
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
      const on = tg === onTarget && firing;
      draw(meshes.sphere, model(tg.c[0], tg.c[1], tg.c[2], tg.r, tg.r, tg.r), on ? TARGET_ON : TARGET, 0, on ? 0.25 : 0.12);
    }
  }
  function updateHud() {
    $('tr-time').textContent = Math.max(0, Math.ceil(st.seconds - st.t));
    $('tr-score').textContent = score();
    if (st.kind === 'track') { $('tr-l3').textContent = 'On target'; $('tr-acc').textContent = st.t ? Math.round(100 * st.on / Math.max(st.t, 0.01)) + '%' : '–'; }
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
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement === canvas || !st) return;
    firing = false;
    if (st.phase === 'run') { st.phase = 'paused'; showPaused(); }
    else if (st.phase === 'count') { st.phase = 'ready'; $('tr-count').hidden = true; hud.hidden = true; showReady(); }
  });

  // ------------------------------------------------------------------ panels
  function setPanel(html) { panel.innerHTML = html; panel.hidden = !html; }
  function planStep() { return plan ? `<div class="tr-step">${esc(plan.name)} · round ${plan.i + 1} of ${plan.items.length}</div>` : ''; }
  function showReady() {
    const sc = byId[st.id];
    if (finder) {
      hud.hidden = true;
      setPanel(`<div class="tr-step">Sens finder · ${finder.i === 0 ? 'warm-up' : `test ${finder.i} of 10`}</div><h2>Find your sens</h2>
        <p>Eleven rounds of 20 seconds: one warm-up at your sens, then ten at other sensitivities, blind and in random order.
        Each round: shoot the targets, and when the moving one comes, just stay on it. Don't think about the sens, aim like in a match.</p>
        <p>About 5 minutes · Esc pauses</p>
        <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Click to start</button><button type="button" class="btn ghost" data-a="quit">Back</button></div>`);
      return;
    }
    hud.hidden = true;
    setPanel(`${planStep()}<h2>${esc(sc.name)}</h2><p>${esc(sc.about)}</p><p>${st.seconds} seconds · ${sc.kind === 'track' ? 'hold the left mouse button on the target' : 'left click to shoot'} · Esc pauses</p>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="go">Click to start</button><button type="button" class="btn ghost" data-a="quit">Back</button></div>`);
  }
  function showPaused() {
    setPanel(`<h2>Paused</h2><p>${Math.ceil(st.seconds - st.t)} seconds left.</p>
      <div class="tr-btns"><button type="button" class="btn primary" data-a="resume">Continue</button><button type="button" class="btn ghost" data-a="restart">Start over</button><button type="button" class="btn ghost" data-a="quit">Quit</button></div>`);
  }
  async function go(resume) {
    setPanel('');
    initAudio();
    await lock();
    if (document.pointerLockElement !== canvas) { resume ? showPaused() : showReady(); return; }   // the browser said no: try again
    hud.hidden = false;
    if (resume) { st.phase = 'run'; return; }
    st.phase = 'count'; st.count = 3; $('tr-count').hidden = false;
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
  function startFinder() {
    const base = clamp(+C.sens_rec || sens(), 0.02, 15);
    finder = {base, list: [r4(base), ...shuffle([0.7, 0.85, 1, 1.15, 1.3].map(f => r4(base * f)))], i: 0, done: [], round2: false};
    plan = null;
    open('mix');
  }
  function finderNext() {
    const cur = finder.list[finder.i];
    if (finder.i > 0) {
      finder.done.push({sens: cur, click: Math.round(st.points * (st.shots ? st.hits / st.shots : 0) * 10) / 10,
                        track: Math.round(1000 * st.trackOn / Math.max(st.trackT, 0.01)) / 1000,
                        over: Math.round(mean(st.over) * 1000) / 1000, under: Math.round(mean(st.under) * 1000) / 1000,
                        acc: st.shots ? Math.round(1000 * st.hits / st.shots) / 1000 : 0,
                        ms: st.times.length ? Math.round(mean(st.times)) : 0});
    }
    finder.i++;
    if (finder.i === finder.list.length && !finder.round2) {        // round 2: close around round 1's best
      finder.round2 = true;
      const cmax = Math.max(...finder.done.map(t => t.click), 1e-9), tmax = Math.max(...finder.done.map(t => t.track), 1e-9);
      const best = finder.done.reduce((b, t) => ((t.click / cmax + t.track / tmax) > (b.click / cmax + b.track / tmax) ? t : b)).sens;
      finder.list.push(...shuffle([0.9, 0.95, 1, 1.05, 1.1].map(f => r4(best * f))));
    }
    if (finder.i >= finder.list.length) { finderEnd(); return; }
    newRun('mix');
    if (document.pointerLockElement === canvas) {                   // straight on to the next one
      st.phase = 'count'; st.count = 3; $('tr-count').hidden = false; updateHud();
    } else showReady();
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
        const r = await fetch(C.urls.sens, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({base, tests})});
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
    newRun(id); showReady();
    last = 0; cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }
  function close() {
    cancelAnimationFrame(raf); st = null; plan = null;
    if (document.pointerLockElement) document.exitPointerLock();
    stage.classList.remove('on'); document.body.style.overflow = '';
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
    if (e.key === 'Escape' && st && (st.phase === 'ready' || st.phase === 'done') && !document.pointerLockElement) close();
  });
  document.querySelectorAll('[data-play]').forEach(b => b.addEventListener('click', () => { plan = null; open(b.dataset.play); }));
  document.querySelectorAll('[data-plan]').forEach(b => b.addEventListener('click', () => {
    const p = C.plans[b.dataset.plan];
    plan = {kind: p.kind, name: p.name, items: p.items, i: 0, total: 0};
    open(p.items[0].id);
  }));
  const sensGo = $('tr-sens-go');
  if (sensGo) sensGo.addEventListener('click', startFinder);
  if (C.start && C.plans[C.start]) {
    const b = document.querySelector(`[data-plan="${C.start}"]`);
    if (b) b.scrollIntoView({block: 'center'});
  }
  window.nexusTrainer = {open, startFinder, finder: () => finder, state: () => st, aim: (y, p) => { yaw = y; pitch = p; }, shoot, score};   // for tests
})();
