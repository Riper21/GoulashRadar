/* Supplier Radar popup: search -> poll job -> cards. Same API as the web app. */
"use strict";

const API_KEY_STORAGE = "api_url";
const THEME_STORAGE = "theme";
const THEMES = ["lifemart", "goulash"];
const DEFAULT_API = "http://127.0.0.1:8000";

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  $("search-form").addEventListener("submit", onSearch);
  $("open-full").addEventListener("click", openFull);
  $("theme-btn").addEventListener("click", toggleTheme);
  chrome.storage.sync.get([API_KEY_STORAGE, THEME_STORAGE], (cfg) => {
    applyTheme(cfg[THEME_STORAGE] || "lifemart");
    if (!cfg[API_KEY_STORAGE]) {
      // first run: show hint to configure the API URL
      setStatus("Укажите адрес сервера: ПКМ по иконке → Настройки");
    }
  });
});

/* ---------- theme ---------- */

function applyTheme(name) {
  document.documentElement.dataset.theme = THEMES.includes(name) ? name : "lifemart";
  $("theme-btn").textContent = document.documentElement.dataset.theme === "lifemart"
    ? "◧ Goulash"
    : "◧ Жизньмарт";
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "lifemart" ? "goulash" : "lifemart";
  applyTheme(next);
  chrome.storage.sync.set({ [THEME_STORAGE]: next });
}

function api() {
  return new Promise((resolve) => {
    chrome.storage.sync.get([API_KEY_STORAGE], (cfg) => {
      resolve((cfg[API_KEY_STORAGE] || DEFAULT_API).replace(/\/$/, ""));
    });
  });
}

async function onSearch(e) {
  e.preventDefault();
  const category = $("category").value.trim();
  const city = $("city").value.trim();
  if (!category || !city) return;

  const base = await api();
  $("search-btn").disabled = true;
  $("search-btn").textContent = "Ищем…";
  $("cards").innerHTML = "";
  setStatus("Запрос к поисковым движкам…");
  try {
    const res = await fetch(`${base}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, city, ru_only: document.getElementById("ru-only").checked }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    await pollAndRender(base, data.job_id);
  } catch (err) {
    setStatus(`Ошибка: ${err.message}. Сервер запущен? Адрес верный?`);
  } finally {
    $("search-btn").disabled = false;
    $("search-btn").textContent = "Найти поставщиков";
  }
}

async function pollAndRender(base, jobId) {
  const started = Date.now();
  for (;;) {
    const res = await fetch(`${base}/api/jobs/${jobId}`);
    const job = await res.json();
    if (job.status === "done" || job.status === "error") {
      if (job.status === "error") throw new Error(job.error || "job failed");
      const snap = await (await fetch(`${base}/api/jobs/${jobId}/suppliers`)).json();
      renderCards(snap.suppliers || []);
      return;
    }
    const waited = Math.round((Date.now() - started) / 1000);
    setStatus(`Обходим сайты поставщиков… ${waited} с`);
    await sleep(2000);
  }
}

function renderCards(suppliers) {
  setStatus("");
  if (!suppliers.length) {
    $("cards").innerHTML = '<div class="empty">Ничего не нашлось — попробуйте другую формулировку</div>';
    return;
  }
  const tpl = $("card-tpl");
  for (const s of suppliers) {
    const card = s.card;
    const node = tpl.content.cloneNode(true);
    const total = s.score ? s.score.total : 0;
    const tier = total >= 70 ? "good" : total >= 50 ? "ok" : total >= 30 ? "low" : "poor";

    node.querySelector(".name").textContent = card.name;
    const sc = node.querySelector(".score");
    sc.textContent = total;
    sc.className = `score ${tier}`;
    node.querySelector(".verdict").textContent = s.verdict || "";
    node.querySelector(".phone").textContent =
      (card.phones && card.phones.length && (card.phones[0].e164 || card.phones[0].raw)) || "—";
    node.querySelector(".minorder").textContent = card.min_order || "—";

    const links = node.querySelector(".links");
    if (card.website) addLink(links, card.website, "сайт ↗");
    const src = card.sources && card.sources[0];
    if (src) addLink(links, src.url, "источник ↗");

    $("cards").appendChild(node);
  }
}

function addLink(container, href, label) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = label;
  container.appendChild(a);
}

function setStatus(text) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("hidden", !text);
}

function openFull(e) {
  e.preventDefault();
  api().then((base) => chrome.tabs.create({ url: base }));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
