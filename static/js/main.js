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
const GROUP_ORIGINAL_PRICE_PER_SUBJECT = 5000;
const GROUP_DISCOUNT_PRICE_PER_SUBJECT = 3000;

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
  if (subjectsCount === 0) subjectsCount = 1;

  let currentPerSubject;
  let originalPerSubject = null;
  if (lessonType === 'group') {
    currentPerSubject = GROUP_DISCOUNT_PRICE_PER_SUBJECT;
    originalPerSubject = GROUP_ORIGINAL_PRICE_PER_SUBJECT;
  } else {
    currentPerSubject = INDIVIDUAL_PRICE_PER_SUBJECT;
  }

  const currentTotal = currentPerSubject * subjectsCount;
  const format = (n) => n.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');

  priceNewEl.textContent = `${format(currentTotal)} ₽/мес`;
  if (priceOldEl) {
    if (originalPerSubject) {
      const originalTotal = originalPerSubject * subjectsCount;
      priceOldEl.textContent = `${format(originalTotal)} ₽/мес`;
    } else {
      priceOldEl.textContent = '';
    }
  }
  if (priceNoteEl) {
    priceNoteEl.textContent = originalPerSubject ? 'до 30 сентября' : '';
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
