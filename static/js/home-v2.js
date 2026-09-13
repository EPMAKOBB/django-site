(function () {
  'use strict';
  const root = document.documentElement;
  let saved;
  try { saved = localStorage.getItem('home-v2-theme') || localStorage.getItem('site-theme'); } catch (_) {}
  function apply(theme) {
    root.dataset.theme = theme;
    const dark = theme === 'night';
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
      button.querySelector('.theme-label').textContent = dark ? 'Светлая' : 'Тёмная';
    }
    document.querySelector('meta[name="theme-color"]').content = dark ? '#03080d' : '#f4f7fb';
  }
  apply(saved === 'night' ? 'night' : 'day');
  document.addEventListener('DOMContentLoaded', function () {
    apply(root.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click', function () {
      const next = root.dataset.theme === 'night' ? 'day' : 'night';
      apply(next);
      try { localStorage.setItem('home-v2-theme', next); } catch (_) {}
    });
  });
})();
