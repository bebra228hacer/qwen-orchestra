(() => {
  const $ = (sel) => document.querySelector(sel);

  const els = {
    chatList: $("#chat-list"),
    chatTitle: $("#chat-title"),
    messages: $("#messages"),
    input: $("#input"),
    btnSend: $("#btn-send"),
    btnNew: $("#btn-new"),
    btnClear: $("#btn-clear"),
    btnDelete: $("#btn-delete"),
    tierSelect: $("#tier-select"),
    health: $("#health"),
    statusLine: $("#status-line"),
    btnModels: $("#btn-models"),
    modelsModal: $("#models-modal"),
    modelsList: $("#models-list"),
    modelsStatus: $("#models-status"),
    btnModelsClose: $("#btn-models-close"),
    btnModelsSave: $("#btn-models-save"),
    btnModelsAdd: $("#btn-models-add"),
    btnModelsReset: $("#btn-models-reset"),
    addSlotModel: $("#add-slot-model"),
    addSlotId: $("#add-slot-id"),
    addSlotRank: $("#add-slot-rank"),
    addSlotLabel: $("#add-slot-label"),
    addSlotPrompt: $("#add-slot-prompt"),
    addSlotAuto: $("#add-slot-auto"),
  };

  const state = {
    chats: [],
    activeId: null,
    busy: false,
    selectGen: 0,
    ollamaModels: [],
    slots: [],
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

  function setBusy(busy) {
    state.busy = busy;
    els.btnSend.disabled = busy || !els.input.value.trim();
    els.input.disabled = busy;
    els.btnNew.disabled = busy;
    els.btnClear.disabled = busy || !state.activeId;
    els.btnDelete.disabled = busy || !state.activeId;
    els.tierSelect.disabled = busy;
    if (els.btnModels) els.btnModels.disabled = busy;
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
      const modelSel = document.createElement("select");
      modelSel.className = "tier-select slot-model";
      fillModelSelect(modelSel, slot.model);
      const rankInp = document.createElement("input");
      rankInp.className = "text-input rank-input slot-rank";
      rankInp.type = "number";
      rankInp.min = "0";
      rankInp.max = "9";
      rankInp.value = String(slot.rank ?? 1);
      rankInp.title = "rank (сила / эскалация)";
      meta.appendChild(modelSel);
      meta.appendChild(rankInp);
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
    renderModelsList(data.slots || []);
    populateTierSelect(data.slots || []);
    fillModelSelect(els.addSlotModel, els.addSlotModel.value || "");
    return data;
  }

  async function openModelsModal() {
    setModelsStatus("");
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
        body: JSON.stringify({ slots }),
      });
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
      setModelsStatus("Сохранено", "ok");
      await refreshHealth();
    } catch (e) {
      setModelsStatus(e.message, "err");
    }
  }

  async function addModelSlot() {
    const model = els.addSlotModel.value.trim();
    if (!model) {
      setModelsStatus("Выберите модель Ollama", "err");
      return;
    }
    setModelsStatus("Добавление…");
    try {
      const body = {
        model,
        label: els.addSlotLabel.value.trim() || null,
        router_prompt: els.addSlotPrompt.value.trim() || null,
        id: els.addSlotId.value.trim() || null,
        rank: Number(els.addSlotRank.value) || 2,
        router_auto: els.addSlotAuto.checked,
      };
      const data = await api("/api/settings/slots", {
        method: "POST",
        body: JSON.stringify(body),
      });
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
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
      renderModelsList(data.slots || []);
      populateTierSelect(data.slots || []);
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

  function renderChatList() {
    els.chatList.innerHTML = "";
    for (const c of state.chats) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chat-item" + (c.id === state.activeId ? " active" : "");
      btn.textContent = c.title || "New Chat";
      btn.addEventListener("click", () => selectChat(c.id));
      els.chatList.appendChild(btn);
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
    wrap.querySelector(".msg-body").textContent = content || "";
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

  async function clearChat() {
    if (!state.activeId || state.busy) return;
    await api(`/api/chats/${state.activeId}/clear`, { method: "POST", body: "{}" });
    els.messages.innerHTML = "";
    els.chatTitle.textContent = "New Chat";
    await loadChats();
  }

  async function deleteChat() {
    if (!state.activeId || state.busy) return;
    const id = state.activeId;
    await api(`/api/chats/${id}`, { method: "DELETE" });
    state.activeId = null;
    els.messages.innerHTML = "";
    els.chatTitle.textContent = "New Chat";
    await loadChats();
    if (state.chats.length) {
      await selectChat(state.chats[0].id);
    } else {
      renderChatList();
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
        /* keep string */
      }
      events.push({ event, data });
    }
    return { events, rest };
  }

  function applySseEvent(event, data, ctx) {
    const { bodyEl, toolsEl, metaSlot } = ctx;
    if (event === "meta") {
      if (data.phase === "retry" || data.phase === "restore") {
        ctx.full = "";
        bodyEl.textContent = "";
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
        checked: data.checked != null ? !!data.checked : !!data.ok,
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
      bodyEl.textContent = ctx.full;
      els.messages.scrollTop = els.messages.scrollHeight;
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
        bodyEl.textContent = ctx.full;
      }
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
    try {
      chatId = await ensureChat();
    } catch (e) {
      setBusy(false);
      els.statusLine.textContent = "Ошибка";
      return;
    }

    els.input.value = "";
    autosize();
    appendMessage("user", text);

    const asst = appendMessage("assistant", "", null, { streaming: true });
    const bodyEl = asst.querySelector(".msg-body");
    const toolsEl = asst.querySelector(".msg-tools");
    const metaSlot = asst.querySelector(".msg-meta-slot");
    const ctx = { liveMeta: {}, full: "", bodyEl, toolsEl, metaSlot };

    try {
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
      if (buf.trim()) {
        const { events } = parseSseChunk(buf + "\n\n");
        for (const { event, data } of events) {
          applySseEvent(event, data, ctx);
        }
      }

      asst.classList.remove("streaming");
      await loadChats();
      const active = state.chats.find((c) => c.id === chatId);
      if (active) els.chatTitle.textContent = active.title;
    } catch (e) {
      asst.classList.remove("streaming");
      if (!bodyEl.textContent) bodyEl.textContent = "Ошибка: " + e.message;
      else bodyEl.textContent += "\n\nОшибка: " + e.message;
      els.statusLine.textContent = "Ошибка";
      metaSlot.innerHTML = `<div class="msg-meta"><span class="chip warn">error</span></div>`;
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
  els.btnClear.addEventListener("click", clearChat);
  els.btnDelete.addEventListener("click", deleteChat);
  els.btnModels.addEventListener("click", openModelsModal);
  els.btnModelsClose.addEventListener("click", closeModelsModal);
  els.btnModelsSave.addEventListener("click", saveModels);
  els.btnModelsAdd.addEventListener("click", addModelSlot);
  els.btnModelsReset.addEventListener("click", resetModels);
  els.modelsModal.addEventListener("click", (e) => {
    if (e.target === els.modelsModal) closeModelsModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.modelsModal.hidden) closeModelsModal();
  });

  async function init() {
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
