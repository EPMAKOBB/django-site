document.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill');
  if (!btn) return;
  const offer = btn.getAttribute('data-offer');
  alert('Офер: ' + offer + '\nЗдесь можно открыть форму записи и передать код оффера.');
});

const VARIANT1_CURRENT = 3000;
const VARIANT1_ORIGINAL = 5000;
const VARIANT1_UNIT = '₽/мес';

function updatePrice() {
  const priceOldEl = document.querySelector('.price-old');
  const priceNewEl = document.querySelector('.price-new');
  const priceNoteEl = document.querySelector('.price-note');
  if (!priceOldEl || !priceNewEl) return;

  const format = (n) => n.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');
  const currentTotal = VARIANT1_CURRENT;
  const originalTotal = VARIANT1_ORIGINAL;
  const unit = VARIANT1_UNIT;

  priceOldEl.textContent = `${format(originalTotal)} ${unit}`;
  priceNewEl.textContent = `${format(currentTotal)} ${unit}`;
  priceNoteEl.textContent = 'при записи до 30 сентября';
}

document.addEventListener('DOMContentLoaded', () => {
  updatePrice();
  ['id_grade', 'id_subject1', 'id_subject2'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updatePrice);
  });
});

if (typeof module !== 'undefined') {
  module.exports = { updatePrice };
}
