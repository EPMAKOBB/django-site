document.addEventListener('DOMContentLoaded', () => {
  // TEMP THEME PREVIEW: remove after design review
  const storageKey = 'theme-preview';
  const body = document.body;
  const select = document.getElementById('theme-preview-select');
  if (!body || !select) return;

  const supportedThemes = new Set(['classic', 'graphite', 'copper', 'daylight']);

  const applyTheme = (theme) => {
    const safeTheme = supportedThemes.has(theme) ? theme : 'classic';
    body.dataset.themePreview = safeTheme;
    select.value = safeTheme;
  };

  const storedTheme = window.localStorage.getItem(storageKey);
  applyTheme(storedTheme || 'classic');

  select.addEventListener('change', () => {
    const nextTheme = select.value;
    window.localStorage.setItem(storageKey, nextTheme);
    applyTheme(nextTheme);
  });
});
