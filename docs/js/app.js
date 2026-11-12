(function () {
  var WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var ROUTE_BANDS = [700, 2000, 5000, 1e12];
  var MESH_LIMIT = 45000;

  var airports = new Map();
  var airportList = [];
  var airlineNames = [];
  var routesBySource = new Map();
  var legAirlines = new Map();
  var airlineRoutes = new Map();
  var airlineAirports = new Map();
  var presets = { myid: [], asianMyid: [] };

  var state = {
    source: null,
    dest: null,
    airlines: [],
    showAll: false,
    combos: false,
    finder: false,
    style: "night",
    globe: true,
    dockClosed: window.matchMedia("(max-width: 900px)").matches
  };

  var mergeCache = new Map();
  var meshCache = new Map();
  var meshInflight = new Map();
  var scheduleShards = new Map();
  var scheduleLoads = new Map();
  var renderGen = 0;
  var panelGen = 0;

  function $(id) { return document.getElementById(id); }

  if (state.dockClosed) {
    $("dock-shell").className = "dock-shell is-closed";
    $("dock-toggle").textContent = "Panel";
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  function roundTo(value, digits) {
    var p = Math.pow(10, digits);
    return Math.round(value * p) / p;
  }

  function named(list) {
    var out = [];
    for (var i = 0; i < list.length; i++) {
      if (list[i] && String(list[i]).trim()) out.push(list[i]);
    }
    return out;
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

  function routeCurveSteps(distanceKm) {
    if (distanceKm < 700) return 16;
    if (distanceKm < 2200) return 24;
    if (distanceKm < 5500) return 36;
    return 48;
  }

  function routeApexM(distanceKm) {
    var km = Math.max(0, distanceKm);
    return 90000 + 110000 * Math.log1p(km / 220);
  }

  function buildWrappedRouteLine(srcLon, srcLat, dstLon, dstLat, steps) {
    srcLon = roundTo(srcLon, 6);
    srcLat = roundTo(srcLat, 6);
    dstLon = roundTo(dstLon, 6);
    dstLat = roundTo(dstLat, 6);
    var lat1 = srcLat * Math.PI / 180;
    var lon1 = srcLon * Math.PI / 180;
    var lat2 = dstLat * Math.PI / 180;
    var lon2 = dstLon * Math.PI / 180;
    var p1 = [Math.cos(lat1) * Math.cos(lon1), Math.cos(lat1) * Math.sin(lon1), Math.sin(lat1)];
    var p2 = [Math.cos(lat2) * Math.cos(lon2), Math.cos(lat2) * Math.sin(lon2), Math.sin(lat2)];
    var dot = Math.max(-1, Math.min(1, p1[0] * p2[0] + p1[1] * p2[1] + p1[2] * p2[2]));
    var omega = Math.acos(dot);
    var rawLons = [];
    var rawLats = [];
    var i, t, sinOmega, a, b, x, y, z, lonDeg, latDeg;
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
      lonDeg = Math.atan2(y, x) * 180 / Math.PI;
      latDeg = Math.atan2(z, Math.hypot(x, y)) * 180 / Math.PI;
      rawLons.push(lonDeg);
      rawLats.push(latDeg);
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

  function archPart(part, distanceKm) {
    if (part.length < 2) return part;
    if (distanceKm == null) {
      distanceKm = haversineKm(part[0][1], part[0][0], part[part.length - 1][1], part[part.length - 1][0]);
    }
    var apex = routeApexM(distanceKm);
    var last = part.length - 1;
    var arched = [];
    for (var i = 0; i < part.length; i++) {
      var t = last === 0 ? 0 : i / last;
      arched.push([part[i][0], part[i][1], Math.round(apex * Math.sin(Math.PI * t))]);
    }
    return arched;
  }

  function lineParts(lons, lats, stride, distanceKm) {
    var parts = [];
    var current = [];
    var i, lon, lat;
    for (i = 0; i < lons.length; i++) {
      lon = lons[i];
      lat = lats[i];
      if (lon == null || lat == null) {
        if (current.length >= 2) parts.push(current);
        current = [];
        continue;
      }
      current.push([roundTo(lon, 3), roundTo(lat, 3)]);
    }
    if (current.length >= 2) parts.push(current);
    if (stride > 1) {
      var thinned = [];
      for (i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (part.length <= 4) {
          thinned.push(part);
          continue;
        }
        var kept = [];
        for (var k = 0; k < part.length; k += stride) kept.push(part[k]);
        var tail = part[part.length - 1];
        var lastKept = kept[kept.length - 1];
        if (lastKept[0] !== tail[0] || lastKept[1] !== tail[1]) kept.push(tail);
        if (kept.length >= 2) thinned.push(kept);
      }
      parts = thinned;
    }
    if (distanceKm != null && parts.length > 1) {
      var total = 0;
      for (i = 0; i < parts.length; i++) total += parts[i].length;
      var apex = routeApexM(distanceKm);
      var seen = 0;
      var archedParts = [];
      for (i = 0; i < parts.length; i++) {
        var arched = [];
        for (var j = 0; j < parts[i].length; j++) {
          var tt = total <= 1 ? 0 : seen / (total - 1);
          arched.push([parts[i][j][0], parts[i][j][1], Math.round(apex * Math.sin(Math.PI * tt))]);
          seen += 1;
        }
        archedParts.push(arched);
      }
      return archedParts;
    }
    var single = [];
    for (i = 0; i < parts.length; i++) single.push(archPart(parts[i], distanceKm));
    return single;
  }

  function routeParts(from, to, steps, stride, useDistance) {
    var km = haversineKm(from.lat, from.lon, to.lat, to.lon);
    var line = buildWrappedRouteLine(from.lon, from.lat, to.lon, to.lat, steps == null ? routeCurveSteps(km) : steps);
    return { km: km, parts: lineParts(line.lons, line.lats, stride || 1, useDistance ? km : null) };
  }

  function initialBearing(lat1, lon1, lat2, lon2) {
    var rlat1 = lat1 * Math.PI / 180;
    var rlat2 = lat2 * Math.PI / 180;
    var dlon = (lon2 - lon1) * Math.PI / 180;
    var y = Math.sin(dlon) * Math.cos(rlat2);
    var x = Math.cos(rlat1) * Math.sin(rlat2) - Math.sin(rlat1) * Math.cos(rlat2) * Math.cos(dlon);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  function bandFor(km) {
    for (var i = 0; i < ROUTE_BANDS.length; i++) {
      if (km <= ROUTE_BANDS[i]) return i;
    }
    return ROUTE_BANDS.length - 1;
  }

  function cameraForPoints(lons, lats) {
    if (!lons.length || !lats.length) return null;
    var base = lons[0];
    var shifted = [];
    var i, x;
    for (i = 0; i < lons.length; i++) {
      x = lons[i];
      while (x - base > 180) x -= 360;
      while (x - base < -180) x += 360;
      shifted.push(x);
    }
    var lonC = 0;
    var latC = 0;
    for (i = 0; i < shifted.length; i++) lonC += shifted[i];
    lonC /= shifted.length;
    while (lonC > 180) lonC -= 360;
    while (lonC < -180) lonC += 360;
    for (i = 0; i < lats.length; i++) latC += lats[i];
    latC /= lats.length;
    var lonSpan = Math.max.apply(null, shifted) - Math.min.apply(null, shifted);
    var latSpan = Math.max.apply(null, lats) - Math.min.apply(null, lats);
    var span = Math.max(lonSpan, latSpan, 0.45);
    var zoom = Math.max(1.2, Math.min(5.6, 5.7 - Math.log2(span + 0.7)));
    return [lonC, Math.max(-62, Math.min(74, latC)), zoom];
  }

  function captionOf(iata) {
    var airport = airports.get(iata);
    if (!airport) return iata;
    return airport.caption;
  }

  function mergedNetwork(names) {
    if (!names.length) return { routes: routesBySource, visible: null };
    var key = names.join("\n");
    var cached = mergeCache.get(key);
    if (cached) return cached;
    var routes = new Map();
    var visible = new Set();
    for (var i = 0; i < names.length; i++) {
      var graph = airlineRoutes.get(names[i]);
      if (graph) {
        graph.forEach(function (dsts, src) {
          var bucket = routes.get(src);
          if (!bucket) {
            bucket = new Set();
            routes.set(src, bucket);
          }
          dsts.forEach(function (dst) { bucket.add(dst); });
        });
      }
      var connected = airlineAirports.get(names[i]);
      if (connected) connected.forEach(function (code) { visible.add(code); });
    }
    cached = { routes: routes, visible: visible };
    mergeCache.set(key, cached);
    return cached;
  }

  function airlinesOnLeg(src, dst, selected) {
    var names = legAirlines.get(src + "|" + dst) || [];
    if (!selected.length) return names.slice();
    var chosen = {};
    for (var i = 0; i < selected.length; i++) chosen[selected[i]] = true;
    return names.filter(function (name) { return chosen[name]; });
  }

  function legMeta(src, dst) {
    return { from: src, to: dst, airlines: airlinesOnLeg(src, dst, state.airlines) };
  }

  function oneStopHubs(origin, dest, routes) {
    if (origin === dest) return [];
    var hubs = [];
    var fromOrigin = routes.get(origin);
    if (!fromOrigin) return [];
    fromOrigin.forEach(function (code) {
      if (code === origin || code === dest) return;
      var onward = routes.get(code);
      if (onward && onward.has(dest)) hubs.push(code);
    });
    return Array.from(new Set(hubs)).sort();
  }

  function routeCombinations(origin, dest, routes) {
    if (!origin || !dest) return [];
    var a = origin.trim().toUpperCase();
    var b = dest.trim().toUpperCase();
    if (!a || !b || a === b) return [];
    var paths = [];
    var direct = routes.get(a);
    if (direct && direct.has(b)) paths.push([a, b]);
    oneStopHubs(a, b, routes).forEach(function (hub) { paths.push([a, hub, b]); });
    return paths;
  }

  function twoStopPaths(origin, dest, routes) {
    var a = origin.trim().toUpperCase();
    var b = dest.trim().toUpperCase();
    if (!a || !b || a === b) return [];
    var paths = [];
    var first = routes.get(a);
    if (!first) return paths;
    var xs = Array.from(first);
    for (var i = 0; i < xs.length; i++) {
      var x = xs[i];
      if (x === a || x === b) continue;
      var mid = routes.get(x);
      if (!mid) continue;
      var ys = Array.from(mid);
      for (var j = 0; j < ys.length; j++) {
        var y = ys[j];
        if (y === a || y === b || y === x) continue;
        var last = routes.get(y);
        if (last && last.has(b)) {
          paths.push([a, x, y, b]);
          if (paths.length >= 160) return paths;
        }
      }
    }
    return paths;
  }

  function routeLegsFromPaths(paths) {
    var seen = {};
    var light = [];
    var middle = [];
    var deep = [];
    function add(src, dst, band, bucket) {
      var key = src + "|" + dst;
      if (seen[key]) return;
      seen[key] = true;
      bucket.push([src, dst, band]);
    }
    paths.forEach(function (path) {
      if (path.length === 2) add(path[0], path[1], 9, deep);
      else if (path.length === 3) {
        add(path[0], path[1], 10, light);
        add(path[1], path[2], 9, deep);
      } else if (path.length >= 4) {
        add(path[0], path[1], 10, light);
        add(path[1], path[2], 11, middle);
        add(path[path.length - 2], path[path.length - 1], 9, deep);
      }
    });
    return light.concat(middle, deep);
  }

  function formatAirlineNames(names) {
    if (!names.length) return "—";
    if (names.length <= 10) return names.join(", ");
    return names.slice(0, 10).join(", ") + " (+" + (names.length - 10) + " more)";
  }

  function selectionFromDropdowns(fromVal, toVal) {
    var from = fromVal ? String(fromVal).trim().toUpperCase() : "";
    var to = toVal ? String(toVal).trim().toUpperCase() : "";
    if (!from) return { source: null, dest: null };
    if (!to || to === from) return { source: from, dest: null };
    return { source: from, dest: to };
  }

  function applyDropdown(fromVal, toVal) {
    var next = selectionFromDropdowns(fromVal, toVal);
    var network = mergedNetwork(state.airlines);
    if (state.airlines.length && next.source && network.visible && !network.visible.has(next.source)) {
      next = { source: null, dest: null };
    } else if (next.source && next.dest && !state.finder) {
      var outs = network.routes.get(next.source);
      if (!outs || !outs.has(next.dest)) next = { source: next.source, dest: null };
    }
    if (next.source === state.source && next.dest === state.dest) {
      syncInputs();
      return;
    }
    state.source = next.source;
    state.dest = next.dest;
    refreshCombos(false);
    render();
  }

  function refreshCombos(toggled) {
    var network = mergedNetwork(state.airlines);
    var has = routeCombinations(state.source, state.dest, network.routes).length > 0;
    if (toggled) state.combos = has && !state.combos;
    else state.combos = state.combos && has;
  }

  function onMapClick(iata) {
    iata = String(iata || "").toUpperCase();
    if (!iata || !airports.has(iata)) return;
    var network = mergedNetwork(state.airlines);
    if (state.finder) {
      if (!state.source || iata === state.source) {
        if (iata === state.source) {
          state.source = null;
          state.dest = null;
        } else {
          state.source = iata;
          state.dest = null;
        }
      } else if (iata === state.dest) {
        state.dest = null;
      } else {
        state.dest = iata;
      }
    } else if (!state.source) {
      state.source = iata;
      state.dest = null;
    } else if (!state.dest) {
      if (iata === state.source) {
        state.source = null;
        state.dest = null;
      } else {
        state.dest = iata;
      }
    } else if (iata === state.source) {
      state.dest = null;
    } else {
      var outs = network.routes.get(state.source);
      if (outs && outs.has(iata)) state.dest = iata;
      else {
        state.source = iata;
        state.dest = null;
      }
    }
    refreshCombos(false);
    render();
  }

  function clearRoute() {
    state.source = null;
    state.dest = null;
    refreshCombos(false);
    render();
  }

  function collectEdges(routes) {
    var edges = [];
    var total = 0;
    routes.forEach(function (dsts, src) {
      var from = airports.get(src);
      if (!from) return;
      dsts.forEach(function (dst) {
        var to = airports.get(dst);
        if (!to) return;
        total += 1;
        edges.push([from, to]);
      });
    });
    var drawn = edges;
    if (total > MESH_LIMIT) {
      var step = Math.max(1, Math.floor(total / MESH_LIMIT));
      drawn = [];
      for (var i = 0; i < edges.length; i += step) drawn.push(edges[i]);
    }
    return { edges: drawn, total: total, drawn: drawn.length };
  }

  function buildMeshAsync(edges) {
    var mesh = [];
    var index = 0;
    return new Promise(function (resolve) {
      function chunk() {
        var end = Math.min(edges.length, index + 900);
        for (; index < end; index++) {
          var parts = routeParts(edges[index][0], edges[index][1], 10, 2, false).parts;
          for (var p = 0; p < parts.length; p++) mesh.push(parts[p]);
        }
        if (index < edges.length) setTimeout(chunk, 0);
        else resolve(mesh);
      }
      chunk();
    });
  }

  function requestMesh(key, edges) {
    if (meshCache.has(key)) return { mesh: meshCache.get(key), promise: null };
    if (!meshInflight.has(key)) {
      meshInflight.set(key, buildMeshAsync(edges).then(function (mesh) {
        meshCache.set(key, mesh);
        meshInflight.delete(key);
        if (meshCache.size > 2) {
          var oldest = meshCache.keys().next().value;
          if (oldest !== key) meshCache.delete(oldest);
        }
        return mesh;
      }));
    }
    return { mesh: null, promise: meshInflight.get(key) };
  }

  function coordsFor(codes) {
    var lons = [];
    var lats = [];
    codes.forEach(function (code) {
      var airport = airports.get(code);
      if (!airport) return;
      lons.push(airport.lon);
      lats.push(airport.lat);
    });
    return { lons: lons, lats: lats };
  }

  function layoverHover(paths) {
    var layovers = {};
    paths.forEach(function (path) {
      if (path.length === 3) {
        layovers[path[1]] = layovers[path[1]] || {
          legs: [legMeta(path[0], path[1]), legMeta(path[1], path[2])]
        };
      } else if (path.length >= 4) {
        var legs = [];
        for (var i = 0; i < path.length - 1; i++) legs.push(legMeta(path[i], path[i + 1]));
        for (var c = 1; c < path.length - 1; c++) {
          if (!layovers[path[c]]) layovers[path[c]] = { legs: legs };
        }
      }
    });
    return layovers;
  }

  function mapPin(code, role) {
    var airport = airports.get(code);
    if (!airport) return null;
    var city = airport.mun && String(airport.mun).trim();
    return {
      lon: roundTo(airport.lon, 4),
      lat: roundTo(airport.lat, 4),
      role: role,
      name: city || code,
      iata: code
    };
  }

  function buildView() {
    var network = mergedNetwork(state.airlines);
    var active = network.routes;
    var source = state.source;
    var dest = state.dest;
    var finderPaths = [];
    if (state.finder && source && dest) {
      finderPaths = routeCombinations(source, dest, active);
      var hasOneStop = finderPaths.some(function (path) { return path.length === 3; });
      if (!hasOneStop) finderPaths = finderPaths.concat(twoStopPaths(source, dest, active));
    }
    var shown = [];
    var highlighted = null;
    if (finderPaths.length) {
      shown = finderPaths;
      highlighted = routeLegsFromPaths(finderPaths);
    } else if (state.combos) {
      shown = routeCombinations(state.source, state.dest, active);
      if (shown.length) highlighted = routeLegsFromPaths(shown);
    }
    var comboOnly = !!highlighted;
    var wantMesh = state.showAll && (!source || (state.finder && source && !dest));
    var meshStats = null;
    var mesh = null;
    var meshPromise = null;
    var meshKey = "off";
    if (wantMesh) {
      var meshNames = state.airlines.slice().sort();
      var meshNetwork = mergedNetwork(meshNames);
      var collected = collectEdges(meshNetwork.routes);
      meshStats = [collected.total, collected.drawn];
      meshKey = meshNames.length ? meshNames.join("|") : "world";
      var requested = requestMesh(meshKey, collected.edges);
      mesh = requested.mesh;
      meshPromise = requested.promise;
    }

    var holdCamera = !!(state.finder && source && !dest);
    var focus = null;
    if (!holdCamera && source && !dest && airports.has(source)) {
      var hub = airports.get(source);
      var distances = [];
      var outs = active.get(source);
      if (outs) {
        outs.forEach(function (code) {
          var airport = airports.get(code);
          if (!airport) return;
          distances.push(haversineKm(hub.lat, hub.lon, airport.lat, airport.lon));
        });
      }
      distances.sort(function (a, b) { return a - b; });
      var typical = distances.length ? distances[Math.floor((distances.length - 1) * 0.42)] : 900;
      var hubZoom = Math.max(2.65, Math.min(5.4, 6.6 - Math.log2(Math.max(typical, 80) / 150)));
      focus = [hub.lon - 14 / hubZoom, hub.lat, hubZoom];
    } else if (!holdCamera && source && dest) {
      var framed = [source, dest];
      if (state.finder) {
        finderPaths.forEach(function (path) {
          for (var i = 1; i < path.length - 1; i++) framed.push(path[i]);
        });
      }
      var frame = coordsFor(framed);
      focus = cameraForPoints(frame.lons, frame.lats);
    } else if (!holdCamera && network.visible && network.visible.size > 0 && network.visible.size <= 280) {
      var visibleFrame = coordsFor(Array.from(network.visible));
      focus = cameraForPoints(visibleFrame.lons, visibleFrame.lats);
    }

    var style = state.style === "day" || state.style === "sat" ? state.style : "night";
    var lon = 10;
    var lat = 16;
    var zoom = state.globe ? 1.25 : 1.55;
    if (focus) {
      lon = focus[0];
      lat = focus[1];
      zoom = focus[2];
      if (state.globe && zoom < 1.7) zoom = 1.25;
    }

    var destinations = [];
    if (source && airports.has(source)) {
      var destSet = active.get(source);
      if (destSet) {
        destSet.forEach(function (code) {
          if (airports.has(code)) destinations.push(code);
        });
        destinations.sort();
      }
    }
    var display;
    if (source && !state.finder) {
      var visibleCodes = {};
      visibleCodes[source] = true;
      destinations.forEach(function (code) { visibleCodes[code] = true; });
      if (dest && airports.has(dest)) visibleCodes[dest] = true;
      display = airportList.filter(function (airport) { return visibleCodes[airport.iata]; });
    } else if (network.visible) {
      display = airportList.filter(function (airport) { return network.visible.has(airport.iata); });
    } else {
      display = airportList;
    }

    var routeRows = [];
    var showHub = !state.finder && !comboOnly;
    var showDestHighlight = showHub;
    if (showHub && source && destinations.length && airports.has(source)) {
      var origin = airports.get(source);
      var hubRoutes = destinations.map(function (code) {
        var airport = airports.get(code);
        return {
          code: code,
          airport: airport,
          bearing: initialBearing(origin.lat, origin.lon, airport.lat, airport.lon)
        };
      });
      hubRoutes.sort(function (a, b) {
        return a.bearing - b.bearing || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0);
      });
      hubRoutes.forEach(function (hop) {
        var drawn = routeParts(origin, hop.airport, null, 1, true);
        var band = bandFor(drawn.km);
        var meta = legMeta(source, hop.code);
        drawn.parts.forEach(function (part) { routeRows.push([band, part, meta]); });
      });
      var chosen = dest && airports.has(dest) && destinations.indexOf(dest) !== -1 ? dest : null;
      if (showDestHighlight && chosen) {
        var destAirport = airports.get(chosen);
        var highlight = routeParts(origin, destAirport, null, 1, true);
        var highlightMeta = legMeta(source, chosen);
        highlight.parts.forEach(function (part) { routeRows.push([8, part, highlightMeta]); });
      }
    }
    if (highlighted) {
      highlighted.forEach(function (leg) {
        var from = airports.get(leg[0]);
        var to = airports.get(leg[1]);
        if (!from || !to) return;
        var drawnLeg = routeParts(from, to, null, 1, true);
        var meta = legMeta(leg[0], leg[1]);
        drawnLeg.parts.forEach(function (part) { routeRows.push([leg[2], part, meta]); });
      });
    }

    var journeys = [];
    if (shown.length) {
      shown.forEach(function (path) {
        var legs = [];
        var hops = path.length - 1;
        for (var hop = 0; hop < hops; hop++) {
          var hopFrom = airports.get(path[hop]);
          var hopTo = airports.get(path[hop + 1]);
          if (!hopFrom || !hopTo) continue;
          var drawnHop = routeParts(hopFrom, hopTo, null, 1, true);
          var hopBand = hops <= 1 ? 9 : (hop === 0 ? 10 : (hop === hops - 1 ? 9 : 11));
          drawnHop.parts.forEach(function (part) {
            if (part && part.length >= 2) legs.push([hopBand, part]);
          });
        }
        if (legs.length) journeys.push(legs);
      });
    }

    var chosenDest = dest && airports.has(dest) ? dest : null;
    var markerDest = showDestHighlight ? chosenDest : null;
    var markers = display.map(function (airport) {
      var kind = airport.tier;
      if (source && airport.iata === source) kind = 5;
      else if (markerDest && airport.iata === markerDest) kind = 6;
      return [roundTo(airport.lon, 3), roundTo(airport.lat, 3), airport.iata, kind, airport.label];
    });

    var showRings = !!(state.finder || (shown.length && source && dest));
    var pins = [];
    function addPin(code, role) {
      if (!code) return;
      var pin = mapPin(code, role);
      if (!pin) return;
      pin.ring = showRings;
      pins.push(pin);
    }
    addPin(source, "origin");
    addPin(dest, "dest");
    var seenLayover = {};
    shown.forEach(function (path) {
      for (var i = 1; i < path.length - 1; i++) {
        if (seenLayover[path[i]]) continue;
        seenLayover[path[i]] = true;
        addPin(path[i], "layover");
      }
    });

    var token = [
      source || "-",
      dest || "-",
      style,
      state.globe ? 1 : 0,
      state.showAll ? 1 : 0,
      state.finder ? 1 : 0
    ].join("|") + "|" + state.airlines.join("|");

    return {
      payload: {
        style: style,
        globe: state.globe,
        token: token,
        holdCamera: holdCamera,
        pins: pins,
        layovers: layoverHover(shown),
        focus: {
          lon: roundTo(lon, 4),
          lat: roundTo(lat, 4),
          zoom: roundTo(zoom, 3),
          pitch: routeRows.length ? 34 : 14
        },
        airports: markers,
        routes: routeRows,
        journeys: journeys
      },
      mesh: mesh,
      meshPromise: meshPromise,
      meshKey: meshKey,
      meshStats: meshStats,
      finderPaths: finderPaths,
      network: network
    };
  }

  function hudText(view) {
    var source = state.source;
    var dest = state.dest;
    var direct = !!(state.finder && source && dest && view.network.routes.get(source) && view.network.routes.get(source).has(dest));
    var oneStop = 0;
    var twoStop = 0;
    view.finderPaths.forEach(function (path) {
      if (path.length === 3) oneStop += 1;
      else if (path.length >= 4) twoStop += 1;
    });
    var title = "World network";
    var sub = airportList.length.toLocaleString("en-US") + " commercial airports";
    if (state.finder && source && dest) {
      if (direct && oneStop) sub = "Direct · " + oneStop + " one-stop";
      else if (direct && twoStop) sub = "Direct · " + twoStop + " two-stop";
      else if (direct) sub = "Direct only";
      else if (oneStop) sub = "No direct · " + oneStop + " one-stop";
      else if (twoStop) sub = "No direct · " + twoStop + " two-stop";
      else sub = "No direct or one-stop route";
      if (state.airlines.length) sub += " · selected airlines";
      title = source + "  →  " + dest;
    } else if (state.finder && source) {
      title = source;
      sub = "Route Finder · pick a second city";
    } else if (source && dest) {
      title = source + "  →  " + dest;
      sub = "Pinned route";
    } else if (source) {
      var outs = view.network.routes.get(source);
      title = source;
      sub = (outs ? outs.size : 0).toLocaleString("en-US") + " outgoing routes";
    } else if (state.showAll) {
      var total = view.meshStats ? view.meshStats[0] : 0;
      var drawn = view.meshStats ? view.meshStats[1] : 0;
      if (drawn && total && drawn < total) sub = drawn.toLocaleString("en-US") + " of " + total.toLocaleString("en-US") + " legs";
      else sub = drawn ? drawn.toLocaleString("en-US") + " legs" : "Route mesh";
      title = "Full network";
    } else if (view.network.visible) {
      title = "World network";
      sub = view.network.visible.size.toLocaleString("en-US") + " commercial airports";
    }
    var banner = "";
    if (state.finder && twoStop && !oneStop) {
      banner = direct
        ? "No one-stop routes. Two-stop routes found, three-leg."
        : "Only two-stop routes found, three-leg.";
    }
    return { title: title, sub: sub, banner: banner };
  }

  function checkerHtml(routes) {
    if (!state.source || !state.dest) {
      return "<p class='muted' style='margin:0;line-height:1.45'>Pick two airports to see whether a nonstop exists in the current map network (respects airline filters).</p>";
    }
    var a = state.source;
    var b = state.dest;
    if (a === b) return "<p class='warn' style='margin:0'>Choose two different airports.</p>";
    if (!airports.has(a) || !airports.has(b)) {
      return "<p class='warn' style='margin:0'>Unknown airport code (not in this app’s commercial set).</p>";
    }
    var direct = routes.get(a) && routes.get(a).has(b);
    var carriers = airlinesOnLeg(a, b, state.airlines);
    var body;
    if (direct) {
      if (carriers.length) {
        body = "Nonstop " + a + " → " + b + " is in the dataset. Carriers (with current filter): " + formatAirlineNames(carriers) + ".";
      } else if (state.airlines.length) {
        body = "Nonstop " + a + " → " + b + " exists on the map, but none of the selected airlines operate this leg in the routes data.";
      } else {
        body = "Nonstop " + a + " → " + b + " is in the dataset. Carriers: " + formatAirlineNames(carriers) + ".";
      }
    } else {
      body = "No nonstop " + a + " → " + b + " in the current network (airline filters apply).";
    }
    return "<p style='margin:0;line-height:1.45'>" + esc(body) + "</p>" +
      "<p class='muted' style='margin:6px 0 0 0;font-size:11px'>" + esc(captionOf(a) + " → " + captionOf(b)) + "</p>";
  }

  function plannerHtml(routes) {
    if (!state.source || !state.dest) {
      return "<p class='muted' style='margin:0;line-height:1.45'>Same airports as above. Lists every itinerary with at most one stop (two segments), using only legs that appear with your airline filter.</p>";
    }
    var a = state.source;
    var b = state.dest;
    if (a === b || !airports.has(a) || !airports.has(b)) {
      return "<p class='muted' style='margin:0'>Set valid, distinct airports to see itineraries.</p>";
    }
    var blocks = [];
    if (routes.get(a) && routes.get(a).has(b)) {
      var air = airlinesOnLeg(a, b, state.airlines);
      var airText = air.length ? formatAirlineNames(air) : (state.airlines.length ? "— (no carriers match filter)" : formatAirlineNames(air));
      blocks.push(
        "<div class='ticket'><div class='ticket-kicker'><strong>Nonstop</strong></div>" +
        "<div class='mono'>" + esc(a + " → " + b) + "</div>" +
        "<div class='muted ticket-airlines'>" + esc(airText) + "</div></div>"
      );
    }
    oneStopHubs(a, b, routes).forEach(function (hub) {
      var leg1 = airlinesOnLeg(a, hub, state.airlines);
      var leg2 = airlinesOnLeg(hub, b, state.airlines);
      var empty = state.airlines.length ? "no filter match" : "—";
      blocks.push(
        "<div class='ticket'><div class='ticket-kicker'><strong>1 stop</strong></div>" +
        "<div class='mono'>" + esc(a + " → " + hub + " → " + b) + "</div>" +
        "<div class='muted' style='font-size:10px;margin:2px 0 6px 0'>" + esc(captionOf(hub)) + "</div>" +
        "<div style='font-size:11px'><span style='font-weight:600'>Leg 1: </span><span>" + esc(leg1.length ? formatAirlineNames(leg1) : empty) + "</span></div>" +
        "<div style='font-size:11px;margin-top:2px'><span style='font-weight:600'>Leg 2: </span><span>" + esc(leg2.length ? formatAirlineNames(leg2) : empty) + "</span></div></div>"
      );
    });
    if (!blocks.length) {
      return "<p class='muted' style='margin:0'>No nonstop or single-stop connection in the current network.</p>";
    }
    return blocks.join("");
  }

  function schedulePanelShell(selectedNames) {
    var source = state.source;
    var dest = state.dest;
    if (!source) {
      return "<h4>Route details</h4><p class='muted'>Click an origin, then a destination. Times below are observed UTC departures.</p>";
    }
    if (!dest) {
      return "<h4>Route details</h4><p class='mono'>Origin " + esc(source) + "</p><p class='muted'>Now choose a destination on the map.</p>";
    }
    var names = airlinesOnLeg(source, dest, selectedNames || []);
    if (!names.length) {
      var filteredOut = selectedNames && selectedNames.length && (legAirlines.get(source + "|" + dest) || []).length;
      var message = filteredOut
        ? "None of the selected airlines fly this route."
        : "No airline data found for this route in the routes dataset.";
      return "<h4>" + esc(source + " → " + dest) + "</h4><p class='muted'>" + esc(message) + "</p>";
    }
    return "<h4 class='mono'>" + esc(source + " → " + dest) + "</h4>" +
      "<p class='muted'>Airlines and observed daily times (UTC).</p>" +
      "<div id='schedule-body'><p class='muted'>Loading observed times…</p></div>";
  }

  function paintSchedule(specByAirline, selectedNames) {
    var host = $("schedule-body");
    if (!host) return;
    var names = airlinesOnLeg(state.source, state.dest, selectedNames || []);
    var html = [];
    names.forEach(function (airline) {
      html.push("<h5 style='margin-bottom:4px'>" + esc(airline) + "</h5>");
      var spec = specByAirline[airline];
      if (!spec) {
        html.push("<div style='margin-bottom:10px'>No observed time data in local flight history.</div>");
        return;
      }
      var days = {};
      String(spec).split(";").forEach(function (part) {
        var eq = part.indexOf("=");
        if (eq <= 0) return;
        days[part.slice(0, eq)] = part.slice(eq + 1).split(",").filter(Boolean);
      });
      WEEKDAYS.forEach(function (day) {
        var times = days[day] || [];
        html.push("<div>" + day + ": " + esc(times.length ? times.slice(0, 12).join(", ") : "-") + "</div>");
      });
      html.push("<div style='height:8px'></div>");
    });
    host.innerHTML = html.join("");
  }

  function panelAirlines() {
    if (state.showAll) return null;
    if (state.airlines.length) return state.airlines;
    return null;
  }

  function renderPanel(view) {
    var source = state.source;
    var dest = state.dest;
    var direct = !!(state.finder && source && dest && view.network.routes.get(source) && view.network.routes.get(source).has(dest));
    var oneStop = 0;
    var twoStop = 0;
    view.finderPaths.forEach(function (path) {
      if (path.length === 3) oneStop += 1;
      else if (path.length >= 4) twoStop += 1;
    });
    var host = $("route-panel-content");
    if (state.finder && source && !dest) {
      host.innerHTML = "<h4>Route Finder</h4><p class='mono'>Origin " + esc(source) + "</p><p class='muted'>Every city stays on the map. Choose a second city to draw direct and one-stop routes.</p>";
      return;
    }
    if (state.finder && source && dest && !direct) {
      var message;
      if (!oneStop && twoStop) {
        message = "No nonstop or one-stop route. " + (twoStop === 1 ? "1 two-stop itinerary is drawn." : twoStop + " two-stop itineraries are drawn.");
      } else if (!oneStop) {
        message = "No nonstop or one-stop route in the current airline filter.";
      } else if (oneStop === 1) {
        message = "No nonstop in the current airline filter. 1 one-stop itinerary is drawn on the map.";
      } else {
        message = "No nonstop in the current airline filter. " + oneStop + " one-stop itineraries are drawn on the map.";
      }
      host.innerHTML = "<h4 class='mono'>" + esc(source + " → " + dest) + "</h4><p class='muted'>" + esc(message) + "</p>";
      return;
    }
    var selected = panelAirlines();
    host.innerHTML = schedulePanelShell(selected);
    if (!source || !dest || !$("schedule-body")) return;
    var token = ++panelGen;
    var letter = source.charAt(0);
    loadSchedule(letter).then(function (shard) {
      if (token !== panelGen) return;
      if (state.source !== source || state.dest !== dest) return;
      paintSchedule((shard && shard[source + "|" + dest]) || {}, selected);
    }).catch(function () {
      if (token !== panelGen) return;
      var body = $("schedule-body");
      if (body) body.innerHTML = "<p class='muted'>Observed times could not be loaded.</p>";
    });
  }

  function loadSchedule(letter) {
    if (scheduleShards.has(letter)) return Promise.resolve(scheduleShards.get(letter));
    if (!scheduleLoads.has(letter)) {
      scheduleLoads.set(letter, fetch("data/schedule/" + letter + ".json").then(function (res) {
        if (!res.ok) return {};
        return res.json();
      }).then(function (data) {
        scheduleShards.set(letter, data || {});
        return scheduleShards.get(letter);
      }));
    }
    return scheduleLoads.get(letter);
  }

  function renderChips() {
    var host = $("selected-airlines-chips");
    var names = state.airlines;
    var wasOpen = !!(host.querySelector(".airline-picker") && host.querySelector(".airline-picker").open);
    if (!names.length) {
      host.innerHTML = "";
      return;
    }
    var rows = names.map(function (name, index) {
      return "<div class='airline-chip'><span>" + esc(name) + "</span><button type='button' class='chip-x' data-index='" + index + "' title='Remove'>×</button></div>";
    }).join("");
    var label = names.length + " airline" + (names.length === 1 ? "" : "s") + " selected";
    host.innerHTML =
      "<details class='airline-picker'><summary class='airline-summary'><span class='airline-summary-label'>" +
      esc(label) + "</span><button type='button' class='chip-clear' id='clear-airline-chips'>Clear all</button></summary><div class='airline-menu'>" +
      rows + "</div></details>";
    if (wasOpen) host.querySelector(".airline-picker").open = true;
    var clear = $("clear-airline-chips");
    if (clear) {
      clear.addEventListener("mousedown", function (event) {
        event.preventDefault();
        event.stopPropagation();
      });
      clear.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        state.airlines = [];
        render();
      });
    }
    host.querySelectorAll(".chip-x").forEach(function (button) {
      button.addEventListener("click", function () {
        var index = Number(button.getAttribute("data-index"));
        state.airlines = state.airlines.filter(function (_name, i) { return i !== index; });
        render();
      });
    });
  }

  function syncInputs() {
    $("route-tool-from").value = state.source ? captionOf(state.source) : "";
    $("route-tool-to").value = state.dest ? captionOf(state.dest) : "";
    $("from-clear").hidden = !state.source;
    $("to-clear").hidden = !state.dest;
  }

  function renderChrome(view) {
    $("route-finder-toggle").className = state.finder
      ? "look-btn route-finder-btn is-on"
      : "look-btn route-finder-btn";
    $("route-combos-toggle-btn").textContent = state.combos
      ? "Hide route combinations on map"
      : "Show route combinations on map";
    $("show-all-routes").checked = state.showAll;
    $("dock-shell").className = state.dockClosed ? "dock-shell is-closed" : "dock-shell";
    $("dock-toggle").textContent = state.dockClosed ? "Panel" : "Hide";
    ["night", "day", "sat"].forEach(function (name) {
      $("look-" + name).className = state.style === name ? "look-btn is-active" : "look-btn";
    });
    $("tilt-toggle").className = state.globe ? "look-btn is-active" : "look-btn";
    $("tilt-toggle").textContent = state.globe ? "Globe" : "Flat";
    var hud = hudText(view);
    $("map-hud").innerHTML = "<div class='hud-title'>" + esc(hud.title) + "</div><div class='hud-sub'>" + esc(hud.sub) + "</div>";
    var banner = $("two-stop-banner");
    banner.textContent = hud.banner;
    banner.className = hud.banner ? "two-stop-banner" : "two-stop-banner is-hidden";
    $("route-checker-content").innerHTML = checkerHtml(view.network.routes);
    $("route-planner-content").innerHTML = plannerHtml(view.network.routes);
    renderChips();
    syncInputs();
    renderPanel(view);
  }

  function render() {
    var gen = ++renderGen;
    var view = buildView();
    renderChrome(view);
    if (view.meshPromise) {
      var drawing = $("map-hud").querySelector(".hud-sub");
      if (drawing && view.meshStats) {
        drawing.textContent = "Drawing " + view.meshStats[1].toLocaleString("en-US") + " legs…";
      }
      window.airwaysRenderMap(view.payload, null);
      view.meshPromise.then(function (mesh) {
        if (gen !== renderGen) return;
        window.airwaysRenderMap(view.payload, mesh);
        var hud = hudText(view);
        $("map-hud").innerHTML = "<div class='hud-title'>" + esc(hud.title) + "</div><div class='hud-sub'>" + esc(hud.sub) + "</div>";
      });
    } else {
      window.airwaysRenderMap(view.payload, view.mesh);
    }
  }

  function matchRank(text, query) {
    var value = String(text || "").toLowerCase();
    if (value === query) return 0;
    if (value.indexOf(query) === 0) return 1;
    if (value.indexOf(" " + query) !== -1) return 2;
    return 3;
  }

  function airportOptions(query) {
    var q = query.trim().toLowerCase();
    var list = airportList;
    if (q) {
      list = airportList.filter(function (airport) {
        return airport.iata.toLowerCase().indexOf(q) !== -1 || airport.caption.toLowerCase().indexOf(q) !== -1;
      }).sort(function (a, b) {
        return matchRank(a.iata, q) - matchRank(b.iata, q) ||
          matchRank(a.caption, q) - matchRank(b.caption, q) ||
          a.caption.localeCompare(b.caption);
      });
    }
    return list.slice(0, 40).map(function (airport) {
      return { value: airport.iata, label: airport.caption };
    });
  }

  function airlineOptions(query) {
    var q = query.trim().toLowerCase();
    var chosen = {};
    state.airlines.forEach(function (name) { chosen[name] = true; });
    var list = airlineNames.filter(function (name) {
      if (chosen[name]) return false;
      return !q || name.toLowerCase().indexOf(q) !== -1;
    });
    if (q) {
      list = list.sort(function (a, b) {
        return matchRank(a, q) - matchRank(b, q) || a.localeCompare(b);
      });
    }
    return list.slice(0, 40).map(function (name) {
      return { value: name, label: name };
    });
  }

  var closeMenus = [];

  function mountCombo(input, menu, optionsFor, onSelect, restore, selectOnFocus) {
    var items = [];
    var active = -1;
    var fresh = false;

    function close() {
      menu.hidden = true;
      menu.innerHTML = "";
      items = [];
      active = -1;
    }
    closeMenus.push(close);

    function place() {
      var rect = input.getBoundingClientRect();
      menu.style.left = Math.round(rect.left) + "px";
      menu.style.top = Math.round(rect.bottom + 4) + "px";
      menu.style.width = Math.round(rect.width) + "px";
    }

    function paint() {
      menu.innerHTML = "";
      place();
      items.forEach(function (item, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "combo-option" + (index === active ? " is-active" : "");
        button.textContent = item.label;
        button.addEventListener("mousedown", function (event) {
          event.preventDefault();
          onSelect(item.value);
          close();
        });
        menu.appendChild(button);
      });
      menu.hidden = !items.length;
    }

    function refresh() {
      items = optionsFor(fresh ? "" : input.value);
      active = items.length ? 0 : -1;
      paint();
    }

    input.addEventListener("focus", function () {
      fresh = !!selectOnFocus;
      if (selectOnFocus) input.select();
      refresh();
    });
    input.addEventListener("input", function () {
      fresh = false;
      refresh();
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        if (!items.length) refresh();
        active = Math.min(items.length - 1, active + 1);
        paint();
        event.preventDefault();
      } else if (event.key === "ArrowUp") {
        active = Math.max(0, active - 1);
        paint();
        event.preventDefault();
      } else if (event.key === "Enter") {
        if (items[active]) {
          onSelect(items[active].value);
          close();
          event.preventDefault();
        } else if (!input.value.trim()) {
          onSelect(null);
          close();
          event.preventDefault();
        }
      } else if (event.key === "Escape") {
        close();
        input.blur();
      }
    });
    input.addEventListener("blur", function () {
      setTimeout(function () {
        close();
        if (restore && document.activeElement !== input) restore();
      }, 140);
    });
  }

  function addAirline(name) {
    if (!name || state.airlines.indexOf(name) !== -1) return;
    state.airlines = state.airlines.concat([name]);
    $("airline-filter").value = "";
    render();
  }

  function applyPreset(names) {
    state.airlines = named(names);
    state.showAll = false;
    $("airline-filter").value = "";
    render();
  }

  function bindControls() {
    function restoreField(input, current) {
      if (!input.value.trim()) {
        if (input === $("route-tool-from")) applyDropdown(null, state.dest);
        else applyDropdown(state.source, null);
        return;
      }
      input.value = current ? captionOf(current) : "";
    }
    mountCombo($("route-tool-from"), $("from-menu"), airportOptions, function (iata) {
      applyDropdown(iata, state.dest);
    }, function () {
      restoreField($("route-tool-from"), state.source);
    }, true);
    mountCombo($("route-tool-to"), $("to-menu"), airportOptions, function (iata) {
      applyDropdown(state.source, iata);
    }, function () {
      restoreField($("route-tool-to"), state.dest);
    }, true);
    mountCombo($("airline-filter"), $("airline-menu"), airlineOptions, function (name) {
      if (name) addAirline(name);
    }, function () {
      $("airline-filter").value = "";
    }, false);
    $("from-clear").addEventListener("click", function () {
      applyDropdown(null, state.dest);
    });
    $("to-clear").addEventListener("click", function () {
      applyDropdown(state.source, null);
    });
    var dock = document.querySelector(".dock");
    if (dock) {
      dock.addEventListener("scroll", function () {
        closeMenus.forEach(function (close) { close(); });
      });
    }
    window.addEventListener("resize", function () {
      closeMenus.forEach(function (close) { close(); });
    });
    $("show-all-routes").addEventListener("change", function () {
      state.showAll = $("show-all-routes").checked;
      render();
    });
    $("myid-travel-preset-button").addEventListener("click", function () { applyPreset(presets.myid); });
    $("asian-myid-preset-button").addEventListener("click", function () { applyPreset(presets.asianMyid); });
    $("clear-airlines-button").addEventListener("click", function () {
      state.airlines = [];
      render();
    });
    $("route-combos-toggle-btn").addEventListener("click", function () {
      refreshCombos(true);
      render();
    });
    $("route-finder-toggle").addEventListener("click", function () {
      state.finder = !state.finder;
      render();
    });
    $("dock-toggle").addEventListener("click", function () {
      state.dockClosed = !state.dockClosed;
      $("dock-shell").className = state.dockClosed ? "dock-shell is-closed" : "dock-shell";
      $("dock-toggle").textContent = state.dockClosed ? "Panel" : "Hide";
    });
    $("look-night").addEventListener("click", function () { state.style = "night"; render(); });
    $("look-day").addEventListener("click", function () { state.style = "day"; render(); });
    $("look-sat").addEventListener("click", function () { state.style = "sat"; render(); });
    $("tilt-toggle").addEventListener("click", function () {
      state.globe = !state.globe;
      render();
    });
    $("reset-selection-button").addEventListener("click", clearRoute);
    window.airwaysOnMapClick = onMapClick;

    var downX = 0;
    var downY = 0;
    var mapEl = $("world-map");
    mapEl.addEventListener("pointerdown", function (event) {
      downX = event.clientX;
      downY = event.clientY;
    }, true);
    mapEl.addEventListener("contextmenu", function (event) {
      event.preventDefault();
      if (Math.hypot(event.clientX - downX, event.clientY - downY) > 8) return;
      clearRoute();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (event.target && event.target.isContentEditable)) return;
      clearRoute();
    });
  }

  function indexData(airportRows, network, meta) {
    airlineNames = named(network.airlines || []);
    presets.myid = named(meta.myid || []);
    presets.asianMyid = named(meta.asianMyid || []);
    var nameByIndex = network.airlines || [];
    airportRows.forEach(function (row) {
      var mun = row.mun || "?";
      var country = row.country || "?";
      var airport = {
        iata: row.iata,
        lon: row.lon,
        lat: row.lat,
        tier: row.tier,
        name: row.name,
        mun: row.mun,
        country: row.country,
        label: row.label || row.name,
        caption: row.iata + " — " + row.name + ", " + mun + " (" + country + ")"
      };
      airports.set(airport.iata, airport);
      airportList.push(airport);
    });
    airportList.sort(function (a, b) {
      var country = (a.country || "\uffff").localeCompare(b.country || "\uffff");
      if (country) return country;
      var mun = (a.mun || "\uffff").localeCompare(b.mun || "\uffff");
      if (mun) return mun;
      return a.iata.localeCompare(b.iata);
    });
    var links = network.links || {};
    Object.keys(links).forEach(function (src) {
      var dests = links[src];
      var bucket = new Set();
      routesBySource.set(src, bucket);
      Object.keys(dests).forEach(function (dst) {
        bucket.add(dst);
        var names = (dests[dst] || []).map(function (index) { return nameByIndex[index]; }).filter(function (name) {
          return name && String(name).trim();
        });
        legAirlines.set(src + "|" + dst, names);
        names.forEach(function (name) {
          var graph = airlineRoutes.get(name);
          if (!graph) {
            graph = new Map();
            airlineRoutes.set(name, graph);
          }
          var set = graph.get(src);
          if (!set) {
            set = new Set();
            graph.set(src, set);
          }
          set.add(dst);
          var connected = airlineAirports.get(name);
          if (!connected) {
            connected = new Set();
            airlineAirports.set(name, connected);
          }
          connected.add(src);
          connected.add(dst);
        });
      });
    });
  }

  function boot() {
    var bootEl = $("boot");
    if (location.protocol === "file:") {
      bootEl.textContent = "Open this folder through a web server. From the docs folder run: python -m http.server";
      return;
    }
    if (!window.maplibregl) {
      bootEl.textContent = "The map library did not load. Check the network connection and reload.";
      return;
    }
    bindControls();
    Promise.all([
      fetch("data/airports.json").then(function (res) { return res.json(); }),
      fetch("data/network.json").then(function (res) { return res.json(); }),
      fetch("data/meta.json").then(function (res) { return res.json(); })
    ]).then(function (files) {
      indexData(files[0], files[1], files[2]);
      bootEl.classList.add("is-hidden");
      render();
    }).catch(function (err) {
      bootEl.textContent = "Could not load the atlas data. " + err;
    });
  }

  boot();
})();
