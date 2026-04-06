(function () {
  "use strict";

  function initTheme() {
    const body = document.body;
    const button = document.getElementById("theme-toggle");
    const storageKey = "site-theme";
    if (!body) return;

    const applyTheme = function (theme) {
      if (theme === "day") {
        body.setAttribute("data-theme", "day");
      } else {
        body.removeAttribute("data-theme");
      }
    };

    const savedTheme = window.localStorage.getItem(storageKey);
    if (savedTheme === "day" || savedTheme === "night") {
      applyTheme(savedTheme);
    }

    if (!button) return;

    button.addEventListener("click", function () {
      const nextTheme = body.getAttribute("data-theme") === "day" ? "night" : "day";
      applyTheme(nextTheme);
      window.localStorage.setItem(storageKey, nextTheme);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTheme, { once: true });
  } else {
    initTheme();
  }
})();
