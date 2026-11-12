(function () {
  var PLACES = {
    MAD: { lon: -3.567, lat: 40.472, name: "Madrid" },
    BCN: { lon: 2.079, lat: 41.297, name: "Barcelona" },
    SIN: { lon: 103.991, lat: 1.364, name: "Singapore" },
    HKG: { lon: 113.915, lat: 22.309, name: "Hong Kong" }
  };

  var TRIPS = [
    { date: "14 Jan 2026", time: "08:15", from: "MAD", to: "BCN", flight: "Iberia IB3152" },
    { date: "2 Feb 2026", time: "19:40", from: "BCN", to: "MAD", flight: "Vueling VY1004" },
    { date: "18 Mar 2026", time: "13:05", from: "MAD", to: "SIN", flight: "Singapore Airlines SQ321" },
    { date: "21 Mar 2026", time: "09:20", from: "SIN", to: "HKG", flight: "Singapore Airlines SQ856" },
    { date: "25 Mar 2026", time: "16:45", from: "HKG", to: "SIN", flight: "Cathay Pacific CX735" },
    { date: "2 Apr 2026", time: "23:10", from: "SIN", to: "BCN", flight: "Singapore Airlines SQ388" },
    { date: "9 May 2026", time: "07:55", from: "BCN", to: "MAD", flight: "Iberia IB146" },
    { date: "16 Jun 2026", time: "14:30", from: "MAD", to: "HKG", flight: "Cathay Pacific CX321" },
    { date: "28 Jul 2026", time: "01:15", from: "HKG", to: "BCN", flight: "Cathay Pacific CX319" },
    { date: "3 Aug 2026", time: "11:50", from: "BCN", to: "SIN", flight: "Singapore Airlines SQ387" }
  ];

  var BAND_CLASS = ["is-short", "is-mid", "is-long", "is-ultra"];
  var BAND_RGBA = [
    [0.984, 0.749, 0.141, 0.96],
    [0.490, 0.827, 0.988, 0.96],
    [0.176, 0.831, 0.749, 0.96],
    [0.847, 0.706, 0.996, 0.96]
  ];
  var HIGHLIGHT = [0.910, 0.475, 0.976, 1];
  var PULSE_MS = 3200;
  var REVEAL_MS = 1800;
  var speed = 1;
  var revealOrigin = 0;
  var map = null;
  var arcs = null;
  var cursor = TRIPS.length - 1;
  var playing = false;
  var revealing = false;
  var revealStart = 0;
  var advanceQueued = false;
  var geometries = [];

  function haversineKm(lat1, lon1, lat2, lon2) {
    var radius = 6371;
    var phi1 = lat1 * Math.PI / 180;
    var phi2 = lat2 * Math.PI / 180;
    var dphi = (lat2 - lat1) * Math.PI / 180;
    var dlambda = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dphi / 2) * Math.sin(dphi / 2) +
      Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) * Math.sin(dlambda / 2);
    return 2 * radius * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function routeApexM(distanceKm) {
    return 90000 + 110000 * Math.log1p(Math.max(0, distanceKm) / 220);
  }

  function routeCurveSteps(distanceKm) {
    if (distanceKm < 700) return 16;
    if (distanceKm < 2200) return 24;
    if (distanceKm < 5500) return 36;
    return 48;
  }

  function bandFor(km) {
    if (km <= 700) return 0;
    if (km <= 2000) return 1;
    if (km <= 5000) return 2;
    return 3;
  }

  function greatCircle(from, to, steps) {
    var lat1 = from.lat * Math.PI / 180;
    var lon1 = from.lon * Math.PI / 180;
    var lat2 = to.lat * Math.PI / 180;
    var lon2 = to.lon * Math.PI / 180;
    var p1 = [Math.cos(lat1) * Math.cos(lon1), Math.cos(lat1) * Math.sin(lon1), Math.sin(lat1)];
    var p2 = [Math.cos(lat2) * Math.cos(lon2), Math.cos(lat2) * Math.sin(lon2), Math.sin(lat2)];
    var dot = Math.max(-1, Math.min(1, p1[0] * p2[0] + p1[1] * p2[1] + p1[2] * p2[2]));
    var omega = Math.acos(dot);
    var rawLons = [];
    var rawLats = [];
    var i, t, sinOmega, a, b, x, y, z;
    for (i = 0; i <= steps; i++) {
      t = i / steps;
      if (omega < 1e-12) {
        x = p1[0]; y = p1[1]; z = p1[2];
      } else {
        sinOmega = Math.sin(omega);
        a = Math.sin((1 - t) * omega) / sinOmega;
        b = Math.sin(t * omega) / sinOmega;
        x = a * p1[0] + b * p2[0];
        y = a * p1[1] + b * p2[1];
        z = a * p1[2] + b * p2[2];
      }
      rawLons.push(Math.atan2(y, x) * 180 / Math.PI);
      rawLats.push(Math.atan2(z, Math.hypot(x, y)) * 180 / Math.PI);
    }
    var unwrapped = [rawLons[0]];
    for (i = 1; i < rawLons.length; i++) {
      var candidate = rawLons[i];
      var prev = unwrapped[unwrapped.length - 1];
      while (candidate - prev > 180) candidate -= 360;
      while (candidate - prev < -180) candidate += 360;
      unwrapped.push(candidate);
    }
    return { lons: unwrapped, lats: rawLats };
  }

  function geometry(index) {
    if (geometries[index]) return geometries[index];
    var trip = TRIPS[index];
    var from = PLACES[trip.from];
    var to = PLACES[trip.to];
    var km = haversineKm(from.lat, from.lon, to.lat, to.lon);
    var steps = routeCurveSteps(km);
    var line = greatCircle(from, to, steps);
    var apex = routeApexM(km);
    var coords = [];
    var last = line.lons.length - 1;
    for (var i = 0; i <= last; i++) {
      var t = last === 0 ? 0 : i / last;
      coords.push([line.lons[i], line.lats[i], Math.round(apex * Math.sin(Math.PI * t))]);
    }
    geometries[index] = { km: km, band: bandFor(km), coords: coords, apex: apex };
    return geometries[index];
  }

  function brighten(rgba) {
    return [
      rgba[0] + (1 - rgba[0]) * 0.45,
      rgba[1] + (1 - rgba[1]) * 0.45,
      rgba[2] + (1 - rgba[2]) * 0.45,
      1
    ];
  }

  function pointAt(coords, t) {
    var last = coords.length - 1;
    var clamped = Math.max(0, Math.min(0.9999, t));
    var pos = clamped * last;
    var i = Math.floor(pos);
    var f = pos - i;
    var a = coords[i];
    var b = coords[Math.min(last, i + 1)];
    return [
      a[0] + (b[0] - a[0]) * f,
      a[1] + (b[1] - a[1]) * f,
      a[2] + (b[2] - a[2]) * f
    ];
  }

  function span(coords, start, end, minLen) {
    if (!coords || coords.length < 2 || end - start < (minLen == null ? 0.03 : minLen)) return null;
    var last = coords.length - 1;
    var out = [pointAt(coords, start)];
    var i;
    for (i = Math.floor(start * last) + 1; i <= Math.floor(end * last); i++) out.push(coords[i]);
    out.push(pointAt(coords, Math.min(0.9999, end)));
    return out.length >= 2 ? out : null;
  }

  function lift(coords, extra) {
    var out = [];
    for (var i = 0; i < coords.length; i++) out.push([coords[i][0], coords[i][1], coords[i][2] + extra]);
    return out;
  }

  function sliceTo(coords, t) {
    var end = Math.max(0.04, Math.min(1, t));
    if (end >= 0.995) return coords;
    var piece = span(coords, 0, end);
    return piece || coords.slice(0, 2);
  }

  function leadDash(coords, phase) {
    var start = phase - Math.floor(phase);
    var end = start + 0.16;
    var piece = span(coords, start, Math.min(0.999, end));
    return piece ? [piece] : [];
  }

  function pulsePieces(coords, phase) {
    var p = phase - Math.floor(phase);
    var travel = p * 1.16;
    var head = Math.min(0.999, travel);
    var tail = Math.max(0, travel - 0.16);
    if (tail >= head) return [];
    var piece = span(coords, tail, head, 0.008);
    return piece ? [piece] : [];
  }

  function elapsedReveal(now) {
    return Math.min(1, revealOrigin + (now - revealStart) / (REVEAL_MS / speed));
  }

  function revealAmount(now) {
    if (!revealing) return 1;
    var linear = elapsedReveal(now);
    if (linear >= 1) {
      revealing = false;
      revealOrigin = 1;
      if (playing) queueNextFlight();
      return 1;
    }
    return linear * linear * (3 - 2 * linear);
  }

  function paintAirports() {
    if (!map || !map.getSource("history-airports")) return;
    var seen = {};
    var features = [];
    for (var i = 0; i <= cursor; i++) {
      [TRIPS[i].from, TRIPS[i].to].forEach(function (code) {
        if (seen[code]) return;
        seen[code] = true;
        var place = PLACES[code];
        features.push({
          type: "Feature",
          properties: { code: code },
          geometry: { type: "Point", coordinates: [place.lon, place.lat] }
        });
      });
    }
    map.getSource("history-airports").setData({ type: "FeatureCollection", features: features });
  }

  function paintArcs(now) {
    if (!arcs) return;
    var screen = document.getElementById("screen-flights");
    if (screen && !screen.classList.contains("is-active")) return;
    var phase = (now % PULSE_MS) / PULSE_MS;
    var shown = revealAmount(now);
    var rows = [];
    var i, geo, color, pieces, p;
    for (i = 0; i <= cursor; i++) {
      geo = geometry(i);
      color = BAND_RGBA[geo.band];
      if (i === cursor && revealing) {
        rows.push([8, sliceTo(geo.coords, shown), null, HIGHLIGHT, 4.4]);
        pieces = leadDash(sliceTo(geo.coords, shown), 0.84);
        for (p = 0; p < pieces.length; p++) rows.push([8, lift(pieces[p], 14000), null, brighten(HIGHLIGHT), 4.2]);
      } else {
        rows.push([i === cursor ? 8 : geo.band, geo.coords, null]);
        pieces = pulsePieces(geo.coords, phase + i * 0.17);
        for (p = 0; p < pieces.length; p++) {
          rows.push([geo.band, lift(pieces[p], 14000), null, brighten(i === cursor ? HIGHLIGHT : color), 3.6]);
        }
      }
    }
    arcs.setData(rows, null);
  }

  function tick(now) {
    var screen = document.getElementById("screen-flights");
    var active = !screen || screen.classList.contains("is-active");
    if (active) paintArcs(now);
    if (active) requestAnimationFrame(tick);
    else setTimeout(function () { requestAnimationFrame(tick); }, 500);
  }

  function stopPlay() {
    playing = false;
    advanceQueued = false;
    var button = document.getElementById("history-play");
    if (button) button.textContent = "Play";
  }

  function queueNextFlight() {
    if (!playing || advanceQueued) return;
    if (cursor >= TRIPS.length - 1) {
      stopPlay();
      return;
    }
    advanceQueued = true;
    setTimeout(function () {
      advanceQueued = false;
      if (!playing) return;
      setCursor(cursor + 1, true, true);
    }, Math.round(260 / speed));
  }

  function stamp(trip) {
    return trip.date + " · " + trip.time;
  }

  function renderSlider() {
    var trip = TRIPS[cursor];
    var label = document.getElementById("history-time-label");
    var sub = document.getElementById("history-time-sub");
    var slider = document.getElementById("history-slider");
    if (label) label.textContent = stamp(trip);
    if (sub) {
      sub.textContent = (cursor + 1) + " of " + TRIPS.length + " flights · up to " + trip.time;
    }
    if (slider && String(slider.value) !== String(cursor)) slider.value = String(cursor);
  }

  function renderList() {
    var list = document.getElementById("history-flow-list");
    if (!list) return;
    var html = "";
    var index;
    for (index = 0; index <= cursor; index++) {
      var trip = TRIPS[index];
      var from = PLACES[trip.from];
      var to = PLACES[trip.to];
      var band = BAND_CLASS[geometry(index).band];
      html += (
        "<li><button type='button' class='flow-item" + (index === cursor ? " is-on" : "") + "' data-index='" + index + "'>" +
        "<span class='flow-dot " + band + "' aria-hidden='true'></span>" +
        "<span class='flow-date'>" + stamp(trip) + "</span>" +
        "<span class='flow-route'>" + trip.from + " → " + trip.to + "</span>" +
        "<span class='flow-meta'>" + from.name + " to " + to.name + " · " + trip.flight + "</span>" +
        "</button></li>"
      );
    }
    list.innerHTML = html;
    list.querySelectorAll(".flow-item").forEach(function (button) {
      button.addEventListener("click", function () {
        stopPlay();
        setCursor(Number(button.getAttribute("data-index")), true);
      });
    });
  }

  function mapPadding() {
    var narrow = window.matchMedia("(max-width: 900px)").matches;
    if (!narrow) return { top: 24, bottom: 28, left: 28, right: 28 };
    var display = document.getElementById("history-display");
    var screen = document.getElementById("screen-flights");
    if (!display || !screen) return { top: 64, bottom: 280, left: 8, right: 8 };
    var cover = screen.getBoundingClientRect().bottom - display.getBoundingClientRect().top + 8;
    return { top: 64, bottom: Math.max(80, cover), left: 8, right: 8 };
  }

  function setCursor(index, animate, flow) {
    cursor = Math.max(0, Math.min(TRIPS.length - 1, index));
    if (flow) {
      revealing = true;
      revealOrigin = 0;
      revealStart = performance.now();
    } else {
      revealing = false;
      revealOrigin = 1;
    }
    renderSlider();
    renderList();
    paintAirports();
    paintArcs(performance.now());
    if (!map) return;
    var camera = { padding: mapPadding(), duration: flow ? REVEAL_MS / speed : animate ? 700 : 0, pitch: 28 };
    if (animate || flow) {
      var trip = TRIPS[cursor];
      var from = PLACES[trip.from];
      var to = PLACES[trip.to];
      camera.center = [(from.lon + to.lon) / 2, (from.lat + to.lat) / 2];
      camera.zoom = Math.abs(from.lon - to.lon) > 40 ? 1.55 : 3.2;
    }
    map.easeTo(camera);
  }

  function addLayers() {
    arcs = window.airwaysCreateArcLayer();
    map.addLayer(arcs);
    map.addSource("history-airports", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] }
    });
    map.addLayer({
      id: "history-airports",
      type: "circle",
      source: "history-airports",
      paint: {
        "circle-radius": 5,
        "circle-color": "#f8fafc",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#0c1424"
      }
    });
    map.addLayer({
      id: "history-labels",
      type: "symbol",
      source: "history-airports",
      layout: {
        "text-field": ["get", "code"],
        "text-font": ["Open Sans Regular", "Arial Unicode MS Regular"],
        "text-size": 12,
        "text-offset": [0, 0.9],
        "text-anchor": "top"
      },
      paint: {
        "text-color": "#f8fafc",
        "text-halo-color": "#0c1424",
        "text-halo-width": 1.2
      }
    });
    setCursor(cursor, false);
    requestAnimationFrame(tick);
  }

  function ensure() {
    var el = document.getElementById("history-map");
    if (!el || !window.maplibregl || !window.airwaysCreateArcLayer || map) return;
    map = new window.maplibregl.Map({
      container: el,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [55, 28],
      zoom: 1.35,
      pitch: 28,
      attributionControl: false,
      fadeDuration: 0,
      maxPitch: 70
    });
    map.dragRotate.enable();
    map.touchZoomRotate.enable();
    window.airwaysHistoryMap = function () { return map; };
    map.on("load", function () {
      if (map.setProjection) map.setProjection({ type: "globe" });
      addLayers();
    });
  }

  function bindToggle() {
    var shell = document.getElementById("history-shell");
    var toggle = document.getElementById("history-toggle");
    if (!shell || !toggle) return;
    var closed = false;
    toggle.addEventListener("click", function () {
      closed = !closed;
      shell.classList.toggle("is-closed", closed);
      toggle.textContent = closed ? "Panel" : "Hide";
      requestAnimationFrame(function () {
        if (map) map.easeTo({ padding: mapPadding(), duration: 400 });
      });
    });
    var display = document.getElementById("history-display");
    var displayToggle = document.getElementById("history-display-toggle");
    if (display && displayToggle) {
      var displayClosed = false;
      displayToggle.addEventListener("click", function () {
        displayClosed = !displayClosed;
        display.classList.toggle("is-closed", displayClosed);
        displayToggle.textContent = displayClosed ? "Display" : "Hide";
        requestAnimationFrame(function () {
          if (map) map.easeTo({ padding: mapPadding(), duration: 400 });
        });
      });
    }
    document.querySelectorAll(".history-speed button").forEach(function (button) {
      button.addEventListener("click", function () {
        var now = performance.now();
        var next = Number(button.getAttribute("data-speed")) || 1;
        if (revealing) {
          revealOrigin = elapsedReveal(now);
          revealStart = now;
        }
        speed = next;
        document.querySelectorAll(".history-speed button").forEach(function (other) {
          var on = Number(other.getAttribute("data-speed")) === speed;
          other.classList.toggle("is-on", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        });
      });
    });
  }

  function bindSlider() {
    var slider = document.getElementById("history-slider");
    var play = document.getElementById("history-play");
    if (slider) {
      slider.min = "0";
      slider.max = String(TRIPS.length - 1);
      slider.value = String(cursor);
      slider.addEventListener("input", function () {
        stopPlay();
        setCursor(Number(slider.value), false);
      });
      slider.addEventListener("change", function () {
        setCursor(Number(slider.value), true);
      });
    }
    if (play) {
      play.addEventListener("click", function () {
        if (playing) {
          stopPlay();
          return;
        }
        playing = true;
        play.textContent = "Pause";
        if (cursor >= TRIPS.length - 1) setCursor(0, true, true);
        else setCursor(cursor + 1, true, true);
      });
    }
  }

  renderSlider();
  renderList();
  bindToggle();
  bindSlider();
  ensure();
  window.addEventListener("resize", function () {
    if (!map) return;
    map.resize();
    map.easeTo({ padding: mapPadding(), duration: 0 });
  });
})();
