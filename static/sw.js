// Service worker: offline shell + push notifications.
const CACHE = "upajna-v6";
const SHELL = ["/", "/style.css", "/app.js", "/manifest.webmanifest", "/icon-192.png", "/logo.svg"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.origin !== location.origin) return;
  // Network first so updates show up; fall back to cache when offline.
  e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});
self.addEventListener("push", (e) => {
  let d = {}; try { d = e.data.json(); } catch { d = { title: "Upajna", body: e.data?.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "Upajna", { body: d.body || "", icon: "/icon-192.png", badge: "/icon-192.png", data: { url: d.url || "/" } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/";
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((cs) => { const c = cs.find((x) => "focus" in x); if (c) { c.navigate(url); return c.focus(); } return self.clients.openWindow(url); }));
});
