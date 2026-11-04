(function () {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  function initialize(root) {
    if (root.dataset.initialized || root.dataset.auth !== '1') return;
    root.dataset.initialized = '1';
    const examId = root.dataset.examId;
    const isTypePage = root.dataset.view === 'type';
    const typeId = Number(root.dataset.typeId);
    const compositionDialog = root.querySelector('#type-training-composition');
    const compositionToggle = root.querySelector('[data-type-composition-toggle]');
    const url = `/api/exams/${examId}/training-draft/`;
    const message = root.querySelector('[data-training-message]');
    let state = null;
    let busy = false;
    let progress = {};
    let works = null;
    let lifecycleRevision = -1;
    let currentTrainingId = null;
    let archivePage = 1, examWorkPage = 1;
    function synchronizeLifecycle(payload, currentId) {
      if (payload.lifecycle_revision >= lifecycleRevision) {
        lifecycleRevision = payload.lifecycle_revision;
        currentTrainingId = currentId;
        root.classList.toggle('has-current-training', !!currentTrainingId);
      }
    }
    function operationId(key) {
      const storage = `training-operation:${examId}:${key}`;
      try {
        let value = sessionStorage.getItem(storage);
        if (!value) { value = crypto.randomUUID(); sessionStorage.setItem(storage, value); }
        return value;
      } catch (_) { return crypto.randomUUID(); }
    }
    const say = (text, error = false) => {
      message.textContent = text;
      message.hidden = !text;
      message.classList.toggle('training-error', error);
    };
    async function json(url, data) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(url, data ? {method:'POST', credentials:'same-origin', signal:controller.signal,
          headers:{'Content-Type':'application/json', 'X-CSRFToken':root.dataset.csrf}, body:JSON.stringify(data)} : {credentials:'same-origin', cache:'no-store', signal:controller.signal});
        const payload = await response.json();
        if (!response.ok) {
          const error = new Error(typeof payload.detail === 'string' ? payload.detail : Object.values(payload).flat().join(' '));
          error.status = response.status;
          throw error;
        }
        return payload;
      } catch(error) {
        if (error.name === 'AbortError') throw new Error('Сервер долго не отвечает. Повторите загрузку.');
        throw error;
      } finally {
        clearTimeout(timeout);
      }
    }
    function setBusy(value) {
      busy = value;
      root.setAttribute('aria-busy', String(value));
      document.querySelectorAll('[data-type-count], [data-training-type] input, [data-training-type] button, [data-training-task], [data-training-remove], [data-training-start], [data-training-clear], [data-training-recommend], [data-type-composition-toggle]').forEach(el => el.disabled = value || !state || !!currentTrainingId);
      const start = root.querySelector('[data-training-start]');
      if (start) start.disabled = value || !state?.count || !!currentTrainingId || state.selections.some(s => !s.available);
    }
    function render() {
      if (!state) return;
      synchronizeLifecycle(state, state.current_attempt_id);
      if (isTypePage) {
        if (currentTrainingId && compositionDialog?.open) compositionDialog.close();
        const current = root.querySelector('[data-type-current]');
        current.hidden = !currentTrainingId;
        current.innerHTML = currentTrainingId ? `<p>У вас есть текущая тренировка.</p><div class="training-builder__actions"><a class="btn btn-primary" href="${escape(state.current_attempt_url || root.dataset.examUrl)}">Продолжить</a><a class="btn btn-secondary" href="${escape(root.dataset.examUrl)}">Управление тренировкой</a></div>` : '';
      }
      root.querySelectorAll('[data-training-count]').forEach(el => el.textContent = state.count);
      const selection = root.querySelector('[data-training-selection]');
      if (selection) selection.innerHTML = state.selections.length ? state.selections.map(s => {
        const type = state.types.find(t => t.id === s.type_id);
        return `<div class="training-selection-row"><div><strong>${escape(s.title)}</strong><small>${escape(type?.name)} · ${escape(s.reason)}${s.available ? '' : ' · Недоступно'}</small></div><button type="button" class="btn btn-secondary" data-training-remove="${s.task_id}" data-type="${s.type_id}" aria-label="Убрать ${escape(s.title)}">Убрать</button></div>`;
      }).join('') : '<p class="muted">Выберите количество по типам, отметьте конкретные задания или используйте рекомендации.</p>';
      document.querySelectorAll('[data-training-type]').forEach(container => {
        const type = state.types.find(t => t.id === Number(container.dataset.trainingType));
        if (!type) return;
        const wasOpen = container.querySelector('details')?.open;
        const counter = `<input type="number" min="0" max="100" value="${type.count}" data-type-count="${type.id}" aria-label="Выбрано задач: ${escape(type.name)}"><span class="muted training-type-count__available" aria-label="Всего доступно задач: ${type.available}">${isTypePage ? 'из' : '/'} ${type.available}</span>`;
        const inlineCounter = document.querySelector(`[data-training-type-count="${type.id}"]`);
        if (inlineCounter) inlineCounter.innerHTML = counter;
        container.hidden = !!inlineCounter && !type.tags.length && type.requested <= type.count;
        const tagRows = type.tags.map(tag => {
          const percent = progress[String(type.id)]?.[String(tag.id)];
          return `<label class="training-tag-row"><span class="training-tag-name">${escape(tag.name)}<small>Доступно ${tag.available}${percent === undefined ? '' : ` · прогресс ${percent}%`}${tag.count < tag.minimum ? ' · Минимум пока не достигнут' : ''}</small></span><span class="training-tag-coverage ${tag.count ? 'is-covered' : ''}"><strong>${tag.count} из ${type.count}</strong><small>в составе</small></span><span class="training-tag-minimum">Не менее <input type="number" min="0" max="${type.count}" value="${tag.minimum}" data-tag-minimum="${tag.id}" data-type="${type.id}" aria-label="Минимум задач: ${escape(tag.name)}"></span></label>`;
        }).join('');
        const tagContents = `<p class="training-tag-help muted">«В составе» — уже выбранные задачи. «Не менее» — условие подбора. Одна задача может покрывать несколько тегов.</p>${tagRows}`;
        container.innerHTML = (inlineCounter ? '' : `<div class="training-type-count training-type-count--inline">${counter}</div>`) +
          (type.requested > type.count ? `<p class="muted">Нашлось ${type.count} из запрошенных ${type.requested}</p>` : '') +
          (type.tags.length ? (inlineCounter ? tagContents : `<details><summary>Темы и теги</summary>${tagContents}</details>`) : '');
        if (wasOpen && container.querySelector('details')) container.querySelector('details').open = true;
        if (isTypePage) {
          const topics = root.querySelector('[data-type-topics]');
          if (topics) topics.hidden = !type.tags.length;
          const shortage = root.querySelector('[data-type-shortage]');
          if (shortage) {
            shortage.hidden = type.requested <= type.count;
            shortage.textContent = type.requested > type.count ? `Доступно ${type.count} из запрошенных ${type.requested} задач.` : '';
          }
        }
      });
      document.querySelectorAll('[data-training-task]').forEach(input => {
        const selected = state.selections.find(s => s.task_id === Number(input.dataset.trainingTask));
        input.checked = !!selected;
        const card = input.closest('[data-training-task-card]');
        card?.classList.toggle('training-task-is-selected', !!selected);
      });
      filterCards();
      setBusy(busy);
    }
    function filterCards() {
      const only = document.querySelector('[data-training-only-selected]')?.checked;
      document.querySelectorAll('[data-training-task-card]').forEach(card => {
        card.hidden = !!only && !card.querySelector('[data-training-task]')?.checked;
      });
      const empty = document.querySelector('[data-type-selected-empty]');
      if (empty) empty.hidden = !only || !!document.querySelector('[data-training-task-card]:not([hidden])');
    }
    async function mutate(data) {
      if (busy || !state) return;
      setBusy(true);
      say('');
      try {
        const extra = data.action === 'start' ? {lifecycle_revision:lifecycleRevision,
          operation_id:operationId(`start:${state.revision}:${lifecycleRevision}`)} : {};
        const payload = await json(url, {...data, revision:state.revision, ...extra});
        if (payload.url) { window.location.assign(payload.url); return; }
        state = payload;
        render();
        const selectedCount = isTypePage ? state.selections.filter(s => s.type_id === typeId).length : state.count;
        say(data.action === 'recommend' && selectedCount < data.count ?
          (isTypePage && state.count >= 100 ? 'В тренировке уже 100 задач. Уберите лишние из состава, чтобы добавить больше задач этого типа.' : 'Новых подходящих задач меньше, чем запрошено. Можно добавить задачи вручную.') : '');
      } catch (error) {
        if (error.status === 409) {
          state = await json(url).catch(() => state);
          await loadWorks().catch(() => {});
        }
        render();
        say(error.message || 'Не удалось сохранить состав. Повторите действие.', true);
      } finally { setBusy(false); }
    }
    function renderWorks() {
      if (isTypePage) return;
      if (!works) return;
      const target = root.querySelector('[data-training-works]');
      const currentTarget = root.querySelector('[data-current-training]');
      synchronizeLifecycle(works, works.current_training?.id || null);
      const row = work => `<div class="training-work-row"><div><strong>${escape(work.name)}</strong><small>${work.mode === 'training' ? `Решено ${work.correct} из ${work.total} · ответов введено ${work.saved}` : `Пробник · ответов ${work.saved} из ${work.total}`} · ${new Date(work.started_at).toLocaleDateString('ru-RU')}</small></div><div class="training-builder__actions">${work.status === 'archived' ? `<a class="btn btn-secondary" href="${escape(work.url)}">Посмотреть</a><button class="btn btn-secondary" data-work-restore="${work.id}">Сделать текущей</button>` : `<a class="btn ${work.status === 'active' ? 'btn-primary' : 'btn-secondary'}" href="${escape(work.url)}">${work.status === 'active' ? 'Продолжить' : 'Результат'}</a>`}${work.status === 'active' && work.mode === 'training' ? `<button class="btn btn-secondary" data-work-archive="${work.id}">В архив</button>` : ''}</div></div>`;
      const pages = (group, name) => group.pages > 1 ? `<nav class="training-archive-pages" aria-label="Страницы ${name === 'archive' ? 'архива' : 'пробников'}"><button class="btn btn-secondary" data-work-page="${group.page - 1}" data-work-group="${name}" ${group.page <= 1 ? 'disabled' : ''}>Назад</button><span>${group.page} из ${group.pages}</span><button class="btn btn-secondary" data-work-page="${group.page + 1}" data-work-group="${name}" ${group.page >= group.pages ? 'disabled' : ''}>Далее</button></nav>` : '';
      const wasOpen = target.querySelector('[data-archive-list]')?.open;
      const examsOpen = target.querySelector('[data-exam-list]')?.open;
      const current = works.current_training;
      currentTarget.innerHTML = current ? `<div class="training-current__row"><p class="training-current__label"><strong>Текущая тренировка</strong><span aria-hidden="true">·</span><span>Решено ${current.correct} из ${current.total}</span></p><div class="training-builder__actions"><a class="btn btn-primary" href="${escape(current.url)}">Продолжить</a><button class="btn btn-secondary" type="button" data-work-archive="${current.id}">В архив</button></div></div>` : '<p class="muted">Соберите тренировку или верните из архива.</p>';
      target.innerHTML = `<details data-archive-list ${wasOpen ? 'open' : ''}><summary>Архив тренировок · ${works.archive.count}</summary>${currentTrainingId && works.archive.count ? '<p class="muted">При возврате выбранной тренировки текущая перейдёт в архив. Все ответы сохранятся.</p>' : ''}${works.archive.results.map(row).join('') || '<p class="muted">В архиве пока нет тренировок.</p>'}${pages(works.archive, 'archive')}</details>` +
        (works.exams.count ? `<details data-exam-list ${examsOpen ? 'open' : ''}><summary>Пробники · ${works.exams.count}</summary>${works.exams.results.map(row).join('')}${pages(works.exams, 'exams')}</details>` : '');
      setBusy(busy);
    }
    async function loadWorks() {
      if (isTypePage) return;
      try {
        const payload = await json(`/api/exams/${examId}/works/?page=${archivePage}&exam_page=${examWorkPage}`);
        if (!payload || !Number.isInteger(payload.lifecycle_revision) ||
            !Object.hasOwn(payload, 'current_training') || !Array.isArray(payload.archive?.results) || !Array.isArray(payload.exams?.results)) {
          throw new Error('Не удалось загрузить список тренировок. Обновите страницу и повторите загрузку.');
        }
        if (payload.lifecycle_revision < lifecycleRevision) {
          if (works) return;
          throw new Error('Состояние тренировок изменилось. Повторите загрузку.');
        }
        works = payload; archivePage = works.archive.page; examWorkPage = works.exams.page;
        renderWorks();
      } catch(error) {
        if (!works) {
          root.querySelector('[data-current-training]').innerHTML = '<p role="alert">Не удалось загрузить текущую тренировку.</p><button type="button" class="btn btn-secondary" data-works-retry>Повторить загрузку</button>';
          root.querySelector('[data-training-works]').innerHTML = '<p class="muted">Архив временно недоступен. Повторите загрузку.</p>';
        }
        throw error;
      }
    }
    root.addEventListener('click', async event => {
      if (event.target.closest('[data-type-composition-toggle]') && compositionDialog) {
        compositionDialog.showModal();
        compositionToggle.setAttribute('aria-expanded', 'true');
        return;
      }
      if (event.target.closest('[data-type-composition-close]') && compositionDialog) {
        compositionDialog.close();
        return;
      }
      const retry = event.target.closest('[data-works-retry]');
      if (retry) {
        retry.disabled = true;
        try { await loadWorks(); say(''); } catch(error) { say(error.message, true); retry.disabled = false; }
        return;
      }
      if (event.target.closest('[data-training-recommend]')) {
        const count = Number(root.querySelector('[data-recommend-count]').value);
        if (!Number.isInteger(count) || count < 1 || count > 100) return say('Укажите количество от 1 до 100.', true);
        mutate({action:'recommend', count, ...(isTypePage ? {type_id:typeId} : {})});
      }
      if (event.target.closest('[data-training-clear]')) mutate({action:'clear'});
      if (event.target.closest('[data-training-start]')) mutate({action:'start'});
      const remove = event.target.closest('[data-training-remove]');
      if (remove) mutate({action:'toggle', task_id:Number(remove.dataset.trainingRemove), type_id:Number(remove.dataset.type), selected:false});
      const pagination = event.target.closest('[data-work-page]');
      if (pagination && !busy) {
        if (pagination.dataset.workGroup === 'archive') archivePage = Number(pagination.dataset.workPage);
        else examWorkPage = Number(pagination.dataset.workPage);
        pagination.disabled = true;
        try { await loadWorks(); } catch(error) { say(error.message, true); pagination.disabled = false; }
      }
      const archive = event.target.closest('[data-work-archive], [data-work-restore]');
      if (archive && !busy) {
        setBusy(true);
        archive.disabled = true;
        try {
          const id = Number(archive.dataset.workArchive || archive.dataset.workRestore);
          const archived = !!archive.dataset.workArchive;
          const result = await json(`/api/variants/attempts/${id}/archive/`, {archived,
            lifecycle_revision:lifecycleRevision, operation_id:operationId(`${id}:${archived}:${lifecycleRevision}`)});
          if (!archived) { window.location.assign(result.url); return; }
          await loadWorks();
          state = await json(url); render();
          say('Тренировка в архиве. Все сохранённые ответы и проверки доступны при возврате.');
          const composition = root.querySelector('.training-composition');
          composition?.setAttribute('open', '');
          (root.querySelector('#training-types') || composition)?.scrollIntoView({behavior:'smooth', block:'start'});
        } catch(error) {
          if (error.status === 409) await loadWorks().catch(() => {});
          say(error.message, true); archive.disabled = false;
        } finally { setBusy(false); }
      }
    });
    document.addEventListener('change', event => {
      const el = event.target;
      if (el.matches('[data-type-count]')) mutate({action:'count', type_id:Number(el.dataset.typeCount), count:Number(el.value)});
      if (el.matches('[data-tag-minimum]')) {
        const typeId = Number(el.dataset.type);
        const type = state.types.find(t => t.id === typeId);
        const minima = Object.fromEntries(type.tags.map(t => [t.id, t.minimum]));
        minima[el.dataset.tagMinimum] = Number(el.value);
        mutate({action:'count', type_id:typeId, count:type.count, tag_minima:minima});
      }
      if (el.matches('[data-training-task]')) mutate({action:'toggle', task_id:Number(el.dataset.trainingTask), type_id:Number(el.dataset.trainingTaskType), selected:el.checked});
      if (el.matches('[data-training-only-selected]')) filterCards();
    });
    if (compositionDialog) {
      compositionDialog.addEventListener('close', () => compositionToggle.setAttribute('aria-expanded', 'false'));
      compositionDialog.addEventListener('click', event => {
        const bounds = compositionDialog.getBoundingClientRect();
        if (event.target === compositionDialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) compositionDialog.close();
      });
    }
    // Each page reads the same server draft; refocusing also reconciles another tab's changes.
    async function reload() {
      if (busy) return;
      try {
        const payload = await json(url);
        if (!state || payload.revision >= state.revision) { state = payload; render(); }
      } catch(error) { say(error.message, true); }
    }
    window.addEventListener('focus', () => { reload(); loadWorks().catch(error => say(error.message, true)); });
    reload();
    loadWorks().catch(error => say(error.message, true));
    const examPage = document.getElementById('exam-page');
    const progressUrl = examPage?.dataset.progressUrl || root.dataset.progressUrl;
    const progressReady = window.examProgressReady || (progressUrl ? json(progressUrl) : Promise.resolve(null));
    progressReady.then(data => { progress = data?.tag_progress || {}; render(); }).catch(() => {});
  }
  const boot = () => {
    const root = document.getElementById('training-builder');
    if (root) { initialize(root); observer.disconnect(); }
  };
  const observer = new MutationObserver(boot);
  observer.observe(document.body, {childList:true, subtree:true});
  boot();
})();
