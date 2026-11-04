(function () {
  "use strict";

  function initTheme() {
    const root = document.documentElement;
    const system = window.matchMedia("(prefers-color-scheme: light)");
    let explicitChoice = false;
    try { explicitChoice = ["day", "night"].includes(localStorage.getItem("site-theme")); } catch (_) {}
    function applyTheme(theme) {
      root.dataset.theme = theme;
      document.body.dataset.theme = theme;
      const light = theme === "day";
      const label = light ? "Тёмная тема" : "Светлая тема";
      document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
        button.setAttribute("aria-label", "Переключить на " + label.toLowerCase());
        button.setAttribute("aria-pressed", String(light));
        button.title = label;
        button.querySelector(".theme-toggle__label").textContent = label;
        button.querySelector("svg").innerHTML = light
          ? '<path d="M20.5 13.2A8.5 8.5 0 0 1 10.8 3.5a8.5 8.5 0 1 0 9.7 9.7Z"/>'
          : '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>';
      });
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = light ? "#f1f5fa" : "#080e16";
    }
    applyTheme(root.dataset.theme || (system.matches ? "day" : "night"));
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        const theme = root.dataset.theme === "day" ? "night" : "day";
        explicitChoice = true;
        try { localStorage.setItem("site-theme", theme); } catch (_) {}
        applyTheme(theme);
      });
    });
    system.addEventListener("change", function (event) {
      if (!explicitChoice) applyTheme(event.matches ? "day" : "night");
    });
    window.addEventListener("storage", function (event) {
      if (event.key === "site-theme") {
        explicitChoice = ["day", "night"].includes(event.newValue);
        applyTheme(explicitChoice ? event.newValue : (system.matches ? "day" : "night"));
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTheme, { once: true });
  } else {
    initTheme();
  }
})();
