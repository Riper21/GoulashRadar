/* Supplier Radar frontend: search -> SSE pipeline -> cards -> compare. Notes in localStorage. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { cards: [], selected: new Set(), jobId: null, es: null };

/* ---------- theme ---------- */

const THEME_KEY = "sr-theme";
const THEMES = ["lifemart", "goulash"];

function applyTheme(theme) {
  const next = THEMES.includes(theme) ? theme : "lifemart";
  document.documentElement.setAttribute("data-theme", next);
  const btn = $("theme-switch");
  if (btn) btn.textContent = "Тема: " + (next === "lifemart" ? "LifeMart" : "Goulash");
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode */ }
}

(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem(THEME_KEY); } catch (e) { /* private mode */ }
  applyTheme(saved);
  const btn = $("theme-switch");
  if (btn) {
    btn.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "lifemart";
      const idx = THEMES.indexOf(cur);
      applyTheme(THEMES[(idx + 1) % THEMES.length]);
    });
  }
})();

/* ---------- search ---------- */

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const category = $("category").value.trim();
  const city = $("city").value.trim();
  if (!category || !city) return;
  runSearch(category, city);
});

async function runSearch(category, city) {
  resetResults();
  const ruOnly = $("ru-only").checked;
  $("search-btn").disabled = true;
  $("search-btn").textContent = "Ищем…";
  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, city, ru_only: ruOnly }),
    });
    const data = await res.json();
    if (data.job_id) listenJob(data.job_id, category, city);
  } catch (err) {
    console.error(err);
    showError("Сервис недоступен, попробуйте ещё раз.");
  } finally {
    $("search-btn").disabled = false;
    $("search-btn").textContent = "Найти поставщиков";
  }
}

function listenJob(jobId, category, city) {
  stopJobStream(); // drop any previous stream before opening the new one
  state.jobId = jobId;
  $("pipeline").classList.remove("hidden");
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  state.es = es;
  // gate: ignore stale events from a previous job (ES reconnects can resurrect them)
  const alive = () => state.es === es && state.jobId === jobId;

  es.addEventListener("stage", (e) => { if (alive()) setStage(JSON.parse(e.data)); });
  es.addEventListener("card", (e) => {
    if (!alive()) return;
    const d = JSON.parse(e.data);
    addCard(d.card, d.score, d.verdict, category, city);
  });
  es.addEventListener("card_update", (e) => {
    if (!alive()) return;
    const d = JSON.parse(e.data);
    updateCard(d.card, d.score, d.verdict);
  });
  es.addEventListener("progress", (e) => {
    if (!alive()) return;
    const d = JSON.parse(e.data);
    $("found-count").textContent = d.fetched;
  });
  es.addEventListener("error", (e) => {
    if (!alive()) return;
    if (e.data) showError(JSON.parse(e.data).message);
  });
  es.addEventListener("done", () => {
    if (!alive()) return;
    es.close();
    setStage({ key: "score", label: "Скорим и сортируем", progress: 1 });
    if (state.cards.length === 0) $("empty").classList.remove("hidden");
  });
}

function stopJobStream() {
  if (state.es) {
    state.es.close();
    state.es = null;
  }
  state.jobId = null;
}

/* ---------- pipeline ---------- */

function setStage(d) {
  const stages = document.querySelectorAll("#stages .stage");
  let seenActive = false;
  stages.forEach((el) => {
    const key = el.dataset.key;
    if (key === d.key) {
      el.className = "stage active";
      seenActive = true;
    } else if (!seenActive && el.classList.contains("active")) {
      el.className = "stage done";
    }
  });
  if (d.progress != null) $("progress-fill").style.width = Math.round(d.progress * 100) + "%";
}

function resetResults() {
  stopJobStream(); // cancel the old job's event stream, not just the visuals
  state.cards = [];
  state.selected = new Set();
  $("cards").innerHTML = "";
  $("found-count").textContent = "0";
  $("progress-fill").style.width = "0";
  $("empty").classList.add("hidden");
  $("results-head").classList.add("hidden");
  $("compare-view").classList.add("hidden");
  document.querySelectorAll("#stages .stage").forEach((el) => (el.className = "stage pending"));
  $("pipeline").classList.add("hidden");
}

function showError(msg) {
  const el = document.createElement("div");
  el.className = "supplier-card";
  el.style.gridColumn = "1/-1";
  el.innerHTML = `<div class="name" style="color:#e5484d">Ошибка: ${msg}</div>`;
  $("cards").prepend(el);
}

/* ---------- cards ---------- */

function addCard(card, score, verdict, category, city) {
  $("results-head").classList.remove("hidden");
  state.cards.push(card);
  const el = renderCard(card, score, verdict, category, city);
  $("cards").appendChild(el);
}

function updateCard(card, score, verdict) {
  const i = state.cards.findIndex((c) => c.identity_key === card.identity_key);
  if (i === -1) {
    addCard(card, score, verdict, card.categories && card.categories[0] || "", card.city || "");
    return;
  }
  state.cards[i] = card;
  const old = $(`card-${cssId(card.identity_key)}`);
  if (old) {
    const el = renderCard(card, score, verdict, "", "");
    el.id = `card-${cssId(card.identity_key)}`;
    old.replaceWith(el);
  }
}

function cssId(key) {
  return String(key).replace(/[^a-zA-Z0-9-]/g, "_");
}

function renderCard(card, score, verdict, category, city) {
  const el = document.createElement("div");
  el.className = "supplier-card";
  el.id = `card-${cssId(card.identity_key)}`;
  const phone = card.phones && card.phones.length ? card.phones[0].e164 || card.phones[0].raw : "—";
  const email = card.emails && card.emails.length ? card.emails[0].address : "—";
  const regionMatch = card.city && city && card.city.toLowerCase().includes(city.toLowerCase());
  const total = score ? score.total : Math.round((card.confidence || 0) * 100);
  const parts = score ? score.parts : null;
  const tier = total >= 70 ? "good" : total >= 50 ? "ok" : total >= 30 ? "low" : "poor";
  const note = getNote(card.identity_key);

  el.innerHTML = `
    <div class="row">
      <div class="name">${esc(card.name)}</div>
      <span class="score-badge ${tier}" title="${parts ? scoreTooltip(parts) : ""}">${total}</span>
    </div>
    ${verdict ? `<div class="verdict ${tier}">${esc(verdict)}</div>` : ""}
    <div class="row"><span class="k">Телефон</span><span>${esc(phone)}</span></div>
    <div class="row"><span class="k">Email</span><span>${esc(email)}</span></div>
    ${card.city ? `<div class="row"><span class="k">Город</span><span>${esc(card.city)}</span></div>` : ""}
    ${card.min_order ? `<div class="row"><span class="k">Мин. заказ</span><span>${esc(card.min_order)}</span></div>` : ""}
    ${card.price_range ? `<div class="row"><span class="k">Цена</span><span>${esc(card.price_range)}</span></div>` : ""}
    ${card.delivery ? `<div class="row"><span class="k">Доставка</span><span>${esc(card.delivery.slice(0, 90))}</span></div>` : ""}
    <div class="badges">
      ${card.inn ? `<span class="badge cert" title="ИНН проверен по чексумме">ИНН ✓</span>` : ""}
      ${(card.certs || []).map((c) => `<span class="badge cert">${esc(c)}</span>`).join("")}
      ${(card.categories || []).slice(0, 3).map((c) => `<span class="badge">${esc(c)}</span>`).join("")}
      ${(card.sources || []).length >= 2 ? `<span class="badge cert">${(card.sources || []).length} источника</span>` : ""}
    </div>
    ${note ? `<div class="user-note">📝 ${esc(note)}</div>` : ""}
    <div class="card-actions">
      ${card.website ? `<a href="${esc(card.website)}" target="_blank" rel="noopener">Сайт ↗</a>` : ""}
      ${sourceLink(card)}
      <button class="ghost note-btn" data-key="${esc(card.identity_key)}" data-name="${esc(card.name)}">Заметка</button>
      <label class="compare-check"><input type="checkbox" data-key="${esc(card.identity_key)}"> сравнить</label>
    </div>`;
  const cb = el.querySelector("input[type=checkbox]");
  cb.addEventListener("change", () => {
    if (cb.checked) state.selected.add(card.identity_key);
    else state.selected.delete(card.identity_key);
    updateCompareBtn();
  });
  const nb = el.querySelector(".note-btn");
  nb.addEventListener("click", () => openNoteDialog(card));
  return el;
}

function scoreTooltip(parts) {
  const labels = {
    completeness: "Полнота данных",
    verifiability: "Проверяемость (ИНН/сайт/источники)",
    contacts: "Контакты",
    relevance: "Релевантность (город/категория)",
  };
  return Object.entries(parts).map(([k, v]) => `${labels[k] || k}: ${v}`).join("\n");
}

function sourceLink(card) {
  const src = card.sources && card.sources[0];
  if (!src) return "";
  return `<a href="${esc(src.url)}" target="_blank" rel="noopener">Источник ↗</a>`;
}

function updateCompareBtn() {
  $("sel-count").textContent = state.selected.size;
  $("compare-btn").disabled = state.selected.size < 2;
}

/* ---------- compare ---------- */

$("export-btn").addEventListener("click", exportCsv);

$("compare-btn").addEventListener("click", async () => {
  const ids = [...state.selected].slice(0, 4).join(",");
  const res = await fetch(`/api/compare?ids=${encodeURIComponent(ids)}`);
  const data = await res.json();
  renderCompare(data.cards);
});

$("compare-close").addEventListener("click", () => $("compare-view").classList.add("hidden"));

const COMPARE_FIELDS = [
  ["name", "Название"],
  ["city", "Город"],
  ["phones", "Телефон"],
  ["emails", "Email"],
  ["website", "Сайт"],
  ["min_order", "Мин. заказ"],
  ["price_range", "Цена"],
  ["delivery", "Доставка"],
  ["certs", "Сертификаты"],
  ["categories", "Категории"],
];

function renderCompare(cards) {
  $("compare-view").classList.remove("hidden");
  const val = (c, f) => {
    let v = c[f];
    if (v == null) return "—";
    if (Array.isArray(v)) {
      if (f === "phones") v = v.map((p) => p.e164 || p.raw);
      if (f === "emails") v = v.map((p) => p.address);
      if (!v.length) return "—";
      return v.join(", ");
    }
    return String(v);
  };
  const values = COMPARE_FIELDS.map(([f]) => cards.map((c) => val(c, f)));
  const rows = COMPARE_FIELDS.map(([f, label], i) => {
    const vals = values[i];
    const uniq = new Set(vals.filter((v) => v !== "—"));
    const isDiff = uniq.size > 1;
    return `<tr>
      <td class="field-name">${label}</td>
      ${vals.map((v) => `<td class="${isDiff ? "diff" : ""}">${esc(v)}</td>`).join("")}
    </tr>`;
  }).join("");
  $("compare-table").innerHTML = `<table class="compare">
    <tr><th></th>${cards.map((c) => `<th>${esc(c.name)}</th>`).join("")}</tr>
    ${rows}</table>`;
  $("compare-view").scrollIntoView({ behavior: "smooth" });
}

/* ---------- utils ---------- */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- notes (localStorage) ---------- */

const NOTES_KEY = "sr_notes";

function getNotes() {
  try { return JSON.parse(localStorage.getItem(NOTES_KEY) || "{}"); } catch { return {}; }
}

function getNote(key) {
  return getNotes()[key] || "";
}

function setNote(key, text) {
  const notes = getNotes();
  if (text && text.trim()) notes[key] = text.trim().slice(0, 500);
  else delete notes[key];
  localStorage.setItem(NOTES_KEY, JSON.stringify(notes));
}

function openNoteDialog(card) {
  const current = getNote(card.identity_key);
  const text = prompt(`Заметка по «${card.name}»:\n(например: позвонить, спросить цену на 1 т, мин. партию)`, current);
  if (text === null) return; // cancel
  setNote(card.identity_key, text);
  // re-render this card to show/remove the note
  const i = state.cards.findIndex((c) => c.identity_key === card.identity_key);
  if (i !== -1) updateCard(state.cards[i], null, null);
}

/* ---------- export CSV ---------- */

// RFC 4180: quote if the cell has any delimiter/quote/newline; single-line always
function csvCell(v) {
  let s = v == null ? "" : String(v);
  s = s.replace(/\r?\n/g, " ").replace(/\r/g, " ").replace(/\t/g, " ").replace(/"/g, '""');
  if (/[;"\n]/.test(s)) s = `"${s}"`;
  return s;
}

function exportCsv() {
  const rows = [["Название", "Город", "Телефон", "Email", "Сайт", "Мин. заказ", "Цена", "Доставка", "ИНН", "Сертификаты", "Заметка", "Источник"]];
  for (const c of state.cards) {
    rows.push([
      c.name, c.city || "",
      (c.phones || []).map((p) => p.e164 || p.raw).join(", "),
      (c.emails || []).map((e) => e.address).join(", "),
      c.website || "", c.min_order || "", c.price_range || "",
      (c.delivery || "").slice(0, 120), c.inn || "",
      (c.certs || []).join(", "), getNote(c.identity_key),
      (c.sources || []).map((s) => s.url).join(", "),
    ]);
  }
  const csv = "\uFEFF" + rows.map((r) => r.map(csvCell).join(";")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "suppliers.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
