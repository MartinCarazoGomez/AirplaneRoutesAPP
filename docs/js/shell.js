(function () {
  var screens = {
    flights: document.getElementById("screen-flights"),
    explore: document.getElementById("screen-explore"),
    settings: document.getElementById("screen-settings")
  };
  var tabs = document.querySelectorAll(".tabbar .tab");

  function show(name) {
    Object.keys(screens).forEach(function (key) {
      var on = key === name;
      screens[key].classList.toggle("is-active", on);
    });
    tabs.forEach(function (tab) {
      var on = tab.getAttribute("data-tab") === name;
      tab.classList.toggle("is-selected", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    var getter = name === "explore" ? window.airwaysMap : name === "flights" ? window.airwaysHistoryMap : null;
    if (!getter) return;
    requestAnimationFrame(function () {
      var map = getter();
      if (!map) return;
      map.resize();
      map.triggerRepaint();
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      show(tab.getAttribute("data-tab"));
    });
  });
})();
