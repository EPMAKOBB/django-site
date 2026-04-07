(function () {
  const pageEl = document.getElementById("exam-page");
  if (!pageEl) return;

  const publicUrl = pageEl.dataset.publicUrl;
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

  const getTypeCards = () => Array.from(blocksEl.querySelectorAll("[data-type-id]"));

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
        description: "Можно использовать как опору и поддерживать регулярной практикой.",
        className: "is-strong",
      };
    }
    if (percent >= 40) {
      return {
        label: "Нужна практика",
        description: "Есть база, но здесь еще можно быстро нарастить результат.",
        className: "is-medium",
      };
    }
    return {
      label: "Слабая зона",
      description: "Лучше начать отсюда или вернуться сюда в ближайшее время.",
      className: "is-weak",
    };
  };

  const updateSummaryForAnonymous = () => {
    if (forecastValueEl) forecastValueEl.textContent = "—";
    if (forecastNoteEl) forecastNoteEl.textContent = "Войдите, чтобы увидеть персональный прогноз.";
    if (progressValueEl) progressValueEl.textContent = "—";
    if (progressFillEl) progressFillEl.style.width = "0%";
    if (progressNoteEl) progressNoteEl.textContent = "Прогресс и рекомендации появятся после входа.";
    setList(strengthsListEl, ["Данные появятся после входа", "После этого можно будет выделить сильные типы"]);
    setList(weaknessesListEl, ["Данные появятся после входа", "После этого можно будет выделить слабые типы"]);
  };

  const applyProgress = (payload) => {
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
      const statusTextEl = card.querySelector("[data-type-status-text]");

      if (pctEl) pctEl.textContent = `${percent}%`;
      if (fillEl) fillEl.style.width = `${percent}%`;

      const status = classifyPercent(percent);
      if (statusBadgeEl) {
        statusBadgeEl.textContent = status.label;
        statusBadgeEl.classList.remove("is-strong", "is-medium", "is-weak");
        statusBadgeEl.classList.add(status.className);
      }
      if (statusTextEl) statusTextEl.textContent = status.description;

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
    const strongest = [...entries].sort((a, b) => b.percent - a.percent).slice(0, 2);
    const weakest = [...entries].sort((a, b) => a.percent - b.percent).slice(0, 2);

    if (forecastValueEl) forecastValueEl.textContent = `${overall}%`;
    if (forecastNoteEl) {
      forecastNoteEl.textContent = overall >= 70
        ? "Хорошая база. Имеет смысл удерживать сильные типы и точечно добирать слабые."
        : "Это черновой прогноз по покрытию типов. Лучше всего улучшать ближайшую слабую зону.";
    }
    if (progressValueEl) progressValueEl.textContent = `${overall}%`;
    if (progressFillEl) progressFillEl.style.width = `${overall}%`;
    if (progressNoteEl) progressNoteEl.textContent = "Среднее покрытие по типам заданий этого экзамена.";

    setList(strengthsListEl, strongest.map((entry) => `${entry.name} (${entry.percent}%)`));
    setList(weaknessesListEl, weakest.map((entry) => `${entry.name} (${entry.percent}%)`));
  };

  fetch(publicUrl, { credentials: "same-origin" })
    .then((resp) => (resp.ok ? resp.json() : null))
    .then((payload) => {
      if (!payload || !payload.html) return;
      blocksEl.innerHTML = payload.html;
      bindPersonalForm();

      if (!isAuth) {
        updateSummaryForAnonymous();
        return null;
      }

      return fetch(progressUrl, { credentials: "same-origin" })
        .then((resp) => (resp.ok ? resp.json() : null))
        .then((progressPayload) => applyProgress(progressPayload));
    })
    .catch(() => {
      blocksEl.innerHTML = '<div class="alert alert-warning">Не удалось загрузить данные экзамена.</div>';
      updateSummaryForAnonymous();
    });
})();
