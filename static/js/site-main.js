document.addEventListener('DOMContentLoaded', () => {
  const typewriterEl = document.querySelector('.brand__title--typewriter');
  if (typewriterEl) {
    const textEl = typewriterEl.querySelector('.brand__title-text');
    const sourceText = typewriterEl.dataset.typewriterText;
    if (textEl && sourceText) {
      typewriterEl.classList.add('is-enhanced');
      textEl.textContent = '';
      let index = 0;
      const tick = () => {
        if (index >= sourceText.length) return;
        textEl.textContent += sourceText.charAt(index);
        index += 1;
        window.setTimeout(tick, 85);
      };
      window.setTimeout(tick, 220);
    }
  }
});

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
const VARIANT1_UNIT = 'в‚Ѕ/РјРµСЃ';

const VARIANT2_CURRENT = 5000;
const VARIANT2_ORIGINAL = 10000;

function countSubjects() {
  const subjectCheckboxes = document.querySelectorAll('input[name="subjects"]:checked');
  if (subjectCheckboxes.length) {
    return subjectCheckboxes.length;
  }

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
  const notePrefix = isVariant2 ? 'Р·Р° РґРІР° РїСЂРµРґРјРµС‚Р° ' : '';

  priceOldEl.textContent = `${format(originalTotal)} ${unit}`;
  priceNewEl.textContent = `${format(currentTotal)} ${unit}`;
  priceNoteEl.textContent = `${notePrefix}РїСЂРё Р·Р°РїРёСЃРё РґРѕ 30 СЃРµРЅС‚СЏР±СЂСЏ`;
}

document.addEventListener('DOMContentLoaded', () => {
  updatePrice();
  ['id_grade', 'id_subject1', 'id_subject2'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updatePrice);
  });
  document.querySelectorAll('input[name="subjects"]').forEach((el) => {
    el.addEventListener('change', updatePrice);
  });
});

document.addEventListener('DOMContentLoaded', () => {
  const fieldset = document.querySelector('.teacher-skillset[data-formset-prefix]');
  if (!fieldset) return;

  const prefix = fieldset.dataset.formsetPrefix;
  const container = fieldset.querySelector('[data-formset-container]');
  const addBtn = fieldset.querySelector('[data-formset-add]');
  const template = fieldset.querySelector('[data-formset-empty]');
  const totalFormsInput = fieldset.querySelector(`input[name="${prefix}-TOTAL_FORMS"]`);

  if (!container || !addBtn || !template || !totalFormsInput) return;

  const getForms = () => Array.from(container.querySelectorAll('[data-formset-form]'));

  const getActiveForms = () =>
    getForms().filter((formEl) => !formEl.classList.contains('teacher-skillset__row--hidden'));

  const updateDeleteButtonsState = () => {
    const activeForms = getActiveForms();
    activeForms.forEach((formEl, index) => {
      const btn = formEl.querySelector('[data-formset-delete]');
      if (!btn) return;
      btn.disabled = activeForms.length === 1 && index === 0;
    });
  };

  const hideForm = (formEl) => {
    const deleteInput = formEl.querySelector('input[name$="-DELETE"]');
    if (deleteInput) {
      deleteInput.checked = true;
    }
    formEl.classList.add('teacher-skillset__row--hidden');
    updateDeleteButtonsState();
  };

  const registerForm = (formEl) => {
    const deleteInput = formEl.querySelector('input[name$="-DELETE"]');
    const deleteBtn = formEl.querySelector('[data-formset-delete]');

    if (deleteInput && deleteInput.checked) {
      formEl.classList.add('teacher-skillset__row--hidden');
    }

    if (deleteBtn && deleteInput) {
      deleteBtn.addEventListener('click', () => {
        if (deleteBtn.disabled) return;
        hideForm(formEl);
      });
    }
  };

  getForms().forEach((form) => registerForm(form));
  updateDeleteButtonsState();

  const buildFormElement = (index) => {
    const templateForm = template.content
      ? template.content.firstElementChild
      : template.firstElementChild;
    if (!templateForm) return null;

    const html = templateForm.outerHTML.replace(/__prefix__/g, index);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html.trim();
    const formEl = wrapper.firstElementChild;
    if (!formEl) return null;

    const deleteInput = formEl.querySelector('input[name$="-DELETE"]');
    if (deleteInput) {
      deleteInput.checked = false;
    }

    return formEl;
  };

  addBtn.addEventListener('click', () => {
    const totalForms = parseInt(totalFormsInput.value, 10) || 0;
    const formEl = buildFormElement(totalForms);
    if (!formEl) return;

    container.appendChild(formEl);
    totalFormsInput.value = String(totalForms + 1);
    registerForm(formEl);
    formEl.classList.remove('teacher-skillset__row--hidden');
    updateDeleteButtonsState();
  });
});

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

async function postForm(url, data) {
  const form = new URLSearchParams();
  Object.entries(data || {}).forEach(([k, v]) => form.append(k, v));
  const csrftoken = getCookie('csrftoken');
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
      'X-CSRFToken': csrftoken || '',
      'X-Requested-With': 'XMLHttpRequest',
      Accept: 'application/json'
    },
    body: form.toString()
  });
  let payload = {};
  try {
    payload = await resp.json();
  } catch (err) {
    payload = {};
  }
  if (!resp.ok) {
    const error = (payload && payload.error) || 'РћС€РёР±РєР° Р·Р°РїСЂРѕСЃР°.';
    throw new Error(error);
  }
  return payload;
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-variant-add]');
  if (!btn) return;
  const taskId = btn.getAttribute('data-task-id');
  if (!taskId) return;
  e.preventDefault();
  try {
    const data = await postForm('/accounts/dashboard/variant-basket/add/', { task_id: taskId });
    if (data && data.ok) {
      btn.classList.add('pulse');
      setTimeout(() => btn.classList.remove('pulse'), 600);
      const badge = document.querySelector('.variant-basket-widget__badge');
      if (badge) badge.textContent = String(data.count || '');
      if (!document.querySelector('.variant-basket-widget') && (data.count || 0) > 0) {
        window.location.reload();
      }
    } else if (data && data.error) {
      console.warn('Variant add error:', data.error);
      alert(data.error);
    }
  } catch (err) {
    console.warn('Variant add request failed:', err);
    alert(err && err.message ? err.message : 'РќРµ СѓРґР°Р»РѕСЃСЊ РґРѕР±Р°РІРёС‚СЊ Р·Р°РґР°С‡Сѓ РІ РІР°СЂРёР°РЅС‚.');
  }
});

if (typeof module !== 'undefined') {
  module.exports = { updatePrice };
}
