"use strict";

const API_KEY_STORAGE = "api_url";
const THEME_STORAGE = "theme";

document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get([API_KEY_STORAGE, THEME_STORAGE], (cfg) => {
    document.getElementById("api-url").value = cfg[API_KEY_STORAGE] || "http://127.0.0.1:8000";
    document.getElementById("theme-select").value = cfg[THEME_STORAGE] || "lifemart";
  });
  document.getElementById("options-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const api = document.getElementById("api-url").value.trim().replace(/\/$/, "");
    const theme = document.getElementById("theme-select").value;
    chrome.storage.sync.set({ [API_KEY_STORAGE]: api, [THEME_STORAGE]: theme }, () => {
      const el = document.getElementById("saved");
      el.classList.remove("hidden");
      setTimeout(() => el.classList.add("hidden"), 1500);
    });
  });
});
