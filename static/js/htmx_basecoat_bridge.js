// Basecoat HTMX re-init bridge (UI-05, D-08).
// Basecoat v0.3.3's internal MutationObserver auto-inits on body subtree mutations;
// this listener is belt-and-suspenders if the observer is detached or loses a race.
document.body.addEventListener("htmx:afterSwap", function () {
  if (window.basecoat && typeof window.basecoat.initAll === "function") {
    window.basecoat.initAll();
  }
});

// Phase 6 — price-cell tick flash (STAGE-08, D-34 UI-SPEC).
// Diff every [data-price-cell] element after an HTMX swap or an SSE message;
// if the rendered text changed since the last observation, add a 150ms
// indigo ring flash. Cache keyed by the DOM element via WeakMap so old nodes
// are collectable.
(function () {
  var priceCache = new WeakMap();

  function flashChangedPriceCells(root) {
    var cells = (root && root.querySelectorAll)
      ? root.querySelectorAll("[data-price-cell]")
      : document.querySelectorAll("[data-price-cell]");
    cells.forEach(function (cell) {
      var now = (cell.innerText || "").trim();
      var prev = priceCache.get(cell);
      if (prev !== undefined && prev !== now) {
        cell.classList.add("ring-1", "ring-indigo-400/40");
        setTimeout(function () {
          cell.classList.remove("ring-1", "ring-indigo-400/40");
        }, 150);
      }
      priceCache.set(cell, now);
    });
  }

  document.body.addEventListener("htmx:afterSwap", function (e) {
    flashChangedPriceCells(e.target);
  });
  document.body.addEventListener("htmx:sseMessage", function () {
    flashChangedPriceCells(document);
  });
})();
