(function () {
'use strict';
const csrfToken = document.currentScript?.dataset.csrfToken;
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

async function postForm(url, data) {
  const form = new URLSearchParams();
  Object.entries(data || {}).forEach(([k, v]) => form.append(k, v));
  const csrftoken = csrfToken || document.querySelector('[name=csrfmiddlewaretoken]')?.value || getCookie('csrftoken');
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
    const error = (payload && payload.error) || 'Ошибка запроса.';
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
    alert(err && err.message ? err.message : 'Не удалось добавить задачу в вариант.');
  }
});

})();
