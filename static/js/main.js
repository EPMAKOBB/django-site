document.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill');
  if (!btn) return;
  const offer = btn.getAttribute('data-offer');
  alert('Офер: ' + offer + '\nЗдесь можно открыть форму записи и передать код оффера.');
});

function setMode(mode) {
  const individualBtn = document.getElementById('mode-individual');
  const groupBtn = document.getElementById('mode-group');
  const input = document.getElementById('id_lesson_type');
  if (!individualBtn || !groupBtn || !input) return;

  if (mode === 'individual') {
    individualBtn.classList.add('active');
    individualBtn.setAttribute('aria-selected', 'true');
    groupBtn.classList.remove('active');
    groupBtn.setAttribute('aria-selected', 'false');
  } else {
    groupBtn.classList.add('active');
    groupBtn.setAttribute('aria-selected', 'true');
    individualBtn.classList.remove('active');
    individualBtn.setAttribute('aria-selected', 'false');
  }

  input.value = mode;
}

const INDIVIDUAL_PRICE_PER_SUBJECT = 4000;
const INDIVIDUAL_ORIGINAL_PRICE_PER_SUBJECT = 5000;
const INDIVIDUAL_DISCOUNT_PRICE_PER_SUBJECT = 2500;
const GROUP_ORIGINAL_PRICE_PER_SUBJECT = 5000;
const GROUP_DISCOUNT_PRICE_PER_SUBJECT = 3000;
const GROUP_TWO_SUBJECTS_PRICE = 2000;

function updatePrice() {
  const lessonTypeEl = document.getElementById('id_lesson_type');
  const subject1El = document.getElementById('id_subject1');
  const subject2El = document.getElementById('id_subject2');
  const priceOldEl = document.querySelector('.price-old');
  const priceNewEl = document.querySelector('.price-new');
  const priceNoteEl = document.querySelector('.price-note');
  if (!lessonTypeEl || !subject1El || !subject2El || !priceNewEl) return;

  const lessonType = lessonTypeEl.value;
  let subjectsCount = 0;
  if (subject1El.value) subjectsCount += 1;
  if (subject2El.value) subjectsCount += 1;

  if (!lessonType || subjectsCount === 0) {
    priceNewEl.textContent = '';
    if (priceOldEl) priceOldEl.textContent = '';
    if (priceNoteEl) priceNoteEl.textContent = '';
    return;
  }

  const format = (n) => n.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');
  let currentTotal;
  let originalTotal = null;
  let unit = '₽/мес';

  if (lessonType === 'individual') {
    if (subjectsCount === 2) {
      currentTotal = INDIVIDUAL_DISCOUNT_PRICE_PER_SUBJECT * subjectsCount;
      originalTotal = INDIVIDUAL_ORIGINAL_PRICE_PER_SUBJECT * subjectsCount;
    } else {
      currentTotal = INDIVIDUAL_PRICE_PER_SUBJECT * subjectsCount;
    }
  } else if (lessonType === 'group') {
    if (subjectsCount === 2) {
      currentTotal = GROUP_TWO_SUBJECTS_PRICE;
      unit = '₽ за занятие';
    } else {
      currentTotal = GROUP_DISCOUNT_PRICE_PER_SUBJECT * subjectsCount;
      originalTotal = GROUP_ORIGINAL_PRICE_PER_SUBJECT * subjectsCount;
    }
  }

  priceNewEl.textContent = `${format(currentTotal)} ${unit}`;
  if (priceOldEl) {
    priceOldEl.textContent = originalTotal ? `${format(originalTotal)} ₽/мес` : '';
  }
  if (priceNoteEl) {
    priceNoteEl.textContent = originalTotal ? 'до 30 сентября' : '';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setMode('group');
  updatePrice();
  ['id_grade', 'id_subject1', 'id_subject2', 'id_lesson_type'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', updatePrice);
    }
  });
});

if (typeof module !== 'undefined') {
  module.exports = { updatePrice };
}
