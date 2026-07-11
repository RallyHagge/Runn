/* Service worker för Sjökort Runn.
 *
 * - App-skal (html/js/css/ikoner): network-first — färskt när man är online,
 *   men fungerar från cache offline. Nya versioner syns alltså direkt.
 * - codes.json: network-first — så att spärrade koder fångas när man är online.
 * - Kartrutor (.bin): cache-first — hämtas en gång och funkar sedan offline.
 * - Förladdning ("precache"): triggas från sidan efter upplåsning och laddar ner
 *   ALLA rutor (~18 MB) i bakgrunden, så hela kartan finns offline.
 *
 * Rutornas version följer docs/chart/tiles-manifest.json. När sjökortet
 * uppdateras (prepare_chart.py) får manifestet en ny version och rutorna laddas
 * om automatiskt. Inget behöver ändras här vid en kartuppdatering.
 */
var SHELL_CACHE = "runn-shell-v2";
var TILES_CACHE = "runn-tiles-v1";

var SHELL_ASSETS = [
  "./",
  "index.html",
  "app.js",
  "style.css",
  "manifest.webmanifest",
  "chart/bounds.json",
  "img/login-bg.jpg",
  "vendor/leaflet/leaflet.js",
  "vendor/leaflet/leaflet.css",
  "vendor/leaflet/images/layers.png",
  "vendor/leaflet/images/layers-2x.png",
  "vendor/leaflet/images/marker-icon.png",
  "vendor/leaflet/images/marker-icon-2x.png",
  "vendor/leaflet/images/marker-shadow.png",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/apple-touch-icon.png",
  "icons/favicon-32.png",
  "icons/favicon-16.png",
];

self.addEventListener("install", function (event) {
  self.skipWaiting();
  event.waitUntil(
    caches.open(SHELL_CACHE).then(function (cache) {
      // Cacha varje resurs för sig så ett enstaka fel inte spräcker allt.
      return Promise.all(
        SHELL_ASSETS.map(function (url) {
          return cache.add(url).catch(function () {});
        })
      );
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    (async function () {
      var keep = [SHELL_CACHE, TILES_CACHE];
      var names = await caches.keys();
      await Promise.all(
        names.filter(function (n) { return keep.indexOf(n) === -1; })
             .map(function (n) { return caches.delete(n); })
      );
      await self.clients.claim();
    })()
  );
});

function isTile(url) {
  return /\/chart\/tiles\/.+\.bin$/.test(url.pathname);
}

async function cacheFirst(request, cacheName) {
  var cached = await caches.match(request);
  if (cached) return cached;
  try {
    var resp = await fetch(request);
    if (resp && resp.ok) {
      var cache = await caches.open(cacheName);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch (e) {
    return new Response("", { status: 504 });
  }
}

async function networkFirst(request) {
  try {
    var resp = await fetch(request);
    if (resp && resp.ok) {
      var cache = await caches.open(SHELL_CACHE);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch (e) {
    // Exakt match först (t.ex. app.js?v=11) så att versioner aldrig blandas.
    var cached = await caches.match(request);
    if (cached) return cached;
    // Navigering offline → fall tillbaka till startsidan.
    if (request.mode === "navigate") {
      var index = await caches.match("index.html");
      if (index) return index;
    }
    return new Response("", { status: 504 });
  }
}

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // t.ex. satellit → direkt till nätet
  if (isTile(url)) {
    event.respondWith(cacheFirst(request, TILES_CACHE));
  } else {
    // App-skal + codes.json + manifest: färskt online, cache offline.
    event.respondWith(networkFirst(request));
  }
});

// --- Förladdning av alla rutor ---

function postAll(msg) {
  self.clients.matchAll().then(function (clients) {
    clients.forEach(function (c) { c.postMessage(msg); });
  });
}

async function precacheTiles() {
  var manifest;
  try {
    manifest = await fetch("chart/tiles-manifest.json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error();
      return r.json();
    });
  } catch (e) {
    postAll({ type: "precache-error" });
    return;
  }

  // Ny kartversion? Släng gamla rut-cachen och börja om.
  var cache = await caches.open(TILES_CACHE);
  var verResp = await cache.match("__version__");
  var current = verResp ? await verResp.text() : null;
  if (current !== manifest.version) {
    await caches.delete(TILES_CACHE);
    cache = await caches.open(TILES_CACHE);
    await cache.put("__version__", new Response(manifest.version));
  }

  var tiles = manifest.tiles || [];
  var total = tiles.length;
  var done = 0;
  var fetched = 0; // hur många som faktiskt laddades ner (0 = allt fanns redan)
  var next = 0;

  async function worker() {
    while (next < tiles.length) {
      var url = tiles[next++];
      try {
        var hit = await cache.match(url);
        if (!hit) {
          var resp = await fetch(url, { cache: "no-store" });
          if (resp && resp.ok) {
            await cache.put(url, resp.clone());
            fetched++;
          }
        }
      } catch (e) {
        /* hoppa över en ruta som inte gick att hämta */
      }
      done++;
      if (done % 25 === 0 || done === total) {
        postAll({ type: "precache-progress", done: done, total: total, fetched: fetched });
      }
    }
  }

  var CONCURRENCY = 6;
  var workers = [];
  for (var i = 0; i < CONCURRENCY; i++) workers.push(worker());
  await Promise.all(workers);
  postAll({ type: "precache-done", total: total, downloaded: fetched });
}

self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "precache") {
    event.waitUntil(precacheTiles());
  }
});
