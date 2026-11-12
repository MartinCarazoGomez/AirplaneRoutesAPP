(function () {
  var EMPTY = { type: "FeatureCollection", features: [] };
  var map = null;
  var pending = null;
  var meshLines = null;
  var popup = null;
  var pinMarkers = [];
  var hoverLines = [];
  var layersReady = false;

  var SATELLITE = {
    version: 8,
    sources: {
      satellite: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ],
        tileSize: 256,
        maxzoom: 18,
        attribution: "Satellite imagery © Esri, Maxar, Earthstar Geographics"
      }
    },
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    layers: [{ id: "satellite", type: "raster", source: "satellite" }]
  };

  function styleFor(name) {
    if (name === "day") {
      return "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
    }
    if (name === "sat") return SATELLITE;
    return "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
  }

  function noUpdate() {
    if (window.dash_clientside) return window.dash_clientside.no_update;
    return null;
  }

  function airportsGeo(rows) {
    var features = [];
    var list = rows || [];
    for (var i = 0; i < list.length; i++) {
      var row = list[i];
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [row[0], row[1]] },
        properties: { iata: row[2], k: row[3], label: row[4] || row[2] }
      });
    }
    return { type: "FeatureCollection", features: features };
  }

  var BAND_COLOR = {
    0: [0.984, 0.749, 0.141, 0.96],
    1: [0.490, 0.827, 0.988, 0.96],
    2: [0.176, 0.831, 0.749, 0.96],
    3: [0.847, 0.706, 0.996, 0.96],
    8: [0.910, 0.475, 0.976, 1],
    9: [0.882, 0.114, 0.282, 1],
    10: [0.984, 0.443, 0.522, 1],
    11: [0.933, 0.275, 0.400, 1]
  };
  var MESH_COLOR = [0.729, 0.902, 0.992, 0.42];
  var cpuVerts = null;

  function mercatorOf(lon, lat) {
    var mc = window.maplibregl.MercatorCoordinate.fromLngLat({ lng: lon, lat: lat });
    return [mc.x, mc.y];
  }

  function pushVertex(out, px, py, pz, ox, oy, oz, side, forward, width, color) {
    out.push(px, py, pz, ox, oy, oz, side, forward, width, color[0], color[1], color[2], color[3]);
  }

  function pushSegment(out, a, b, width, color) {
    pushVertex(out, a[0], a[1], a[2], b[0], b[1], b[2], -1, 1, width, color);
    pushVertex(out, a[0], a[1], a[2], b[0], b[1], b[2], 1, 1, width, color);
    pushVertex(out, b[0], b[1], b[2], a[0], a[1], a[2], -1, -1, width, color);
    pushVertex(out, a[0], a[1], a[2], b[0], b[1], b[2], 1, 1, width, color);
    pushVertex(out, b[0], b[1], b[2], a[0], a[1], a[2], -1, -1, width, color);
    pushVertex(out, b[0], b[1], b[2], a[0], a[1], a[2], 1, -1, width, color);
  }

  function appendLine(out, coords, color, width) {
    if (!coords || coords.length < 2) return;
    var prev = null;
    for (var i = 0; i < coords.length; i++) {
      var c = coords[i];
      var m = mercatorOf(c[0], c[1]);
      var here = [m[0], m[1], c.length > 2 ? c[2] : 0];
      if (prev) pushSegment(out, prev, here, width, color);
      prev = here;
    }
  }

  function buildArcVerts(routes, mesh) {
    var out = [];
    var lines = mesh || [];
    for (var i = 0; i < lines.length; i++) appendLine(out, lines[i], MESH_COLOR, 1.15);
    var rows = routes || [];
    for (var r = 0; r < rows.length; r++) {
      var band = rows[r][0];
      var color = BAND_COLOR[band] || BAND_COLOR[1];
      var width = band === 8 ? 4.4 : band === 9 || band === 10 || band === 11 ? 3.6 : 2.5;
      appendLine(out, rows[r][1], color, width);
    }
    return out;
  }

  function compileShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      window.__arcShaderError = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  var arcLayer = {
    id: "route-arcs",
    type: "custom",
    renderingMode: "3d",
    program: null,
    programKey: "",
    buffer: null,
    count: 0,
    onAdd: function (m, gl) {
      this.gl = gl;
      this.program = null;
      this.programKey = "";
      if (this.buffer) {
        gl.deleteBuffer(this.buffer);
        this.buffer = null;
      }
      if (cpuVerts && cpuVerts.length) this.upload(gl);
    },
    onRemove: function () {
      var gl = this.gl;
      if (!gl) return;
      if (this.buffer) gl.deleteBuffer(this.buffer);
      if (this.program) gl.deleteProgram(this.program);
      this.buffer = null;
      this.program = null;
    },
    upload: function (gl) {
      if (!this.buffer) this.buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(cpuVerts), gl.DYNAMIC_DRAW);
      this.count = cpuVerts.length / 13;
    },
    setData: function (routes, mesh) {
      cpuVerts = buildArcVerts(routes, mesh);
      if (this.gl) this.upload(this.gl);
      if (map) map.triggerRepaint();
    },
    shaderFor: function (gl, shaderData) {
      var key = shaderData.variantName || "";
      if (this.program && this.programKey === key) return this.program;
      var vsSource = "#version 300 es\n" + shaderData.vertexShaderPrelude + "\n" + shaderData.define + "\n" +
        "precision highp float;\n" +
        "in vec3 a_pos;\n" +
        "in vec3 a_other;\n" +
        "in float a_side;\n" +
        "in float a_forward;\n" +
        "in float a_width;\n" +
        "in vec4 a_color;\n" +
        "uniform vec2 u_viewport;\n" +
        "uniform float u_world_shift;\n" +
        "out vec4 v_color;\n" +
        "#ifndef GLOBE\n" +
        "uniform highp vec4 u_projection_tile_mercator_coords;\n" +
        "float airwaysCosLat(float tileY) {\n" +
        "  float mercatorY = u_projection_tile_mercator_coords.y + u_projection_tile_mercator_coords.w * tileY;\n" +
        "  float lat = 2.0 * atan(exp(3.14159265 - mercatorY * 6.2831853)) - 1.5707963;\n" +
        "  return max(cos(lat), 0.05);\n" +
        "}\n" +
        "#endif\n" +
        "void main() {\n" +
        "  vec2 pos = vec2(a_pos.x + u_world_shift, a_pos.y);\n" +
        "  vec2 other = vec2(a_other.x + u_world_shift, a_other.y);\n" +
        "  float elev = a_pos.z;\n" +
        "  float elevOther = a_other.z;\n" +
        "#ifndef GLOBE\n" +
        "  elev = a_pos.z / (40075016.68557849 * airwaysCosLat(pos.y));\n" +
        "  elevOther = a_other.z / (40075016.68557849 * airwaysCosLat(other.y));\n" +
        "#endif\n" +
        "  vec4 clip = projectTileFor3D(pos, elev);\n" +
        "  vec4 clipOther = projectTileFor3D(other, elevOther);\n" +
        "  if (clip.w <= 0.0) { gl_Position = vec4(0.0, 0.0, 2.0, 1.0); v_color = a_color; return; }\n" +
        "  vec2 here = clip.xy / clip.w;\n" +
        "  vec2 there = clipOther.xy / max(clipOther.w, 1e-4);\n" +
        "  vec2 dir = there - here;\n" +
        "  if (a_forward < 0.0) dir = -dir;\n" +
        "  float len2 = dot(dir, dir);\n" +
        "  vec2 normal = len2 > 1e-12 ? vec2(-dir.y, dir.x) * inversesqrt(len2) : vec2(0.0, 1.0);\n" +
        "  vec2 ndc = here + normal * a_side * a_width * vec2(2.0 / u_viewport.x, 2.0 / u_viewport.y);\n" +
        "  gl_Position = vec4(ndc * clip.w, clip.z, clip.w);\n" +
        "  v_color = a_color;\n" +
        "}\n";
      var fsSource = "#version 300 es\nprecision highp float;\nin vec4 v_color;\nout vec4 fragColor;\nvoid main() {\n  fragColor = v_color;\n}\n";
      var vs = compileShader(gl, gl.VERTEX_SHADER, vsSource);
      var fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSource);
      if (!vs || !fs) return null;
      var program = gl.createProgram();
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.linkProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        window.__arcShaderError = gl.getProgramInfoLog(program);
        gl.deleteProgram(program);
        return null;
      }
      if (this.program) gl.deleteProgram(this.program);
      this.program = program;
      this.programKey = key;
      this.loc = {
        pos: gl.getAttribLocation(program, "a_pos"),
        other: gl.getAttribLocation(program, "a_other"),
        side: gl.getAttribLocation(program, "a_side"),
        forward: gl.getAttribLocation(program, "a_forward"),
        width: gl.getAttribLocation(program, "a_width"),
        color: gl.getAttribLocation(program, "a_color"),
        viewport: gl.getUniformLocation(program, "u_viewport"),
        shift: gl.getUniformLocation(program, "u_world_shift"),
        fallback: gl.getUniformLocation(program, "u_projection_fallback_matrix"),
        matrix: gl.getUniformLocation(program, "u_projection_matrix"),
        tile: gl.getUniformLocation(program, "u_projection_tile_mercator_coords"),
        clip: gl.getUniformLocation(program, "u_projection_clipping_plane"),
        transition: gl.getUniformLocation(program, "u_projection_transition")
      };
      return program;
    },
    render: function (gl, args) {
      try {
      if (!this.count || !args || !args.shaderData || !args.defaultProjectionData) return;
      var program = this.shaderFor(gl, args.shaderData);
      if (!program) return;
      var proj = args.defaultProjectionData;
      var loc = this.loc;
      gl.useProgram(program);
      gl.uniformMatrix4fv(loc.fallback, false, proj.fallbackMatrix);
      gl.uniformMatrix4fv(loc.matrix, false, proj.mainMatrix);
      gl.uniform4fv(loc.tile, proj.tileMercatorCoords);
      gl.uniform4fv(loc.clip, proj.clippingPlane);
      gl.uniform1f(loc.transition, proj.projectionTransition);
      var canvas = map.getCanvas();
      gl.uniform2f(loc.viewport, canvas.width, canvas.height);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      var stride = 13 * 4;
      function attrib(location, size, offset) {
        if (location < 0) return;
        gl.enableVertexAttribArray(location);
        gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride, offset);
      }
      attrib(loc.pos, 3, 0);
      attrib(loc.other, 3, 12);
      attrib(loc.side, 1, 24);
      attrib(loc.forward, 1, 28);
      attrib(loc.width, 1, 32);
      attrib(loc.color, 4, 36);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.enable(gl.DEPTH_TEST);
      gl.depthMask(false);
      var shifts = visibleWorldShifts();
      for (var s = 0; s < shifts.length; s++) {
        if (loc.shift) gl.uniform1f(loc.shift, shifts[s]);
        gl.drawArrays(gl.TRIANGLES, 0, this.count);
      }
      gl.depthMask(true);
      } catch (err) {
        window.__arcErr = String(err);
      }
    }
  };

  function addLayers() {
    if (!map || map.getSource("airports")) return;
    if (!map.getLayer("route-arcs")) map.addLayer(arcLayer);
    var labelFont = ["Open Sans Regular"];
    var styleLayers = (map.getStyle() && map.getStyle().layers) || [];
    for (var li = 0; li < styleLayers.length; li++) {
      var existingFont = styleLayers[li].layout && styleLayers[li].layout["text-font"];
      if (existingFont && existingFont.length) {
        labelFont = existingFont;
        break;
      }
    }
    map.addSource("layover-names", { type: "geojson", data: EMPTY });
    map.addSource("airports", { type: "geojson", data: EMPTY });
    map.addLayer({
      id: "airports",
      type: "circle",
      source: "airports",
      paint: {
        "circle-color": [
          "match", ["get", "k"],
          0, "#1e40af",
          1, "#7dd3fc",
          2, "#fb923c",
          3, "#fb7185",
          4, "#ef4444",
          5, "#f8fafc",
          6, "#f0abfc",
          "#ef4444"
        ],
        "circle-radius": ["match", ["get", "k"], 0, 6.4, 1, 4.8, 2, 3.6, 3, 2.7, 4, 2.0, 5, 7, 6, 5.5, 2.0],
        "circle-stroke-width": ["match", ["get", "k"], 0, 1.6, 5, 2.5, 1],
        "circle-stroke-color": ["match", ["get", "k"], 0, "#bfdbfe", 5, "#fbbf24", "rgba(5,8,15,0.75)"],
        "circle-pitch-alignment": "viewport"
      }
    });
    map.addLayer({
      id: "layover-names",
      type: "symbol",
      source: "layover-names",
      layout: {
        "text-field": ["get", "iata"],
        "text-font": labelFont,
        "text-size": 12,
        "text-letter-spacing": 0.06,
        "text-offset": [0, 0.85],
        "text-anchor": "top",
        "text-max-width": 8,
        "text-allow-overlap": true,
        "text-ignore-placement": true
      },
      paint: {
        "text-color": "#f8fafc",
        "text-halo-color": "#0c1424",
        "text-halo-width": 1.25
      }
    });
    if (map.__airportsBound) return;
    map.__airportsBound = true;
    map.on("click", "airports", function (event) {
      var feature = event.features && event.features[0];
      if (!feature || featureBehindGlobe(feature) || !window.dash_clientside || !window.dash_clientside.set_props) return;
      window.dash_clientside.set_props("map-click", {
        data: { iata: feature.properties.iata, t: Date.now() }
      });
    });
    map.on("mouseenter", "airports", function () {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("click", "layover-names", function (event) {
      var feature = event.features && event.features[0];
      var iata = feature && feature.properties && feature.properties.iata;
      if (!iata || featureBehindGlobe(feature) || !window.dash_clientside || !window.dash_clientside.set_props) return;
      window.dash_clientside.set_props("map-click", {
        data: { iata: iata, t: Date.now() }
      });
    });
    map.on("mouseenter", "layover-names", function () {
      map.getCanvas().style.cursor = "pointer";
    });
  }

  function legHtml(meta) {
    var airlines = (meta && meta.airlines) || [];
    var shown = airlines.slice(0, 8).map(escapeHtml);
    var extra = airlines.length - shown.length;
    var names = shown.length ? shown.join(", ") : "No airline listed";
    if (extra > 0) names += " (+" + extra + " more)";
    return (
      "<div class='tip-leg'><div class='tip-route'>" +
      escapeHtml(meta.from) + " → " + escapeHtml(meta.to) +
      "</div><div class='tip-air'>" + names + "</div></div>"
    );
  }

  function indexHoverRoutes(routes) {
    hoverLines = [];
    var rows = routes || [];
    for (var i = 0; i < rows.length; i++) {
      var meta = rows[i][2];
      var coords = rows[i][1];
      if (!meta || !coords || coords.length < 2) continue;
      hoverLines.push({ meta: meta, coords: coords });
    }
  }

  function distToSegment(px, py, ax, ay, bx, by) {
    var dx = bx - ax;
    var dy = by - ay;
    var len2 = dx * dx + dy * dy;
    var t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
    if (t < 0) t = 0;
    else if (t > 1) t = 1;
    var x = ax + t * dx;
    var y = ay + t * dy;
    var ox = px - x;
    var oy = py - y;
    return ox * ox + oy * oy;
  }

  function alignLng(lng, target) {
    var x = lng;
    while (x - target > 180) x -= 360;
    while (x - target < -180) x += 360;
    return x;
  }

  function visibleWorldShifts() {
    if (!map || !map.transform || !map.getRenderWorldCopies || !map.getRenderWorldCopies()) return [0];
    var projection = map.getProjection && map.getProjection();
    if (projection && projection.type === "globe") return [0];
    var transform = map.transform;
    var worldSize = transform.worldSize;
    var width = transform.width;
    if (!worldSize || !width) return [0];
    var centerX = (transform.center.lng + 180) / 360;
    var half = width / worldSize * 0.5;
    var minK = Math.ceil(centerX - half - 1.5 - 1e-6);
    var maxK = Math.floor(centerX + half + 0.5 + 1e-6);
    if (maxK - minK > 8) {
      var mid = Math.round(centerX);
      minK = mid - 4;
      maxK = mid + 4;
    }
    var shifts = [];
    for (var k = minK; k <= maxK; k++) shifts.push(k);
    return shifts.length ? shifts : [0];
  }

  function isBehindGlobe(lng, lat) {
    if (!map || !map.transform || typeof map.transform.isLocationOccluded !== "function") return false;
    var projection = map.getProjection && map.getProjection();
    if (projection && projection.type !== "globe") return false;
    var wrapped = ((lng % 360) + 540) % 360 - 180;
    return map.transform.isLocationOccluded({ lng: wrapped, lat: lat });
  }

  function featureBehindGlobe(feature) {
    var coords = feature && feature.geometry && feature.geometry.coordinates;
    if (!coords) return false;
    return isBehindGlobe(coords[0], coords[1]);
  }

  function projectSample(sample, lonShift) {
    if (isBehindGlobe(sample[0], sample[1])) return null;
    var projected = map.project([sample[0] + (lonShift || 0), sample[1]]);
    var height = sample[2] || 0;
    if (!height || !map.getPitch() || !map.transform) return projected;
    var radiusPx = map.transform.worldSize / (2 * Math.PI);
    var pitch = map.getPitch() * Math.PI / 180;
    var gx = map.transform.centerPoint.x;
    var gy = map.transform.centerPoint.y + Math.sin(pitch) * radiusPx;
    var scale = height / 6371008.8;
    return {
      x: projected.x + (projected.x - gx) * scale,
      y: projected.y + (projected.y - gy) * scale
    };
  }

  function lineShifts(firstLon) {
    if (!map.getRenderWorldCopies || !map.getRenderWorldCopies()) return [0];
    var base = alignLng(firstLon, map.getCenter().lng) - firstLon;
    return [base - 360, base, base + 360];
  }

  function nearestRoute(point) {
    var best = null;
    var bestDist = 22 * 22;
    for (var i = 0; i < hoverLines.length; i++) {
      var line = hoverLines[i];
      var coords = line.coords;
      if (!coords.length) continue;
      var shifts = lineShifts(coords[0][0]);
      for (var s = 0; s < shifts.length; s++) {
        var shift = shifts[s];
        var prev = null;
        var stride = coords.length > 28 ? 2 : 1;
        for (var c = 0; c < coords.length; c += stride) {
          var projected = projectSample(coords[c], shift);
          if (!projected) {
            prev = null;
            continue;
          }
          if (prev) {
            var dist = distToSegment(point.x, point.y, prev.x, prev.y, projected.x, projected.y);
            if (dist < bestDist) {
              bestDist = dist;
              best = line.meta;
            }
          }
          prev = projected;
        }
        var last = coords[coords.length - 1];
        if (stride > 1 && last && prev && (prev.lng === undefined)) {
          var end = projectSample(last, shift);
          if (end && (end.x !== prev.x || end.y !== prev.y)) {
            var tail = distToSegment(point.x, point.y, prev.x, prev.y, end.x, end.y);
            if (tail < bestDist) {
              bestDist = tail;
              best = line.meta;
            }
          }
        }
      }
    }
    return best;
  }

  function onMapMove(event) {
    if (!popup || !map || !map.getLayer("airports")) return;
    var airports = [];
    try {
      airports = map.queryRenderedFeatures(event.point, { layers: ["airports"] });
    } catch (err) {
      airports = [];
    }
    airports = airports.filter(function (feature) { return !featureBehindGlobe(feature); });
    if (airports.length) {
      var feature = airports[0];
      var iata = feature.properties.iata;
      var layover = pending && pending.layovers && pending.layovers[iata];
      var city = String(feature.properties.label || "").split("<br>").map(escapeHtml).join("<br>");
      var html = layover
        ? "<div class='tip-city'>" + city + "</div>" + layover.legs.map(legHtml).join("")
        : city;
      var at = feature.geometry.coordinates;
      var tipLng = at[0];
      if (event.lngLat && map.getRenderWorldCopies && map.getRenderWorldCopies()) tipLng = alignLng(tipLng, event.lngLat.lng);
      popup.setLngLat([tipLng, at[1]]).setHTML(html).addTo(map);
      map.getCanvas().style.cursor = "pointer";
      return;
    }
    var route = nearestRoute(event.point);
    if (route) {
      popup.setLngLat(event.lngLat).setHTML(legHtml(route)).addTo(map);
      map.getCanvas().style.cursor = "pointer";
      return;
    }
    map.getCanvas().style.cursor = "";
    popup.remove();
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  function syncPins(pins) {
    pinMarkers.forEach(function (marker) { marker.remove(); });
    pinMarkers = [];
    if (!map || !window.maplibregl) return;
    var surface = map.getCanvasContainer && map.getCanvasContainer();
    if (surface) surface.style.pointerEvents = "";
    (pins || []).forEach(function (pin) {
      if (pin.ring === false) return;
      var el = document.createElement("div");
      var roleClass = pin.role === "dest" ? " is-dest" : pin.role === "layover" ? " is-layover" : "";
      el.className = "route-pin" + roleClass;
      el.style.pointerEvents = "none";
      var marker = new window.maplibregl.Marker({
        element: el,
        anchor: "center",
        opacityWhenCovered: "0"
      })
        .setLngLat([pin.lon, pin.lat])
        .addTo(map);
      marker._airwaysLng = pin.lon;
      marker._airwaysLat = pin.lat;
      pinMarkers.push(marker);
    });
    settlePins();
  }

  function settlePins() {
    if (!map || !pinMarkers.length || !map.getRenderWorldCopies || !map.getRenderWorldCopies()) return;
    var center = map.getCenter().lng;
    for (var i = 0; i < pinMarkers.length; i++) {
      var marker = pinMarkers[i];
      if (marker._airwaysLng == null) continue;
      var lng = alignLng(marker._airwaysLng, center);
      if (Math.abs(marker.getLngLat().lng - lng) > 0.01) marker.setLngLat([lng, marker._airwaysLat]);
    }
  }

  function syncLayoverNames(pins) {
    var source = map.getSource("layover-names");
    if (!source) return;
    var features = [];
    (pins || []).forEach(function (pin) {
      if (!pin.iata) return;
      if (pin.role !== "origin" && pin.role !== "dest" && pin.role !== "layover") return;
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [pin.lon, pin.lat] },
        properties: { iata: pin.iata, role: pin.role }
      });
    });
    source.setData({ type: "FeatureCollection", features: features });
    if (!map.getLayer("layover-names")) return;
    var day = pending && pending.style === "day";
    map.setPaintProperty("layover-names", "text-color", [
      "match", ["get", "role"],
      "dest", day ? "#86198f" : "#f5d0fe",
      "layover", day ? "#9a3412" : "#fde68a",
      day ? "#0f172a" : "#f8fafc"
    ]);
    map.setPaintProperty("layover-names", "text-halo-color", day ? "#fff7ed" : "#0c1424");
  }

  function pushData() {
    if (!map || !layersReady || !pending) return;
    var airports = map.getSource("airports");
    if (airports) airports.setData(airportsGeo(pending.airports));
    arcLayer.setData(pending.routes, meshLines);
    indexHoverRoutes(pending.routes);
    syncPins(pending.pins);
    syncLayoverNames(pending.pins);
  }

  function moveCamera() {
    if (!map || !pending) return;
    if (pending.token === map.__token) return;
    if (pending.holdCamera || !pending.focus) {
      map.__token = pending.token;
      return;
    }
    map.__token = pending.token;
    map.easeTo({
      center: [pending.focus.lon, pending.focus.lat],
      zoom: pending.focus.zoom,
      bearing: 0,
      pitch: pending.focus.pitch || 0,
      duration: map.__moved ? 650 : 0
    });
    map.__moved = true;
  }

  function applyProjection(globe) {
    if (map.setProjection) map.setProjection({ type: globe ? "globe" : "mercator" });
    if (map.setRenderWorldCopies) map.setRenderWorldCopies(!globe);
  }

  function apply() {
    if (!map || !pending) return;
    var styleKey = pending.style || "night";
    var globe = !!pending.globe;
    if (map.__styleKey !== styleKey) {
      map.__styleKey = styleKey;
      map.__globe = globe;
      layersReady = false;
      map.setStyle(styleFor(styleKey));
      map.once("style.load", function () {
        if (map.__styleKey !== styleKey) return;
        applyProjection(globe);
        addLayers();
        layersReady = true;
        pushData();
        moveCamera();
      });
      return;
    }
    if (map.__globe !== globe) {
      map.__globe = globe;
      applyProjection(globe);
    }
    if (!layersReady) return;
    pushData();
    moveCamera();
  }

  function ensure() {
    var el = document.getElementById("world-map");
    if (!el || !window.maplibregl || map) return;
    popup = new window.maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 10,
      locationOccludedOpacity: 0
    });
    map = new window.maplibregl.Map({
      container: el,
      style: styleFor("night"),
      center: [10, 16],
      zoom: 1.25,
      bearing: 0,
      pitch: 0,
      attributionControl: false,
      fadeDuration: 0,
      maxPitch: 70
    });
    map.__styleKey = "night";
    map.__globe = true;
    map.dragRotate.enable();
    map.touchZoomRotate.enable();
    window.airwaysMap = function () { return map; };
    map.on("mousemove", onMapMove);
    map.on("move", settlePins);
    map.on("mouseout", function () {
      if (popup) popup.remove();
    });
    map.on("load", function () {
      applyProjection(true);
      addLayers();
      layersReady = true;
      apply();
    });
  }

  window.airwaysRenderMap = function (payload, mesh) {
    if (mesh !== undefined) meshLines = mesh || null;
    if (payload) pending = payload;
    ensure();
    apply();
    return noUpdate();
  };

  setInterval(ensure, 400);
})();
