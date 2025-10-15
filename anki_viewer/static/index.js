(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", () => {
    const filterButtons = Array.from(
      document.querySelectorAll('[data-role="deck-filter-button"]')
    );
    const deckItems = Array.from(
      document.querySelectorAll('[data-role="deck-list-item"]')
    );
    const emptyState = document.querySelector('[data-role="deck-filter-empty"]');

    if (filterButtons.length === 0 || deckItems.length === 0) {
      return;
    }

    const filtersByShortcut = new Map();
    filterButtons.forEach((button) => {
      const shortcut = button.dataset.shortcut;
      if (shortcut) {
        filtersByShortcut.set(shortcut.toLowerCase(), button);
      }
    });

    function setButtonStates(activeFilter) {
      filterButtons.forEach((button) => {
        const isActive = button.dataset.filter === activeFilter;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function applyFilter(targetFilter) {
      const filterValue = targetFilter || "all";
      setButtonStates(filterValue);

      let visibleCount = 0;
      deckItems.forEach((item) => {
        const rootName = item.getAttribute("data-root-name") || "";
        const matches = filterValue === "all" || rootName === filterValue;
        item.hidden = !matches;
        if (matches) {
          visibleCount += 1;
        }
      });

      if (emptyState) {
        emptyState.hidden = visibleCount > 0;
      }

      return filterValue;
    }

    function findDefaultButton() {
      return (
        filtersByShortcut.get("0") ||
        filterButtons.find((button) => button.dataset.filter === "all") ||
        null
      );
    }

    function isTypingTarget(element) {
      if (!(element instanceof HTMLElement)) {
        return false;
      }

      if (element.isContentEditable) {
        return true;
      }

      if (element.tagName === "TEXTAREA" || element.tagName === "SELECT") {
        return true;
      }

      if (element.tagName === "INPUT") {
        const type = (element.getAttribute("type") || "").toLowerCase();
        return !["button", "submit", "reset", "checkbox", "radio"].includes(type);
      }

      return false;
    }

    let activeFilter = applyFilter("all");

    filterButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const nextFilter = button.dataset.filter || "all";
        activeFilter = applyFilter(nextFilter);
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }

      if (isTypingTarget(event.target)) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === "escape" || key === "0") {
        activeFilter = applyFilter("all");
        const defaultButton = findDefaultButton();
        if (defaultButton) {
          defaultButton.focus();
        }
        event.preventDefault();
        return;
      }

      const shortcutButton = filtersByShortcut.get(key);
      if (shortcutButton) {
        activeFilter = applyFilter(shortcutButton.dataset.filter || "all");
        shortcutButton.focus();
        event.preventDefault();
      }
    });
  });
})();
