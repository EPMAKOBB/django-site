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
  updatePrice();
}

const VARIANT1_CURRENT = 3000;
const VARIANT1_ORIGINAL = 5000;
const VARIANT2_CURRENT = 5000;
const VARIANT2_ORIGINAL = 10000;
const VARIANT3_PRICE = 2000;
const VARIANT3_UNIT = '₽ за занятие (60 минут)';
const DEFAULT_UNIT = '₽/мес';

function updatePrice() {
  const lessonTypeEl = document.getElementById('id_lesson_type');
  const subject1El = document.getElementById('id_subject1');
  const subject2El = document.getElementById('id_subject2');
  const priceOldEl = document.querySelector('.price-old');
  const priceNewEl = document.querySelector('.price-new');
  const priceNoteEl = document.querySelector('.price-note');
  if (!lessonTypeEl || !subject1El || !subject2El || !priceNewEl) return;

  const lessonType = lessonTypeEl.value || 'group';
  let subjectsCount = 0;
  if (subject1El.value) subjectsCount += 1;
  if (subject2El.value) subjectsCount += 1;

  const format = (n) => n.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');
  let currentTotal;
  let originalTotal = null;
  let perLesson = false;

  if (lessonType === 'individual') {
    currentTotal = VARIANT2_CURRENT;
    originalTotal = VARIANT2_ORIGINAL;
  } else if (subjectsCount === 0) {
    currentTotal = VARIANT1_CURRENT;
    originalTotal = VARIANT1_ORIGINAL;
  } else if (lessonType === 'group' && subjectsCount === 2) {
    currentTotal = VARIANT3_PRICE;
    perLesson = true;
  } else {
    currentTotal = VARIANT2_CURRENT;
    originalTotal = VARIANT2_ORIGINAL;
  }

  const unit = perLesson ? VARIANT3_UNIT : DEFAULT_UNIT;
  priceNewEl.textContent = `${format(currentTotal)} ${unit}`;
  if (priceOldEl) {
    if (originalTotal) {
      priceOldEl.textContent = `${format(originalTotal)} ${unit}`;
      priceOldEl.style.display = '';
    } else {
      priceOldEl.textContent = '';
      priceOldEl.style.display = 'none';
    }
  }
  if (priceNoteEl) {
    if (originalTotal) {
      priceNoteEl.textContent = 'до 30 сентября';
      priceNoteEl.style.display = '';
    } else {
      priceNoteEl.textContent = '';
      priceNoteEl.style.display = 'none';
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setMode('group');
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
