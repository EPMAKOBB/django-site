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
