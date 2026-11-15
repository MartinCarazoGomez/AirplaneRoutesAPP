(function () {
  var SHEET_URL = "https://docs.google.com/spreadsheets/d/1CiNDOUDSymnV-9J7q6X2aEu26YhSdQ28zWr_8N6Xsf8/export?format=csv&gid=389720084";
  var PROFILE_NAMES = {
    martin: "Martin",
    mati: "Mati",
    cristina: "Cristina",
    elena: "Elena",
    elias: "Elias",
    martinillo: "Martinillo"
  };
  var PROFILE_SHEET = {
    martin: { martin: 1, papa: 1 },
    mati: { mati: 1, mama: 1 },
    cristina: { cris: 1, cristina: 1 },
    elena: { elena: 1 },
    elias: { elias: 1, ia: 1 },
    martinillo: { martinillo: 1 }
  };
  var MONTHS = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
  var MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var PLACES = {};
  var TRIPS = [];
  var allRows = null;
  var activeId = readActive();
  var loadState = "loading";

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

  function readActive() {
    try {
      var data = JSON.parse(localStorage.getItem("airways-profile") || "{}");
      return data && data.active ? data.active : "";
    } catch (err) {
      return "";
    }
  }

  function cell(row, index) {
    return index < row.length ? String(row[index] || "").trim() : "";
  }

  function parseCsv(text) {
    var rows = [];
    var row = [];
    var value = "";
    var quoted = false;
    var i, ch;
    for (i = 0; i < text.length; i++) {
      ch = text.charAt(i);
      if (quoted) {
        if (ch === "\"") {
          if (text.charAt(i + 1) === "\"") {
            value += "\"";
            i++;
          } else quoted = false;
        } else value += ch;
      } else if (ch === "\"") quoted = true;
      else if (ch === ",") {
        row.push(value);
        value = "";
      } else if (ch === "\n") {
        row.push(value);
        rows.push(row);
        row = [];
        value = "";
      } else if (ch !== "\r") value += ch;
    }
    if (value.length || row.length) {
      row.push(value);
      rows.push(row);
    }
    return rows;
  }

  function parseWhen(text) {
    var match = String(text || "").match(/(\d{1,2})[-\/]([A-Za-z]{3,})[-\/](\d{4})/);
    if (!match) return null;
    var month = MONTHS[match[2].slice(0, 3).toLowerCase()];
    if (month == null) return null;
    return new Date(Number(match[3]), month, Number(match[1]));
  }

  function parseClock(text) {
    var match = String(text || "").match(/(\d{1,2}):(\d{2})/);
    if (!match) return "";
    var hour = match[1];
    if (hour.length < 2) hour = "0" + hour;
    return hour + ":" + match[2];
  }

  function clockMinutes(text) {
    var match = String(text || "").match(/(\d{1,2}):(\d{2})/);
    if (!match) return -1;
    return Number(match[1]) * 60 + Number(match[2]);
  }

  function flown(status) {
    var value = String(status || "").trim().toLowerCase();
    return !value || value.indexOf("realizado") === 0;
  }

  function flightLabel(airline, code) {
    var name = String(airline || "").trim();
    var number = String(code || "").trim();
    if (name && number) return name + " " + number;
    return name || number || "Flight";
  }

  function pushTrip(list, person, airline, code, origin, dest, dateText, timeText, status) {
    if (!flown(status)) return;
    var from = String(origin || "").trim().toUpperCase();
    var to = String(dest || "").trim().toUpperCase();
    var when = parseWhen(dateText);
    if (!/^[A-Z]{3}$/.test(from) || !/^[A-Z]{3}$/.test(to) || from === to || !when) return;
    list.push({
      person: String(person || "").trim().toLowerCase(),
      date: when.getDate() + " " + MONTH_NAMES[when.getMonth()] + " " + when.getFullYear(),
      time: parseClock(timeText),
      sort: when.getTime() + Math.max(0, clockMinutes(timeText)) * 60000,
      from: from,
      to: to,
      flight: flightLabel(airline, code)
    });
  }

  function rowsFromSheet(table) {
    var list = [];
    var i, row;
    for (i = 4; i < table.length; i++) {
      row = table[i];
      pushTrip(list, cell(row, 3), cell(row, 6), cell(row, 13), cell(row, 8), cell(row, 9), cell(row, 10) || cell(row, 2), cell(row, 11), cell(row, 12));
      pushTrip(list, cell(row, 16), cell(row, 19), cell(row, 20), cell(row, 21), cell(row, 22), cell(row, 23), cell(row, 24), cell(row, 25));
    }
    return list;
  }

  function showForActive() {
    var names = PROFILE_SHEET[activeId] || {};
    var next = [];
    var i;
    for (i = 0; i < allRows.length; i++) {
      if (names[allRows[i].person]) next.push(allRows[i]);
    }
    next.sort(function (a, b) { return a.sort - b.sort; });
    TRIPS = next;
    geometries = [];
    cursor = TRIPS.length ? TRIPS.length - 1 : -1;
    revealing = false;
    revealOrigin = 1;
    stopPlay();
    syncSliderBounds();
    setCursor(cursor, false);
  }

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
    if (!from || !to) {
      geometries[index] = null;
      return null;
    }
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
        if (!place) return;
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
    if (cursor < 0) return;
    var phase = (now % PULSE_MS) / PULSE_MS;
    var shown = revealAmount(now);
    var rows = [];
    var i, geo, color, pieces, p;
    for (i = 0; i <= cursor; i++) {
      geo = geometry(i);
      if (!geo) continue;
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
    return trip.time ? trip.date + " · " + trip.time : trip.date;
  }

  function profileLabel() {
    return PROFILE_NAMES[activeId] || "This profile";
  }

  function syncSliderBounds() {
    var slider = document.getElementById("history-slider");
    if (!slider) return;
    slider.disabled = !TRIPS.length;
    slider.max = String(Math.max(0, TRIPS.length - 1));
    slider.value = String(Math.max(0, cursor));
  }

  function renderSlider() {
    var label = document.getElementById("history-time-label");
    var sub = document.getElementById("history-time-sub");
    var slider = document.getElementById("history-slider");
    if (!TRIPS.length) {
      if (label) label.textContent = loadState === "loading" ? "Loading flights" : loadState === "error" ? "Sheet unavailable" : "No flights";
      if (sub) {
        sub.textContent = loadState === "loading"
          ? "Reading Super Flights"
          : loadState === "error"
            ? "The flight sheet could not be opened"
            : profileLabel() + " has no flights in Super Flights";
      }
      if (slider) {
        slider.disabled = true;
        slider.value = "0";
      }
      return;
    }
    var trip = TRIPS[cursor];
    if (label) label.textContent = stamp(trip);
    if (sub) sub.textContent = (cursor + 1) + " of " + TRIPS.length + " flights";
    if (slider && String(slider.value) !== String(cursor)) slider.value = String(cursor);
  }

  function renderList() {
    var list = document.getElementById("history-flow-list");
    if (!list) return;
    if (!TRIPS.length) {
      var note = loadState === "loading" ? "Loading Super Flights…" : loadState === "error" ? "The flight sheet could not be opened." : "No flights for " + profileLabel() + " in Super Flights.";
      list.innerHTML = "<li class='is-empty'>" + note + "</li>";
      return;
    }
    var html = "";
    var index;
    for (index = 0; index <= cursor; index++) {
      var trip = TRIPS[index];
      var from = PLACES[trip.from];
      var to = PLACES[trip.to];
      var geo = geometry(index);
      var band = geo ? BAND_CLASS[geo.band] : "is-mid";
      html += (
        "<li><button type='button' class='flow-item" + (index === cursor ? " is-on" : "") + "' data-index='" + index + "'>" +
        "<span class='flow-dot " + band + "' aria-hidden='true'></span>" +
        "<span class='flow-date'>" + stamp(trip) + "</span>" +
        "<span class='flow-route'>" + trip.from + " → " + trip.to + "</span>" +
        "<span class='flow-meta'>" + (from ? from.name : trip.from) + " to " + (to ? to.name : trip.to) + " · " + trip.flight + "</span>" +
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
    var screen = document.getElementById("screen-flights");
    var display = document.getElementById("history-display");
    var shell = document.getElementById("history-shell");
    var screenBox = screen ? screen.getBoundingClientRect() : null;
    var narrow = window.matchMedia("(max-width: 900px)").matches;

    function fromTop(el) {
      if (!el || !screenBox) return 0;
      return Math.max(0, el.getBoundingClientRect().bottom - screenBox.top);
    }

    function fromBottom(el) {
      if (!el || !screenBox) return 0;
      return Math.max(0, screenBox.bottom - el.getBoundingClientRect().top);
    }

    if (!narrow) {
      var left = 28;
      if (shell && screenBox) {
        var shellRight = shell.getBoundingClientRect().right - screenBox.left;
        if (shellRight > 0) left = Math.max(28, Math.round(shellRight) + 12);
      }
      return {
        top: Math.max(24, Math.round(fromTop(display)) + 12),
        bottom: 28,
        left: left,
        right: 28
      };
    }

    return {
      top: Math.max(16, Math.round(fromTop(display)) + 10),
      bottom: Math.max(16, Math.round(fromBottom(shell)) + 10),
      left: 8,
      right: 8
    };
  }

  function setCursor(index, animate, flow) {
    if (!TRIPS.length) {
      cursor = -1;
      revealing = false;
      renderSlider();
      renderList();
      paintAirports();
      if (arcs) arcs.setData([], null);
      return;
    }
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
      if (from && to) {
        camera.center = [(from.lon + to.lon) / 2, (from.lat + to.lat) / 2];
        camera.zoom = Math.abs(from.lon - to.lon) > 40 ? 1.55 : 3.2;
      }
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

  var MAP_GESTURES = ["dragPan", "dragRotate", "scrollZoom", "touchZoomRotate", "touchPitch", "doubleClickZoom"];

  function setGlobeTouch(enabled) {
    if (!map) return;
    for (var i = 0; i < MAP_GESTURES.length; i++) {
      var handler = map[MAP_GESTURES[i]];
      if (!handler) continue;
      if (enabled) handler.enable();
      else handler.disable();
    }
  }

  function bindOverlayGesture() {
    var shield = document.getElementById("history-gesture-shield");
    var shell = document.getElementById("history-shell");
    var display = document.getElementById("history-display");
    var flow = shell ? shell.querySelector(".history-flow") : null;
    if (!shield || !shell) return;
    var active = null;

    function overlayTarget(node) {
      return !!(node && ((shell && shell.contains(node)) || (display && display.contains(node))));
    }

    function pointOutside(el, x, y) {
      if (!el) return true;
      var box = el.getBoundingClientRect();
      return x < box.left || x > box.right || y < box.top || y > box.bottom;
    }

    function onTouchMove(event) {
      if (!active) return;
      var touch = event.touches && event.touches[0];
      if (!touch) return;
      var outsideList = !active.scrolling || pointOutside(flow, touch.clientX, touch.clientY);
      if (!outsideList) {
        active.y = touch.clientY;
        return;
      }
      if (!active.scrolling && overlayTarget(event.target)) return;
      if (event.cancelable) event.preventDefault();
      event.stopPropagation();
      if (!active.scrolling || !flow) return;
      var dy = active.y - touch.clientY;
      active.y = touch.clientY;
      if (dy) flow.scrollTop += dy;
    }

    function arm(event) {
      if (!overlayTarget(event.target)) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (!active) {
        document.addEventListener("touchmove", onTouchMove, { capture: true, passive: false });
      }
      active = {
        id: event.pointerId,
        y: event.clientY,
        scrolling: !!(flow && flow.contains(event.target))
      };
      shield.classList.add("is-on");
      setGlobeTouch(false);
    }

    function end(event) {
      if (!active || event.pointerId !== active.id) return;
      active = null;
      shield.classList.remove("is-on");
      setGlobeTouch(true);
      document.removeEventListener("touchmove", onTouchMove, true);
    }

    shell.addEventListener("pointerdown", arm);
    if (display) display.addEventListener("pointerdown", arm);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);

    document.addEventListener("mousemove", function (event) {
      if (!active || overlayTarget(event.target)) return;
      event.stopImmediatePropagation();
    }, true);
  }

  function bindToggle() {
    var shell = document.getElementById("history-shell");
    var toggle = document.getElementById("history-toggle");
    if (!shell || !toggle) return;
    var closed = true;
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
      var displayClosed = true;
      displayToggle.addEventListener("click", function () {
        displayClosed = !displayClosed;
        display.classList.toggle("is-closed", displayClosed);
        displayToggle.textContent = displayClosed ? "Timeline" : "Hide";
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
        if (!TRIPS.length) return;
        playing = true;
        play.textContent = "Pause";
        if (cursor >= TRIPS.length - 1) setCursor(0, true, true);
        else setCursor(cursor + 1, true, true);
      });
    }
  }

  function loadSheet() {
    Promise.all([
      fetch(SHEET_URL).then(function (res) { if (!res.ok) throw new Error("sheet"); return res.text(); }),
      fetch("data/airports.json").then(function (res) { if (!res.ok) throw new Error("airports"); return res.json(); })
    ]).then(function (parts) {
      var airports = parts[1];
      var i;
      for (i = 0; i < airports.length; i++) {
        PLACES[airports[i].iata] = {
          lon: airports[i].lon,
          lat: airports[i].lat,
          name: airports[i].mun || airports[i].name
        };
      }
      allRows = rowsFromSheet(parseCsv(parts[0]));
      loadState = "ready";
      activeId = readActive();
      showForActive();
    }).catch(function () {
      loadState = "error";
      allRows = [];
      showForActive();
    });
  }

  window.addEventListener("airways-profile", function (event) {
    activeId = event.detail || "";
    if (allRows) showForActive();
  });

  renderSlider();
  renderList();
  bindOverlayGesture();
  bindToggle();
  bindSlider();
  ensure();
  loadSheet();
  window.addEventListener("resize", function () {
    if (!map) return;
    map.resize();
    map.easeTo({ padding: mapPadding(), duration: 0 });
  });
})();
