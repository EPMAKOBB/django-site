document.querySelectorAll('[data-tutor-formset]').forEach(function (section) {
  const prefix = section.dataset.tutorFormset;
  const total = section.querySelector('[name="' + prefix + '-TOTAL_FORMS"]');
  const maximum = section.querySelector('[name="' + prefix + '-MAX_NUM_FORMS"]');
  const button = section.querySelector('[data-add]');
  button.addEventListener('click', function () {
    const count = Number(total.value);
    if (count >= Number(maximum.value)) return;
    const template = section.querySelector('[data-empty]');
    const wrapper = document.createElement('div');
    wrapper.innerHTML = template.innerHTML.replaceAll('__prefix__', String(count));
    section.querySelector('[data-rows]').append(...wrapper.childNodes);
    total.value = count + 1;
    button.disabled = count + 1 >= Number(maximum.value);
  });
});
