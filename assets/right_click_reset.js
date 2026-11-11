(function () {
  function attachRightClickReset() {
    var graphRoot = document.getElementById("world-map");
    var resetButton = document.getElementById("reset-selection-button");
    if (!graphRoot || !resetButton) return;
    if (graphRoot.dataset.rightClickResetAttached === "1") return;

    var downX = 0;
    var downY = 0;
    graphRoot.addEventListener("pointerdown", function (event) {
      downX = event.clientX;
      downY = event.clientY;
    }, true);
    graphRoot.addEventListener("contextmenu", function (event) {
      event.preventDefault();
      var moved = Math.hypot(event.clientX - downX, event.clientY - downY);
      if (moved > 8) return;
      resetButton.click();
    });
    graphRoot.dataset.rightClickResetAttached = "1";
  }

  function attachEscapeReset() {
    if (document.body.dataset.escapeResetAttached === "1") return;
    document.body.dataset.escapeResetAttached = "1";
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      var target = event.target;
      var tag = target && target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (target && target.isContentEditable)) return;
      var resetButton = document.getElementById("reset-selection-button");
      if (!resetButton) return;
      resetButton.click();
    });
  }

  setInterval(attachRightClickReset, 1000);
  setInterval(attachEscapeReset, 1000);
})();
