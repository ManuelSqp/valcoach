// Nexus interface language in the browser: text that scripts add after the page loaded goes through the
// same catalog the server used for the page (see nexus/i18n). Only loaded when the language isn't English.
(function () {
  'use strict';
  const lang = document.documentElement.lang;
  const src = document.currentScript && document.currentScript.dataset.catalog;
  if (!src || lang === 'en') return;
  const NUM = /(?<![\w#])[-+]?\d+(?:[.,'’]\d+)*(?!\w)/g;
  const MARK = '\ue000', MARK_G = /\ue000/g;      // a number in the catalog ("#" there; "#TAG" stays literal)
  const toMark = x => String(x).replace(/#(?![A-Za-z])/g, MARK);
  const SKIP = new Set(['SCRIPT', 'STYLE', 'PRE', 'CODE', 'TEXTAREA', 'KBD']);
  const ATTRS = ['title', 'placeholder', 'aria-label', 'data-q', 'data-tip', 'alt'];
  let exact = null, patterns = [];

  function build(data) {
    exact = new Map();
    for (let [k0, v] of Object.entries(data)) {
      const k = toMark(k0.replace(/\s+/g, ' ').trim());
      v = toMark(v);
      if (/\{\w+\}/.test(k)) {
        const names = [...k.matchAll(/\{(\w+)\}/g)].map(m => m[1]);
        const rx = '^' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\{(\w+)\\\}/g, (_, n) => `(?<${n}>.+?)`) + '$';
        const fixed = (k.replace(/\{\w+\}/g, '').match(/[A-Za-z]/g) || []).length;   // see nexus/i18n
        const loose = fixed < 4 || (fixed < 8 && k.startsWith('{'));
        try { patterns.push([new RegExp(rx, 'sd'), v, names, loose]); } catch (e) {}
      } else exact.set(k, v);
    }
    patterns.sort((a, b) => b[0].source.length - a[0].source.length);
    done = new Set(Object.values(data).map(v => String(v).replace(/\s+/g, ' ').trim()));
  }
  function lookup(s, depth = 0) {
    if (exact.has(s)) return exact.get(s);
    const nums = s.match(NUM);
    let key = null;
    if (nums) {
      key = s.replace(NUM, MARK);
      const t = exact.get(key);
      if (t !== undefined && (t.match(MARK_G) || []).length === nums.length) { let i = 0; return t.replace(MARK_G, () => nums[i++]); }
    }
    if (depth > 0) return null;          // parts of a pattern: only whole known phrases
    for (const pat of patterns) {             // most specific first; each on the text and on its #-form
      let out = apply(pat, s, depth, null);
      if (out == null && key) out = apply(pat, key, depth, nums);
      if (out != null) return out;
    }
    return null;
  }
  // one pattern; with nums, s is the #-form: parts get their own numbers back, the rest fill the fixed text
  function apply([rx, tmpl, names, loose], s, depth, nums) {
    const m = rx.exec(s);
    if (!m) return null;
    let out = tmpl, known = 0;
    const used = new Set();
    for (const n of names) {
      let part = m.groups[n];
      if (nums && part.includes(MARK)) {
        const start = m.indices && m.indices.groups ? m.indices.groups[n][0] : s.indexOf(part);
        const i0 = (s.slice(0, start).match(MARK_G) || []).length, k = (part.match(MARK_G) || []).length;
        let j = i0;
        part = part.replace(MARK_G, () => nums[j++]);
        for (let i = i0; i < i0 + k; i++) used.add(i);
      }
      const t = /[A-Za-z]/.test(part) ? lookup(part, depth + 1) : null;
      if (t != null || !/[A-Za-z]/.test(part)) known++;
      out = out.split('{' + n + '}').join((t != null ? t : part).split(MARK).join('#'));
    }
    if (loose && known < names.length) return null;
    if (nums) {
      const rest = nums.filter((_, i) => !used.has(i));
      if ((out.match(MARK_G) || []).length !== rest.length) return null;
      let i = 0;
      out = out.replace(MARK_G, () => rest[i++]);
    }
    return out;
  }
  let done = new Set();
  function text(s) {
    if (!exact || !s || !/[A-Za-z]/.test(s)) return s;
    const core = s.trim();
    if (done.has(core.replace(/\s+/g, ' '))) return s;
    const norm = core.replace(/\s+/g, ' ');
    let t = lookup(norm);
    if (t == null) {                    // several sentences (messages): one by one, only if all are known
      const parts = norm.split(/(?<=[.!?])\s+(?=[A-Z0-9])/);
      if (parts.length > 1) { const tr = parts.map(p => lookup(p)); if (tr.every(x => x != null)) t = tr.join(' '); }
    }
    if (t == null) return s;
    const i = s.indexOf(core);
    return s.slice(0, i) + t + s.slice(i + core.length);
  }
  window.vcT = text;
  const skipped = el => { for (let e = el; e && e.nodeType === 1; e = e.parentElement) { if (SKIP.has(e.tagName) || e.getAttribute('translate') === 'no' || e.isContentEditable) return true; } return false; };
  function node(n) {
    if (n.nodeType === 3) {
      if (n.parentElement && !skipped(n.parentElement)) { const t = text(n.nodeValue); if (t !== n.nodeValue) n.nodeValue = t; }
      return;
    }
    if (n.nodeType !== 1 || skipped(n)) return;
    attrs(n);
    const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: x => (x.nodeType === 1 && (SKIP.has(x.tagName) || x.getAttribute('translate') === 'no')) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
    for (let x = w.nextNode(); x; x = w.nextNode()) {
      if (x.nodeType === 3) { const t = text(x.nodeValue); if (t !== x.nodeValue) x.nodeValue = t; } else attrs(x);
    }
  }
  function attrs(el) {
    for (const a of ATTRS) { const v = el.getAttribute(a); if (v) { const t = text(v); if (t !== v) el.setAttribute(a, t); } }
    if ((el.tagName === 'INPUT' && /^(submit|button)$/.test(el.type)) && el.value) { const t = text(el.value); if (t !== el.value) el.value = t; }
  }
  // messages from scripts
  const oc = window.confirm, oa = window.alert, op = window.prompt;
  window.confirm = m => oc.call(window, text(String(m)));
  window.alert = m => oa.call(window, text(String(m)));
  window.prompt = (m, d) => op.call(window, text(String(m)), d);

  fetch(src, {credentials: 'same-origin'}).then(r => r.ok ? r.json() : {}).then(data => {
    build(data);
    node(document.body);                 // anything a script already changed before the catalog arrived
    new MutationObserver(list => {
      for (const m of list) {
        if (m.type === 'childList') m.addedNodes.forEach(node);
        else if (m.type === 'characterData') node(m.target);
        else if (m.type === 'attributes') attrs(m.target);
      }
    }).observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
  }).catch(() => {});
})();
