(function () {
  "use strict";

  var statusEl = document.getElementById("status");
  var locateBtn = document.getElementById("locate-btn");

  function showStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.classList.remove("hidden");
    statusEl.classList.toggle("error", !!isError);
  }

  function hideStatus() {
    statusEl.classList.add("hidden");
  }

  // ---------------------------------------------------------------------------
  // Kryptering / köpkod
  //
  // Kartrutorna är krypterade med en huvudnyckel K (AES-256-GCM). En köpkod
  // packar upp K via PBKDF2 (samma parametrar som scripts/access.py). K sparas i
  // localStorage så man slipper skriva koden varje gång. Allt sker i webbläsaren.
  // ---------------------------------------------------------------------------

  var KEY_STORAGE = "runn_chart_key";
  var contentKey = null; // CryptoKey (AES-GCM) för K

  function b64ToBytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }

  function importContentKey(rawBytes) {
    return crypto.subtle.importKey("raw", rawBytes, "AES-GCM", false, ["decrypt"]);
  }

  // Gör koden okänslig för bindestreck och gemener. MÅSTE matcha normalize_code()
  // i scripts/access.py. Saknas RUNN-prefixet läggs det till.
  function normalizeCode(s) {
    var a = (s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (a.indexOf("RUNN") !== 0) a = "RUNN" + a;
    return a;
  }

  // Visar koden med automatiska bindestreck medan man skriver: RUNN-XXXX-XXXX-XXXX.
  function formatCode(s) {
    var a = (s || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 16);
    return a.replace(/(.{4})/g, "$1-").replace(/-$/, "");
  }

  // Försök packa upp K ur codes.json med en inskriven kod.
  function unlockWithCode(code, cfg) {
    var enc = new TextEncoder();
    var salt = b64ToBytes(cfg.kdf.salt);
    return crypto.subtle
      .importKey("raw", enc.encode(code), "PBKDF2", false, ["deriveKey"])
      .then(function (baseKey) {
        return crypto.subtle.deriveKey(
          { name: "PBKDF2", salt: salt, iterations: cfg.kdf.iterations, hash: "SHA-256" },
          baseKey,
          { name: "AES-GCM", length: 256 },
          false,
          ["decrypt"]
        );
      })
      .then(function (kek) {
        // Rätt kod låser upp exakt en entry; övriga ger autentiseringsfel.
        var entries = cfg.entries || [];
        var tryEntry = function (i) {
          if (i >= entries.length) return Promise.resolve(null);
          var e = entries[i];
          return crypto.subtle
            .decrypt({ name: "AES-GCM", iv: b64ToBytes(e.iv) }, kek, b64ToBytes(e.data))
            .then(function (raw) {
              return new Uint8Array(raw);
            })
            .catch(function () {
              return tryEntry(i + 1);
            });
        };
        return tryEntry(0);
      });
  }

  // Dekryptera en ruta (iv || ciphertext+tag) till en JPEG-blob.
  function decryptTile(buffer) {
    var bytes = new Uint8Array(buffer);
    var iv = bytes.subarray(0, 12);
    var data = bytes.subarray(12);
    return crypto.subtle
      .decrypt({ name: "AES-GCM", iv: iv }, contentKey, data)
      .then(function (plain) {
        return new Blob([plain], { type: "image/jpeg" });
      });
  }

  // Leaflet-lager som hämtar krypterade .bin-rutor och dekrypterar dem i farten.
  var EncryptedTileLayer = L.TileLayer.extend({
    createTile: function (coords, done) {
      var tile = document.createElement("img");
      tile.alt = "";
      fetch(this.getTileUrl(coords))
        .then(function (res) {
          if (!res.ok) throw new Error("tile " + res.status);
          return res.arrayBuffer();
        })
        .then(decryptTile)
        .then(function (blob) {
          tile.src = URL.createObjectURL(blob);
          tile.onload = function () {
            URL.revokeObjectURL(tile.src);
          };
          done(null, tile);
        })
        .catch(function () {
          // Saknad kantruta eller nätfel — visa tom ruta, inte fel-ikon.
          done(null, tile);
        });
      return tile;
    },
  });

  // ---------------------------------------------------------------------------
  // Karta
  // ---------------------------------------------------------------------------

  var map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
    maxZoom: 21,
    minZoom: 2,
  });
  map.attributionControl.setPrefix("");

  var satellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxNativeZoom: 19,
      maxZoom: 21,
      attribution:
        'Satellit: &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics',
    }
  );

  var mapInitDone = false;

  function initMapContent() {
    if (mapInitDone) return;
    mapInitDone = true;

    fetch("chart/bounds.json")
      .then(function (res) {
        if (!res.ok) throw new Error("bounds.json saknas (" + res.status + ")");
        return res.json();
      })
      .then(function (b) {
        var bounds = L.latLngBounds([b.south, b.west], [b.north, b.east]);
        var chart = new EncryptedTileLayer("chart/tiles/{z}/{x}/{y}.bin", {
          minZoom: 2,
          maxNativeZoom: 16,
          maxZoom: 21,
          bounds: bounds,
          attribution: "Sjökort Runn 2023 1:25000",
        }).addTo(map);
        map.fitBounds(bounds);
        map.setMaxBounds(bounds.pad(0.5));

        L.control
          .layers({ Sjökort: chart, Satellit: satellite }, {}, { collapsed: false })
          .addTo(map);
      })
      .catch(function (err) {
        showStatus("Kunde inte läsa in sjökortet: " + err.message, true);
        map.setView([60.6, 15.7], 12);
      });

    startWatching();
  }

  // ---------------------------------------------------------------------------
  // Inloggningsflöde
  // ---------------------------------------------------------------------------

  var loginEl = document.getElementById("login");
  var loginForm = document.getElementById("login-form");
  var loginInput = document.getElementById("login-code");
  var loginMsg = document.getElementById("login-msg");
  var loginBtn = loginForm.querySelector("button");
  var accessConfig = null;

  function showLogin() {
    loginEl.classList.remove("hidden");
    loginInput.focus();
  }

  function openMap() {
    loginEl.classList.add("hidden");
    initMapContent();
  }

  function secureContextOk() {
    return window.isSecureContext && window.crypto && crypto.subtle;
  }

  // Redan upplåst tidigare? Återanvänd sparad nyckel.
  function tryRestore() {
    var saved = localStorage.getItem(KEY_STORAGE);
    if (!saved) return Promise.resolve(false);
    return importContentKey(b64ToBytes(saved))
      .then(function (key) {
        contentKey = key;
        return true;
      })
      .catch(function () {
        localStorage.removeItem(KEY_STORAGE);
        return false;
      });
  }

  // Lägg till bindestreck automatiskt medan man skriver.
  loginInput.addEventListener("input", function () {
    loginInput.value = formatCode(loginInput.value);
  });

  loginForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var code = normalizeCode(loginInput.value);
    if (code === "RUNN" || !accessConfig) return;
    loginMsg.textContent = "";
    loginBtn.disabled = true;
    loginBtn.textContent = "Öppnar…";

    unlockWithCode(code, accessConfig)
      .then(function (rawKey) {
        if (!rawKey) throw new Error("fel kod");
        return importContentKey(rawKey).then(function (key) {
          contentKey = key;
          localStorage.setItem(KEY_STORAGE, bytesToB64(rawKey));
          openMap();
        });
      })
      .catch(function () {
        loginMsg.textContent = "Koden stämmer inte. Kontrollera och försök igen.";
      })
      .then(function () {
        loginBtn.disabled = false;
        loginBtn.textContent = "Öppna kartan";
      });
  });

  // --- Hjälp/info-ruta ---
  (function setupHelp() {
    var helpBtn = document.getElementById("help-btn");
    var helpOverlay = document.getElementById("help");
    var helpClose = document.getElementById("help-close");
    var iosSteps = document.getElementById("help-ios");
    var androidSteps = document.getElementById("help-android");

    // Visa bara instruktionen för besökarens plattform (båda om okänd).
    var ua = navigator.userAgent || "";
    var isIOS =
      /iphone|ipad|ipod/i.test(ua) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    var isAndroid = /android/i.test(ua);
    if (isIOS && !isAndroid) androidSteps.style.display = "none";
    if (isAndroid && !isIOS) iosSteps.style.display = "none";

    function openHelp() {
      helpOverlay.classList.remove("hidden");
    }
    function closeHelp() {
      helpOverlay.classList.add("hidden");
    }
    helpBtn.addEventListener("click", openHelp);
    helpClose.addEventListener("click", closeHelp);
    helpOverlay.addEventListener("click", function (ev) {
      if (ev.target === helpOverlay) closeHelp();
    });
  })();

  function boot() {
    if (!secureContextOk()) {
      showLogin();
      loginBtn.disabled = true;
      loginMsg.textContent = "Öppna sidan via https:// för att kunna låsa upp kartan.";
      return;
    }
    fetch("access/codes.json")
      .then(function (res) {
        if (!res.ok) throw new Error();
        return res.json();
      })
      .then(function (cfg) {
        accessConfig = cfg;
      })
      .catch(function () {
        /* codes.json saknas – hanteras vid inloggningsförsök */
      })
      .then(tryRestore)
      .then(function (restored) {
        if (restored) {
          openMap();
        } else {
          showLogin();
        }
      });
  }

  // ---------------------------------------------------------------------------
  // Live-position
  // ---------------------------------------------------------------------------

  var meMarker = null;
  var accuracyCircle = null;
  var following = false;
  var watchId = null;
  var meIcon = L.divIcon({
    className: "",
    html: '<div class="me-dot"></div>',
    iconSize: [18, 18],
  });

  function onPosition(pos) {
    hideStatus();
    var latlng = [pos.coords.latitude, pos.coords.longitude];

    if (!meMarker) {
      meMarker = L.marker(latlng, { icon: meIcon, zIndexOffset: 1000 }).addTo(map);
      accuracyCircle = L.circle(latlng, {
        radius: pos.coords.accuracy || 0,
        color: "#1a73e8",
        weight: 1,
        fillColor: "#1a73e8",
        fillOpacity: 0.15,
      }).addTo(map);
    } else {
      meMarker.setLatLng(latlng);
      accuracyCircle.setLatLng(latlng);
      accuracyCircle.setRadius(pos.coords.accuracy || 0);
    }

    if (following) {
      map.setView(latlng, Math.max(map.getZoom(), 16));
    }
  }

  function onPositionError(err) {
    var msg;
    switch (err.code) {
      case err.PERMISSION_DENIED:
        msg = "Platsåtkomst nekad. Tillåt plats i webbläsarens inställningar för att se din position.";
        break;
      case err.POSITION_UNAVAILABLE:
        msg = "Positionen är inte tillgänglig just nu.";
        break;
      case err.TIMEOUT:
        msg = "Det tog för lång tid att hämta positionen.";
        break;
      default:
        msg = "Kunde inte hämta position: " + err.message;
    }
    showStatus(msg, true);
    following = false;
    locateBtn.classList.remove("active");
  }

  function startWatching() {
    if (!("geolocation" in navigator)) {
      showStatus("Den här webbläsaren stöder inte platsåtkomst.", true);
      return;
    }
    if (watchId !== null) return;
    watchId = navigator.geolocation.watchPosition(onPosition, onPositionError, {
      enableHighAccuracy: true,
      maximumAge: 5000,
      timeout: 15000,
    });
  }

  locateBtn.addEventListener("click", function () {
    following = !following;
    locateBtn.classList.toggle("active", following);
    startWatching();
    if (following && meMarker) {
      map.setView(meMarker.getLatLng(), Math.max(map.getZoom(), 16));
    }
  });

  map.on("dragstart", function () {
    if (following) {
      following = false;
      locateBtn.classList.remove("active");
    }
  });

  boot();
})();
