(function() {
  function getSchemaConfig(schema) {
    return schema && typeof schema === "object" ? (schema.config || {}) : {};
  }

  function getGridSize(schema) {
    const cfg = getSchemaConfig(schema);
    return {
      rows: Math.max(1, Number(cfg.rows || 1)),
      cols: Math.max(1, Number(cfg.cols || 1)),
    };
  }

  function normalizeValue(rawValue, inputType) {
    const value = (rawValue ?? "").toString().trim();
    if (!value) return "";
    if (inputType === "int") {
      return /^-?\d+$/.test(value) ? parseInt(value, 10) : value;
    }
    if (inputType === "uint" || inputType === "number") {
      return /^\d+$/.test(value) ? parseInt(value, 10) : value;
    }
    if (inputType === "float") {
      const parsed = Number(value.replace(",", "."));
      return Number.isFinite(parsed) ? parsed : value;
    }
    return value;
  }

  function normaliseDisplayValue(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function setInputsFromPayload(container, schema, payload) {
    if (!container || payload === null || payload === undefined) return;
    const { rows, cols } = getGridSize(schema);
    const setCell = (r, c, value) => {
      const input = container.querySelector(`input[data-row="${r}"][data-col="${c}"]`);
      if (input) input.value = normaliseDisplayValue(value);
    };

    if (rows === 1 && cols === 1) {
      setCell(0, 0, payload);
      return;
    }

    if (rows === 1) {
      const rowValues = Array.isArray(payload) ? payload : [];
      for (let col = 0; col < cols; col += 1) {
        setCell(0, col, rowValues[col]);
      }
      return;
    }

    const matrix = Array.isArray(payload) ? payload : [];
    for (let row = 0; row < rows; row += 1) {
      const rowValues = Array.isArray(matrix[row]) ? matrix[row] : [];
      for (let col = 0; col < cols; col += 1) {
        setCell(row, col, rowValues[col]);
      }
    }
  }

  function setupPasteFill(container, schema, inputSelector) {
    const inputs = Array.from(container.querySelectorAll(inputSelector));
    const cfg = getSchemaConfig(schema);
    const { rows, cols } = getGridSize(schema);
    const inputType = cfg.input_type || "string";
    const total = Math.max(1, rows * cols);
    if (total <= 1 || !inputs.length) return;

    const tokenize = (text) => {
      const raw = String(text || "").trim();
      if (!raw) return [];
      if (inputType === "int") {
        return raw.match(/-?\d+/g) || [];
      }
      if (inputType === "uint" || inputType === "number") {
        return raw.match(/\d+/g) || [];
      }
      if (inputType === "float") {
        return raw
          .split(/[\s;|/\\]+/)
          .map((value) => value.trim())
          .filter((value) => /^-?\d+(?:[.,]\d+)?$/.test(value));
      }
      return raw
        .replace(/\r\n/g, "\n")
        .replace(/\t/g, " ")
        .split(/[\s,;|/\\]+/)
        .map((value) => value.trim())
        .filter((value) => value.length);
    };

    inputs.forEach((input, index) => {
      input.addEventListener("paste", (event) => {
        const raw = (event.clipboardData || window.clipboardData)?.getData("text") || "";
        const tokens = tokenize(raw);
        if (tokens.length <= 1) return;
        event.preventDefault();
        let cursor = index;
        tokens.forEach((token) => {
          if (cursor >= total) return;
          if (inputs[cursor]) {
            inputs[cursor].value = token;
            inputs[cursor].dispatchEvent(new Event("input", { bubbles: true }));
            inputs[cursor].dispatchEvent(new Event("change", { bubbles: true }));
          }
          cursor += 1;
        });
      });
    });
  }

  function setupAutoAdvance(container, schema, inputSelector) {
    const cfg = getSchemaConfig(schema);
    const { rows, cols } = getGridSize(schema);
    const perCellMax = cfg.per_cell_max_length ? Number(cfg.per_cell_max_length) : null;
    if (!(rows === 1 && cols > 1 && perCellMax === 1)) return;
    const inputs = Array.from(container.querySelectorAll(inputSelector));
    inputs.forEach((input, index) => {
      input.addEventListener("input", (event) => {
        const value = event.target.value || "";
        if (value.length >= 1 && index < inputs.length - 1) {
          inputs[index + 1].focus();
          inputs[index + 1].select();
        }
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Backspace" && !event.target.value && index > 0) {
          inputs[index - 1].focus();
        }
      });
    });
  }

  function buildInputs(container, schema, savedValue, options) {
    if (!container || !schema) return;
    const opts = options || {};
    const cfg = getSchemaConfig(schema);
    const { rows, cols } = getGridSize(schema);
    const inputType = cfg.input_type || "string";
    const perCellMax = cfg.per_cell_max_length ? Number(cfg.per_cell_max_length) : null;
    const gridClassName = opts.gridClassName || "answer-grid";
    const rowClassName = opts.rowClassName || "answer-row";
    const cellClassName = opts.cellClassName || "answer-cell";
    const inputClassName = opts.inputClassName || "answer-input";
    const inputSelector = `input.${inputClassName.split(" ").join(".")}`;

    container.innerHTML = "";

    const grid = document.createElement("div");
    grid.className = gridClassName;

    for (let row = 0; row < rows; row += 1) {
      const rowEl = document.createElement("div");
      rowEl.className = rowClassName;
      for (let col = 0; col < cols; col += 1) {
        const cell = document.createElement("div");
        cell.className = cellClassName;
        const input = document.createElement("input");
        input.name = `answer_r${row}_c${col}`;
        input.dataset.row = String(row);
        input.dataset.col = String(col);
        input.className = inputClassName;
        input.type = opts.htmlInputType || "text";
        if (inputType === "uint" || inputType === "int" || inputType === "number") {
          input.inputMode = "numeric";
        } else if (inputType === "float") {
          input.inputMode = "decimal";
        }
        if (perCellMax) input.maxLength = perCellMax;
        if (opts.readOnly) {
          input.readOnly = true;
          input.disabled = true;
        }
        cell.appendChild(input);
        rowEl.appendChild(cell);
      }
      grid.appendChild(rowEl);
    }

    container.appendChild(grid);
    if (!opts.readOnly && opts.autoAdvance) {
      setupAutoAdvance(container, schema, inputSelector);
    }
    if (!opts.readOnly && opts.pasteFill) {
      setupPasteFill(container, schema, inputSelector);
    }
    setInputsFromPayload(container, schema, savedValue);
  }

  function buildReadOnlyInputs(container, schema, payload, options) {
    buildInputs(container, schema, payload, Object.assign({}, options, { readOnly: true }));
  }

  function collectPayload(container, schema) {
    if (!container || !schema) return null;
    const cfg = getSchemaConfig(schema);
    const { rows, cols } = getGridSize(schema);
    const allowBlankRows = !!cfg.allow_blank_rows;
    const inputType = cfg.input_type || "string";
    const getCell = (row, col) => {
      const input = container.querySelector(`input[data-row="${row}"][data-col="${col}"]`);
      return input ? input.value : "";
    };

    if (rows === 1 && cols === 1) {
      return normalizeValue(getCell(0, 0), inputType);
    }

    if (rows === 1) {
      return Array.from({ length: cols }, (_, col) => normalizeValue(getCell(0, col), inputType));
    }

    const matrix = [];
    for (let row = 0; row < rows; row += 1) {
      const rowValues = Array.from({ length: cols }, (_, col) => normalizeValue(getCell(row, col), inputType));
      if (allowBlankRows && rowValues.every((value) => value === "")) {
        matrix.push([]);
      } else {
        matrix.push(rowValues);
      }
    }
    return matrix;
  }

  window.FractalTaskResponse = {
    buildInputs,
    buildReadOnlyInputs,
    setInputsFromPayload,
    collectPayload,
  };
})();
