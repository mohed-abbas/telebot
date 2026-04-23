// Basecoat HTMX re-init bridge (UI-05, D-08).
// Only initialize components WITHIN the swapped element, not the whole document.
// Calling initAll() after every swap resets sidebar state (closes mobile nav).
document.body.addEventListener("htmx:afterSwap", function (evt) {
  if (window.basecoat && evt.detail && evt.detail.target) {
    // Re-init only components inside the swap target
    var target = evt.detail.target;
    ["dropdown-menu", "popover", "select", "tabs", "toast"].forEach(function(comp) {
      var selector = "." + comp + ":not([data-" + comp + "-initialized])";
      target.querySelectorAll(selector).forEach(function(el) {
        window.basecoat.init(comp);
      });
    });
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
