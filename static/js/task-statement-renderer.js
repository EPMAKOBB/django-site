(function() {
  function cleanTaskBodyHtml(html) {
    if (!html) return "";
    const wrapper = document.createElement("div");
    wrapper.innerHTML = html;

    wrapper.querySelectorAll("form").forEach((form) => {
      form.replaceWith(...Array.from(form.childNodes));
    });
    wrapper.querySelectorAll("input, textarea, select, button").forEach((node) => {
      node.remove();
    });

    let changed = true;
    while (changed) {
      changed = false;
      Array.from(wrapper.querySelectorAll("*")).forEach((node) => {
        if (node.closest("table")) return;
        if (node.matches("br, hr, img, svg, iframe, canvas, video, audio")) return;
        if (node.querySelector("br, hr, img, svg, table, iframe, canvas, video, audio")) return;
        const text = (node.textContent || "").trim();
        if (node.children.length === 0 && !text) {
          node.remove();
          changed = true;
        }
      });
    }
    return wrapper.innerHTML.trim();
  }

  function appendBody(container, html, emptyMessage, bodyClassName) {
    const cleanedHtml = cleanTaskBodyHtml(html);
    if (cleanedHtml) {
      const body = document.createElement("div");
      body.className = bodyClassName || "task-statement__body task-content";
      body.dataset.format = "html";
      body.innerHTML = cleanedHtml;
      container.appendChild(body);
      return true;
    }

    const empty = document.createElement("p");
    empty.className = "task-statement__empty muted";
    empty.textContent = emptyMessage || "Условие задания недоступно.";
    container.appendChild(empty);
    return false;
  }

  function appendImage(container, imageUrl, imageAlt) {
    if (!imageUrl) return;
    const figure = document.createElement("figure");
    figure.className = "task-statement__figure";
    const image = document.createElement("img");
    image.className = "task-statement__image";
    image.src = imageUrl;
    image.alt = imageAlt || "Иллюстрация к заданию";
    figure.appendChild(image);
    container.appendChild(figure);
  }

  function appendAttachments(container, attachments, titleText) {
    if (!Array.isArray(attachments) || !attachments.length) return;
    const validAttachments = attachments.filter((attachment) => attachment && attachment.url);
    if (!validAttachments.length) return;

    const section = document.createElement("section");
    section.className = "task-statement__attachments";
    section.setAttribute("aria-label", "Материалы к заданию");

    const title = document.createElement("p");
    title.className = "task-statement__attachments-title";
    title.textContent = titleText || "Материалы";
    section.appendChild(title);

    const list = document.createElement("ul");
    list.className = "task-statement__attachments-list";
    validAttachments.forEach((attachment) => {
      const item = document.createElement("li");
      item.className = "task-statement__attachments-item";
      const link = document.createElement("a");
      link.className = "task-statement__attachments-link";
      link.href = attachment.url;
      link.target = "_blank";
      link.rel = "noopener";

      if (attachment.label) {
        const label = document.createElement("span");
        label.className = "task-statement__attachments-label";
        label.textContent = attachment.label;
        link.appendChild(label);
      }

      const name = document.createElement("span");
      name.textContent = attachment.name || attachment.url;
      link.appendChild(name);
      item.appendChild(link);
      list.appendChild(item);
    });
    section.appendChild(list);
    container.appendChild(section);
  }

  function render(container, statement, options) {
    if (!container) return;
    const opts = options || {};
    const payload = statement || {};
    container.innerHTML = "";
    container.className = opts.statementClassName || "task-statement";

    appendBody(
      container,
      payload.task_body_html || payload.body_html || "",
      opts.emptyMessage,
      opts.bodyClassName
    );
    appendImage(container, payload.image || payload.image_url, opts.imageAlt);
    appendAttachments(container, payload.attachments, opts.attachmentsTitle);
  }

  window.FractalTaskStatement = {
    cleanTaskBodyHtml,
    render,
  };
})();
