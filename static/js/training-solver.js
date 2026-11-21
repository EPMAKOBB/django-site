(function () {
  'use strict';
  const root = document.querySelector('.solver');
  if (!root) return;
  const attemptId = root.dataset.attemptId;
  const base = `/api/variants/attempts/${attemptId}/`;
  const examUrl = root.dataset.examUrl;
  const storageKey = `training-answers:${root.dataset.userId}:${attemptId}`;
  const byId = id => document.getElementById(id);
  const body = byId('solver-task-body');
  const list = byId('solver-task-list');
  const footer = root.querySelector('.solver__footer');
  const answer = byId('solver-answer');
  const fields = byId('solver-answer-fields');
  const builder = byId('solver-answer-builder');
  const attachments = byId('solver-attachments');
  const status = root.querySelector('.solver__status-right');
  const checkButton = byId('training-check');
  const navToggle = byId('training-nav-toggle');
  const feedback = byId('training-feedback');
  const notice = byId('training-notice');
  const pending = new Map();
  const pendingBases = new Map();
  const stateBanner = byId('training-state');
  const archiveButton = byId('training-archive');
  let needsRecovery = false;
  let lifecycleRevision = 0;
  let currentTrainingUrl = null;
  let refreshPromise;
  const readOnly = () => !!work?.archived_at || !!work?.completed_at;
  const blocked = () => readOnly() || needsRecovery;
  let work, currentId, flushPromise, saveTimer;
  let actionBusy = false;
  const submissionKeys = new Map();
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const format = value => typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—');
  let backgroundNotice = false;
  const say = (text, error = false) => {
    backgroundNotice = false;
    notice.hidden = !text || !error;
    notice.textContent = error ? text : '';
    status.textContent = error ? '' : text;
    status.dataset.kind = 'info';
  };
  const backgroundError = error => {
    // Do not replace an answer-saving or other user-action error.
    if (!notice.hidden && !backgroundNotice) return;
    say(error.message, true);
    backgroundNotice = true;
  };
  const backgroundRecovered = () => {
    if (backgroundNotice) say('');
  };
  const current = () => work?.tasks_progress.find(t => t.variant_task_id === currentId);
  const latest = task => task.attempts?.at(-1);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const responseOf = task => pending.has(task.variant_task_id) ? pending.get(task.variant_task_id) : task.saved_response;
  const isBlank = value => value == null || value === '' || (Array.isArray(value) && value.every(isBlank));
  function taskState(task) {
    if (task.assessment_source === 'self') return {label:`Самооценка: ${task.assessed_score} из ${task.max_score}`, className:'is-saved', solved:false};
    if (task.solution_submitted) return {label:'Ожидает оценки по критериям', className:'is-saved', solved:false};
    const response = responseOf(task), last = latest(task);
    if (isBlank(response)) return {label:'Без ответа', className:'', solved:false};
    if (!last || !same(last.task_snapshot?.response?.value, response)) return {label:'Не проверено', className:'is-saved', solved:false};
    if (last.score == null) return {label:'Нужна ручная проверка', className:'is-saved', solved:false};
    if (last.is_correct) return {label:'Решено', className:'is-correct', solved:true};
    if (last.score > 0) return {label:'Частично верно', className:'is-partial', solved:false};
    return {label:'Нужно исправить', className:'is-wrong', solved:false};
  }
  async function focusTask() {
    if (currentId && work && !blocked() && !document.hidden) {
      try { await request(`${base}tasks/${currentId}/focus/`, {}); } catch(error) { backgroundError(error); }
    }
  }
  async function request(url, data) {
    const method = data === undefined ? 'GET' : 'POST';
    let response, payload;
    try {
      response = await fetch(url, data === undefined ? {credentials:'same-origin', headers:{Accept:'application/json'}} : {
        method, credentials:'same-origin', headers:{Accept:'application/json', 'Content-Type':'application/json', 'X-CSRFToken':root.dataset.csrf, 'X-Training-Revision':String(work?.training_revision ?? 0)}, body:JSON.stringify(data),
      });
      const contentType = response.headers.get('Content-Type') || '';
      if (!/\bapplication\/(?:[\w.-]+\+)?json\b/i.test(contentType)) throw new Error('unexpected-content-type');
      payload = await response.json();
    } catch (cause) {
      // Keep answers, CSRF tokens and HTML response bodies out of diagnostics.
      console.error('[training] Request failed', {
        timestamp:new Date().toISOString(), attemptId, method,
        path:new URL(url, window.location.href).pathname,
        status:response?.status ?? null,
        contentType:response?.headers.get('Content-Type') ?? null,
        redirected:response?.redirected ?? false,
        responsePath:response ? new URL(response.url || url, window.location.href).pathname : null,
        reason:response ? 'invalid-json-response' : 'network-error',
      });
      const message = response?.status === 401 || response?.status === 403 || (response?.redirected && response.ok)
        ? 'Не удалось подтвердить доступ. Обновите страницу; возможно, потребуется войти заново.'
        : 'Не удалось связаться с сервером или получить корректный ответ. Повторите попытку через некоторое время.';
      const error = new Error(message);
      error.status = response?.status;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(typeof payload?.detail === 'string' ? payload.detail : Object.values(payload || {}).flat().join(' ') || 'Не удалось выполнить запрос. Повторите попытку.');
      error.status = response.status;
      if (response.status === 409) {
        clearTimeout(saveTimer);
        needsRecovery = pending.size > 0;
        store();
        setTimeout(() => refreshState().catch(() => {}), 0);
      }
      throw error;
    }
    return payload;
  }
  function store() {
    try {
      if (pending.size) localStorage.setItem(storageKey, JSON.stringify({version:2, entries:[...pending].map(([id, value]) => [id, value, pendingBases.get(id)])}));
      else localStorage.removeItem(storageKey);
    } catch (_) { /* Server saves continue when browser storage is unavailable. */ }
  }
  function collect() {
    const task = current();
    if (task?.answer_schema && window.FractalTaskResponse) return window.FractalTaskResponse.collectPayload(fields, task.answer_schema);
    const raw = answer.value;
    try { return JSON.parse(raw); } catch (_) { return raw; }
  }
  function remember() {
    const task = current();
    if (!task || task.solution_url || blocked() || actionBusy) return;
    const value = collect();
    if (same(value, responseOf(task)) || (isBlank(value) && isBlank(responseOf(task)))) return;
    if (!pending.has(task.variant_task_id)) pendingBases.set(task.variant_task_id, task.saved_response);
    pending.set(task.variant_task_id, value);
    store();
    say('Сохраняем ответ…');
    renderList();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => flush().catch(error => say(`Ответ сохранён в браузере. ${error.message} Повторите сохранение.`, true)), 600);
  }
  async function flush() {
    clearTimeout(saveTimer);
    if (blocked()) { if (pending.size) throw new Error('Неотправленные ответы сохранены в браузере.'); return; }
    if (flushPromise) return flushPromise;
    flushPromise = (async () => {
      while (pending.size && !blocked()) {
        const [taskId, value] = pending.entries().next().value;
        const payload = await request(`${base}tasks/${taskId}/save/`, {answer:value, expected_answer:pendingBases.get(taskId) ?? null});
        work = payload;
        if (same(pending.get(taskId), value)) { pending.delete(taskId); pendingBases.delete(taskId); }
        else pendingBases.set(taskId, value);
        store();
        renderList();
      }
      say('Сохранено');
    })();
    try { await flushPromise; } finally { flushPromise = null; }
  }
  function renderList() {
    list.innerHTML = work.tasks_progress.map(task => {
      const {label, className:stateClass} = taskState(task);
      return `<li class="solver__task-item"><button type="button" class="solver__task-button ${stateClass} ${task.variant_task_id === currentId ? 'is-active' : ''}" data-task="${task.variant_task_id}" title="${esc(task.task_type_name)} · ${label}" aria-label="Задание ${task.order}: ${label}" ${task.variant_task_id === currentId ? 'aria-current="step"' : ''}>${task.order}</button></li>`;
    }).join('');
    list.querySelectorAll('[data-task]').forEach(button => button.addEventListener('click', () => select(Number(button.dataset.task))));
    const count = work.tasks_progress.length;
    const solved = work.tasks_progress.filter(task => taskState(task).solved).length;
    byId('training-progress').textContent = `Решено ${solved} из ${count}`;
    root.classList.toggle('training-many-tasks', count > 20);
    navToggle.hidden = count <= 20;
    const expanded = root.classList.contains('training-nav-expanded');
    navToggle.textContent = expanded ? 'Скрыть задания' : `Все задания · ${count}`;
    navToggle.setAttribute('aria-expanded', String(expanded));
  }
  function renderTask() {
    const task = current();
    if (!task) return;
    const response = responseOf(task);
    byId('solver-task-meta-value').textContent = `Задание ${task.order} из ${work.tasks_progress.length}${task.task_type_name ? ` · ${task.task_type_name}` : ''}`;
    body.innerHTML = task.task_body_html || '<p>Условие недоступно.</p>';
    body.dataset.format = task.task_rendering_strategy || 'html';
    body.classList.toggle('markdown-content', task.task_rendering_strategy === 'markdown');
    delete body.dataset.mathRendered;
    if (task.image && !body.querySelector('img')) {
      const img = document.createElement('img'); img.src = task.image; img.alt = 'Условие задания'; img.style.maxWidth = '100%'; body.appendChild(img);
    }
    if (task.solution_url) {
      const panel = document.createElement('p');
      const link = document.createElement('a'); link.className = 'btn btn-primary';
      link.href = task.solution_url; link.textContent = 'Фото решения и самооценка';
      panel.appendChild(link); body.appendChild(panel);
      const state = document.createElement('p'); state.textContent = taskState(task).label; body.appendChild(state);
    }
    window.renderMathBlocks?.();
    attachments.hidden = !task.attachments?.length;
    attachments.innerHTML = (task.attachments || []).map(file => `<a href="${esc(file.url)}" target="_blank" rel="noopener">${esc(file.name || file.label || 'Скачать файл')}</a>`).join(' · ');
    footer.hidden = false;
    if (task.answer_schema && window.FractalTaskResponse) {
      builder.hidden = false; answer.hidden = true;
      window.FractalTaskResponse.buildInputs(fields, task.answer_schema, response, {gridClassName:'answer-grid', rowClassName:'answer-row', cellClassName:'answer-cell', inputClassName:'answer-input', autoAdvance:true, pasteFill:true});
      const inputs = fields.querySelectorAll('input, textarea');
      inputs.forEach(input => input.setAttribute('aria-label', inputs.length === 1 ? 'Ответ' : `Ответ, строка ${Number(input.dataset.row) + 1}, столбец ${Number(input.dataset.col) + 1}`));
    } else {
      builder.hidden = true; fields.innerHTML = ''; answer.hidden = false;
      answer.value = response == null ? '' : format(response);
    }
    const config = task.answer_schema?.config || {};
    const rows = Number(config.rows || 1), cols = Number(config.cols || 1);
    footer.classList.toggle('training-response--large', rows > 2 || rows * cols > 6);
    footer.style.setProperty('--training-answer-cols', Math.min(cols, 6));
    footer.querySelectorAll('input, textarea').forEach(input => input.disabled = !!blocked() || actionBusy);
    checkButton.hidden = !!blocked();
    checkButton.disabled = actionBusy || blocked();
    // A correct answer is already present in the input; do not repeat the same fields.
    byId('solver-correct-answer').closest('.solver__correct-answer').hidden = true;
    const last = latest(task);
    const checked = last && same(last.task_snapshot?.response?.value, response);
    feedback.hidden = !checked;
    feedback.textContent = checked ? (last.score == null ? 'Ответ сохранён · нужна ручная проверка' : `${last.is_correct ? 'Верно' : last.score > 0 ? 'Частично верно' : 'Пока неверно'} · ${last.score} из ${last.max_score}`) : '';
    feedback.dataset.kind = checked && last.is_correct ? 'success' : 'info';
    footer.hidden = !!task.solution_url;
    const index = work.tasks_progress.findIndex(t => t.variant_task_id === currentId);
    byId('solver-prev').disabled = index <= 0;
    byId('solver-next').disabled = index >= work.tasks_progress.length - 1;
    renderList();
  }
  function select(id) {
    if (actionBusy) return;
    remember();
    if (pending.size && !blocked()) flush().catch(error => say(error.message, true));
    currentId = id;
    try { sessionStorage.setItem(`${storageKey}:current`, String(id)); } catch (_) {}
    renderTask();
    focusTask();
  }
  function summary() {
    if (actionBusy) return;
    remember();
    if (pending.size && !blocked()) flush().catch(error => say(error.message, true));
    currentId = null;
    if (!blocked()) request(base + 'pause/', {}).catch(() => {});
    footer.hidden = true; attachments.hidden = true;
    const correct = work.tasks_progress.filter(task => taskState(task).solved).length;
    const saved = work.tasks_progress.filter(t => !isBlank(responseOf(t))).length;
    byId('solver-task-meta-value').textContent = 'Итоги тренировки';
    body.innerHTML = `<h1>${readOnly() ? 'Тренировка в архиве' : 'Ваша тренировка'}</h1><p>Решено: ${correct} из ${work.tasks_progress.length}. Ответов введено: ${saved}.</p><p>${readOnly() ? 'Можно посмотреть ответы или сделать тренировку текущей и продолжить решение.' : 'Можно продолжить решение, вернуться позже или отправить тренировку в архив. Архивирование не проверяет оставшиеся ответы.'}</p><div class="training-result-list">${work.tasks_progress.map(task => {
      const state = taskState(task);
      return `<button type="button" class="btn btn-secondary training-result-button ${state.className}" data-result-task="${task.variant_task_id}">${task.order}. ${esc(task.task_type_name)} · ${state.label}</button>`;
    }).join('')}</div>${readOnly() ? '<button class="btn btn-primary" id="training-errors">Собрать тренировку по ошибкам</button>' : '<button class="btn btn-primary" id="training-archive-summary">В архив</button>'}`;
    body.querySelectorAll('[data-result-task]').forEach(button => button.addEventListener('click', () => select(Number(button.dataset.resultTask))));
    byId('training-archive-summary')?.addEventListener('click', () => switchArchive(true));
    byId('training-errors')?.addEventListener('click', buildFromErrors);
    renderList();
  }
  async function check() {
    if (actionBusy || blocked() || !current()) return;
    if ([...fields.querySelectorAll('input,textarea')].some(input => !input.reportValidity())) return;
    remember();
    const taskId = currentId;
    const value = responseOf(current());
    if (isBlank(value)) return say('Введите ответ перед проверкой.', true);
    actionBusy = true; renderTask();
    const fingerprint = JSON.stringify([taskId, value]);
    if (!submissionKeys.has(fingerprint)) submissionKeys.set(fingerprint, crypto.randomUUID());
    try {
      await flush();
      work = await request(`${base}tasks/${taskId}/check/`, {answer:value, submission_key:submissionKeys.get(fingerprint)});
      say('');
    } catch(error) { say(error.message, true); }
    finally { actionBusy = false; renderTask(); }
  }
  function operationId(archived) {
    const key = `training-switch:${attemptId}:${archived}:${lifecycleRevision}`;
    try {
      let value = sessionStorage.getItem(key);
      if (!value) { value = crypto.randomUUID(); sessionStorage.setItem(key, value); }
      return value;
    } catch (_) { return crypto.randomUUID(); }
  }
  async function switchArchive(archived) {
    if (actionBusy) return;
    if (archived) remember();
    actionBusy = true;
    try {
      if (archived) await flush();
      const result = await request(base + 'archive/', {archived, lifecycle_revision:lifecycleRevision, operation_id:operationId(archived)});
      lifecycleRevision = result.lifecycle_revision;
      if (archived) { window.location.assign(examUrl + '#training-builder'); return; }
      await refreshState();
      say('Тренировка стала текущей');
    } catch(error) { say(error.message, true); }
    finally { actionBusy = false; updateStateBanner(); if (currentId) renderTask(); }
  }
  function updateStateBanner() {
    archiveButton.hidden = readOnly();
    archiveButton.disabled = actionBusy || needsRecovery;
    const text = readOnly() ? 'Эта тренировка находится в архиве. Сохранённые ответы доступны для просмотра.' : '';
    stateBanner.hidden = !text && !needsRecovery;
    stateBanner.innerHTML = `${text ? `<p>${text}</p>` : ''}${readOnly() ? `<p>${currentTrainingUrl ? 'При возврате этой тренировки текущая перейдёт в архив. Все ответы сохранятся.' : ''}</p><button type="button" class="btn btn-primary" data-training-restore>Сделать текущей</button>${currentTrainingUrl ? `<a class="btn btn-secondary" href="${esc(currentTrainingUrl)}">К текущей тренировке</a>` : ''}` : ''}${needsRecovery ? `<p>В браузере есть неотправленные ответы. ${readOnly() ? 'После возврата тренировки можно восстановить их.' : 'Восстановление заменит соответствующие ответы на сервере вашим локальным вариантом.'}</p>${!readOnly() ? '<button type="button" class="btn btn-secondary" data-recover-local>Восстановить мои ответы</button>' : ''}<button type="button" class="btn btn-secondary" data-discard-local>Оставить ответы с сервера</button>` : ''}`;
  }
  async function refreshState() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      const state = await request(base + 'state/');
      if (work && state.training_revision < work.training_revision) return;
      const changed = work && state.training_revision !== work.training_revision;
      if (changed && pending.size) { needsRecovery = true; clearTimeout(saveTimer); store(); }
      if (changed) work = await request(base);
      lifecycleRevision = state.lifecycle_revision;
      currentTrainingUrl = state.current_attempt_id !== Number(attemptId) ? state.current_url : null;
      updateStateBanner();
      if (changed && !actionBusy) { if (currentId) renderTask(); else summary(); }
    })();
    try { await refreshPromise; } finally { refreshPromise = null; }
  }
  stateBanner.addEventListener('click', async event => {
    if (event.target.closest('[data-training-restore]')) { await switchArchive(false); return; }
    if (actionBusy) return;
    if (event.target.closest('[data-discard-local]')) {
      work = await request(base);
      pending.clear(); pendingBases.clear(); needsRecovery = false; store();
      updateStateBanner(); if (currentId) renderTask();
    }
    if (event.target.closest('[data-recover-local]') && !readOnly()) {
      // The user explicitly chose to replace conflicting server answers.
      work = await request(base);
      if (readOnly()) { updateStateBanner(); return; }
      for (const [id] of pending) pendingBases.set(id, work.tasks_progress.find(t => t.variant_task_id === id)?.saved_response ?? null);
      needsRecovery = false; store(); updateStateBanner();
      try { await flush(); if (currentId) renderTask(); }
      catch(error) { needsRecovery = true; store(); updateStateBanner(); say(error.message, true); }
    }
  });
  archiveButton.addEventListener('click', () => switchArchive(true));
  async function buildFromErrors() {
    if (actionBusy) return;
    actionBusy = true;
    try {
      const draftUrl = `/api/exams/${work.exam_context.exam_version_id}/training-draft/`;
      const draft = await request(draftUrl);
      await request(draftUrl, {action:'mistakes', revision:draft.revision, attempt_id:Number(attemptId)});
      window.location.assign(examUrl + '#training-builder');
    } catch(error) { say(error.message, true); }
    finally { actionBusy = false; }
  }
  root.addEventListener('input', event => { if (footer.contains(event.target)) remember(); });
  checkButton.addEventListener('click', check);
  byId('solver-prev').addEventListener('click', () => { const index = work.tasks_progress.findIndex(t => t.variant_task_id === currentId); if (index > 0) select(work.tasks_progress[index - 1].variant_task_id); });
  byId('solver-next').addEventListener('click', () => { const index = work.tasks_progress.findIndex(t => t.variant_task_id === currentId); if (index < work.tasks_progress.length - 1) select(work.tasks_progress[index + 1].variant_task_id); });
  byId('solver-finalize').addEventListener('click', summary);
  navToggle.addEventListener('click', () => {
    root.classList.toggle('training-nav-expanded');
    renderList();
  });
  byId('training-leave').addEventListener('click', async event => {
    event.preventDefault();
    if (actionBusy) return;
    remember(); actionBusy = true;
    try { if (!blocked()) { await flush(); await request(base + 'pause/', {}); } window.location.assign(examUrl + '#training-builder'); }
    catch(error) { say(`Не удалось сохранить ответы на сервере. ${error.message}`, true); }
    finally { actionBusy = false; }
  });
  window.addEventListener('beforeunload', event => { if (pending.size || flushPromise) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('online', () => { if (pending.size) flush().catch(error => say(error.message, true)); });
  document.addEventListener('visibilitychange', () => {
    if (!work) return;
    if (document.hidden) { if (!blocked()) request(base + 'pause/', {}).catch(() => {}); }
    else refreshState().then(focusTask).catch(backgroundError);
  });
  window.addEventListener('pagehide', () => {
    if (work && !blocked()) fetch(base + 'pause/', {method:'POST', keepalive:true, credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-CSRFToken':root.dataset.csrf, 'X-Training-Revision':String(work.training_revision)}, body:'{}'}).catch(() => {});
  });
  setInterval(() => {
    if (work && !document.hidden) refreshState().then(() => { if (!blocked() && currentId) return request(base + 'heartbeat/', {}); }).then(backgroundRecovered).catch(backgroundError);
  }, 30000);
  async function load() {
    try {
      work = await request(base);
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
        const entries = saved.version === 2 ? saved.entries : saved;
        for (const [id, value, original] of entries) {
          const task = work.tasks_progress.find(t => t.variant_task_id === id);
          if (task && !same(value, task.saved_response) && !(isBlank(value) && isBlank(task.saved_response))) {
            pending.set(id, value); pendingBases.set(id, original ?? null);
          }
        }
        needsRecovery = pending.size > 0;
        store();
      } catch (_) {}
      byId('solver-finalize').textContent = 'Итоги';
      let remembered;
      try { remembered = Number(sessionStorage.getItem(`${storageKey}:current`)); } catch (_) {}
      currentId = work.tasks_progress.find(t => t.variant_task_id === remembered)?.variant_task_id || work.tasks_progress[0]?.variant_task_id;
      renderTask();
      await refreshState();
      focusTask();
    } catch(error) { say(error.message, true); body.textContent = 'Не удалось загрузить тренировку. Обновите страницу.'; footer.hidden = true; }
  }
  window.addEventListener('focus', () => { if (work) refreshState().then(focusTask).catch(backgroundError); });
  load();
})();
