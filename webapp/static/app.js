"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 3500);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* пустой ответ */ }
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || res.statusText);
    throw new Error(detail);
  }
  return data;
}

// Даты приходят в ISO (UTC) и показываются в часовом поясе браузера.
function fmtDt(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function fmtDur(sec) {
  if (sec === null || sec === undefined) return "—";
  if (sec < 60) return Math.round(sec) + " с";
  return Math.floor(sec / 60) + " мин " + Math.round(sec % 60) + " с";
}

const STATUS_TITLES = { success: "успех", error: "ошибка", running: "выполняется" };
const TRIGGER_TITLES = { manual: "вручную", schedule: "по расписанию" };

async function refreshStatus() {
  let data;
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    data = await res.json();
  } catch (e) {
    return; // сеть моргнула — обновимся в следующий тик
  }

  const serverNow = $("#server-now");
  if (serverNow) {
    serverNow.textContent =
      new Date(data.server_now).toLocaleTimeString("ru-RU", { timeZone: "UTC", hour: "2-digit", minute: "2-digit" }) + " UTC";
  }

  const debugBadge = $("#debug-badge");
  if (debugBadge) debugBadge.hidden = !data.debug_publish;
  const debugToggle = $("#debug-toggle");
  if (debugToggle && document.activeElement !== debugToggle) debugToggle.checked = data.debug_publish;

  if (document.body.dataset.page !== "dashboard") return;

  $("#stat-enabled").textContent = data.enabled_count;
  $("#stat-running").textContent = data.running_count;

  for (const g of data.generators) {
    const card = document.querySelector(`.gen-card[data-key="${g.key}"]`);
    if (!card) continue;

    const dot = card.querySelector(".js-dot");
    let state = "idle", dotTitle = "ещё не запускался";
    if (g.running) { state = "run"; dotTitle = "выполняется"; }
    else if (g.last_run?.status === "success") { state = "ok"; dotTitle = "последний запуск успешен"; }
    else if (g.last_run?.status === "error") { state = "err"; dotTitle = "последний запуск с ошибкой"; }
    dot.className = `dot js-dot dot-${state}`;
    dot.title = dotTitle;
    card.classList.remove("state-ok", "state-err", "state-run", "state-idle");
    card.classList.add(`state-${state}`);

    card.querySelector(".js-next").textContent = g.enabled ? fmtDt(g.next_run) : "выключено";
    card.querySelector(".js-last").textContent = g.last_run
      ? `${fmtDt(g.last_run.started_at)} · ${STATUS_TITLES[g.last_run.status] || g.last_run.status}`
      : "—";

    const btn = card.querySelector(".js-run");
    btn.disabled = g.running;
    btn.textContent = g.running ? "⏳ Выполняется…" : "▶ Запустить";
  }

  // пересортировка карточек по времени расписания (payload уже отсортирован);
  // не трогаем DOM, пока фокус внутри сетки (например, редактируется время)
  const grid = document.querySelector(".gen-grid");
  if (grid && !grid.contains(document.activeElement)) {
    for (const g of data.generators) {
      const card = grid.querySelector(`.gen-card[data-key="${g.key}"]`);
      if (card) grid.appendChild(card);
    }
  }

  renderRecentRuns(data.recent_runs);
}

function renderRecentRuns(runs) {
  const tbody = document.querySelector("#recent-runs tbody");
  if (!tbody) return;
  if (!runs.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">Запусков ещё не было</td></tr>`;
    return;
  }
  tbody.innerHTML = runs.map(r => `
    <tr onclick="location.href='/runs'" style="cursor:pointer">
      <td class="nowrap">${fmtDt(r.started_at)}</td>
      <td>${escapeHtml(r.title)}</td>
      <td class="muted">${TRIGGER_TITLES[r.trigger] || escapeHtml(r.trigger)}</td>
      <td><span class="badge badge-${escapeHtml(r.status)}">${STATUS_TITLES[r.status] || escapeHtml(r.status)}</span></td>
      <td class="nowrap">${fmtDur(r.duration)}</td>
    </tr>`).join("");
}

function bindDashboard() {
  const debugToggle = $("#debug-toggle");
  if (debugToggle) debugToggle.addEventListener("change", async () => {
    try {
      const r = await postJSON("/api/debug", { enabled: debugToggle.checked });
      toast(r.debug_publish
        ? "🐞 Debug-режим включён: публикации идут в отладочный чат"
        : "Debug-режим выключен: публикации идут в боевой канал");
    } catch (e) {
      debugToggle.checked = !debugToggle.checked;
      toast("Ошибка: " + e.message, true);
    }
    refreshStatus();
  });

  $$(".gen-card").forEach(card => {
    const key = card.dataset.key;
    const title = card.dataset.title;

    const saveSchedule = async () => {
      const enabled = card.querySelector(".js-enabled").checked;
      const [hour, minute] = card.querySelector(".js-time").value.split(":").map(Number);
      if (Number.isNaN(hour) || Number.isNaN(minute)) {
        toast("Укажите время запуска", true);
        return;
      }
      try {
        const res = await fetch(`/api/schedule/${key}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled, hour, minute }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || res.statusText);
        const hhmm = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
        toast(enabled ? `«${title}»: ежедневно в ${hhmm} UTC` : `«${title}»: расписание выключено`);
        refreshStatus();
      } catch (e) {
        toast("Ошибка сохранения: " + e.message, true);
        refreshStatus();
      }
    };

    card.querySelector(".js-enabled").addEventListener("change", saveSchedule);
    card.querySelector(".js-time").addEventListener("change", saveSchedule);

    card.querySelector(".js-run").addEventListener("click", async () => {
      if (!confirm(`Запустить «${title}» сейчас? Результат будет опубликован в Telegram.`)) return;
      try {
        const res = await fetch(`/api/run/${key}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || res.statusText);
        toast(`«${title}» запущен`);
        refreshStatus();
        openDrawer(key); // сразу показываем живой лог запуска
      } catch (e) {
        toast("Не удалось запустить: " + e.message, true);
      }
    });
  });
}

// ------------------------------------------------------- панель задачи (drawer)

const drawer = { key: null, title: "", timer: null };

function openDrawer(key, opts = {}) {
  if (!$("#drawer")) return;
  const modal = opts.modal !== false; // немодальный режим — страница остаётся активной
  drawer.key = key;
  if (modal) {
    $("#drawer-overlay").hidden = false;
    requestAnimationFrame(() => $("#drawer-overlay").classList.add("open"));
  } else {
    $("#drawer-overlay").classList.remove("open");
    $("#drawer-overlay").hidden = true;
  }
  $("#drawer").hidden = false;
  requestAnimationFrame(() => $("#drawer").classList.add("open"));
  const logEl = $("#drawer-log");
  logEl.textContent = "Загрузка…";
  delete logEl.dataset.loaded;
  refreshDrawer();
  clearInterval(drawer.timer);
  drawer.timer = setInterval(refreshDrawer, 3500);
}

function closeDrawer() {
  if (!$("#drawer") || drawer.key === null) return;
  drawer.key = null;
  clearInterval(drawer.timer);
  $("#drawer-overlay").classList.remove("open");
  $("#drawer").classList.remove("open");
  setTimeout(() => {
    if (drawer.key === null) { $("#drawer-overlay").hidden = true; $("#drawer").hidden = true; }
  }, 220);
}

async function refreshDrawer() {
  if (!drawer.key) return;
  let d;
  try {
    const res = await fetch(`/api/jobs/${drawer.key}/card`);
    if (!res.ok) return;
    d = await res.json();
  } catch (e) { return; }
  if (d.key !== drawer.key) return;
  drawer.title = d.title;

  $("#drawer-title").textContent =
    `${d.title}${d.media === "video" ? " 🎬" : ""}${d.debug ? " 🐞" : ""}${d.archived ? " 📦" : ""}`;
  const parts = [];
  if (d.running) parts.push("⏳ выполняется…");
  else if (d.last_run) parts.push(`${STATUS_TITLES[d.last_run.status] || d.last_run.status} · ${fmtDt(d.last_run.started_at)} · ${fmtDur(d.last_run.duration)}`);
  else parts.push("ещё не запускалась");
  parts.push(d.enabled && d.next_run ? `следующий: ${fmtDt(d.next_run)}` : "расписание выключено");
  $("#drawer-sub").textContent = parts.join("  ·  ");

  const runBtn = $("#drawer-run");
  runBtn.disabled = d.running || d.archived;
  runBtn.textContent = d.running ? "⏳ Выполняется…" : (d.archived ? "📦 В архиве" : "▶ Запустить");

  const dbg = $("#drawer-debug");
  if (document.activeElement !== dbg) dbg.checked = d.debug;
  dbg.disabled = d.pipeline === "legacy";
  $("#drawer-debug-wrap").title = d.pipeline === "legacy"
    ? "Legacy-раннер публикует напрямую — debug не действует"
    : "Публиковать эту задачу в отладочный чат";

  $("#drawer-settings").href = `/jobs/${d.key}`;
  $("#drawer-full-log").href = `/logs?job=${d.key}`;

  $("#drawer-images").innerHTML = d.images.map(im => `
    <a href="/history/${im.id}" title="${escapeHtml(im.date)}">
      ${im.is_video
        ? `<video src="${im.url}" muted preload="metadata"></video>`
        : `<img src="${im.url}" loading="lazy" alt="">`}
    </a>`).join("");

  const logEl = $("#drawer-log");
  const wasAtBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  logEl.textContent = d.log || "(запусков ещё не было)";
  if (wasAtBottom || !logEl.dataset.loaded) {
    logEl.scrollTop = logEl.scrollHeight;
    logEl.dataset.loaded = "1";
  }
  $("#drawer-log-state").textContent = d.running ? "· идёт запуск, лог обновляется" : "";
}

function bindDrawer() {
  if (!$("#drawer")) return;
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-overlay").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  $("#drawer-run").addEventListener("click", async () => {
    if (!confirm(`Запустить «${drawer.title}» сейчас? Результат будет опубликован в Telegram.`)) return;
    try {
      await postJSON(`/api/run/${drawer.key}`, {});
      toast(`«${drawer.title}» запущен — лог ниже живой`);
      refreshDrawer();
      refreshStatus();
    } catch (e) { toast("Не удалось запустить: " + e.message, true); }
  });

  $("#drawer-debug").addEventListener("change", async e => {
    try {
      await postJSON(`/api/jobs/${drawer.key}`, { publish: { debug: e.target.checked } });
      toast(e.target.checked
        ? "🐞 Задача публикует в отладочный чат"
        : "Задача публикует в боевой канал");
      refreshDrawer();
      refreshStatus();
    } catch (err) {
      e.target.checked = !e.target.checked;
      toast("Ошибка: " + err.message, true);
    }
  });

  $$(".gen-card").forEach(card => card.addEventListener("click", e => {
    if (e.target.closest("button, a, input, label, select")) return;
    openDrawer(card.dataset.key);
  }));
}

function bindRunsPage() {
  $$(".js-log").forEach(btn => {
    btn.addEventListener("click", async () => {
      const row = document.getElementById("log-" + btn.dataset.run);
      if (!row) return;
      if (!row.hidden) { row.hidden = true; return; }
      const pre = row.querySelector("pre");
      if (!pre.textContent) {
        try {
          const res = await fetch(`/api/runs/${btn.dataset.run}/logs`);
          pre.textContent = res.ok ? await res.text() : "Не удалось получить лог";
        } catch (e) {
          pre.textContent = "Не удалось получить лог";
        }
      }
      row.hidden = false;
    });
  });
}

// ---------------------------------------------------------------- провайдеры

function bindProvidersPage() {
  $$(".js-health").forEach(btn => btn.addEventListener("click", async () => {
    const el = document.getElementById(`health-${btn.dataset.kind}-${btn.dataset.name}`);
    el.textContent = "проверяю…";
    el.className = "health";
    try {
      const r = await postJSON(`/api/providers/${btn.dataset.kind}/${btn.dataset.name}/health`, {});
      el.textContent = (r.ok ? "✅ " : "❌ ") + r.message;
      el.className = "health " + (r.ok ? "ok" : "err");
    } catch (e) {
      el.textContent = "❌ " + e.message;
      el.className = "health err";
    }
  }));

  $$(".js-toggle-edit").forEach(btn => btn.addEventListener("click", () => {
    const row = document.getElementById(btn.dataset.target);
    if (row) row.hidden = !row.hidden;
  }));

  $$(".js-save-provider").forEach(btn => btn.addEventListener("click", async () => {
    const ta = document.querySelector(
      `textarea.cfg-edit[data-kind="${btn.dataset.kind}"][data-name="${btn.dataset.name}"]`);
    let config;
    try { config = JSON.parse(ta.value); }
    catch (e) { toast("Невалидный JSON: " + e.message, true); return; }
    try {
      await postJSON(`/api/providers/${btn.dataset.kind}/${btn.dataset.name}`, { config });
      toast(`Провайдер «${btn.dataset.name}» сохранён`);
    } catch (e) { toast("Ошибка: " + e.message, true); }
  }));

  const chainBtn = $("#save-chain");
  if (chainBtn) chainBtn.addEventListener("click", async () => {
    const chain = $("#llm-chain").value.split(",").map(s => s.trim()).filter(Boolean);
    try {
      await postJSON("/api/providers/llm-chain", { chain });
      toast("Цепочка LLM сохранена: " + chain.join(" → "));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

// ---------------------------------------------------------------------- логи

function bindLogsPage() {
  const output = $("#log-output");
  if (!output) return;
  let timer = null;

  async function refresh() {
    const params = new URLSearchParams({
      lines: $("#log-lines").value,
      level: $("#log-level").value,
      q: $("#log-q").value,
      job: $("#log-job").value,
      runs: $("#log-runs").value,
    });
    try {
      const res = await fetch("/api/logs?" + params.toString());
      if (!res.ok) return;
      const wasAtBottom =
        output.scrollHeight - output.scrollTop - output.clientHeight < 40;
      output.textContent = await res.text();
      if (wasAtBottom || !output.dataset.loaded) {
        output.scrollTop = output.scrollHeight;
        output.dataset.loaded = "1";
      }
    } catch (e) { /* сеть моргнула */ }
  }

  function applyAuto() {
    if (timer) { clearInterval(timer); timer = null; }
    if ($("#log-auto").checked) timer = setInterval(refresh, 5000);
  }

  ["log-level", "log-lines", "log-runs"].forEach(id => $("#" + id).addEventListener("change", refresh));
  $("#log-job").addEventListener("change", () => {
    $("#log-runs").hidden = !$("#log-job").value;
    delete output.dataset.loaded; // прокрутить вниз при смене источника
    refresh();
  });
  $("#log-q").addEventListener("input", () => {
    clearTimeout(output._qTimer);
    output._qTimer = setTimeout(refresh, 400);
  });
  $("#log-refresh").addEventListener("click", refresh);
  $("#log-auto").addEventListener("change", applyAuto);

  refresh();
  applyAuto();
}

// ----------------------------------------------------------- настройки задачи

function bindJobSettingsPage() {
  const form = $("#job-form");
  if (!form) return;
  const key = form.dataset.key;

  $("#jf-image-provider").addEventListener("change", async e => {
    try {
      await postJSON(`/api/jobs/${key}`, { image: { provider: e.target.value, params: {} } });
      location.reload(); // форма параметров перерисуется под нового провайдера
    } catch (err) { toast("Ошибка смены провайдера: " + err.message, true); }
  });

  function collectJobForm() {
    const params = {};
    $$(".jf-param").forEach(el => {
      params[el.dataset.key] = el.dataset.kind === "bool" ? el.checked : el.value;
    });
    return {
      prompt: {
        system: $("#jf-prompt-system").value,
        user: $("#jf-prompt-user").value,
      },
      llm: {
        provider: $("#jf-llm-provider").value || null,
        temperature: parseFloat($("#jf-temperature").value),
        max_theme: parseInt($("#jf-max-theme").value, 10),
        max_category: parseInt($("#jf-max-category").value, 10),
      },
      image: { provider: $("#jf-image-provider").value, params },
      watermark: { enabled: $("#jf-wm-enabled").checked, letter: $("#jf-wm-letter").value },
      publish: {
        retries: parseInt($("#jf-retries").value, 10),
        chat_id: $("#jf-chat-id").value || null,
        debug: $("#jf-debug").checked,
      },
    };
  }

  // «закончил»: сохранить и вернуться на дашборд
  $("#jf-save").addEventListener("click", async () => {
    try {
      const r = await postJSON(`/api/jobs/${key}`, collectJobForm());
      const message = r.prompt_saved
        ? `Сохранено, промпт — версия ${r.prompt_version}`
        : "Настройки сохранены";
      location.href = "/?saved=" + encodeURIComponent(message);
    } catch (e) { toast("Ошибка сохранения: " + e.message, true); }
  });

  // цикл подбора промпта: сохранить, запустить, живой лог здесь же
  $("#jf-save-run").addEventListener("click", async () => {
    const debugOn = $("#jf-debug").checked;
    if (!debugOn && !confirm("🐞 Debug у задачи выключен — результат уйдёт в боевой канал. Запустить?")) return;
    const btn = $("#jf-save-run");
    btn.disabled = true;
    try {
      const r = await postJSON(`/api/jobs/${key}`, collectJobForm());
      const saved = r.prompt_saved ? `Сохранено (промпт v${r.prompt_version})` : "Сохранено";
      try {
        await postJSON(`/api/run/${key}`, {});
        toast(`${saved}, запущено — лог справа`);
      } catch (e) {
        if (!e.message.includes("уже выполняется")) throw e;
        toast(`${saved}. Предыдущий запуск ещё идёт (лог справа) — изменения применятся к следующему`);
      }
      openDrawer(key, { modal: false }); // форма остаётся активной, лог сбоку
    } catch (e) {
      toast("Ошибка: " + e.message, true);
    } finally {
      btn.disabled = false;
    }
  });
}

function bindArchiveButtons() {
  $$(".js-archive").forEach(btn => btn.addEventListener("click", async () => {
    const toArchive = btn.dataset.to === "1";
    if (toArchive && !confirm(`Убрать «${btn.dataset.title}» в архив? Расписание будет отключено, изображения останутся в галерее.`)) return;
    try {
      await postJSON(`/api/jobs/${btn.dataset.key}/archive`, { archived: toArchive });
      location.reload();
    } catch (e) { toast("Ошибка: " + e.message, true); }
  }));
}

document.addEventListener("DOMContentLoaded", () => {
  $$(".js-dt").forEach(el => { el.textContent = fmtDt(el.dataset.iso); });
  bindArchiveButtons();

  // тост после редиректа (например, «Настройки сохранены» со страницы задачи)
  const savedMessage = new URLSearchParams(location.search).get("saved");
  if (savedMessage) {
    toast(savedMessage);
    history.replaceState(null, "", location.pathname);
  }
  refreshStatus();
  bindDrawer(); // панель задачи доступна на всех страницах
  const page = document.body.dataset.page;
  if (page === "dashboard") {
    bindDashboard();
    setInterval(refreshStatus, 5000);
  }
  if (page === "runs") bindRunsPage();
  if (page === "providers") bindProvidersPage();
  if (page === "job_settings") bindJobSettingsPage();
  if (page === "logs") bindLogsPage();
});
