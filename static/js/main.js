document.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill');
  if (!btn) return;
  const offer = btn.getAttribute('data-offer');
  alert('Офер: ' + offer + '\nЗдесь можно открыть форму записи и передать код оффера.');
});

function setMode(mode) {
  const input = document.getElementById('id_lesson_type');
  if (!input) return;
  input.value = mode;
  updatePrice();
}

const VARIANT1_CURRENT = 3000;
const VARIANT1_ORIGINAL = 5000;
const VARIANT1_UNIT = '₽/мес';
const VARIANT2_CURRENT = 5000;
const VARIANT2_ORIGINAL = 10000;
const VARIANT2_UNIT = '₽/мес';
const VARIANT3_CURRENT = 2000;
const VARIANT3_ORIGINAL = 2500;
const VARIANT3_UNIT = '₽ за занятие (60 минут)';

function updatePrice() {
  const lessonTypeEl = document.getElementById('id_lesson_type');
  const subject1El = document.getElementById('id_subject1');
  const subject2El = document.getElementById('id_subject2');
  const priceOldEl = document.querySelector('.price-old');
  const priceNewEl = document.querySelector('.price-new');
  const priceNoteEl = document.querySelector('.price-note');
  if (!lessonTypeEl || !subject1El || !subject2El || !priceOldEl || !priceNewEl || !priceNoteEl) return;

  const lessonType = lessonTypeEl.value === 'individual' ? 'individual' : 'group';
  const isSelected = (el) => !!(el && el.value && el.value !== 'none');
  let subjectsCount = 0;
  if (isSelected(subject1El)) subjectsCount += 1;
  if (isSelected(subject2El)) subjectsCount += 1;

  const format = (n) => n.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');
  let currentTotal;
  let originalTotal;
  let unit;

  if (lessonType === 'individual' || subjectsCount === 1) {
    currentTotal = VARIANT2_CURRENT;
    originalTotal = VARIANT2_ORIGINAL;
    unit = VARIANT2_UNIT;
  } else if (subjectsCount === 2) {
    currentTotal = VARIANT3_CURRENT;
    originalTotal = VARIANT3_ORIGINAL;
    unit = VARIANT3_UNIT;
  } else {
    currentTotal = VARIANT1_CURRENT;
    originalTotal = VARIANT1_ORIGINAL;
    unit = VARIANT1_UNIT;
  }

  priceOldEl.textContent = `${format(originalTotal)} ${unit}`;
  priceNewEl.textContent = `${format(currentTotal)} ${unit}`;
  priceNoteEl.textContent = 'при записи до 30 сентября';
}

document.addEventListener('DOMContentLoaded', () => {
  updatePrice();
  ['id_grade', 'id_subject1', 'id_subject2', 'id_lesson_type'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updatePrice);
  });
});

if (typeof module !== 'undefined') {
  module.exports = { updatePrice };
}
