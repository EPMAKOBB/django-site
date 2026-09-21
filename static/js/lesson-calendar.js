(function () {
  "use strict";

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value || "—";
  }

  function formatLessonTime(event) {
    if (!event.start) return "—";
    return new Intl.DateTimeFormat("ru-RU", {
      weekday: "long",
      day: "2-digit",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(event.start);
  }

  function createActionLink(label, href, primary) {
    var link = document.createElement("a");
    link.className = "btn " + (primary ? "btn-primary" : "btn-secondary");
    link.href = href;
    link.textContent = label;
    return link;
  }

  function createPostAction(label, url, action, primary, confirmation) {
    var form = document.createElement("form");
    form.method = "post";
    form.action = url;
    if (confirmation) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(confirmation)) event.preventDefault();
      });
    }
    var csrf = document.createElement("input");
    csrf.type = "hidden";
    csrf.name = "csrfmiddlewaretoken";
    csrf.value = getCookie("csrftoken");
    form.appendChild(csrf);
    var actionInput = document.createElement("input");
    actionInput.type = "hidden";
    actionInput.name = "action";
    actionInput.value = action;
    form.appendChild(actionInput);
    var button = document.createElement("button");
    button.type = "submit";
    button.className = "btn " + (primary ? "btn-primary" : "btn-secondary");
    button.textContent = label;
    form.appendChild(button);
    return form;
  }

  function getCookie(name) {
    var prefix = name + "=";
    var cookies = document.cookie ? document.cookie.split(";") : [];
    for (var index = 0; index < cookies.length; index += 1) {
      var cookie = cookies[index].trim();
      if (cookie.indexOf(prefix) === 0) {
        return decodeURIComponent(cookie.slice(prefix.length));
      }
    }
    return "";
  }

  function toFloatingIso(date) {
    function pad(value) { return String(value).padStart(2, "0"); }
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
      + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
  }

  document.addEventListener("DOMContentLoaded", function () {
    var calendarElement = document.getElementById("lesson-calendar");
    if (!calendarElement) return;

    var errorElement = document.getElementById("lesson-calendar-error");
    var noticeElement = document.getElementById("lesson-calendar-notice");
    if (!window.FullCalendar) {
      errorElement.textContent = "Не удалось загрузить календарь. Подробный список занятий доступен ниже.";
      errorElement.hidden = false;
      return;
    }

    var detail = document.getElementById("lesson-calendar-detail");
    var detailActions = document.getElementById("lesson-detail-actions");
    var closeButton = document.getElementById("lesson-detail-close");
    var savedView = null;
    try {
      savedView = window.localStorage.getItem("lessonCalendarView");
    } catch (error) {
      savedView = null;
    }
    var allowedViews = ["timeGridDay", "timeGridWeek", "dayGridMonth", "listMonth"];
    var narrowScreen = window.matchMedia("(max-width: 700px)").matches;
    var initialView = allowedViews.indexOf(savedView) !== -1
      ? savedView
      : (narrowScreen ? "listMonth" : "timeGridWeek");

    var calendar = new FullCalendar.Calendar(calendarElement, {
      locale: "ru",
      initialView: initialView,
      firstDay: 1,
      nowIndicator: true,
      navLinks: true,
      allDaySlot: false,
      dayMaxEvents: true,
      displayEventEnd: true,
      eventDisplay: "block",
      height: "auto",
      expandRows: true,
      slotMinTime: "07:00:00",
      slotMaxTime: "23:00:00",
      scrollTime: "15:00:00",
      slotDuration: "00:30:00",
      headerToolbar: {
        left: "prev,next today",
        center: "title",
        right: "timeGridDay,timeGridWeek,dayGridMonth,listMonth",
      },
      buttonText: {
        today: "Сегодня",
        day: "День",
        week: "Неделя",
        month: "Месяц",
        list: "Список",
      },
      eventTimeFormat: {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      },
      editable: true,
      eventStartEditable: true,
      eventDurationEditable: false,
      events: {
        url: calendarElement.dataset.eventsUrl,
        failure: function () {
          errorElement.textContent = "Не удалось получить уроки. Обновите страницу или используйте подробный список ниже.";
          errorElement.hidden = false;
        },
        success: function () {
          errorElement.hidden = true;
        },
      },
      datesSet: function (info) {
        try {
          window.localStorage.setItem("lessonCalendarView", info.view.type);
        } catch (error) {
          // The calendar works normally when browser storage is unavailable.
        }
      },
      eventDidMount: function (info) {
        var props = info.event.extendedProps;
        info.el.title = [info.event.title, props.statusLabel, props.paymentLabel]
          .filter(Boolean)
          .join(" · ");
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        var event = info.event;
        var props = event.extendedProps;

        setText("lesson-detail-title", event.title);
        setText("lesson-detail-time", formatLessonTime(event) + " (" + props.timezone + ")");
        setText("lesson-detail-counterpart-label", props.counterpartLabel);
        setText("lesson-detail-counterpart", props.counterpartName);
        setText("lesson-detail-status", props.statusLabel);
        setText("lesson-detail-payment", props.paymentLabel);
        setText("lesson-detail-price", props.price);
        setText("lesson-detail-duration", props.duration + " мин");

        detailActions.replaceChildren();
        if (props.seriesEditUrl) {
          detailActions.appendChild(createActionLink("Изменить серию", props.seriesEditUrl, false));
        }
        if (props.canReschedule && props.rescheduleUrl) {
          detailActions.appendChild(createActionLink(props.canManage ? "Перенести" : "Запросить перенос", props.rescheduleUrl, false));
        }
        if (props.canManage && props.status === "scheduled") {
          detailActions.appendChild(
            createPostAction("Урок проведён", props.lessonActionUrl, "complete", true, "Отметить урок проведённым?")
          );
        }
        if (props.canMarkPaid) {
          detailActions.appendChild(
            createPostAction("Урок оплачен", props.lessonActionUrl, "paid", false, "Отметить урок оплаченным?")
          );
        }
        if (props.canManage && props.status === "scheduled") {
          detailActions.appendChild(
            createPostAction("Отменить урок", props.lessonActionUrl, "cancel", false,
              "Отметить этот урок отменённым? Остальные уроки серии не изменятся.")
          );
        }
        if (props.canManage && (props.status !== "scheduled" || props.paymentStatus === "paid")) {
          var corrections = document.createElement("details");
          var correctionTitle = document.createElement("summary");
          correctionTitle.textContent = "Исправить отметку";
          corrections.appendChild(correctionTitle);
          if (props.status !== "scheduled") {
            corrections.appendChild(createPostAction("Вернуть в запланированные", props.lessonActionUrl, "reopen", false,
              "Снять отметку о результате урока?"));
          }
          if (props.paymentStatus === "paid") {
            corrections.appendChild(createPostAction("Снять ошибочную отметку оплаты", props.lessonActionUrl, "unpaid", false,
              "Снять отметку оплаты? Используйте это действие, если отметка поставлена по ошибке."));
          }
          detailActions.appendChild(corrections);
        }
        if (props.canDelete) {
          detailActions.appendChild(createPostAction("Удалить ошибочный урок", props.lessonActionUrl, "delete", false,
            "Удалить ошибочный урок из расписания? Остальные занятия серии останутся без изменений."));
        }
        var lessonCard = document.getElementById(props.cardId);
        if (lessonCard) {
          var listButton = document.createElement("button");
          listButton.className = "btn btn-secondary";
          listButton.type = "button";
          listButton.textContent = "Открыть действия";
          listButton.addEventListener("click", function () {
            var details = lessonCard.closest("details");
            if (details) details.open = true;
            lessonCard.scrollIntoView({ behavior: "smooth", block: "center" });
          });
          detailActions.appendChild(listButton);
        }
        if (props.hasPendingReschedule) {
          var pending = document.createElement("span");
          pending.className = "hint";
          pending.textContent = "Ожидается решение по переносу";
          detailActions.appendChild(pending);
        }

        detail.hidden = false;
        detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
      },
      eventDrop: function (info) {
        var props = info.event.extendedProps;
        if (!props.canReschedule || !props.calendarRescheduleUrl) {
          info.revert();
          return;
        }
        var newTime = formatLessonTime(info.event);
        if (!window.confirm((props.canManage ? "Перенести урок на " : "Отправить запрос на перенос урока на ") + newTime + "?")) {
          info.revert();
          return;
        }

        fetch(props.calendarRescheduleUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken"),
          },
          body: JSON.stringify({
            proposed_start: toFloatingIso(info.event.start),
            reason: "Перенос из календаря",
          }),
        })
          .then(function (response) {
            return response.json().then(function (data) {
              if (!response.ok) throw new Error(data.error || "Не удалось запросить перенос.");
              return data;
            });
          })
          .then(function (data) {
            if (data.rescheduled) {
              window.location.reload();
              return;
            }
            info.revert();
            calendar.refetchEvents();
            noticeElement.textContent = data.message;
            noticeElement.hidden = false;
            errorElement.hidden = true;
          })
          .catch(function (error) {
            info.revert();
            errorElement.textContent = error.message;
            errorElement.hidden = false;
            noticeElement.hidden = true;
          });
      },
    });

    closeButton.addEventListener("click", function () {
      detail.hidden = true;
    });
    calendar.render();
  });
})();
