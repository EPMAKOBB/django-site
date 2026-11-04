/* Apply the preference before first paint. Preserve existing day/night values. */
(function () {
  "use strict";
  let theme;
  try { theme = localStorage.getItem("site-theme"); } catch (_) {}
  if (theme !== "day" && theme !== "night") {
    theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "day" : "night";
  }
  document.documentElement.dataset.theme = theme;
})();
