/* No saved choice: follow the device. The only explicit choices are light and dark. */
(function () {
  "use strict";
  var KEY = "hv-theme", root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  function stored() {
    try { var v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : null; }
    catch (e) { return null; }
  }
  function effective() { return stored() || (media.matches ? "dark" : "light"); }
  function apply() {
    var selected = stored();
    if (selected) root.setAttribute("data-theme", selected); else root.removeAttribute("data-theme");
  }
  function save(mode) { try { localStorage.setItem(KEY, mode); } catch (e) { /* private mode */ } apply(); }
  apply();
  document.addEventListener("DOMContentLoaded", function () {
    var cycle = document.getElementById("theme-cycle"), buttons = document.querySelectorAll("[data-theme-set]");
    function paint() {
      var mode = effective();
      if (cycle) {
        cycle.textContent = mode === "dark" ? "\u263e" : "\u2600";
        cycle.title = "Switch to " + (mode === "dark" ? "light" : "dark") + " theme";
        cycle.setAttribute("aria-label", cycle.title);
      }
      buttons.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-theme-set") === mode ? "true" : "false"); });
    }
    function set(mode) { save(mode); paint(); }
    if (cycle) cycle.addEventListener("click", function () { set(effective() === "dark" ? "light" : "dark"); });
    buttons.forEach(function (b) { b.addEventListener("click", function () { set(b.getAttribute("data-theme-set")); }); });
    if (media.addEventListener) media.addEventListener("change", paint);
    else if (media.addListener) media.addListener(paint);
    paint();
  });
})();
