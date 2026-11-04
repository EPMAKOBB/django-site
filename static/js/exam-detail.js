(function () {
  const pageEl = document.getElementById("exam-page");
  if (!pageEl) return;

  const modeHelpSelector = 'details.exam-mode-help';
  const positionModeHelp = help => {
    const panel = help.querySelector('.exam-mode-help__text');
    const trigger = help.querySelector('summary').getBoundingClientRect();
    panel.style.position = 'fixed';
    const size = panel.getBoundingClientRect();
    panel.style.left = `${Math.max(12, Math.min(trigger.left, window.innerWidth - size.width - 12))}px`;
    const below = trigger.bottom + 8;
    panel.style.top = `${below + size.height <= window.innerHeight - 12 ? below : Math.max(12, trigger.top - size.height - 8)}px`;
  };
  document.addEventListener('click', event => {
    const trigger = event.target.closest(`${modeHelpSelector} > summary`);
    if (trigger) {
      event.preventDefault();
      const help = trigger.parentElement;
      help.open = !help.open;
      if (help.open) positionModeHelp(help);
    }
    document.querySelectorAll(`${modeHelpSelector}[open]`).forEach(help => {
      if (!help.contains(event.target)) help.open = false;
    });
  });
  document.addEventListener('toggle', event => {
    if (!event.target.matches(modeHelpSelector) || !event.target.open) return;
    document.querySelectorAll(`${modeHelpSelector}[open]`).forEach(help => {
      if (help !== event.target) help.open = false;
    });
    positionModeHelp(event.target);
  }, true);
  window.addEventListener('resize', () => {
    document.querySelectorAll(`${modeHelpSelector}[open]`).forEach(positionModeHelp);
  });
  document.addEventListener('scroll', event => {
    document.querySelectorAll(`${modeHelpSelector}[open]`).forEach(help => {
      if (!help.contains(event.target)) help.open = false;
    });
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll(`${modeHelpSelector}[open]`).forEach(help => {
      const returnFocus = help.contains(document.activeElement);
      help.open = false;
      if (returnFocus) help.querySelector('summary').focus();
    });
  });

  const progressUrl = pageEl.dataset.progressUrl;
  const isAuth = pageEl.dataset.auth === "1";
  const loginUrl = pageEl.dataset.loginUrl || "";
  const blocksEl = document.getElementById("exam-public-blocks");

  const forecastValueEl = document.getElementById("exam-forecast-value");
  const forecastNoteEl = document.getElementById("exam-forecast-note");
  const progressValueEl = document.getElementById("exam-progress-value");
  const progressFillEl = document.getElementById("exam-progress-fill");
  const progressNoteEl = document.getElementById("exam-progress-note");
  const strengthsListEl = document.getElementById("exam-strengths-list");
  const weaknessesListEl = document.getElementById("exam-weaknesses-list");

  const escapeHtml = (value) =>
    String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  const setList = (listEl, items) => {
    if (!listEl) return;
    listEl.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  };

  const formatScore = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return String(value);
  };

  const formatRange = (fallbackLow, fallbackHigh, label) => {
    if (label) return String(label);
    const low = formatScore(fallbackLow);
    const high = formatScore(fallbackHigh);
    if (low === "—" || high === "—") return "—";
    return low === high ? low : `${low}-${high}`;
  };

  const getTypeCards = () => Array.from(blocksEl.querySelectorAll("[data-type-id]"));

  let stopProgressDemo = () => {};
  const bindProgressDemo = () => {
    const button = blocksEl.querySelector('[data-progress-demo]');
    const note = blocksEl.querySelector('[data-progress-demo-note]');
    if (!button) return;
    let running = false;
    button.addEventListener('click', () => {
      if (running) { stopProgressDemo(); return; }
      const cards = getTypeCards();
      if (!cards.length) return;
      const rows = cards.map(card => ({
        label: card.querySelector('.exam-type-card__score-value, .exam-type-card__score-muted'),
        fill: card.querySelector('.progress-bar .fill'),
      }));
      const snapshots = rows.map(row => ({text: row.label?.textContent, width: row.fill?.style.width}));
      const summarySnapshot = {text: progressValueEl?.textContent, width: progressFillEl?.style.width};
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      let frame;
      let started;
      running = true;
      cards.forEach(card => card.classList.add('is-progress-demo'));
      button.textContent = 'Остановить демонстрацию';
      button.setAttribute('aria-pressed', 'true');
      note.textContent = 'Демонстрация · ваши результаты не изменяются';
      stopProgressDemo = () => {
        if (!running) return;
        cancelAnimationFrame(frame);
        cards.forEach(card => card.classList.remove('is-progress-demo'));
        rows.forEach((row, index) => {
          if (row.label) row.label.textContent = snapshots[index].text;
          if (row.fill) row.fill.style.width = snapshots[index].width;
        });
        if (progressValueEl) progressValueEl.textContent = summarySnapshot.text;
        if (progressFillEl) progressFillEl.style.width = summarySnapshot.width;
        running = false;
        button.textContent = 'Демонстрация';
        button.setAttribute('aria-pressed', 'false');
        note.textContent = '';
      };
      const tick = now => {
        if (started === undefined) started = now;
        const elapsed = now - started;
        let total = 0;
        rows.forEach((row, index) => {
          // Different speeds, with every row complete before the final pause.
          const duration = 2600 + (index * 613 % 1701);
          const fraction = Math.min(1, elapsed / duration);
          const percent = reducedMotion ? 100 : Math.round(100 * Math.pow(fraction, 0.8 + (index % 4) * 0.35));
          total += percent;
          if (row.label) row.label.textContent = `${percent}%`;
          if (row.fill) row.fill.style.width = `${percent}%`;
        });
        const overall = Math.round(total / rows.length);
        if (progressValueEl) progressValueEl.textContent = `${overall}%`;
        if (progressFillEl) progressFillEl.style.width = `${overall}%`;
        if (elapsed >= 5000) stopProgressDemo();
        else frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    });
  };
  window.addEventListener('pagehide', () => stopProgressDemo());

  const getTypeMeta = (card) => ({
    id: card.dataset.typeId,
    name: card.dataset.typeName || "",
    url: card.dataset.typeUrl || "#",
  });

  const bindPersonalForm = () => {
    const form = blocksEl.querySelector("[data-exam-personal-form]");
    if (!form) return;
    const auth = form.dataset.auth === "1";
    if (auth) return;
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const alertEl = blocksEl.querySelector("#exam-auth-alert");
      if (alertEl) {
        alertEl.style.display = "block";
        alertEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } else if (loginUrl) {
        window.location.href = loginUrl;
      }
    });
  };

  const classifyPercent = (percent) => {
    if (percent >= 70) {
      return {
        label: "Сильная зона",
        className: "is-strong",
      };
    }
    if (percent >= 40) {
      return {
        label: "Нужна практика",
        className: "is-medium",
      };
    }
    return {
      label: "Слабая зона",
      className: "is-weak",
    };
  };

  const updateSummaryForAnonymous = () => {
    if (forecastValueEl) { forecastValueEl.textContent = "После входа"; forecastValueEl.classList.add('is-empty'); }
    if (forecastNoteEl) forecastNoteEl.textContent = "Войдите, чтобы увидеть персональный прогноз.";
    if (progressValueEl) progressValueEl.textContent = "—";
    if (progressFillEl) progressFillEl.style.width = "0%";
    if (progressNoteEl) progressNoteEl.textContent = "Прогресс и рекомендации появятся после входа.";
    setList(strengthsListEl, ["Данные появятся после входа"]);
    setList(weaknessesListEl, ["Данные появятся после входа"]);
  };

  const applyProgress = (payload) => {
    stopProgressDemo();
    const historyEl = document.getElementById("exam-period-history");
    if (historyEl) {
      const rows = payload?.period_history?.types || [];
      historyEl.innerHTML = rows.length
        ? '<table><thead><tr><th>Тип</th><th>Ответов</th><th>Полностью верных</th><th>Время, мин</th></tr></thead><tbody>'
          + rows.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${row.attempts}</td><td>${row.correct}</td><td>${row.time_spent_seconds == null ? "—" : Math.round(row.time_spent_seconds / 60)}</td></tr>`).join("") + '</tbody></table>'
        : "В этом периоде ответов нет.";
    }
    const typeProgress = payload?.type_progress || {};
    const tagProgress = payload?.tag_progress || {};
    const cards = getTypeCards();
    const entries = [];

    cards.forEach((card) => {
      const typeId = card.dataset.typeId;
      const progressInfo = typeProgress[typeId] || { percent: 0 };
      const percent = progressInfo.percent || 0;
      const pctEl = card.querySelector(".exam-type-card__score-value");
      const fillEl = card.querySelector(".progress-bar .fill");
      const statusBadgeEl = card.querySelector("[data-type-status]");

      if (pctEl) pctEl.textContent = `${percent}%`;
      if (fillEl) fillEl.style.width = `${percent}%`;

      const status = classifyPercent(percent);
      if (statusBadgeEl) {
        statusBadgeEl.textContent = status.label;
        statusBadgeEl.classList.remove("is-strong", "is-medium", "is-weak");
        statusBadgeEl.classList.add(status.className);
      }

      const tags = tagProgress[typeId] || {};
      Object.keys(tags).forEach((tagId) => {
        const chip = card.querySelector(`[data-tag-id="${tagId}"]`);
        if (chip) {
          chip.style.setProperty("--tag-progress", `${tags[tagId]}%`);
        }
      });

      entries.push({
        card,
        percent,
        ...getTypeMeta(card),
      });
    });

    if (!entries.length) {
      updateSummaryForAnonymous();
      return;
    }

    const overall = Math.round(entries.reduce((sum, entry) => sum + entry.percent, 0) / entries.length);
    const reports = payload?.annual_report?.types || {};
    const answerCount = Object.values(reports).reduce((sum, row) => sum + Number(row.attempts || 0) + Number(row.previous_year_evidence || 0), 0);
    // Preserve forecasts backed by compatible prior experience; avoid a numeric range before initial evidence.
    const hasEvidence = answerCount >= 5;
    const namedEntries = entries.filter(entry => entry.name.trim());
    const strongest = [...namedEntries]
      .filter((entry) => entry.percent > 0)
      .sort((a, b) => b.percent - a.percent)
      .slice(0, 2);
    const weakest = [...namedEntries].filter(entry => Number(reports[entry.id]?.attempts || 0) > 0 || entry.percent > 0)
      .sort((a, b) => a.percent - b.percent).slice(0, 2);
    const forecast = payload?.score_forecast || null;

    if (forecastValueEl) {
      forecastValueEl.classList.toggle('is-empty', !forecast || !hasEvidence);
      if (!hasEvidence) {
        forecastValueEl.textContent = "Нужно больше решений";
      } else if (forecast && forecast.has_scale && forecast.secondary_range_label) {
        forecastValueEl.textContent = `${forecast.secondary_range_label} баллов`;
      } else if (forecast) {
        forecastValueEl.textContent = formatRange(
          forecast.primary_range_min,
          forecast.primary_range_max,
          forecast.primary_range_label
        ) + " первичных";
      } else {
        forecastValueEl.textContent = "—";
      }
    }
    if (forecastNoteEl) {
      if (!hasEvidence) {
        forecastNoteEl.textContent = "Для прогноза нужно больше решений. Результаты появятся по мере подготовки.";
      } else if (forecast && forecast.has_scale) {
        forecastNoteEl.textContent = `${formatRange(
          forecast.primary_range_min,
          forecast.primary_range_max,
          forecast.primary_range_label
        )} первичных из ${formatScore(forecast.primary_max)}. ${forecast.scale_label || ""}`;
      } else if (forecast) {
        forecastNoteEl.textContent = `${formatRange(
          forecast.primary_range_min,
          forecast.primary_range_max,
          forecast.primary_range_label
        )} первичных из ${formatScore(forecast.primary_max)}. Шкала вторичных баллов для экзамена не настроена.`;
      } else {
        forecastNoteEl.textContent = "Прогноз появится после загрузки прогресса.";
      }
    }
    if (progressValueEl) progressValueEl.textContent = `${overall}%`;
    if (progressFillEl) progressFillEl.style.width = `${overall}%`;
    if (progressNoteEl) progressNoteEl.textContent = "Среднее покрытие по типам заданий этого экзамена.";

    setList(
      strengthsListEl,
      strongest.length
        ? strongest.map((entry) => `${entry.name} (${entry.percent}%)`)
        : [hasEvidence ? "Пока нет устойчивых сильных сторон" : "Пока недостаточно данных"]
    );
    setList(weaknessesListEl, hasEvidence && weakest.length
      ? weakest.map((entry) => `${entry.name} (${entry.percent}%)`) : ["Пока недостаточно данных"]);
  };

  document.getElementById("exam-history-filter")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = new URL(progressUrl, window.location.href);
    for (const [key, value] of new FormData(event.currentTarget)) {
      if (value) url.searchParams.set(key, value);
    }
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Не удалось загрузить историю");
      applyProgress(payload);
    } catch (error) {
      document.getElementById("exam-period-history").textContent = error.message;
    }
  });

  blocksEl.addEventListener('click', event => {
    const card = event.target.closest('.exam-type-card--compact');
    if (!card) return;
    const toggle = event.target.closest('[data-type-toggle]');
    if (!toggle && event.target.closest('a, input, button, label, select, textarea, [data-type-panel]')) return;
    if (!toggle && window.getSelection()?.toString()) return;
    const button = card.querySelector('[data-type-toggle]');
    const panel = card.querySelector('[data-type-panel]');
    const expanded = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(expanded));
    button.title = expanded ? 'Свернуть темы и теги' : 'Раскрыть темы и теги';
    button.setAttribute('aria-label', `${expanded ? 'Свернуть' : 'Раскрыть'} темы и теги: ${card.dataset.typeName}`);
    panel.hidden = !expanded;
    card.classList.toggle('is-expanded', expanded);
  });

  // Share the same response with the training builder instead of fetching twice.
  window.examProgressReady = isAuth
    ? fetch(progressUrl, { credentials: "same-origin" })
        .then(response => {
          if (!response.ok) throw new Error("Progress unavailable");
          return response.json();
        })
        .then(payload => { applyProgress(payload); return payload; })
        .catch(() => {
          if (progressValueEl) progressValueEl.textContent = "?";
          return null;
        })
    : Promise.resolve(null);
  bindPersonalForm();
  bindProgressDemo();
  if (!isAuth) updateSummaryForAnonymous();
})();
