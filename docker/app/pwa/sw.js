/* Service Worker：只缓存界面外壳，API 一律不缓存。
 * 流量数据必须实时，离线时前端显示提示条而不是拿旧数据糊弄人。
 * 修改前端文件后请把 CACHE 版本号 +1，客户端下次打开会自动换新缓存。
 */
const CACHE = 'ttm-shell-v50';
const SHELL = [
  '/',
  '/static/style.css',
  '/static/charts.js',
  '/static/app.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable-512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/favicon-32.png',
  '/manifest.webmanifest'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 1) 所有 /api/ 请求走原始网络，Service Worker 完全不介入
  if (url.pathname.startsWith('/api/')) return;

  // 2) 页面导航：网络优先，断网时回落到缓存的首页
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put('/', copy));
        return res;
      }).catch(() => caches.match('/'))
    );
    return;
  }

  // 3) 静态资源：stale-while-revalidate（先给缓存秒开，后台悄悄更新）
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req).then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => cached || Response.error());
      return cached || network;
    })
  );
});
