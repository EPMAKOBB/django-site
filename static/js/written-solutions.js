(function () {
  'use strict';
  document.querySelectorAll('[data-photo-input]').forEach(input => {
    input.addEventListener('change', () => {
      if (!input.files.length) return;
      const form = input.form;
      const files = [...input.files];
      const status = form.querySelector('[data-upload-status]');
      if (files.some(file => file.size > 10 * 1024 * 1024)) {
        status.textContent = 'Фото больше 10 МБ. Выберите файл меньшего размера.';
        input.value = ''; return;
      }
      const data = new FormData();
      data.set('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
      data.set('action', 'upload');
      files.forEach(file => data.append('photos', file));
      form.querySelectorAll('input,button').forEach(item => item.disabled = true);
      status.textContent = 'Загружаем фото… Не закрывайте страницу.';
      fetch(location.href, {method:'POST', body:data, credentials:'same-origin', redirect:'follow'})
        .then(async response => {
          const html = await response.text();
          const doc = new DOMParser().parseFromString(html, 'text/html');
          const error = doc.querySelector('.solution-error');
          if (!response.ok || error) throw new Error(error?.textContent || 'Загрузка не выполнена. Обновите страницу или получите новую ссылку.');
          const currentPhotos = document.getElementById('solution-photos');
          const nextPhotos = doc.getElementById('solution-photos');
          if (currentPhotos && nextPhotos) {
            currentPhotos.innerHTML = nextPhotos.innerHTML;
            status.textContent = 'Фото сохранены.';
            form.querySelectorAll('input,button').forEach(item => item.disabled = false);
            input.value = '';
          } else location.reload();
        }).catch(error => {
          status.textContent = error.message;
          form.querySelectorAll('input,button').forEach(item => item.disabled = false);
          input.value = '';
        });
    });
  });
  const photos = document.getElementById('solution-photos');
  if (photos && document.querySelector('.solution-upload')) {
    setInterval(async () => {
      if (document.hidden || document.querySelector('.solution-file:disabled')) return;
      try {
        const response = await fetch(photos.dataset.statusUrl, {credentials:'same-origin'});
        if (!response.ok) return;
        const data = await response.json();
        const known = [...photos.querySelectorAll('[data-photo-id]')].map(item => Number(item.dataset.photoId));
        if (data.submitted) { location.reload(); return; }
        if (JSON.stringify(data.photos) !== JSON.stringify(known)) {
          const page = await fetch(location.href, {credentials:'same-origin'});
          if (!page.ok) return;
          const doc = new DOMParser().parseFromString(await page.text(), 'text/html');
          const nextPhotos = doc.getElementById('solution-photos');
          if (nextPhotos) photos.innerHTML = nextPhotos.innerHTML;
        }
      } catch (_) { /* Retry on the next polling cycle. */ }
    }, 5000);
  }
})();
