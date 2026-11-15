(function () {
  var PEOPLE = [
    { id: "martin", name: "Martin", tint: "#0c4a6e" },
    { id: "mati", name: "Mati", tint: "#134e4a" },
    { id: "cristina", name: "Cristina", tint: "#4c1d95" },
    { id: "elena", name: "Elena", tint: "#831843" },
    { id: "elias", name: "Elias", tint: "#78350f" },
    { id: "martinillo", name: "Martinillo", tint: "#1e3a8a" }
  ];
  var KEY = "airways-profile";

  function $(id) { return document.getElementById(id); }

  function personById(id) {
    for (var i = 0; i < PEOPLE.length; i++) {
      if (PEOPLE[i].id === id) return PEOPLE[i];
    }
    return null;
  }

  function emptyPerson() {
    return { photo: "", born: "", about: "", firstLogin: "", loginNoted: false };
  }

  function load() {
    var data = { active: "", people: {} };
    try {
      var raw = localStorage.getItem(KEY);
      var parsed = raw ? JSON.parse(raw) : null;
      if (parsed && typeof parsed === "object") data = parsed;
    } catch (err) {
      data = { active: "", people: {} };
    }
    if (!data.people || typeof data.people !== "object") data.people = {};
    if (!personById(data.active)) data.active = "";
    return data;
  }

  function save(data) {
    try {
      localStorage.setItem(KEY, JSON.stringify(data));
      return true;
    } catch (err) {
      return false;
    }
  }

  function todayISO() {
    var d = new Date();
    var month = String(d.getMonth() + 1);
    var day = String(d.getDate());
    if (month.length < 2) month = "0" + month;
    if (day.length < 2) day = "0" + day;
    return d.getFullYear() + "-" + month + "-" + day;
  }

  function record(data, id) {
    if (!data.people[id]) data.people[id] = emptyPerson();
    var person = data.people[id];
    if (!person.loginNoted) {
      person.firstLogin = person.firstLogin || todayISO();
      person.loginNoted = true;
    }
    return person;
  }

  function paintAvatar(button, img, letter, person, profile) {
    button.style.background = profile.tint;
    letter.textContent = profile.name.charAt(0);
    if (person.photo) {
      img.src = person.photo;
      button.classList.add("has-photo");
    } else {
      img.removeAttribute("src");
      button.classList.remove("has-photo");
    }
  }

  function formatPretty(iso) {
    var parts = String(iso || "").split("-");
    if (parts.length !== 3) return iso || "";
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var month = months[Number(parts[1]) - 1];
    var day = Number(parts[2]);
    if (!month || !day) return iso;
    return day + " " + month + " " + parts[0];
  }

  function paintSettings() {
    var data = load();
    var profile = personById(data.active);
    var person = profile ? record(data, profile.id) : emptyPerson();
    if (profile) save(data);
    $("profile-title").textContent = profile ? profile.name : "Settings";
    $("profile-name").textContent = profile ? profile.name : "Choose a profile";
    $("profile-first").textContent = person.firstLogin
      ? "First login " + formatPretty(person.firstLogin)
      : "First login can stay empty.";
    paintAvatar($("profile-photo"), $("profile-photo-img"), $("profile-photo-letter"), person, profile || { name: "?", tint: "#0c4a6e" });
    $("profile-clear-photo").hidden = !person.photo;
    if (document.activeElement !== $("profile-born")) $("profile-born").value = person.born || "";
    if (document.activeElement !== $("profile-login")) $("profile-login").value = person.firstLogin || "";
    if (document.activeElement !== $("profile-about")) $("profile-about").value = person.about || "";
    var enabled = !!profile;
    $("profile-born").disabled = !enabled;
    $("profile-login").disabled = !enabled;
    $("profile-about").disabled = !enabled;
    $("profile-photo").disabled = !enabled;
    $("profile-change-photo").disabled = !enabled;
  }

  function updateActive(mutate) {
    var data = load();
    if (!personById(data.active)) return;
    var person = record(data, data.active);
    mutate(person);
    if (!save(data)) {
      $("profile-photo-note").hidden = false;
      $("profile-photo-note").textContent = "This device could not store that change.";
      return;
    }
    $("profile-photo-note").hidden = true;
    paintSettings();
  }

  function choose(id) {
    if (!personById(id)) return;
    var data = load();
    record(data, id);
    data.active = id;
    save(data);
    closeGate();
    paintSettings();
  }

  function setAppBlocked(blocked) {
    var nodes = document.querySelectorAll(".screen, .tabbar");
    for (var i = 0; i < nodes.length; i++) {
      if (blocked) nodes[i].setAttribute("inert", "");
      else nodes[i].removeAttribute("inert");
    }
  }

  function renderGate(switching) {
    var data = load();
    var list = $("who-list");
    list.innerHTML = "";
    PEOPLE.forEach(function (profile) {
      var person = data.people[profile.id] || emptyPerson();
      var button = document.createElement("button");
      button.type = "button";
      button.className = "who-person" + (data.active === profile.id ? " is-current" : "");
      var badge = document.createElement("span");
      badge.className = "who-letter";
      badge.style.background = profile.tint;
      if (person.photo) {
        var img = document.createElement("img");
        img.alt = "";
        img.src = person.photo;
        badge.appendChild(img);
      } else {
        badge.textContent = profile.name.charAt(0);
      }
      var label = document.createElement("span");
      label.textContent = profile.name;
      button.appendChild(badge);
      button.appendChild(label);
      button.addEventListener("click", function () { choose(profile.id); });
      list.appendChild(button);
    });
    $("who-title").textContent = switching ? "Switch person" : "Who are you?";
    $("who-lead").textContent = switching
      ? "Each profile keeps its own photo, dates, and note on this device."
      : "Pick your profile. This phone or computer will remember it next time.";
    $("who-cancel").hidden = !switching;
    $("who-gate").hidden = false;
    setAppBlocked(true);
  }

  function closeGate() {
    $("who-gate").hidden = true;
    setAppBlocked(false);
  }

  function openPhotoPicker() {
    if (!personById(load().active)) return;
    $("profile-file").click();
  }

  function storePhoto(file) {
    if (!file || file.type.indexOf("image/") !== 0) return;
    var url = URL.createObjectURL(file);
    var image = new Image();
    image.onload = function () {
      var size = 256;
      var canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      var side = Math.min(image.width, image.height);
      var sx = (image.width - side) / 2;
      var sy = (image.height - side) / 2;
      canvas.getContext("2d").drawImage(image, sx, sy, side, side, 0, 0, size, size);
      URL.revokeObjectURL(url);
      updateActive(function (person) { person.photo = canvas.toDataURL("image/jpeg", 0.82); });
    };
    image.onerror = function () {
      URL.revokeObjectURL(url);
      $("profile-photo-note").hidden = false;
      $("profile-photo-note").textContent = "That picture could not be opened.";
    };
    image.src = url;
  }

  $("profile-photo").addEventListener("click", openPhotoPicker);
  $("profile-change-photo").addEventListener("click", openPhotoPicker);
  $("profile-clear-photo").addEventListener("click", function () {
    updateActive(function (person) { person.photo = ""; });
  });
  $("profile-file").addEventListener("change", function () {
    var file = $("profile-file").files && $("profile-file").files[0];
    $("profile-file").value = "";
    if (file) storePhoto(file);
  });
  $("profile-born").addEventListener("change", function () {
    var value = $("profile-born").value;
    updateActive(function (person) { person.born = value; });
  });
  $("profile-login").addEventListener("change", function () {
    var value = $("profile-login").value;
    updateActive(function (person) {
      person.firstLogin = value;
      person.loginNoted = true;
    });
  });
  $("profile-about").addEventListener("input", function () {
    var value = $("profile-about").value;
    updateActive(function (person) { person.about = value; });
  });
  $("profile-switch").addEventListener("click", function () { renderGate(true); });
  $("who-cancel").addEventListener("click", closeGate);

  if (load().active) {
    paintSettings();
  } else {
    paintSettings();
    renderGate(false);
  }
})();
