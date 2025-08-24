document.addEventListener('DOMContentLoaded', () => {
    const body = document.body;
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    const icon = toggle.querySelector('.icon');
    const fallback = toggle.querySelector('.fallback');
    const navbar = document.querySelector('nav.navbar');
    const hero = document.getElementById('hero-block');

    let theme = localStorage.getItem('theme') || 'dark';
    applyTheme(theme);

    toggle.addEventListener('click', () => {
        theme = theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', theme);
        applyTheme(theme);
    });

    function applyTheme(current) {
        const isDark = current === 'dark';
        body.classList.toggle('theme-dark', isDark);
        body.classList.toggle('theme-light', !isDark);
        if (navbar) {
            navbar.classList.toggle('navbar-dark', isDark);
            navbar.classList.toggle('bg-dark', isDark);
            navbar.classList.toggle('navbar-light', !isDark);
            navbar.classList.toggle('bg-light', !isDark);
        }
        if (hero) {
            hero.classList.toggle('bg-dark', isDark);
            hero.classList.toggle('bg-light', !isDark);
        }
        if (isDark) {
            icon.textContent = '🌞';
            fallback.textContent = 'дневная';
        } else {
            icon.textContent = '🌙';
            fallback.textContent = 'ночная';
        }
    }
});
