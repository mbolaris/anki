/**
 * Theme Toggle - Switch between default and Galaga arcade theme
 */

(function() {
  'use strict';

  const THEME_KEY = 'anki-viewer-theme';
  const GALAGA_THEME = 'theme-galaga';

  /**
   * Initialize theme on page load
   */
  function initTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY);
    if (savedTheme === GALAGA_THEME) {
      document.body.classList.add(GALAGA_THEME);
    }
  }

  /**
   * Toggle between themes
   */
  function toggleTheme() {
    const isGalaga = document.body.classList.toggle(GALAGA_THEME);

    // Save preference
    if (isGalaga) {
      localStorage.setItem(THEME_KEY, GALAGA_THEME);
    } else {
      localStorage.removeItem(THEME_KEY);
    }

    // Add visual feedback
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.style.transform = 'scale(0.9)';
      setTimeout(() => {
        button.style.transform = '';
      }, 150);
    }
  }

  /**
   * Setup theme toggle button
   */
  function setupThemeToggle() {
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.addEventListener('click', toggleTheme);
    }
  }

  // Initialize theme immediately (before DOM loads)
  initTheme();

  // Setup toggle button when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupThemeToggle);
  } else {
    setupThemeToggle();
  }
})();
