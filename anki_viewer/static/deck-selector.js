/**
 * Deck Selector Dropdown - Allows switching between deck files
 */

(function() {
  'use strict';

  let trigger, dropdown, deckList;

  /**
   * Initialize the deck selector
   */
  function init() {
    trigger = document.getElementById('deck-selector-trigger');
    dropdown = document.getElementById('deck-selector-dropdown');
    deckList = document.getElementById('deck-list');

    if (!trigger || !dropdown) return;

    // Setup event listeners
    trigger.addEventListener('click', toggleDropdown);

    // Close dropdown when clicking outside
    document.addEventListener('click', handleClickOutside);

    // Close dropdown on escape key
    document.addEventListener('keydown', handleEscapeKey);

    // Close dropdown when clicking an item
    const items = dropdown.querySelectorAll('.deck-selector__item');
    items.forEach(item => {
      item.addEventListener('click', () => {
        closeDropdown();
      });
    });
  }

  /**
   * Toggle dropdown open/close
   */
  function toggleDropdown(event) {
    event.stopPropagation();
    const isExpanded = trigger.getAttribute('aria-expanded') === 'true';

    if (isExpanded) {
      closeDropdown();
    } else {
      openDropdown();
    }
  }

  /**
   * Open the dropdown
   */
  function openDropdown() {
    trigger.setAttribute('aria-expanded', 'true');
    dropdown.removeAttribute('hidden');
  }

  /**
   * Close the dropdown
   */
  function closeDropdown() {
    trigger.setAttribute('aria-expanded', 'false');
    dropdown.setAttribute('hidden', '');
  }

  /**
   * Handle clicks outside the dropdown
   */
  function handleClickOutside(event) {
    if (!trigger || !dropdown) return;

    const isExpanded = trigger.getAttribute('aria-expanded') === 'true';
    if (!isExpanded) return;

    const isClickInside = trigger.contains(event.target) || dropdown.contains(event.target);
    if (!isClickInside) {
      closeDropdown();
    }
  }

  /**
   * Handle escape key to close dropdown
   */
  function handleEscapeKey(event) {
    if (event.key === 'Escape') {
      const isExpanded = trigger?.getAttribute('aria-expanded') === 'true';
      if (isExpanded) {
        closeDropdown();
        trigger.focus();
      }
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
