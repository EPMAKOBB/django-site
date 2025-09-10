document.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill');
  if (!btn) return;
  const offer = btn.getAttribute('data-offer');
  alert('Офер: ' + offer + '\nЗдесь можно открыть форму записи и передать код оффера.');
});

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('typewriter');
  if (!el) return;
  const text = el.dataset.text || '';
  const cursor = el.querySelector('.cursor');
  let index = 0;
  let current = '';
  el.textContent = '';
  if (cursor) el.appendChild(cursor);
  const interval = setInterval(() => {
    if (index < text.length) {
      current += text[index++];
      el.textContent = current;
      if (cursor) el.appendChild(cursor);
    } else {
      clearInterval(interval);
      if (cursor) el.appendChild(cursor);
    }
  }, 100);
});

// Scroll reveal animations
document.addEventListener('DOMContentLoaded', () => {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('reveal-visible');
        observer.unobserve(entry.target);
      }
    });
  });

  document.querySelectorAll('.card').forEach((el) => {
    el.classList.add('reveal');
    observer.observe(el);
  });
});

const VARIANT1_CURRENT = 3000;
const VARIANT1_ORIGINAL = 5000;
const VARIANT1_UNIT = '₽/мес';

const VARIANT2_CURRENT = 5000;
const VARIANT2_ORIGINAL = 10000;

function countSubjects() {
  return ['id_subject1', 'id_subject2'].reduce((count, id) => {
    const el = document.getElementById(id);
    const value = el && el.value;
    if (value && value !== '0' && value !== 'none') {
      return count + 1;
    }
    return count;
  }, 0);
}

function updatePrice() {
  const priceOldEl = document.querySelector('.price-old');
  const priceNewEl = document.querySelector('.price-new');
  const priceNoteEl = document.querySelector('.price-note');
  if (!priceOldEl || !priceNewEl || !priceNoteEl) return;

  const format = (n) => n.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');
  const unit = VARIANT1_UNIT;

  const subjects = countSubjects();
  const isVariant2 = subjects >= 2;

  const currentTotal = isVariant2 ? VARIANT2_CURRENT : VARIANT1_CURRENT;
  const originalTotal = isVariant2 ? VARIANT2_ORIGINAL : VARIANT1_ORIGINAL;
  const notePrefix = isVariant2 ? 'за два предмета ' : '';

  priceOldEl.textContent = `${format(originalTotal)} ${unit}`;
  priceNewEl.textContent = `${format(currentTotal)} ${unit}`;
  priceNoteEl.textContent = `${notePrefix}при записи до 30 сентября`;
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
