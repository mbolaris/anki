(function () {
  "use strict";

  function normalize(value) {
    if (typeof value !== "string") {
      return "";
    }
    return value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const filterInput = document.querySelector('[data-role="deck-filter"]');
    const deckItems = Array.from(
      document.querySelectorAll('[data-role="deck-list-item"]')
    );
    const emptyState = document.querySelector('[data-role="deck-filter-empty"]');

    if (!filterInput || deckItems.length === 0) {
      return;
    }

    const searchableValues = new Map();
    deckItems.forEach((item) => {
      const searchValue = item.getAttribute("data-search-value") ?? item.textContent ?? "";
      searchableValues.set(item, normalize(searchValue));
    });

    function updateVisibility() {
      const query = normalize(filterInput.value.trim());
      let visibleCount = 0;

      deckItems.forEach((item) => {
        const matches = query.length === 0 || searchableValues.get(item).includes(query);
        item.hidden = !matches;
        if (matches) {
          visibleCount += 1;
        }
      });

      if (emptyState) {
        emptyState.hidden = visibleCount > 0;
      }
    }

    filterInput.addEventListener("input", updateVisibility);
    filterInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (filterInput.value.length > 0) {
          filterInput.value = "";
          updateVisibility();
          event.preventDefault();
        } else {
          filterInput.blur();
        }
      }
    });

    updateVisibility();
  });
})();
