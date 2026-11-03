// valcoach service worker {{ version }}: makes the site installable, keeps the look (CSS, fonts, scripts)
// for fast starts, shows a page when you're offline, and shows push notifications.
// Pages and data are never cached: they're private and always loaded fresh.
const CACHE = 'valcoach-{{ version }}';
const SHELL = ['/offline', '/static/app.css?v={{ version }}', '/static/ui.js?v={{ version }}',
               '/static/fonts/archivo-latin.woff2', '/static/icons/icon-192.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/static/')) {             // look & fonts: cache first, refresh in the background
    e.respondWith(caches.open(CACHE).then(async c => {
      const hit = await c.match(req);
      const net = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  if (req.mode === 'navigate') {                         // pages: always from the server, a notice when offline
    e.respondWith(fetch(req).catch(() => caches.match('/offline')));
  }
});
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {title: 'valcoach', body: e.data ? e.data.text() : ''}; }
  e.waitUntil(self.registration.showNotification(d.title || 'valcoach', {
    body: d.body || '', tag: d.tag || 'valcoach', renotify: true,
    icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', data: {url: d.url || '/'}}));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || '/', location.origin).href;
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const c of list) { if (c.url === url && 'focus' in c) return c.focus(); }
    for (const c of list) { if ('navigate' in c) return c.navigate(url).then(x => x && x.focus()); }
    return self.clients.openWindow(url);
  }));
});
