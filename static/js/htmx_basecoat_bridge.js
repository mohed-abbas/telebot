// Basecoat HTMX re-init bridge (UI-05, D-08).
// Basecoat v0.3.3's internal MutationObserver auto-inits on body subtree mutations;
// this listener is belt-and-suspenders if the observer is detached or loses a race.
document.body.addEventListener("htmx:afterSwap", function () {
  if (window.basecoat && typeof window.basecoat.initAll === "function") {
    window.basecoat.initAll();
  }
});
