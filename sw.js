// PWAのオフライン対応用サービスワーカー。
// index.html には配信中バージョンを検知して自動リロードする仕組みが
// 既にあるため(app-versionメタタグの比較)、それを妨げないように
// 同一オリジンのドキュメントは常に network-first とし、オフライン時のみ
// キャッシュへフォールバックする。CDN配信のライブラリはほぼ更新されない
// ため cache-first とし、オフラインでもアプリ本体が確実に動くようにする。
const CACHE_VERSION = "v1";
const CACHE_NAME = `daily-notes-${CACHE_VERSION}`;

const CDN_URLS = [
  "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
  "https://cdn.jsdelivr.net/npm/qrcode@1/build/qrcode.min.js",
  "https://cdn.jsdelivr.net/npm/jsqr@1/dist/jsQR.js",
];

const SAME_ORIGIN_PATHS = [
  "/",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

const APP_SHELL = [...SAME_ORIGIN_PATHS, ...CDN_URLS];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.all(
          APP_SHELL.map((url) =>
            cache.add(url).catch((err) => {
              console.warn("[sw] precache failed:", url, err);
            })
          )
        )
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if ("GET" !== req.method) return;

  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/"))
    return;

  if (CDN_URLS.includes(req.url)) {
    event.respondWith(
      caches.match(req).then(
        (cached) =>
          cached ||
          fetch(req).then((res) => {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
            return res;
          })
      )
    );
    return;
  }

  if (url.origin !== self.location.origin) return;

  // クエリ文字列違いのキャッシュが無限に増えないよう、アプリ shell の
  // パスだけをキャッシュ対象にする(バージョン確認用の "/?_=..." 等は
  // ネットワークから直接返すのみでキャッシュしない)。
  const isShellPath = SAME_ORIGIN_PATHS.includes(url.pathname);

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (isShellPath) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(url.pathname, clone));
        }
        return res;
      })
      .catch(() =>
        caches
          .match(isShellPath ? url.pathname : req)
          .then(
            (cached) =>
              cached ||
              ("navigate" === req.mode ? caches.match("/") : undefined)
          )
      )
  );
});
