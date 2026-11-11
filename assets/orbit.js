(function () {
  var MAX_PITCH = 70;
  var orbiting = false;
  var raf = 0;
  var lastTs = 0;
  var dialDrag = false;

  function maplibre() {
    return window.airwaysMap ? window.airwaysMap() : null;
  }

  function paintDial(bearing, pitch) {
    var needle = document.getElementById("dial-needle");
    if (!needle) return;
    var reach = 0.28 + 0.72 * Math.max(0, Math.min(1, pitch / MAX_PITCH));
    needle.style.transform = "rotate(" + bearing + "deg) scaleY(" + reach + ")";
  }

  function readView() {
    var map = maplibre();
    if (!map) return null;
    return { bearing: map.getBearing(), pitch: map.getPitch() };
  }

  function setOrbit(on) {
    orbiting = !!on;
    var btn = document.getElementById("orbit-toggle");
    if (btn) btn.classList.toggle("is-active", orbiting);
    cancelAnimationFrame(raf);
    if (!orbiting) return;
    lastTs = 0;
    var step = function (ts) {
      if (!orbiting) return;
      var map = maplibre();
      if (map) {
        var dt = lastTs ? Math.min(48, ts - lastTs) : 16;
        lastTs = ts;
        var center = map.getCenter();
        // Shift longitude only, so the globe turns on its polar axis
        // instead of yawing around the selected city.
        var lon = center.lng - dt * 0.012;
        if (lon < -180) lon += 360;
        map.jumpTo({ center: [lon, center.lat] });
        paintDial(map.getBearing(), map.getPitch());
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }

  function applyDial(event) {
    var dial = document.getElementById("heading-dial");
    var map = maplibre();
    if (!dial || !map) return;
    var rect = dial.getBoundingClientRect();
    var dx = event.clientX - (rect.left + rect.width / 2);
    var dy = event.clientY - (rect.top + rect.height / 2);
    var dist = Math.min(1, Math.hypot(dx, dy) / (rect.width * 0.46));
    var bearing = dist < 0.12 ? map.getBearing() : Math.atan2(dx, -dy) * (180 / Math.PI);
    map.jumpTo({ bearing: bearing, pitch: dist * MAX_PITCH });
    paintDial(bearing, dist * MAX_PITCH);
  }

  function bindControls() {
    var dial = document.getElementById("heading-dial");
    var orbitBtn = document.getElementById("orbit-toggle");
    var levelBtn = document.getElementById("north-compass-button");
    if (!dial || dial.dataset.orbitBound === "1") return;
    dial.dataset.orbitBound = "1";

    dial.addEventListener("pointerdown", function (event) {
      dialDrag = true;
      setOrbit(false);
      dial.setPointerCapture(event.pointerId);
      applyDial(event);
      event.preventDefault();
    });
    dial.addEventListener("pointermove", function (event) {
      if (!dialDrag) return;
      applyDial(event);
    });
    dial.addEventListener("pointerup", function () { dialDrag = false; });
    dial.addEventListener("pointercancel", function () { dialDrag = false; });

    if (orbitBtn) {
      orbitBtn.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        setOrbit(!orbiting);
      });
    }
    if (levelBtn) {
      levelBtn.addEventListener("click", function (event) {
        var map = maplibre();
        if (!map) return;
        event.preventDefault();
        event.stopPropagation();
        setOrbit(false);
        map.easeTo({ bearing: 0, pitch: 0, duration: 420 });
        paintDial(0, 0);
      });
    }
  }

  window.addEventListener("keydown", function (event) {
    var target = event.target;
    if (!target) return;
    var tag = target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    var map = maplibre();
    if (!map) return;
    if (event.key === "ArrowLeft") map.easeTo({ bearing: map.getBearing() - 14, duration: 160 });
    else if (event.key === "ArrowRight") map.easeTo({ bearing: map.getBearing() + 14, duration: 160 });
    else if (event.key === "ArrowUp") map.easeTo({ pitch: Math.min(MAX_PITCH, map.getPitch() + 8), duration: 160 });
    else if (event.key === "ArrowDown") map.easeTo({ pitch: Math.max(0, map.getPitch() - 8), duration: 160 });
    else return;
    event.preventDefault();
    setOrbit(false);
  });

  function attach() {
    bindControls();
    var map = maplibre();
    if (!map || dialDrag || orbiting) return;
    if (map.__orbitMoveBound !== "1") {
      map.__orbitMoveBound = "1";
      map.on("move", function () {
        if (dialDrag || orbiting) return;
        paintDial(map.getBearing(), map.getPitch());
      });
    }
    var view = readView();
    if (view) paintDial(view.bearing, view.pitch);
  }

  setInterval(attach, 800);
})();
