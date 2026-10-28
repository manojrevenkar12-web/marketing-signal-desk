// Small, CSP-safe behaviour: Alpine components are registered here (the CSP build cannot evaluate
// inline expressions) and HTMX transport errors become a visible, retryable message.
document.addEventListener("alpine:init", () => {
  window.Alpine.data("theme", () => ({
    mode: document.documentElement.dataset.theme || "system",
    init() {
      try {
        const saved = localStorage.getItem("msd-theme");
        if (saved) this.mode = saved;
      } catch (e) { /* storage blocked: follow the system */ }
      this.apply();
    },
    apply() {
      if (this.mode === "system") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = this.mode;
      try { localStorage.setItem("msd-theme", this.mode); } catch (e) { /* ignore */ }
    },
    cycle() {
      this.mode = this.mode === "system" ? "light" : this.mode === "light" ? "dark" : "system";
      this.apply();
    },
    get label() { return this.mode === "system" ? "Theme: system" : this.mode === "light" ? "Theme: light" : "Theme: dark"; },
  }));
  window.Alpine.data("disclosure", () => ({
    open: false,
    toggle() { this.open = !this.open; },
    close() { this.open = false; },
  }));
  window.Alpine.data("suggest", () => ({
    fill(event) {
      const box = document.getElementById("question");
      box.value = event.currentTarget.dataset.q;
      box.focus();
    },
  }));
});

function showProblem(text) {
  const el = document.getElementById("problem");
  if (!el) return;
  el.querySelector("[data-text]").textContent = text;
  el.hidden = false;
}

document.addEventListener("htmx:sendError", () => showProblem("The server did not answer. Check your connection and try again."));
document.addEventListener("htmx:responseError", (e) => {
  const s = e.detail.xhr.status;
  if (s === 422 || s === 409) return; // the fragment explains itself
  showProblem(s === 403 ? "Your role cannot do that here." : s === 404 ? "That no longer exists." : `Something went wrong on our side (HTTP ${s}). Try again.`);
});
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-dismiss-problem]")) document.getElementById("problem").hidden = true;
});
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-reload]")) location.reload();
});
