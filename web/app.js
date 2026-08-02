(() => {
  const $ = (sel) => document.querySelector(sel);

  const els = {
    app: $(".app"),
    chatList: $("#chat-list"),
    chatTitle: $("#chat-title"),
    messages: $("#messages"),
    input: $("#input"),
    btnSend: $("#btn-send"),
    btnNew: $("#btn-new"),
    tierSelect: $("#tier-select"),
    health: $("#health"),
    statusLine: $("#status-line"),
    btnModels: $("#btn-models"),
    modelsModal: $("#models-modal"),
    modelsList: $("#models-list"),
    modelsStatus: $("#models-status"),
    btnModelsClose: $("#btn-models-close"),
    btnModelsHelp: $("#btn-models-help"),
    modelsHelp: $("#models-help"),
    routerModelSelect: $("#router-model-select"),
    btnModelsSave: $("#btn-models-save"),
    btnModelsAdd: $("#btn-models-add"),
    btnModelsReset: $("#btn-models-reset"),
    addSlotModel: $("#add-slot-model"),
    addSlotId: $("#add-slot-id"),
    addSlotRank: $("#add-slot-rank"),
    addSlotLabel: $("#add-slot-label"),
    addSlotPrompt: $("#add-slot-prompt"),
    addSlotAuto: $("#add-slot-auto"),
    monitorPanel: $("#monitor-panel"),
    panelResizer: $("#panel-resizer"),
    btnPanelToggle: $("#btn-panel-toggle"),
    metricsInterval: $("#metrics-interval"),
    metricsOllama: $("#metrics-ollama"),
    metricsGpu: $("#metrics-gpu"),
    metricsTemp: $("#metrics-temp"),
    metricsRam: $("#metrics-ram"),
    metricsCpu: $("#metrics-cpu"),
    metricsNote: $("#metrics-note"),
  };

  const LS_PANEL_OPEN = "qwen.monitor.open";
  const LS_PANEL_WIDTH = "qwen.monitor.width";
  const LS_METRICS_INTERVAL = "qwen.monitor.interval";
  const LS_CHART_HEIGHTS = "qwen.monitor.chartHeights";
  const PANEL_MIN = 220;
  const PANEL_MAX_CAP = 960;
  const PANEL_DEFAULT = 300;
  const HISTORY_LEN = 60;
  const SPARK_H_MIN = 28;
  const SPARK_H_MAX = 280;
  const SPARK_H_DEFAULT = 48;

  const state = {
    chats: [],
    activeId: null,
    busy: false,
    selectGen: 0,
    ollamaModels: [],
    slots: [],
    routerModel: "",
    panelOpen: true,
    panelWidth: PANEL_DEFAULT,
    metricsTimer: null,
    metricsInflight: false,
    metricsHistory: {
      cpu: [],
      ram: [],
      gpuUtil: [],
      gpuMem: [],
      gpuTemp: [],
      memTemp: [],
    },
    chartHeights: {
      "spark-gpu": SPARK_H_DEFAULT,
      "spark-vram": SPARK_H_DEFAULT,
      "spark-temp-gpu": SPARK_H_DEFAULT,
      "spark-temp-mem": SPARK_H_DEFAULT,
      "spark-ram": SPARK_H_DEFAULT,
      "spark-cpu": SPARK_H_DEFAULT,
    },
  };

  function forceTier() {
    const v = els.tierSelect.value;
    return v === "auto" ? null : v;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  if (typeof marked !== "undefined") {
    marked.setOptions({ gfm: true, breaks: true });
  }

  /** Закрыть незакрытый fence, чтобы стрим не ломал разметку. */
  function closeOpenFences(text) {
    const n = (String(text).match(/```/g) || []).length;
    return n % 2 === 1 ? text + "\n```" : text;
  }

  function hasOpenFence(text) {
    return ((String(text).match(/```/g) || []).length % 2) === 1;
  }

  function renderMarkdown(text, { streaming = false } = {}) {
    let src = text == null ? "" : String(text);
    if (streaming) src = closeOpenFences(src);
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      return escapeHtml(src).replace(/\n/g, "<br>");
    }
    const html = marked.parse(src, { async: false });
    return DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "option"],
      FORBID_ATTR: ["style", "srcset"],
    });
  }

  function langFromCode(codeEl) {
    const cls = codeEl?.getAttribute?.("class") || codeEl?.className || "";
    const m = String(cls).match(/(?:^|\s)(?:language|lang)-([^\s]+)/i);
    if (!m) return "";
    let raw = m[1];
    try {
      if (/%[0-9A-Fa-f]{2}/.test(raw)) raw = decodeURIComponent(raw);
    } catch (_) {
      /* битый percent-encoding — оставляем как есть */
    }
    return raw.replace(/[^a-zA-Z0-9_+#.-]/g, "").slice(0, 40);
  }

  function codePlainText(preOrCode) {
    const code = preOrCode.querySelector?.("code") || preOrCode;
    const clone = code.cloneNode(true);
    clone.querySelectorAll(".stream-caret").forEach((n) => n.remove());
    return clone.textContent || "";
  }

  const ICON_COPY =
    '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M5.75 2.5A1.75 1.75 0 0 0 4 4.25v7a.75.75 0 0 1-1.5 0v-7A3.25 3.25 0 0 1 5.75 1h5a.75.75 0 0 1 0 1.5h-5zm1.5 3A1.75 1.75 0 0 0 5.5 7.25v6c0 .966.784 1.75 1.75 1.75h5A1.75 1.75 0 0 0 14 13.25v-6A1.75 1.75 0 0 0 12.25 5.5h-5zm0 1.5h5a.25.25 0 0 1 .25.25v6a.25.25 0 0 1-.25.25h-5a.25.25 0 0 1-.25-.25v-6a.25.25 0 0 1 .25-.25z"/></svg>';
  const ICON_CHECK =
    '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M12.53 4.22a.75.75 0 0 1 0 1.06l-5.25 5.25a.75.75 0 0 1-1.06 0L4.22 8.53a.75.75 0 0 1 1.06-1.06L6.75 9l4.72-4.72a.75.75 0 0 1 1.06 0z"/></svg>';

  const LANG_ALIASES = {
    "c++": "cpp",
    cplusplus: "cpp",
    "c#": "csharp",
    cs: "csharp",
    "f#": "fsharp",
    js: "javascript",
    ts: "typescript",
    py: "python",
    rb: "ruby",
    sh: "bash",
    shell: "bash",
    zsh: "bash",
    yml: "yaml",
    golang: "go",
    kt: "kotlin",
    rs: "rust",
    text: "plaintext",
    txt: "plaintext",
  };

  function normalizeLangClass(code) {
    const lang = langFromCode(code);
    if (!lang) return;
    const mapped = LANG_ALIASES[lang.toLowerCase()] || lang.toLowerCase();
    if (!/^[a-z0-9_+#.-]+$/i.test(mapped)) return;
    const cls = String(code.className || "").replace(/(?:^|\s)(?:language|lang)-[^\s]+/gi, "").trim();
    code.className = cls;
    code.classList.add("language-" + mapped);
  }

  function highlightCodeBlocks(el, { streaming = false, text = "" } = {}) {
    if (typeof hljs === "undefined") return;
    const codes = [...el.querySelectorAll("pre code")];
    const skipLast = streaming && hasOpenFence(text);
    for (let i = 0; i < codes.length; i++) {
      if (skipLast && i === codes.length - 1) continue;
      const code = codes[i];
      normalizeLangClass(code);
      try {
        hljs.highlightElement(code);
      } catch (_) {
        /* неизвестный язык — оставляем plain */
      }
    }
  }

  function enhanceCodeBlocks(el) {
    for (const pre of [...el.querySelectorAll("pre")]) {
      if (pre.parentElement?.classList.contains("code-block")) continue;
      const code = pre.querySelector("code");
      const lang = langFromCode(code);

      const wrap = document.createElement("div");
      wrap.className = "code-block";

      const header = document.createElement("div");
      header.className = "code-block-header";

      const langEl = document.createElement("span");
      langEl.className = "code-lang";
      langEl.textContent = lang || "";
      if (!lang) langEl.hidden = true;

      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "code-copy";
      copyBtn.title = "Копировать";
      copyBtn.setAttribute("aria-label", "Копировать код");
      copyBtn.innerHTML = ICON_COPY;

      header.appendChild(langEl);
      header.appendChild(copyBtn);

      pre.replaceWith(wrap);
      wrap.appendChild(header);
      wrap.appendChild(pre);
    }
  }

  function placeStreamCaret(el, text) {
    const caret = document.createElement("span");
    caret.className = "stream-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "▍";
    if (hasOpenFence(text)) {
      const blocks = el.querySelectorAll(".code-block pre, pre");
      const hostPre = blocks[blocks.length - 1];
      const host = hostPre?.querySelector("code") || hostPre;
      if (host) {
        host.appendChild(caret);
        return;
      }
    }
    el.appendChild(caret);
  }

  function setMsgBody(el, text, { streaming = false } = {}) {
    const src = text == null ? "" : String(text);
    el.innerHTML = renderMarkdown(src, { streaming });
    for (const table of el.querySelectorAll("table")) {
      if (table.parentElement?.classList.contains("md-table-wrap")) continue;
      const wrap = document.createElement("div");
      wrap.className = "md-table-wrap";
      table.replaceWith(wrap);
      wrap.appendChild(table);
    }
    for (const a of el.querySelectorAll("a[href]")) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    }
    for (const img of el.querySelectorAll("img[src]")) {
      const srcAttr = img.getAttribute("src") || "";
      if (/^https?:\/\//i.test(srcAttr)) {
        img.removeAttribute("src");
        img.setAttribute("alt", img.getAttribute("alt") || "[изображение]");
        img.classList.add("blocked-remote-img");
      }
    }
    enhanceCodeBlocks(el);
    highlightCodeBlocks(el, { streaming, text: src });
    renderMathInMsg(el);
    if (streaming) placeStreamCaret(el, src);
  }

  /** LaTeX $…$ / $$…$$ → KaTeX (после sanitize; в code/pre не трогаем). */
  function renderMathInMsg(el) {
    if (typeof renderMathInElement !== "function") return;
    try {
      renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
        ignoredTags: [
          "script",
          "noscript",
          "style",
          "textarea",
          "pre",
          "code",
          "kbd",
          "samp",
          "annotation",
          "annotation-xml",
        ],
        ignoredClasses: ["code-block", "code-copy"],
      });
    } catch (_) {
      /* неполная формула при стриме — оставляем сырой текст */
    }
  }

  async function copyCodeBlock(btn) {
    const block = btn.closest(".code-block");
    const pre = block?.querySelector("pre");
    if (!pre) return;
    const text = codePlainText(pre);
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } finally {
        ta.remove();
      }
    }
    btn.classList.add("copied");
    btn.title = "Скопировано";
    btn.innerHTML = ICON_CHECK;
    clearTimeout(btn._copyTimer);
    btn._copyTimer = setTimeout(() => {
      btn.classList.remove("copied");
      btn.title = "Копировать";
      btn.innerHTML = ICON_COPY;
    }, 1500);
  }

  function setBusy(busy) {
    state.busy = busy;
    els.btnSend.disabled = busy || !els.input.value.trim();
    els.input.disabled = busy;
    els.btnNew.disabled = busy;
    els.tierSelect.disabled = busy;
    if (els.btnModels) els.btnModels.disabled = busy;
    els.chatList.classList.toggle("busy", busy);
  }

  function autosize() {
    const el = els.input;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      let msg = res.statusText;
      try {
        const j = await res.json();
        msg = j.detail || JSON.stringify(j);
      } catch (_) {
        /* ignore */
      }
      throw new Error(msg);
    }
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function populateTierSelect(slots) {
    const prev = els.tierSelect.value || "auto";
    els.tierSelect.innerHTML = "";
    const auto = document.createElement("option");
    auto.value = "auto";
    auto.textContent = "Auto";
    els.tierSelect.appendChild(auto);
    for (const s of slots || []) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.label || `${s.id} · ${s.model}`;
      els.tierSelect.appendChild(opt);
    }
    const ok = [...els.tierSelect.options].some((o) => o.value === prev);
    els.tierSelect.value = ok ? prev : "auto";
  }

  function fillModelSelect(selectEl, selected) {
    selectEl.innerHTML = "";
    const models = state.ollamaModels.length
      ? state.ollamaModels
      : selected
        ? [selected]
        : [];
    if (!models.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Нет моделей Ollama";
      selectEl.appendChild(opt);
      return;
    }
    for (const name of models) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      selectEl.appendChild(opt);
    }
    if (selected && models.includes(selected)) {
      selectEl.value = selected;
    } else if (selected) {
      const opt = document.createElement("option");
      opt.value = selected;
      opt.textContent = selected + " (не установлена)";
      selectEl.appendChild(opt);
      selectEl.value = selected;
    }
  }

  function setModelsStatus(text, kind) {
    els.modelsStatus.textContent = text || "";
    els.modelsStatus.className = "modal-status" + (kind ? " " + kind : "");
  }

  function renderModelsList(slots) {
    state.slots = (slots || []).map((s) => ({ ...s }));
    els.modelsList.innerHTML = "";
    for (const slot of state.slots) {
      const card = document.createElement("div");
      card.className = "slot-card";
      card.dataset.id = slot.id;

      const head = document.createElement("div");
      head.className = "slot-card-head";
      const idEl = document.createElement("span");
      idEl.className = "slot-id";
      idEl.textContent = slot.id + (slot.builtin ? " · builtin" : "");
      head.appendChild(idEl);
      if (!slot.builtin && !slot.required) {
        const del = document.createElement("button");
        del.type = "button";
        del.className = "btn btn-ghost danger";
        del.textContent = "Удалить";
        del.addEventListener("click", () => removeSlot(slot.id));
        head.appendChild(del);
      }
      card.appendChild(head);

      const meta = document.createElement("div");
      meta.className = "slot-meta";

      const modelWrap = document.createElement("div");
      modelWrap.className = "field-with-label";
      const modelLab = document.createElement("label");
      modelLab.className = "field-label";
      modelLab.textContent = "Модель";
      const modelSel = document.createElement("select");
      modelSel.className = "tier-select slot-model";
      fillModelSelect(modelSel, slot.model);
      modelWrap.appendChild(modelLab);
      modelWrap.appendChild(modelSel);

      const rankWrap = document.createElement("div");
      rankWrap.className = "field-with-label rank-field";
      const rankLab = document.createElement("label");
      rankLab.className = "field-label";
      rankLab.textContent = "Rank";
      const rankInp = document.createElement("input");
      rankInp.className = "text-input rank-input slot-rank";
      rankInp.type = "number";
      rankInp.min = "0";
      rankInp.max = "9";
      rankInp.value = String(slot.rank ?? 1);
      rankInp.title = "Сила / порядок эскалации";
      rankWrap.appendChild(rankLab);
      rankWrap.appendChild(rankInp);

      meta.appendChild(modelWrap);
      meta.appendChild(rankWrap);
      card.appendChild(meta);

      const labelInp = document.createElement("input");
      labelInp.className = "text-input slot-label";
      labelInp.type = "text";
      labelInp.value = slot.label || "";
      labelInp.placeholder = "Подпись";
      card.appendChild(labelInp);

      const promptInp = document.createElement("textarea");
      promptInp.className = "prompt-input slot-prompt";
      promptInp.rows = 3;
      promptInp.value = slot.router_prompt || "";
      promptInp.placeholder = "Когда роутеру выбирать эту модель…";
      card.appendChild(promptInp);

      const autoLab = document.createElement("label");
      autoLab.className = "check-label";
      const autoCb = document.createElement("input");
      autoCb.type = "checkbox";
      autoCb.className = "slot-auto";
      autoCb.checked = !!slot.router_auto;
      autoLab.appendChild(autoCb);
      autoLab.appendChild(document.createTextNode(" Участвует в Auto-роутере"));
      card.appendChild(autoLab);

      els.modelsList.appendChild(card);
    }
  }

  function collectSlotsFromDom() {
    const out = [];
    for (const card of els.modelsList.querySelectorAll(".slot-card")) {
      const id = card.dataset.id;
      const prev = state.slots.find((s) => s.id === id) || {};
      out.push({
        id,
        model: card.querySelector(".slot-model").value,
        label: card.querySelector(".slot-label").value.trim(),
        router_prompt: card.querySelector(".slot-prompt").value.trim(),
        rank: Number(card.querySelector(".slot-rank").value) || 0,
        router_auto: card.querySelector(".slot-auto").checked,
        required: !!prev.required,
        optional: prev.optional !== false,
        builtin: !!prev.builtin,
      });
    }
    return out;
  }

  async function loadSettings() {
    const data = await api("/api/settings");
    state.routerModel = data.router_model || "";
    renderModelsList(data.slots || []);
    populateTierSelect(data.slots || []);
    fillModelSelect(els.addSlotModel, els.addSlotModel.value || "");
    fillModelSelect(els.routerModelSelect, state.routerModel);
    return data;
  }

  function toggleModelsHelp() {
    const open = els.modelsHelp.hidden;
    els.modelsHelp.hidden = !open;
    els.btnModelsHelp.setAttribute("aria-expanded", open ? "true" : "false");
  }

  async function openModelsModal() {
    setModelsStatus("");
    els.modelsHelp.hidden = true;
    els.btnModelsHelp.setAttribute("aria-expanded", "false");
    try {
      await refreshHealth();
      await loadSettings();
      els.modelsModal.hidden = false;
    } catch (e) {
      setModelsStatus(e.message, "err");
      els.modelsModal.hidden = false;
    }
  }

  function closeModelsModal() {
    els.modelsModal.hidden = true;
  }

  async function saveModels() {
    setModelsStatus("Сохранение…");
    try {
      const slots = collectSlotsFromDom();
      const data = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          slots,
          router_model: els.routerModelSelect.value || null,
        }),
      });
      state.routerModel = data.router_model || "";
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
      fillModelSelect(els.routerModelSelect, state.routerModel);
      setModelsStatus("Сохранено", "ok");
      await refreshHealth();
    } catch (e) {
      setModelsStatus(e.message, "err");
    }
  }

  async function persistDraftSlots() {
    const slots = collectSlotsFromDom();
    if (!slots.length) return null;
    return api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        slots,
        router_model: els.routerModelSelect.value || null,
      }),
    });
  }

  async function addModelSlot() {
    const model = els.addSlotModel.value.trim();
    if (!model) {
      setModelsStatus("Выберите модель Ollama", "err");
      return;
    }
    setModelsStatus("Добавление…");
    try {
      await persistDraftSlots();
      const body = {
        model,
        label: els.addSlotLabel.value.trim() || null,
        router_prompt: els.addSlotPrompt.value.trim() || null,
        id: els.addSlotId.value.trim() || null,
        rank: Number.isFinite(Number(els.addSlotRank.value))
          ? Number(els.addSlotRank.value)
          : 2,
        router_auto: els.addSlotAuto.checked,
      };
      const data = await api("/api/settings/slots", {
        method: "POST",
        body: JSON.stringify(body),
      });
      state.routerModel = data.router_model || state.routerModel;
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
      fillModelSelect(els.routerModelSelect, state.routerModel);
      els.addSlotId.value = "";
      els.addSlotLabel.value = "";
      els.addSlotPrompt.value = "";
      els.addSlotRank.value = "2";
      els.addSlotAuto.checked = true;
      setModelsStatus("Добавлено", "ok");
      await refreshHealth();
    } catch (e) {
      setModelsStatus(e.message, "err");
    }
  }

  async function removeSlot(id) {
    if (!confirm(`Удалить слот «${id}»?`)) return;
    setModelsStatus("Удаление…");
    try {
      await persistDraftSlots();
      const data = await api(`/api/settings/slots/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
      setModelsStatus("Удалено", "ok");
    } catch (e) {
      setModelsStatus(e.message, "err");
    }
  }

  async function resetModels() {
    if (!confirm("Сбросить модели и промпты роутера к значениям по умолчанию?")) return;
    setModelsStatus("Сброс…");
    try {
      const data = await api("/api/settings/reset", { method: "POST", body: "{}" });
      state.routerModel = data.router_model || "";
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
      fillModelSelect(els.routerModelSelect, state.routerModel);
      setModelsStatus("Сброшено к defaults", "ok");
      await refreshHealth();
    } catch (e) {
      setModelsStatus(e.message, "err");
    }
  }

  async function refreshHealth() {
    try {
      const h = await api("/api/health");
      state.ollamaModels = h.models || [];
      if (h.slots) {
        populateTierSelect(h.slots);
      } else if (h.tiers) {
        populateTierSelect(
          Object.entries(h.tiers).map(([id, model]) => ({
            id,
            model,
            label: `${id} · ${model}`,
          }))
        );
      }
      if (!h.ollama) {
        els.health.className = "health err";
        els.health.textContent = "Ollama недоступна" + (h.error ? `: ${h.error}` : "");
        return;
      }
      if (h.missing && h.missing.length) {
        els.health.className = "health warn";
        els.health.textContent = "Нет моделей: " + h.missing.join(", ");
        return;
      }
      if (h.missing_optional && h.missing_optional.length) {
        els.health.className = "health warn";
        els.health.textContent = "Опционально: " + h.missing_optional.join(", ");
        return;
      }
      els.health.className = "health ok";
      els.health.textContent = "Ollama · модели на месте";
    } catch (e) {
      els.health.className = "health err";
      els.health.textContent = "Сервер: " + e.message;
    }
  }

  const ICON_CLEAR =
    '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8.09 2.09a1.75 1.75 0 0 1 2.47 0l3.35 3.35a1.75 1.75 0 0 1 0 2.47L8.4 13.42A2.25 2.25 0 0 1 6.81 14H2.75a.75.75 0 0 1-.75-.75V9.19c0-.6.24-1.17.66-1.59l5.43-5.51zm1.41.88a.25.25 0 0 0-.35 0L4.2 8.1l3.7 3.7 5.05-5.05a.25.25 0 0 0 0-.35L8.5 2.97zM3.5 9.4v3.1h2.9L3.5 9.4z"/></svg>';
  const ICON_DELETE =
    '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M6.5 1.75A.75.75 0 0 1 7.25 1h1.5a.75.75 0 0 1 .75.75V3h3.75a.75.75 0 0 1 0 1.5h-.34l-.7 8.05A1.75 1.75 0 0 1 10.47 14H5.53a1.75 1.75 0 0 1-1.74-1.45L3.09 4.5H2.75a.75.75 0 0 1 0-1.5H6.5V1.75zM5.1 4.5l.68 7.85a.25.25 0 0 0 .25.2h4.94a.25.25 0 0 0 .25-.2l.68-7.85H5.1zm1.65 1.75a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5a.75.75 0 0 1 .75-.75zm2.5 0a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5a.75.75 0 0 1 .75-.75z"/></svg>';

  function renderChatList() {
    els.chatList.innerHTML = "";
    for (const c of state.chats) {
      const row = document.createElement("div");
      row.className = "chat-row" + (c.id === state.activeId ? " active" : "");
      row.dataset.id = c.id;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chat-item";
      btn.textContent = c.title || "New Chat";
      btn.title = c.title || "New Chat";
      btn.addEventListener("click", () => selectChat(c.id));

      const actions = document.createElement("div");
      actions.className = "chat-actions";

      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "chat-action";
      clearBtn.title = "Очистить";
      clearBtn.setAttribute("aria-label", "Очистить чат");
      clearBtn.innerHTML = ICON_CLEAR;
      clearBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        clearChat(c.id);
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "chat-action danger";
      delBtn.title = "Удалить";
      delBtn.setAttribute("aria-label", "Удалить чат");
      delBtn.innerHTML = ICON_DELETE;
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteChat(c.id);
      });

      actions.appendChild(clearBtn);
      actions.appendChild(delBtn);
      row.appendChild(btn);
      row.appendChild(actions);
      els.chatList.appendChild(row);
    }
  }

  function metaChips(meta) {
    if (!meta) return "";
    const chips = [];
    if (meta.tier) chips.push(`<span class="chip accent">${escapeHtml(meta.tier)}</span>`);
    if (meta.model) chips.push(`<span class="chip">${escapeHtml(meta.model)}</span>`);
    if (meta.need_web) chips.push(`<span class="chip">web</span>`);
    if (meta.num_ctx) chips.push(`<span class="chip">ctx ${escapeHtml(meta.num_ctx)}</span>`);
    if (meta.used_history === false) chips.push(`<span class="chip">без истории</span>`);
    else if (meta.used_history === true) chips.push(`<span class="chip">история</span>`);
    if (meta.escalated) chips.push(`<span class="chip warn">escalated</span>`);
    if (meta.attempts > 1)
      chips.push(`<span class="chip warn">попыток: ${escapeHtml(meta.attempts)}</span>`);
    if (meta.problems && meta.problems.length)
      chips.push(`<span class="chip warn">${escapeHtml(meta.problems.join(", "))}</span>`);
    else if (meta.checked) chips.push(`<span class="chip">проверено</span>`);
    if (meta.route_reason)
      chips.push(`<span class="chip" title="${escapeHtml(meta.route_reason)}">${escapeHtml(meta.route_reason)}</span>`);
    return chips.length ? `<div class="msg-meta">${chips.join("")}</div>` : "";
  }

  function appendMessage(role, content, meta, { streaming = false } = {}) {
    const wrap = document.createElement("article");
    wrap.className = "msg " + role + (streaming ? " streaming" : "");
    wrap.innerHTML = `
      <div class="msg-role">${role === "user" ? "You" : "Orchestra"}</div>
      <div class="msg-body"></div>
      <div class="msg-tools"></div>
      <div class="msg-meta-slot"></div>
    `;
    setMsgBody(wrap.querySelector(".msg-body"), content || "");
    wrap.querySelector(".msg-meta-slot").innerHTML = metaChips(meta);
    els.messages.appendChild(wrap);
    els.messages.scrollTop = els.messages.scrollHeight;
    return wrap;
  }

  function renderMessages(messages) {
    els.messages.innerHTML = "";
    for (const m of messages || []) {
      appendMessage(m.role, m.content, m.meta);
    }
  }

  async function loadChats() {
    state.chats = await api("/api/chats");
    renderChatList();
  }

  async function selectChat(id) {
    if (state.busy) return;
    const gen = ++state.selectGen;
    state.activeId = id;
    const data = await api(`/api/chats/${id}`);
    if (gen !== state.selectGen || state.activeId !== id) return;
    els.chatTitle.textContent = data.title || "New Chat";
    renderMessages(data.messages);
    renderChatList();
    setBusy(false);
  }

  async function ensureChat() {
    if (state.activeId) return state.activeId;
    const chat = await api("/api/chats", { method: "POST", body: "{}" });
    state.chats.unshift(chat);
    state.activeId = chat.id;
    els.chatTitle.textContent = chat.title;
    renderChatList();
    return chat.id;
  }

  async function newChat() {
    if (state.busy) return;
    setBusy(true);
    try {
      const chat = await api("/api/chats", { method: "POST", body: "{}" });
      state.chats.unshift(chat);
      state.activeId = chat.id;
      els.chatTitle.textContent = chat.title;
      els.messages.innerHTML = "";
      renderChatList();
    } finally {
      setBusy(false);
      els.input.focus();
    }
  }

  async function clearChat(id) {
    id = id || state.activeId;
    if (!id || state.busy) return;
    if (!confirm("Очистить историю этого чата?")) return;
    state.selectGen += 1;
    try {
      await api(`/api/chats/${id}/clear`, { method: "POST", body: "{}" });
      if (id === state.activeId) {
        els.messages.innerHTML = "";
        els.chatTitle.textContent = "New Chat";
      }
      await loadChats();
    } catch (e) {
      els.statusLine.textContent = "Ошибка: " + e.message;
    }
  }

  async function deleteChat(id) {
    id = id || state.activeId;
    if (!id || state.busy) return;
    if (!confirm("Удалить этот чат?")) return;
    state.selectGen += 1;
    const wasActive = id === state.activeId;
    try {
      await api(`/api/chats/${id}`, { method: "DELETE" });
      if (wasActive) {
        state.activeId = null;
        els.messages.innerHTML = "";
        els.chatTitle.textContent = "New Chat";
      }
      await loadChats();
      if (wasActive) {
        if (state.chats.length) await selectChat(state.chats[0].id);
        else renderChatList();
      }
    } catch (e) {
      els.statusLine.textContent = "Ошибка: " + e.message;
    }
  }

  function parseSseChunk(buffer) {
    const events = [];
    const parts = buffer.split(/\r?\n\r?\n/);
    const rest = parts.pop() || "";
    for (const block of parts) {
      if (!block.trim()) continue;
      let event = "message";
      const dataLines = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      const raw = dataLines.join("\n");
      let data = raw;
      try {
        data = JSON.parse(raw);
      } catch (_) {
        data = { message: raw || "bad sse json" };
        event = "error";
      }
      if (data == null || typeof data !== "object") {
        data = { message: String(raw || "bad sse payload") };
        event = "error";
      }
      events.push({ event, data });
    }
    return { events, rest };
  }

  function flushBodyRender(ctx, { streaming = false } = {}) {
    if (ctx._raf) {
      cancelAnimationFrame(ctx._raf);
      ctx._raf = 0;
    }
    setMsgBody(ctx.bodyEl, ctx.full, { streaming });
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function scheduleBodyRender(ctx) {
    if (ctx._raf) return;
    ctx._raf = requestAnimationFrame(() => {
      ctx._raf = 0;
      setMsgBody(ctx.bodyEl, ctx.full, { streaming: true });
      els.messages.scrollTop = els.messages.scrollHeight;
    });
  }

  function applySseEvent(event, data, ctx) {
    const { toolsEl, metaSlot } = ctx;
    if (event === "meta") {
      if (data.phase === "retry" || data.phase === "restore") {
        ctx.full = "";
        flushBodyRender(ctx, { streaming: true });
      }
      if (data.phase === "retry" && data.problems && data.problems.length) {
        const line = document.createElement("div");
        line.className = "tool-line";
        line.textContent = `повтор (${data.problems.join(", ")}) → ${data.model || ""}`;
        toolsEl.appendChild(line);
      }
      if (data.phase === "restore") {
        ctx.liveMeta = { ...ctx.liveMeta, ...data, problems: [] };
        const line = document.createElement("div");
        line.className = "tool-line";
        line.textContent = `восстановлен лучший ответ (${data.model || ""})`;
        toolsEl.appendChild(line);
      } else {
        ctx.liveMeta = { ...ctx.liveMeta, ...data };
      }
      metaSlot.innerHTML = metaChips(ctx.liveMeta);
      const bits = [];
      if (ctx.liveMeta.tier) bits.push(ctx.liveMeta.tier);
      if (ctx.liveMeta.model) bits.push(ctx.liveMeta.model);
      if (ctx.liveMeta.need_web) bits.push("web");
      if (ctx.liveMeta.num_ctx) bits.push("ctx " + ctx.liveMeta.num_ctx);
      if (ctx.liveMeta.used_history === false) bits.push("без истории");
      if (data.phase === "retry") bits.push("повтор");
      else if (data.phase === "restore") bits.push("restore");
      else if (ctx.liveMeta.escalated) bits.push("escalate");
      els.statusLine.textContent = bits.join(" · ") || "Генерация…";
    } else if (event === "check") {
      ctx.liveMeta = {
        ...ctx.liveMeta,
        checked: data.checked != null ? !!data.checked : false,
        problems: data.ok ? [] : data.problems || [],
      };
      metaSlot.innerHTML = metaChips(ctx.liveMeta);
      if (!data.ok) {
        const line = document.createElement("div");
        line.className = "tool-line";
        const note = data.note ? ` — ${data.note}` : "";
        line.textContent = `self-check: ${(data.problems || []).join(", ")}${note}`;
        toolsEl.appendChild(line);
      }
    } else if (event === "token") {
      ctx.full += data.text || "";
      scheduleBodyRender(ctx);
    } else if (event === "tool") {
      const line = document.createElement("div");
      line.className = "tool-line";
      const args =
        typeof data.arguments === "string"
          ? data.arguments
          : JSON.stringify(data.arguments || {});
      line.textContent = `tool ${data.name}(${args})`;
      toolsEl.appendChild(line);
    } else if (event === "done") {
      ctx.doneReceived = true;
      ctx.liveMeta = {
        tier: data.tier,
        model: data.model,
        need_web: data.need_web,
        route_reason: data.route_reason,
        escalated: data.escalated,
        attempts: data.attempts,
        checked: data.checked,
        problems: data.problems || [],
        num_ctx: data.num_ctx,
        used_history: data.used_history,
        context_reason: data.context_reason,
      };
      if (data.text) {
        ctx.full = data.text;
      }
      flushBodyRender(ctx, { streaming: false });
      metaSlot.innerHTML = metaChips(ctx.liveMeta);
      els.statusLine.textContent = [
        data.tier,
        data.model,
        data.need_web ? "web" : null,
        data.num_ctx ? `ctx ${data.num_ctx}` : null,
        data.used_history === false ? "без истории" : null,
        data.escalated ? "escalated" : null,
        data.attempts > 1 ? `попыток: ${data.attempts}` : null,
        data.checked ? "проверено" : null,
      ]
        .filter(Boolean)
        .join(" · ");
    } else if (event === "error") {
      throw new Error(data.message || "Ошибка оркестра");
    }
  }

  async function send() {
    const text = els.input.value.trim();
    if (!text || state.busy) return;

    setBusy(true);
    els.statusLine.textContent = "Роутинг…";

    let chatId;
    let asst = null;
    const ctx = {
      liveMeta: {},
      full: "",
      bodyEl: null,
      toolsEl: null,
      metaSlot: null,
      doneReceived: false,
    };

    try {
      chatId = await ensureChat();
      els.input.value = "";
      autosize();
      appendMessage("user", text);

      asst = appendMessage("assistant", "", null, { streaming: true });
      ctx.bodyEl = asst.querySelector(".msg-body");
      ctx.toolsEl = asst.querySelector(".msg-tools");
      ctx.metaSlot = asst.querySelector(".msg-meta-slot");

      const res = await fetch(`/api/chats/${chatId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text, force_tier: forceTier() }),
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || res.statusText);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const { events, rest } = parseSseChunk(buf);
        buf = rest;

        for (const { event, data } of events) {
          applySseEvent(event, data, ctx);
        }
      }
      buf += decoder.decode();
      if (buf.trim()) {
        const { events } = parseSseChunk(buf + "\n\n");
        for (const { event, data } of events) {
          applySseEvent(event, data, ctx);
        }
      }

      if (!ctx.doneReceived) {
        throw new Error("Соединение оборвалось до завершения ответа");
      }

      asst.classList.remove("streaming");
      flushBodyRender(ctx, { streaming: false });
      await loadChats();
      const active = state.chats.find((c) => c.id === chatId);
      if (active) els.chatTitle.textContent = active.title;
    } catch (e) {
      if (asst) asst.classList.remove("streaming");
      if (ctx._raf) {
        cancelAnimationFrame(ctx._raf);
        ctx._raf = 0;
      }
      if (ctx.bodyEl && ctx.metaSlot) {
        const errLine = "Ошибка: " + e.message;
        ctx.full = ctx.full ? ctx.full + "\n\n" + errLine : errLine;
        flushBodyRender(ctx, { streaming: false });
        els.statusLine.textContent = "Ошибка";
        ctx.metaSlot.innerHTML = `<div class="msg-meta"><span class="chip warn">error</span></div>`;
      } else {
        els.statusLine.textContent = "Ошибка: " + (e.message || e);
      }
    } finally {
      setBusy(false);
      els.input.focus();
    }
  }

  els.input.addEventListener("input", () => {
    autosize();
    els.btnSend.disabled = state.busy || !els.input.value.trim();
  });

  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  els.btnSend.addEventListener("click", send);
  els.btnNew.addEventListener("click", newChat);
  els.btnModels.addEventListener("click", openModelsModal);
  els.btnModelsClose.addEventListener("click", closeModelsModal);
  els.btnModelsHelp.addEventListener("click", toggleModelsHelp);
  els.btnModelsSave.addEventListener("click", saveModels);
  els.btnModelsAdd.addEventListener("click", addModelSlot);
  els.btnModelsReset.addEventListener("click", resetModels);
  els.messages.addEventListener("click", (e) => {
    const btn = e.target.closest(".code-copy");
    if (!btn || !els.messages.contains(btn)) return;
    e.preventDefault();
    copyCodeBlock(btn);
  });
  els.modelsModal.addEventListener("click", (e) => {
    if (e.target === els.modelsModal) closeModelsModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.modelsModal.hidden) closeModelsModal();
  });

  /* —— Monitor panel —— */

  function pushHistory(key, value) {
    const arr = state.metricsHistory[key];
    if (!arr) return;
    const n = value == null || Number.isNaN(value) ? null : Number(value);
    arr.push(n);
    while (arr.length > HISTORY_LEN) arr.shift();
  }

  function drawSparkline(canvas, values, color) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 200;
    const cssH = canvas.clientHeight || 36;
    if (canvas.width !== Math.floor(cssW * dpr) || canvas.height !== Math.floor(cssH * dpr)) {
      canvas.width = Math.floor(cssW * dpr);
      canvas.height = Math.floor(cssH * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const pts = values.filter((v) => v != null);
    if (pts.length < 2) {
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.35;
      ctx.beginPath();
      ctx.moveTo(0, cssH * 0.7);
      ctx.lineTo(cssW, cssH * 0.7);
      ctx.stroke();
      ctx.globalAlpha = 1;
      return;
    }

    const min = 0;
    const max = Math.max(100, ...pts);
    const pad = 2;
    const n = values.length;
    const coords = [];
    for (let i = 0; i < n; i++) {
      const v = values[i];
      if (v == null) {
        coords.push(null);
        continue;
      }
      const x = (i / Math.max(1, n - 1)) * cssW;
      const y = cssH - pad - ((v - min) / (max - min)) * (cssH - pad * 2);
      coords.push({ x, y });
    }

    ctx.fillStyle = color;
    ctx.globalAlpha = 0.12;
    ctx.beginPath();
    let fillStarted = false;
    let first = null;
    let last = null;
    for (const c of coords) {
      if (!c) {
        if (fillStarted && first && last) {
          ctx.lineTo(last.x, cssH);
          ctx.lineTo(first.x, cssH);
          ctx.closePath();
          ctx.fill();
          ctx.beginPath();
        }
        fillStarted = false;
        first = null;
        last = null;
        continue;
      }
      if (!fillStarted) {
        ctx.moveTo(c.x, c.y);
        first = c;
        fillStarted = true;
      } else {
        ctx.lineTo(c.x, c.y);
      }
      last = c;
    }
    if (fillStarted && first && last) {
      ctx.lineTo(last.x, cssH);
      ctx.lineTo(first.x, cssH);
      ctx.closePath();
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    ctx.beginPath();
    let strokeStarted = false;
    for (const c of coords) {
      if (!c) {
        strokeStarted = false;
        continue;
      }
      if (!strokeStarted) {
        ctx.moveTo(c.x, c.y);
        strokeStarted = true;
      } else {
        ctx.lineTo(c.x, c.y);
      }
    }
    ctx.stroke();
  }

  function pctBar(cls, pct) {
    const p = Math.max(0, Math.min(100, pct == null ? 0 : Number(pct)));
    return `<div class="monitor-bar ${cls}"><span style="width:${p}%"></span></div>`;
  }

  function fmtPct(v) {
    if (v == null || Number.isNaN(v)) return "—";
    return `${Number(v).toFixed(0)}%`;
  }

  function fmtTemp(v) {
    if (v == null || Number.isNaN(Number(v))) return "—";
    return `${Math.round(Number(v))}°C`;
  }

  function tempBar(cls, temp, scaleMax) {
    const max = scaleMax && scaleMax > 0 ? Number(scaleMax) : 100;
    const t = temp == null || Number.isNaN(Number(temp)) ? null : Number(temp);
    const p = t == null ? 0 : Math.max(0, Math.min(100, (t / max) * 100));
    let level = "";
    if (t != null) {
      if (t >= max * 0.95 || t >= 90) level = " hot";
      else if (t >= max * 0.85 || t >= 75) level = " warm";
      else level = " ok";
    }
    return `<div class="monitor-bar temp${level} ${cls}"><span style="width:${p}%"></span></div>`;
  }

  function sparkHeight(id) {
    const h = state.chartHeights[id];
    return h != null ? h : SPARK_H_DEFAULT;
  }

  function sparkHtml(id, title) {
    const h = sparkHeight(id);
    const t = title ? ` title="${escapeHtml(title)}"` : "";
    return `<div class="monitor-spark-wrap" data-spark="${escapeHtml(id)}" style="--spark-h:${h}px">
      <canvas class="monitor-spark" id="${escapeHtml(id)}"${t}></canvas>
      <div class="spark-resizer" data-spark="${escapeHtml(id)}" title="Тяните, чтобы изменить высоту"></div>
    </div>`;
  }

  function chartColor(varName, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
  }

  function paintSpark(id, values, color) {
    drawSparkline(document.getElementById(id), values, color);
  }

  function saveChartHeights() {
    try {
      localStorage.setItem(LS_CHART_HEIGHTS, JSON.stringify(state.chartHeights));
    } catch (_) {
      /* ignore */
    }
  }

  function loadChartHeights() {
    try {
      const raw = localStorage.getItem(LS_CHART_HEIGHTS);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return;
      for (const [k, v] of Object.entries(parsed)) {
        const n = Number(v);
        if (n >= SPARK_H_MIN && n <= SPARK_H_MAX) state.chartHeights[k] = Math.round(n);
      }
    } catch (_) {
      /* ignore */
    }
  }

  function fmtModelSize(mb) {
    if (mb == null || Number.isNaN(Number(mb))) return "—";
    const n = Number(mb);
    const gb = n / 1024;
    if (gb < 0.1) return `${Math.round(n)} МБ`;
    return `${gb.toFixed(1)} ГБ`;
  }

  function renderOllama(data, gpus) {
    const box = els.metricsOllama;
    if (!data || !data.ok) {
      box.innerHTML = `<div class="monitor-empty">Ollama: ${escapeHtml(
        (data && data.error) || "недоступна"
      )}</div>`;
      return;
    }
    const models = data.models || [];
    if (!models.length) {
      box.innerHTML = `<div class="monitor-empty">Нет загруженных моделей</div>`;
      return;
    }
    // size_vram/size — доля модели на GPU, не заполненность VRAM карты
    const gpuTotalMb =
      Array.isArray(gpus) && gpus[0] ? Number(gpus[0].mem_total_mb) || 0 : 0;
    box.innerHTML = models
      .map((m) => {
        const gpuPct = Math.round((m.gpu_ratio || 0) * 100);
        const cpuPct = Math.round((m.cpu_ratio || 0) * 100);
        const sizeMb = Number(m.size_mb) || 0;
        const vramMb = Number(m.size_vram_mb) || 0;
        const cpuMb = Math.max(0, sizeMb - vramMb);
        const cardPct =
          gpuTotalMb > 0 ? Math.min(100, Math.round((100 * vramMb) / gpuTotalMb)) : null;

        let placeShort;
        let layersLabel;
        if (m.place === "GPU" || gpuPct >= 99) {
          placeShort = "GPU";
          layersLabel = "слои: все на GPU";
        } else if (m.place === "CPU" || gpuPct <= 1) {
          placeShort = "CPU";
          layersLabel = "слои: все на CPU";
        } else {
          placeShort = "hybrid";
          layersLabel = `слои: ${gpuPct}% GPU · ${cpuPct}% CPU`;
        }

        const footprint =
          cpuMb > 1
            ? `${fmtModelSize(vramMb)} GPU + ${fmtModelSize(cpuMb)} RAM`
            : `${fmtModelSize(sizeMb)} модель`;
        const cardShare =
          cardPct != null ? ` · ${cardPct}% VRAM карты` : "";
        const detail = `${layersLabel} · ${footprint}${cardShare}`;
        const splitTitle = `Размещение слоёв модели (не заполненность памяти): ${layersLabel}`;

        return `<div class="monitor-card">
          <div class="monitor-metric-head">
            <span class="monitor-metric-name" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</span>
            <span class="monitor-metric-value">${escapeHtml(placeShort)}</span>
          </div>
          <div class="monitor-split" title="${escapeHtml(splitTitle)}">
            <span class="gpu-part" style="width:${gpuPct}%"></span>
            <span class="cpu-part" style="width:${cpuPct}%"></span>
          </div>
          <div class="monitor-place">${escapeHtml(detail)}</div>
        </div>`;
      })
      .join("");
  }

  function renderGpu(gpus) {
    const box = els.metricsGpu;
    if (!gpus || !gpus.length) {
      pushHistory("gpuUtil", null);
      pushHistory("gpuMem", null);
      box.innerHTML = `<div class="monitor-empty">Нет данных GPU (нужен nvidia-smi)</div>
        ${sparkHtml("spark-gpu", "Загрузка GPU %")}`;
      paintSpark("spark-gpu", state.metricsHistory.gpuUtil, chartColor("--chart-gpu", "#4a9eff"));
      return;
    }
    const g = gpus[0];
    pushHistory("gpuUtil", g.util_percent);
    pushHistory("gpuMem", g.mem_percent);
    const usedGb = (g.mem_used_mb / 1024).toFixed(1);
    const totalGb = (g.mem_total_mb / 1024).toFixed(1);
    box.innerHTML = `
      <div class="monitor-card">
        <div class="monitor-metric-head">
          <span class="monitor-metric-name" title="${escapeHtml(g.name)}">${escapeHtml(g.name)}</span>
          <span class="monitor-metric-value">${fmtPct(g.util_percent)}</span>
        </div>
        ${pctBar("gpu", g.util_percent)}
        <div class="monitor-metric-head">
          <span>VRAM</span>
          <span class="monitor-metric-value">${usedGb} / ${totalGb} ГБ · ${fmtPct(g.mem_percent)}</span>
        </div>
        ${pctBar("vram", g.mem_percent)}
        ${sparkHtml("spark-gpu", "Загрузка GPU %")}
        ${sparkHtml("spark-vram", "VRAM %")}
      </div>`;
    paintSpark("spark-gpu", state.metricsHistory.gpuUtil, chartColor("--chart-gpu", "#4a9eff"));
    paintSpark("spark-vram", state.metricsHistory.gpuMem, chartColor("--chart-vram", "#7ec699"));
  }

  function renderTemps(gpus) {
    const box = els.metricsTemp;
    if (!gpus || !gpus.length) {
      pushHistory("gpuTemp", null);
      pushHistory("memTemp", null);
      box.innerHTML = `<div class="monitor-empty">Нет данных температуры (нужен nvidia-smi)</div>
        ${sparkHtml("spark-temp-gpu", "GPU °C")}`;
      paintSpark(
        "spark-temp-gpu",
        state.metricsHistory.gpuTemp,
        chartColor("--chart-temp-gpu", "#f0a050")
      );
      return;
    }
    const g = gpus[0];
    pushHistory("gpuTemp", g.temp_gpu_c != null ? Number(g.temp_gpu_c) : null);
    pushHistory("memTemp", g.temp_memory_c != null ? Number(g.temp_memory_c) : null);
    const scale = g.temp_max_op_c || g.temp_shutdown_c || 100;
    const memScale = g.temp_memory_max_c || scale;
    const limits = [
      g.temp_target_c != null ? `цель ${fmtTemp(g.temp_target_c)}` : null,
      g.temp_max_op_c != null ? `макс ${fmtTemp(g.temp_max_op_c)}` : null,
      g.temp_slowdown_c != null ? `троттлинг ${fmtTemp(g.temp_slowdown_c)}` : null,
      g.temp_shutdown_c != null ? `выкл. ${fmtTemp(g.temp_shutdown_c)}` : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const memRow =
      g.temp_memory_c != null
        ? `${tempBar("temp-mem", g.temp_memory_c, memScale)}
        ${sparkHtml("spark-temp-mem", "Memory °C")}`
        : `<div class="monitor-place">не отдаёт драйвер (часто на GDDR; HBM обычно есть)</div>`;

    const tlimit =
      g.temp_tlimit_c != null
        ? `<div class="monitor-metric-head">
            <span class="monitor-metric-name">T.Limit</span>
            <span class="monitor-metric-value">${fmtTemp(g.temp_tlimit_c)}</span>
          </div>`
        : "";

    box.innerHTML = `
      <div class="monitor-card">
        <div class="monitor-metric-head">
          <span class="monitor-metric-name" title="${escapeHtml(g.name || "GPU")}">GPU (ядро)</span>
          <span class="monitor-metric-value">${fmtTemp(g.temp_gpu_c)}</span>
        </div>
        ${tempBar("temp-gpu", g.temp_gpu_c, scale)}
        ${sparkHtml("spark-temp-gpu", "GPU °C")}
        <div class="monitor-metric-head">
          <span class="monitor-metric-name" title="Температура цепей видеопамяти">Память (цепи VRAM)</span>
          <span class="monitor-metric-value">${fmtTemp(g.temp_memory_c)}</span>
        </div>
        ${memRow}
        ${tlimit}
        ${limits ? `<div class="monitor-place">${escapeHtml(limits)}</div>` : ""}
      </div>`;
    paintSpark(
      "spark-temp-gpu",
      state.metricsHistory.gpuTemp,
      chartColor("--chart-temp-gpu", "#f0a050")
    );
    if (g.temp_memory_c != null) {
      paintSpark(
        "spark-temp-mem",
        state.metricsHistory.memTemp,
        chartColor("--chart-temp-mem", "#e8c96a")
      );
    }
  }

  function renderRam(ram) {
    const box = els.metricsRam;
    const pct = ram && ram.percent != null ? ram.percent : null;
    pushHistory("ram", pct);
    if (pct == null) {
      box.innerHTML = `<div class="monitor-empty">Нет данных RAM</div>`;
      return;
    }
    box.innerHTML = `
      <div class="monitor-card">
        <div class="monitor-metric-head">
          <span class="monitor-metric-name">Оперативная память</span>
          <span class="monitor-metric-value">${ram.used_gb} / ${ram.total_gb} ГБ · ${fmtPct(pct)}</span>
        </div>
        ${pctBar("ram", pct)}
        ${sparkHtml("spark-ram", "RAM %")}
      </div>`;
    paintSpark("spark-ram", state.metricsHistory.ram, chartColor("--chart-ram", "#d4a574"));
  }

  function renderCpu(cpu) {
    const box = els.metricsCpu;
    const pct = cpu && cpu.percent != null ? cpu.percent : null;
    pushHistory("cpu", pct);
    if (pct == null) {
      box.innerHTML = `<div class="monitor-empty">Нет данных CPU</div>`;
      return;
    }
    const cores = cpu.count != null ? ` · ${cpu.count} ядр.` : "";
    box.innerHTML = `
      <div class="monitor-card">
        <div class="monitor-metric-head">
          <span class="monitor-metric-name">CPU${escapeHtml(cores)}</span>
          <span class="monitor-metric-value">${fmtPct(pct)}</span>
        </div>
        ${pctBar("cpu", pct)}
        ${sparkHtml("spark-cpu", "CPU %")}
      </div>`;
    paintSpark("spark-cpu", state.metricsHistory.cpu, chartColor("--chart-cpu", "#e06c75"));
  }

  async function refreshMetrics() {
    if (!state.panelOpen || state.metricsInflight) return;
    state.metricsInflight = true;
    try {
      const data = await api("/api/metrics");
      if (!state.panelOpen) return;
      renderOllama(data.ollama, data.gpu);
      renderGpu(data.gpu);
      renderTemps(data.gpu);
      renderRam(data.ram);
      renderCpu(data.cpu);
      if (data.note) {
        els.metricsNote.hidden = false;
        els.metricsNote.textContent = data.note;
      } else {
        els.metricsNote.hidden = true;
        els.metricsNote.textContent = "";
      }
    } catch (e) {
      if (state.panelOpen) {
        els.metricsOllama.innerHTML = `<div class="monitor-empty">Ошибка: ${escapeHtml(e.message)}</div>`;
      }
    } finally {
      state.metricsInflight = false;
    }
  }

  function stopMetricsPoll() {
    if (state.metricsTimer) {
      clearTimeout(state.metricsTimer);
      state.metricsTimer = null;
    }
  }

  function startMetricsPoll() {
    stopMetricsPoll();
    if (!state.panelOpen) return;
    const tick = async () => {
      await refreshMetrics();
      if (!state.panelOpen) return;
      const ms = Number(els.metricsInterval.value) || 2000;
      state.metricsTimer = setTimeout(tick, ms);
    };
    tick();
  }

  function panelMaxWidth() {
    // sidebar (~260) + минимальный чат (~320)
    return Math.max(PANEL_MIN, Math.min(PANEL_MAX_CAP, window.innerWidth - 580));
  }

  function applyPanelWidth(px) {
    const w = Math.max(PANEL_MIN, Math.min(panelMaxWidth(), Math.round(px)));
    state.panelWidth = w;
    document.documentElement.style.setProperty("--panel-width", `${w}px`);
    return w;
  }

  function syncToggleButton() {
    const btn = els.btnPanelToggle;
    if (!btn) return;
    if (state.panelOpen) {
      btn.textContent = "›";
      btn.title = "Свернуть панель";
      btn.setAttribute("aria-label", "Свернуть панель");
      btn.setAttribute("aria-expanded", "true");
    } else {
      btn.textContent = "‹";
      btn.title = "Показать монитор";
      btn.setAttribute("aria-label", "Показать монитор");
      btn.setAttribute("aria-expanded", "false");
    }
  }

  function setPanelOpen(open) {
    state.panelOpen = !!open;
    els.app.classList.toggle("panel-collapsed", !state.panelOpen);
    syncToggleButton();
    try {
      localStorage.setItem(LS_PANEL_OPEN, state.panelOpen ? "1" : "0");
    } catch (_) {
      /* ignore */
    }
    if (state.panelOpen) {
      applyPanelWidth(state.panelWidth);
      startMetricsPoll();
    } else {
      stopMetricsPoll();
    }
  }

  function initPanelResize() {
    let dragging = false;
    let startX = 0;
    let startW = 0;

    const onMove = (e) => {
      if (!dragging) return;
      const dx = startX - e.clientX;
      applyPanelWidth(startW + dx);
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      els.app.classList.remove("resizing");
      try {
        localStorage.setItem(LS_PANEL_WIDTH, String(state.panelWidth));
      } catch (_) {
        /* ignore */
      }
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };

    els.panelResizer.addEventListener("pointerdown", (e) => {
      if (!state.panelOpen) return;
      e.preventDefault();
      dragging = true;
      startX = e.clientX;
      startW = state.panelWidth;
      els.app.classList.add("resizing");
      els.panelResizer.setPointerCapture?.(e.pointerId);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });

    window.addEventListener("resize", () => {
      if (state.panelOpen) applyPanelWidth(state.panelWidth);
    });
  }

  function initSparkResize() {
    let dragging = false;
    let sparkId = null;
    let startY = 0;
    let startH = 0;

    const historyKey = {
      "spark-gpu": "gpuUtil",
      "spark-vram": "gpuMem",
      "spark-temp-gpu": "gpuTemp",
      "spark-temp-mem": "memTemp",
      "spark-ram": "ram",
      "spark-cpu": "cpu",
    };
    const colorKey = {
      "spark-gpu": ["--chart-gpu", "#4a9eff"],
      "spark-vram": ["--chart-vram", "#7ec699"],
      "spark-temp-gpu": ["--chart-temp-gpu", "#f0a050"],
      "spark-temp-mem": ["--chart-temp-mem", "#e8c96a"],
      "spark-ram": ["--chart-ram", "#d4a574"],
      "spark-cpu": ["--chart-cpu", "#e06c75"],
    };

    const repaint = (id) => {
      const hk = historyKey[id];
      const ck = colorKey[id];
      if (!hk || !ck) return;
      paintSpark(id, state.metricsHistory[hk], chartColor(ck[0], ck[1]));
    };

    const onMove = (e) => {
      if (!dragging || !sparkId) return;
      const dy = e.clientY - startY;
      const h = Math.max(SPARK_H_MIN, Math.min(SPARK_H_MAX, Math.round(startH + dy)));
      state.chartHeights[sparkId] = h;
      const wrap = els.monitorPanel.querySelector(`.monitor-spark-wrap[data-spark="${sparkId}"]`);
      if (wrap) wrap.style.setProperty("--spark-h", `${h}px`);
      repaint(sparkId);
    };

    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      sparkId = null;
      els.app.classList.remove("spark-resizing");
      saveChartHeights();
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };

    els.monitorPanel.addEventListener("pointerdown", (e) => {
      const handle = e.target.closest(".spark-resizer");
      if (!handle || !els.monitorPanel.contains(handle)) return;
      e.preventDefault();
      e.stopPropagation();
      sparkId = handle.getAttribute("data-spark");
      if (!sparkId) return;
      dragging = true;
      startY = e.clientY;
      startH = sparkHeight(sparkId);
      els.app.classList.add("spark-resizing");
      handle.setPointerCapture?.(e.pointerId);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });
  }

  function initMonitorPanel() {
    loadChartHeights();
    let open = true;
    let width = PANEL_DEFAULT;
    let interval = "2000";
    try {
      const o = localStorage.getItem(LS_PANEL_OPEN);
      if (o === "0") open = false;
      const w = Number(localStorage.getItem(LS_PANEL_WIDTH));
      if (w >= PANEL_MIN && w <= PANEL_MAX_CAP) width = w;
      const iv = localStorage.getItem(LS_METRICS_INTERVAL);
      if (iv && [...els.metricsInterval.options].some((opt) => opt.value === iv)) {
        interval = iv;
      }
    } catch (_) {
      /* ignore */
    }
    applyPanelWidth(width);
    els.metricsInterval.value = interval;
    els.btnPanelToggle.addEventListener("click", () => setPanelOpen(!state.panelOpen));
    els.metricsInterval.addEventListener("change", () => {
      try {
        localStorage.setItem(LS_METRICS_INTERVAL, els.metricsInterval.value);
      } catch (_) {
        /* ignore */
      }
      startMetricsPoll();
    });
    initPanelResize();
    initSparkResize();
    setPanelOpen(open);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopMetricsPoll();
      else if (state.panelOpen) startMetricsPoll();
    });
  }

  async function init() {
    initMonitorPanel();
    await refreshHealth();
    setInterval(refreshHealth, 30000);
    try {
      await loadSettings();
    } catch (_) {
      /* health уже заполнил select */
    }
    await loadChats();
    if (state.chats.length) {
      await selectChat(state.chats[0].id);
    } else {
      await newChat();
    }
    setBusy(false);
    els.input.focus();
  }

  init().catch((e) => {
    els.health.className = "health err";
    els.health.textContent = e.message;
  });
})();
