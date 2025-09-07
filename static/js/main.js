document.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill');
  if (!btn) return;
  const offer = btn.getAttribute('data-offer');
  alert('Офер: ' + offer + '\nЗдесь можно открыть форму записи и передать код оффера.');
});

document.addEventListener('DOMContentLoaded', () => {
  const seg = document.querySelector('.seg[role="tablist"]');
  const input = document.getElementById('id_lesson_type');
  if (!seg || !input) return;
  seg.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-mode]');
    if (!btn) return;
    const mode = btn.getAttribute('data-mode');
    input.value = mode;
    seg.querySelectorAll('button[data-mode]').forEach((b) => {
      const active = b === btn;
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  });
});
