(function () {
  "use strict";

  function storageIsAvailable() {
    try {
      const testKey = "anki_viewer_test";
      sessionStorage.setItem(testKey, "1");
      sessionStorage.removeItem(testKey);
      return true;
    } catch (error) {
      console.warn("Session storage is not available; progress will not persist across this tab session.", error);
      return false;
    }
  }

  const storageEnabled = storageIsAvailable();
  const fallbackStore = new Map();

  function readFromStorage(key) {
    if (storageEnabled) {
      return sessionStorage.getItem(key);
    }
    return fallbackStore.get(key) ?? null;
  }

  function writeToStorage(key, value) {
    if (storageEnabled) {
      sessionStorage.setItem(key, value);
    } else {
      fallbackStore.set(key, value);
    }
  }

  function removeFromStorage(key) {
    if (storageEnabled) {
      sessionStorage.removeItem(key);
    } else {
      fallbackStore.delete(key);
    }
  }

  function readSet(key) {
    const raw = readFromStorage(key);
    if (!raw) {
      return new Set();
    }
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return new Set(parsed.map(String));
      }
    } catch (error) {
      console.warn("Unable to parse stored data for", key, error);
    }
    return new Set();
  }

  function writeSet(key, set) {
    const value = JSON.stringify(Array.from(set));
    writeToStorage(key, value);
  }

  function shuffleArray(values) {
    const copy = Array.isArray(values) ? [...values] : [];
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const viewer = document.querySelector(".card-viewer");
    if (!viewer) {
      return;
    }

    const deckId = viewer.getAttribute("data-deck-id") ?? "unknown";
    const totalCards = Number.parseInt(viewer.getAttribute("data-total-cards") || "0", 10);

    const cardElements = Array.from(viewer.querySelectorAll(".card"));
    if (cardElements.length === 0) {
      return;
    }

    cardElements.forEach((card) => {
      setupCardMedia(card);
    });

    const cardById = new Map(cardElements.map((card) => [card.dataset.cardId, card]));
    const baseOrder = cardElements
      .map((card) => card.dataset.cardId)
      .filter((cardId) => typeof cardId === "string" && cardId.length > 0);
    const counterEl = viewer.querySelector('[data-role="counter"]');
    const counterCurrent = counterEl ? counterEl.querySelector('[data-role="counter-current"]') : null;
    const counterTotal = counterEl ? counterEl.querySelector('[data-role="counter-total"]') : null;
    const progressLabel = viewer.querySelector('[data-role="progress-percent"]');
    const progressBar = viewer.querySelector(".progress-bar");
    const progressBarInner = viewer.querySelector(".progress-bar__inner");
    const emptyState = viewer.querySelector('[data-role="empty-state"]');
    const helpToggleButton = viewer.querySelector('[data-action="toggle-help"]');
    const helpOverlay = document.querySelector('[data-role="shortcut-overlay"]');
    const cardTypeIndicator = viewer.querySelector('[data-role="card-type"]');
    const cardStage = viewer.querySelector('[data-role="card-stage"]');
    const fullscreenToggleButton = viewer.querySelector('[data-action="toggle-fullscreen"]');
    const shuffleToggleButton = viewer.querySelector('[data-action="toggle-shuffle"]');

    if (counterTotal) {
      counterTotal.textContent = String(totalCards);
    }

    const viewedKey = `deck-${deckId}-viewed`;
    const ratingsKey = `deck-${deckId}-ratings`;
    const debugModeKey = `deck-${deckId}-debug-mode`;

    const viewedSet = readSet(viewedKey);
    const ratingsMap = new Map();
    const VALID_RATINGS = new Set(["favorite", "bad", "memorized"]);

    function normalizeRatingValue(value) {
      const normalized = new Set();
      if (!value) {
        return normalized;
      }
      if (typeof value === "string") {
        if (VALID_RATINGS.has(value)) {
          normalized.add(value);
        }
        return normalized;
      }
      if (Array.isArray(value)) {
        value.forEach((entry) => {
          if (typeof entry === "string" && VALID_RATINGS.has(entry)) {
            normalized.add(entry);
          }
        });
        return normalized;
      }
      if (typeof value === "object") {
        Object.entries(value).forEach(([label, active]) => {
          if (active && VALID_RATINGS.has(label)) {
            normalized.add(label);
          }
        });
      }
      return normalized;
    }

    function setupCardMedia(card) {
      if (!card || card.dataset.mediaSetup === "true") {
        return;
      }
      const images = card.querySelectorAll("img");
      images.forEach((img) => {
        if (img instanceof HTMLImageElement) {
          enhanceImageElement(img);
        }
      });
      card.dataset.mediaSetup = "true";
    }

    function enhanceImageElement(img) {
      if (!(img instanceof HTMLImageElement)) {
        return;
      }
      if (img.closest("[data-media-wrapper]") || !img.parentNode) {
        return;
      }

      if (shouldPreserveImageStructure(img)) {
        return;
      }

      const wrapper = document.createElement("span");
      wrapper.className = "media-wrapper";
      wrapper.setAttribute("data-media-wrapper", "true");
      wrapper.dataset.state = "loading";

      const parent = img.parentNode;
      parent.insertBefore(wrapper, img);
      wrapper.appendChild(img);

      img.classList.add("card-image");
      if (!img.hasAttribute("loading")) {
        img.setAttribute("loading", "lazy");
      }

      function updateState() {
        if (img.naturalWidth > 0) {
          wrapper.dataset.state = "loaded";
        } else if (img.complete) {
          wrapper.dataset.state = "error";
        } else {
          wrapper.dataset.state = "loading";
        }
      }

      img.addEventListener("load", updateState);
      img.addEventListener("error", updateState);
      updateState();
    }

    function shouldPreserveImageStructure(img) {
      if (!(img instanceof HTMLImageElement)) {
        return false;
      }

      if (img.matches("[data-preserve-image-structure]")) {
        return true;
      }

      const parent = img.parentElement;
      if (!(parent instanceof HTMLElement)) {
        return false;
      }

      if (parent.matches("[data-preserve-image-structure]")) {
        return true;
      }

      const parentId = parent.getAttribute("id") || "";
      if (parentId.startsWith("io-")) {
        return true;
      }

      return false;
    }

    let activeCardIds = [];
    let currentIndex = -1;
    let isShuffled = false;
    const hideMemorizedAttr = viewer.getAttribute("data-hide-memorized-default");
    let hideMemorized = true;
    if (hideMemorizedAttr !== null) {
      hideMemorized = hideMemorizedAttr.trim().toLowerCase() !== "false";
    }

    const storedDebugMode = readFromStorage(debugModeKey);
    let debugMode = storedDebugMode === "true";

    const keyToAction = new Map([
      [" ", "flip"],
      ["f", "flip"],
      ["F", "flip"],
      ["ArrowRight", "next"],
      ["ArrowLeft", "prev"],
      ["r", "random"],
      ["R", "random"],
      ["k", "mark-memorized"],
      ["K", "mark-memorized"],
      ["d", "toggle-debug"],
      ["D", "toggle-debug"],
      ["1", "set-rating-favorite"],
      ["2", "set-rating-bad"],
      ["3", "set-rating-memorized"],
      ["0", "clear-rating"],
    ]);

    function persistViewed() {
      writeSet(viewedKey, viewedSet);
    }

    function persistDebugMode() {
      writeToStorage(debugModeKey, debugMode ? "true" : "false");
    }

    function loadRatings() {
      const raw = readFromStorage(ratingsKey);
      ratingsMap.clear();
      if (!raw) {
        return;
      }
      try {
        const obj = JSON.parse(raw);
        Object.entries(obj).forEach(([id, ratingValue]) => {
          const normalized = normalizeRatingValue(ratingValue);
          if (normalized.size > 0) {
            ratingsMap.set(id, normalized);
          }
        });
      } catch (error) {
        console.warn("Unable to parse ratings data", error);
      }

      ratingsMap.forEach((_, cardId) => {
        updateCardRatingUI(cardId);
      });
    }

    function persistRatings() {
      const obj = {};
      for (const [id, ratingSet] of ratingsMap.entries()) {
        obj[id] = Array.from(ratingSet).sort();
      }
      writeToStorage(ratingsKey, JSON.stringify(obj));
    }

    async function saveRatingsToServer(cardId, ratingSet) {
      try {
        const response = await fetch(`/api/card/${cardId}/rating`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            deck_id: Number.parseInt(deckId, 10),
            rating: ratingSet ? Array.from(ratingSet).sort() : [],
          }),
        });
        if (!response.ok) {
          console.error("Failed to save rating to server:", response.statusText);
        }
      } catch (error) {
        console.error("Failed to save rating to server:", error);
      }
    }

    async function toggleCardRating(cardId, rating) {
      if (!VALID_RATINGS.has(rating)) {
        return;
      }

      const existing = ratingsMap.get(cardId);
      const updated = existing ? new Set(existing) : new Set();

      if (updated.has(rating)) {
        updated.delete(rating);
      } else {
        updated.add(rating);
      }

      if (updated.size > 0) {
        ratingsMap.set(cardId, updated);
      } else {
        ratingsMap.delete(cardId);
      }

      persistRatings();
      updateCardRatingUI(cardId);
      refreshActiveCards(cardId);
      await saveRatingsToServer(cardId, ratingsMap.get(cardId));
    }

    async function clearCardRatings(cardId) {
      if (!ratingsMap.has(cardId)) {
        return;
      }
      ratingsMap.delete(cardId);
      persistRatings();
      updateCardRatingUI(cardId);
      refreshActiveCards(cardId);
      await saveRatingsToServer(cardId, undefined);
    }

    function updateCardRatingUI(cardId) {
      const card = cardById.get(cardId);
      if (!card) {
        return;
      }

      const ratingSet = ratingsMap.get(cardId);

      // Update card class
      card.classList.remove("card--rated-favorite", "card--rated-bad", "card--rated-memorized");
      const isFavorite = Boolean(ratingSet && ratingSet.has("favorite"));
      const isBad = Boolean(ratingSet && ratingSet.has("bad"));
      const isMemorized = Boolean(ratingSet && ratingSet.has("memorized"));
      if (isFavorite) {
        card.classList.add("card--rated-favorite");
      }
      if (isBad) {
        card.classList.add("card--rated-bad");
      }
      if (isMemorized) {
        card.classList.add("card--rated-memorized");
      }

      // Update button states
      const buttons = card.querySelectorAll(".rating-button");
      buttons.forEach((button) => {
        const buttonRating = button.getAttribute("data-rating");
        const isActive = Boolean(buttonRating && ratingSet && ratingSet.has(buttonRating));
        button.classList.toggle("is-active", isActive);
        if (buttonRating) {
          button.setAttribute("aria-pressed", isActive ? "true" : "false");
        }
      });

      const clearButton = card.querySelector('[data-action="clear-rating"]');
      if (clearButton) {
        const hasAnyRating = Boolean(ratingSet && ratingSet.size > 0);
        clearButton.classList.toggle("is-visible", hasAnyRating);
        clearButton.setAttribute("aria-pressed", hasAnyRating ? "true" : "false");
      }
    }

    async function loadRatingsFromServer() {
      try {
        const response = await fetch(`/api/deck/${deckId}/ratings`);
        if (!response.ok) {
          console.warn("Failed to load ratings from server:", response.statusText);
          return;
        }
        const data = await response.json();
        if (data.ratings) {
          const previouslyRated = new Set(ratingsMap.keys());
          ratingsMap.clear();
          Object.entries(data.ratings).forEach(([cardId, ratingValue]) => {
            const normalized = normalizeRatingValue(ratingValue);
            if (normalized.size > 0) {
              ratingsMap.set(cardId, normalized);
              previouslyRated.delete(cardId);
            }
          });
          persistRatings();

          // Update UI for all rated cards
          ratingsMap.forEach((_, cardId) => {
            updateCardRatingUI(cardId);
          });
          previouslyRated.forEach((cardId) => {
            updateCardRatingUI(cardId);
          });
          const activeCard = getActiveCardElement();
          const preserveId = activeCard ? activeCard.dataset.cardId : undefined;
          refreshActiveCards(preserveId);
        }
      } catch (error) {
        console.warn("Failed to load ratings from server:", error);
      }
    }

    function markViewed(cardId) {
      if (!viewedSet.has(cardId)) {
        viewedSet.add(cardId);
        persistViewed();
        updateProgress();
      }
    }

    function getActiveCardElement() {
      if (currentIndex < 0) {
        return null;
      }
      const cardId = activeCardIds[currentIndex];
      return cardById.get(cardId) ?? null;
    }

    function updateCardTypeIndicator(card) {
      if (!cardTypeIndicator) {
        if (card && card.dataset.cardType) {
          viewer.dataset.activeCardType = card.dataset.cardType;
        } else {
          delete viewer.dataset.activeCardType;
        }
        return;
      }

      const type = card && card.dataset.cardType ? card.dataset.cardType : "";
      if (!type) {
        cardTypeIndicator.hidden = true;
        cardTypeIndicator.textContent = "";
        cardTypeIndicator.removeAttribute("data-card-type");
        delete viewer.dataset.activeCardType;
        return;
      }

      cardTypeIndicator.hidden = false;
      const display = type.charAt(0).toUpperCase() + type.slice(1);
      cardTypeIndicator.textContent = `${display} card`;
      cardTypeIndicator.setAttribute("data-card-type", type);
      viewer.dataset.activeCardType = type;
    }

    function updateQuestionVisibility(card) {
      if (!card) {
        return;
      }
      const questionContent = card.querySelector(".card-face.question .content.has-revealed");
      if (!questionContent) {
        return;
      }
      const front = questionContent.querySelector(".question-front");
      const revealed = questionContent.querySelector(".question-revealed");
      const isRevealed = card.classList.contains("revealed");
      if (front) {
        front.setAttribute("aria-hidden", isRevealed ? "true" : "false");
      }
      if (revealed) {
        revealed.setAttribute("aria-hidden", isRevealed ? "false" : "true");
      }
    }

    function setCardActive(cardId) {
      let activeCard = null;
      cardElements.forEach((card) => {
        const isActive = card.dataset.cardId === cardId;
        card.classList.toggle("is-active", isActive);
        // Force display with inline styles as fallback for CSS issues
        if (!isActive) {
          card.classList.remove("revealed");
          card.style.display = "none";
          card.style.visibility = "hidden";
          card.style.position = "absolute";
        } else {
          activeCard = card;
          card.style.display = "flex";
          card.style.visibility = "visible";
          card.style.position = "relative";
        }
        updateQuestionVisibility(card);
      });
      if (cardId) {
        markViewed(cardId);
      }
      updateCardTypeIndicator(activeCard);
      syncDebugPanels();
    }

    function updateCounter() {
      if (!counterEl) {
        return;
      }
      if (activeCardIds.length === 0) {
        counterEl.dataset.state = "empty";
        if (counterCurrent) {
          counterCurrent.textContent = "0";
        }
        return;
      }
      counterEl.dataset.state = "active";
      const activeCard = getActiveCardElement();
      const position = activeCard && activeCard.dataset.cardPosition
        ? Number.parseInt(activeCard.dataset.cardPosition, 10)
        : currentIndex + 1;
      if (counterCurrent) {
        counterCurrent.textContent = String(position);
      }
    }

    function updateProgress() {
      if (!progressBar || !progressBarInner || !progressLabel) {
        return;
      }
      if (totalCards === 0) {
        progressBarInner.style.width = "0%";
        progressBar.setAttribute("aria-valuenow", "0");
        progressLabel.textContent = "No cards available";
        return;
      }
      const percent = Math.round((viewedSet.size / totalCards) * 100);
      progressBarInner.style.width = `${percent}%`;
      progressBar.setAttribute("aria-valuenow", String(percent));
      progressLabel.textContent = `${viewedSet.size} / ${totalCards} viewed • ${percent}%`;
    }

    function updateControlsState() {
      const hasCards = activeCardIds.length > 0;
      const hasMultiple = activeCardIds.length > 1;
      const buttons = viewer.querySelectorAll("[data-action]");
      buttons.forEach((button) => {
        const action = button.getAttribute("data-action");
        if (!action) {
          return;
        }
        if (
          action === "toggle-help" ||
          action === "close-help" ||
          action === "toggle-fullscreen"
        ) {
          button.disabled = false;
          return;
        }
        if (action === "reset-progress") {
          button.disabled = cardElements.length === 0;
          return;
        }
        if (action === "toggle-shuffle") {
          button.disabled = !hasMultiple && !isShuffled;
          return;
        }
        button.disabled = !hasCards;
      });
    }

    function updateToggleSwitch(toggle, active, options = {}) {
      if (!toggle) {
        return;
      }

      const isActive = Boolean(active);
      toggle.setAttribute("aria-checked", isActive ? "true" : "false");
      toggle.dataset.state = isActive ? "on" : "off";

      const {
        activeTitle,
        inactiveTitle,
        activeStateText,
        inactiveStateText,
        activeLabel,
        inactiveLabel,
        pressedWhenActive = true,
      } = options;

      const isPressed = pressedWhenActive ? isActive : !isActive;
      toggle.setAttribute("aria-pressed", isPressed ? "true" : "false");

      const title = isActive ? activeTitle : inactiveTitle;
      if (title) {
        toggle.setAttribute("title", title);
      }

      const stateLabel = toggle.querySelector('[data-role="toggle-state"]');
      if (stateLabel) {
        const onText = activeStateText ?? "On";
        const offText = inactiveStateText ?? "Off";
        stateLabel.textContent = isActive ? onText : offText;
      }

      const labelEl = toggle.querySelector(".toggle-switch__label");
      if (labelEl && (activeLabel || inactiveLabel)) {
        const labelText = isActive
          ? activeLabel ?? labelEl.textContent
          : inactiveLabel ?? labelEl.textContent;
        labelEl.textContent = labelText;
      }
    }

    function updateShuffleToggle() {
      if (!shuffleToggleButton) {
        return;
      }
      updateToggleSwitch(shuffleToggleButton, isShuffled, {
        activeTitle: "Restore original order",
        inactiveTitle: "Shuffle order",
      });
    }

    function updateHideMemorizedToggle() {
      const toggle = viewer.querySelector('[data-action="toggle-hide-memorized"]');
      if (!toggle) {
        return;
      }
      updateToggleSwitch(toggle, hideMemorized, {
        activeTitle: "Show memorized cards",
        inactiveTitle: "Hide memorized cards",
        activeLabel: "Hide Memorized",
        inactiveLabel: "Show Memorized",
      });
    }

    function toggleHideMemorized() {
      const activeCard = getActiveCardElement();
      const preserveCardId = activeCard ? activeCard.dataset.cardId : undefined;
      hideMemorized = !hideMemorized;
      updateHideMemorizedToggle();
      refreshActiveCards(preserveCardId);
    }

    function updateDebugToggle() {
      const toggle = viewer.querySelector('[data-action="toggle-debug"]');
      if (!toggle) {
        return;
      }
      updateToggleSwitch(toggle, debugMode, {
        activeTitle: "Hide debug information (D)",
        inactiveTitle: "Show debug information (D)",
        activeStateText: "On",
        inactiveStateText: "Off",
      });
    }

    function setDebugPanelState(card, open) {
      if (!card) {
        return;
      }
      const debugPanel = card.querySelector('[data-role="debug-panel"]');
      if (!debugPanel) {
        return;
      }
      if (open) {
        debugPanel.hidden = false;
        debugPanel.setAttribute("open", "");
      } else {
        debugPanel.hidden = true;
        debugPanel.removeAttribute("open");
      }
    }

    function syncDebugPanels() {
      cardElements.forEach((card) => {
        const shouldShow = debugMode && card.classList.contains("is-active");
        setDebugPanelState(card, shouldShow);
      });
    }

    function rebuildActiveCardIds(preserveCardId) {
      const available = baseOrder.filter((cardId) => {
        if (!cardId) {
          return false;
        }
        const ratingSet = ratingsMap.get(cardId);
        const isMemorized = Boolean(ratingSet && ratingSet.has("memorized"));
        const excludeMemorized = hideMemorized && isMemorized;
        const card = cardById.get(cardId);
        if (card) {
          card.classList.toggle("is-memorized", isMemorized);
          if (isMemorized) {
            card.classList.remove("revealed");
            updateQuestionVisibility(card);
          }
        }
        return !excludeMemorized;
      });

      activeCardIds = isShuffled ? shuffleArray(available) : available;

      if (preserveCardId && activeCardIds.includes(preserveCardId)) {
        currentIndex = activeCardIds.indexOf(preserveCardId);
      } else if (activeCardIds.length === 0) {
        currentIndex = -1;
      } else if (currentIndex < 0 || currentIndex >= activeCardIds.length) {
        currentIndex = 0;
      }
    }

    function refreshActiveCards(preserveCardId) {
      rebuildActiveCardIds(preserveCardId);
      showCardByIndex(currentIndex);
    }

    function setShuffleState(shuffled, preserveCardId) {
      isShuffled = Boolean(shuffled);
      updateShuffleToggle();
      refreshActiveCards(preserveCardId);
    }

    function toggleShuffle() {
      const activeCard = getActiveCardElement();
      const preserveCardId = activeCard ? activeCard.dataset.cardId : undefined;
      setShuffleState(!isShuffled, preserveCardId);
    }

    function updateFullscreenButton(active) {
      if (!fullscreenToggleButton) {
        return;
      }
      fullscreenToggleButton.setAttribute("aria-pressed", active ? "true" : "false");
      fullscreenToggleButton.setAttribute(
        "title",
        active ? "Exit fullscreen (Esc)" : "Enter fullscreen"
      );
      const label = fullscreenToggleButton.querySelector(".toolbar-button__label");
      if (label) {
        label.textContent = active ? "Exit" : "Fullscreen";
      }
    }

    function syncFullscreenFromDocument() {
      const element = document.fullscreenElement;
      const active = Boolean(element) && element.contains(viewer);
      if (active) {
        viewer.dataset.mode = "fullscreen";
      } else {
        delete viewer.dataset.mode;
      }
      updateFullscreenButton(active);
    }

    function toggleFullscreenMode() {
      if (document.fullscreenElement) {
        if (document.exitFullscreen) {
          document.exitFullscreen().catch(() => {});
        }
      } else {
        const target = document.documentElement;
        if (target && target.requestFullscreen) {
          target.requestFullscreen().catch(() => {
            syncFullscreenFromDocument();
          });
        }
      }
    }

    function showEmptyStateIfNeeded() {
      if (!emptyState) {
        return;
      }
      emptyState.hidden = activeCardIds.length > 0;
    }

    function showCardByIndex(index) {
      if (activeCardIds.length === 0) {
        currentIndex = -1;
        cardElements.forEach((card) => {
          card.classList.remove("is-active", "revealed");
          updateQuestionVisibility(card);
        });
        updateCardTypeIndicator(null);
      showEmptyStateIfNeeded();
      updateCounter();
      updateControlsState();
      syncDebugPanels();
      return;
    }
      const normalizedIndex = ((index % activeCardIds.length) + activeCardIds.length) % activeCardIds.length;
      currentIndex = normalizedIndex;
      const cardId = activeCardIds[currentIndex];
      setCardActive(cardId);
      showEmptyStateIfNeeded();
      updateCounter();
      updateControlsState();
      syncDebugPanels();
    }

    function flipCurrentCard() {
      const card = getActiveCardElement();
      if (!card) {
        return;
      }
      card.classList.toggle("revealed");
      updateQuestionVisibility(card);
    }

    function goToNext() {
      if (activeCardIds.length === 0) {
        return;
      }
      showCardByIndex(currentIndex + 1);
    }

    function goToPrevious() {
      if (activeCardIds.length === 0) {
        return;
      }
      showCardByIndex(currentIndex - 1);
    }

    function goToRandom() {
      if (activeCardIds.length <= 1) {
        return;
      }
      let newIndex = currentIndex;
      while (newIndex === currentIndex) {
        newIndex = Math.floor(Math.random() * activeCardIds.length);
      }
      showCardByIndex(newIndex);
    }

    function applyMemorizedState(cardId, memorize) {
      const existing = ratingsMap.get(cardId);
      const updated = existing ? new Set(existing) : new Set();
      if (memorize) {
        updated.add("memorized");
      } else {
        updated.delete("memorized");
      }

      if (updated.size > 0) {
        ratingsMap.set(cardId, updated);
      } else {
        ratingsMap.delete(cardId);
      }

      persistRatings();
      updateCardRatingUI(cardId);

      const ratingSet = ratingsMap.get(cardId);
      saveRatingsToServer(cardId, ratingSet).catch((error) => {
        console.error("Failed to save rating to server:", error);
      });

      return updated.has("memorized");
    }

    function markCurrentCardMemorized() {
      if (activeCardIds.length === 0) {
        return;
      }
      const cardId = activeCardIds[currentIndex];
      const ratingSet = ratingsMap.get(cardId);
      const alreadyMemorized = Boolean(ratingSet && ratingSet.has("memorized"));
      const isMemorized = applyMemorizedState(cardId, !alreadyMemorized);

      if (isMemorized) {
        if (hideMemorized) {
          refreshActiveCards();
        } else {
          refreshActiveCards(cardId);
          showCardByIndex(currentIndex + 1);
        }
      } else {
        refreshActiveCards(cardId);
      }
    }

    function resetProgress() {
      viewedSet.clear();
      removeFromStorage(viewedKey);
      const cardsToUpdate = [];
      ratingsMap.forEach((ratingSet, cardId) => {
        if (ratingSet.delete("memorized")) {
          if (ratingSet.size === 0) {
            ratingsMap.delete(cardId);
          }
          cardsToUpdate.push(cardId);
        }
      });
      persistRatings();
      cardElements.forEach((card) => {
        card.classList.remove("is-memorized", "revealed");
        updateQuestionVisibility(card);
      });
      cardsToUpdate.forEach((cardId) => {
        updateCardRatingUI(cardId);
        const ratingSet = ratingsMap.get(cardId);
        saveRatingsToServer(cardId, ratingSet).catch((error) => {
          console.error("Failed to save rating to server:", error);
        });
      });
      updateProgress();
      isShuffled = false;
      updateShuffleToggle();
      currentIndex = 0;
      refreshActiveCards();
    }

    function isHelpOpen() {
      return helpOverlay && helpOverlay.getAttribute("aria-hidden") === "false";
    }

    function setHelpOpen(open) {
      if (!helpOverlay) {
        return;
      }
      helpOverlay.setAttribute("aria-hidden", open ? "false" : "true");
      if (helpToggleButton) {
        helpToggleButton.setAttribute("aria-expanded", open ? "true" : "false");
      }
      if (open) {
        const focusTarget = helpOverlay.querySelector(".shortcut-overlay__content");
        if (focusTarget instanceof HTMLElement) {
          focusTarget.focus({ preventScroll: true });
        } else {
          helpOverlay.focus({ preventScroll: true });
        }
      } else if (
        helpToggleButton &&
        helpOverlay.contains(document.activeElement)
      ) {
        helpToggleButton.focus({ preventScroll: true });
      }
    }

    function toggleHelp() {
      setHelpOpen(!isHelpOpen());
    }

    function closeHelp() {
      setHelpOpen(false);
    }

    function toggleDebug() {
      debugMode = !debugMode;
      persistDebugMode();
      updateDebugToggle();
      syncDebugPanels();
    }

    async function fetchCardData(deckId, cardId) {
      try {
        const url = `/deck/${deckId}/card/${cardId}.json`;
        console.log(`Fetching card data from: ${url}`);
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        console.log("Card data:", data);
        const jsonPreElement = document.querySelector(`[data-role="debug-json-${cardId}"]`);
        if (jsonPreElement) {
          jsonPreElement.textContent = JSON.stringify(data, null, 2);
          jsonPreElement.style.display = "block";
        }
        return data;
      } catch (error) {
        console.error("Failed to fetch card data:", error);
        alert(`Failed to fetch card data: ${error.message}`);
      }
    }

    function flashControl(action) {
      if (!action) {
        return;
      }
      let target;
      if (action === "toggle-help" && helpToggleButton) {
        target = helpToggleButton;
      } else if (action === "close-help" && helpOverlay) {
        target = helpOverlay.querySelector('[data-action="close-help"]');
      } else if (action === "mark-memorized") {
        const activeCard = getActiveCardElement();
        if (activeCard) {
          target = activeCard.querySelector('[data-action="set-rating"][data-rating="memorized"]');
        }
      } else {
        target = viewer.querySelector(`[data-action="${action}"]`);
      }
      if (!target) {
        return;
      }
      target.classList.add("key-pressed");
      window.setTimeout(() => target.classList.remove("key-pressed"), 180);
    }

    function performAction(action) {
      switch (action) {
        case "flip":
          flipCurrentCard();
          break;
        case "next":
          goToNext();
          break;
        case "prev":
          goToPrevious();
          break;
        case "random":
          goToRandom();
          break;
        case "toggle-shuffle":
          toggleShuffle();
          break;
        case "toggle-hide-memorized":
          toggleHideMemorized();
          break;
        case "mark-memorized":
          markCurrentCardMemorized();
          break;
        case "reset-progress":
          resetProgress();
          break;
        case "toggle-fullscreen":
          toggleFullscreenMode();
          break;
        case "toggle-help":
          toggleHelp();
          break;
        case "close-help":
          closeHelp();
          break;
        case "toggle-debug":
          toggleDebug();
          break;
        case "set-rating-favorite": {
          const card = getActiveCardElement();
          if (card) {
            toggleCardRating(card.dataset.cardId, "favorite");
          }
          break;
        }
        case "set-rating-bad": {
          const card = getActiveCardElement();
          if (card) {
            toggleCardRating(card.dataset.cardId, "bad");
          }
          break;
        }
        case "set-rating-memorized":
          markCurrentCardMemorized();
          break;
        case "clear-rating": {
          const card = getActiveCardElement();
          if (card) {
            clearCardRatings(card.dataset.cardId);
          }
          break;
        }
        default:
          break;
      }
    }

    viewer.addEventListener("click", (event) => {
      const rawTarget = event.target;
      if (!(rawTarget instanceof HTMLElement)) {
        return;
      }
      const target = rawTarget.closest("[data-action]");
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const action = target.getAttribute("data-action");
      if (action === "fetch-card-data") {
        event.preventDefault();
        const deckId = target.getAttribute("data-deck-id");
        const cardId = target.getAttribute("data-card-id");
        if (deckId && cardId) {
          fetchCardData(deckId, cardId);
        }
      } else if (action === "set-rating") {
        event.preventDefault();
        const rating = target.getAttribute("data-rating");
        const card = target.closest(".card");
        if (card && rating) {
          if (rating === "memorized" && card.classList.contains("is-active")) {
            markCurrentCardMemorized();
          } else {
            toggleCardRating(card.dataset.cardId, rating);
          }
        }
      } else if (action === "clear-rating") {
        event.preventDefault();
        const card = target.closest(".card");
        if (card) {
          clearCardRatings(card.dataset.cardId);
        }
      } else if (action) {
        event.preventDefault();
        performAction(action);
        flashControl(action);
      }
    });

    if (cardStage) {
      cardStage.addEventListener("click", (event) => {
        if (isHelpOpen()) {
          return;
        }
        const rawTarget = event.target;
        if (!(rawTarget instanceof HTMLElement)) {
          return;
        }
        const activeCard = getActiveCardElement();
        if (!activeCard || !activeCard.contains(rawTarget)) {
          return;
        }
        if (rawTarget.closest("a, button, summary, details")) {
          return;
        }
        if (rawTarget.closest(".extra-fields")) {
          return;
        }
        const clozeTarget = rawTarget.closest(".cloze");
        if (clozeTarget instanceof HTMLElement) {
          return;
        }
        const selection = window.getSelection();
        if (selection && selection.toString().trim() !== "") {
          return;
        }
        performAction("flip");
        flashControl("flip");
      });
    }

    if (helpOverlay) {
      helpOverlay.addEventListener("click", (event) => {
        if (event.target === helpOverlay) {
          closeHelp();
        }
      });
      const closeButton = helpOverlay.querySelector('[data-action="close-help"]');
      if (closeButton) {
        closeButton.addEventListener("click", (event) => {
          event.preventDefault();
          closeHelp();
          flashControl("close-help");
        });
      }
    }

    document.addEventListener("keydown", (event) => {
      if (event.target instanceof HTMLElement) {
        const tagName = event.target.tagName;
        if (tagName === "INPUT" || tagName === "TEXTAREA" || event.target.isContentEditable) {
          return;
        }
      }

      if (event.key === "?" || (event.shiftKey && event.key === "/")) {
        event.preventDefault();
        toggleHelp();
        flashControl("toggle-help");
        return;
      }

      if (event.key === "Escape" && isHelpOpen()) {
        event.preventDefault();
        closeHelp();
        flashControl("close-help");
        return;
      }

      if (isHelpOpen()) {
        return;
      }

      const action = keyToAction.get(event.key);
      if (!action) {
        return;
      }

      if (action === "flip" || action === "next" || action === "prev") {
        event.preventDefault();
      }

      performAction(action);
      flashControl(action);
    });

    document.addEventListener("fullscreenchange", () => {
      syncFullscreenFromDocument();
    });

    // Swipe gesture support for mobile navigation
    let touchStartX = 0;
    let touchStartY = 0;
    let touchEndX = 0;
    let touchEndY = 0;
    const swipeThreshold = 50; // Minimum distance for a swipe
    const swipeAngleThreshold = 30; // Maximum angle deviation from horizontal (in degrees)

    if (cardStage) {
      cardStage.addEventListener("touchstart", (event) => {
        if (event.touches.length !== 1) {
          return;
        }
        const touch = event.touches[0];
        touchStartX = touch.clientX;
        touchStartY = touch.clientY;
      }, { passive: true });

      cardStage.addEventListener("touchmove", (event) => {
        if (event.touches.length !== 1) {
          return;
        }
        const touch = event.touches[0];
        touchEndX = touch.clientX;
        touchEndY = touch.clientY;
      }, { passive: true });

      cardStage.addEventListener("touchend", (event) => {
        if (isHelpOpen()) {
          return;
        }

        const deltaX = touchEndX - touchStartX;
        const deltaY = touchEndY - touchStartY;
        const absDeltaX = Math.abs(deltaX);
        const absDeltaY = Math.abs(deltaY);

        // Check if the swipe distance meets threshold
        if (absDeltaX < swipeThreshold && absDeltaY < swipeThreshold) {
          return;
        }

        // Calculate angle to ensure it's mostly horizontal
        const angle = Math.abs(Math.atan2(deltaY, deltaX) * 180 / Math.PI);
        const isHorizontal = angle < swipeAngleThreshold || angle > (180 - swipeAngleThreshold);

        if (!isHorizontal) {
          return;
        }

        // Determine swipe direction
        if (absDeltaX > absDeltaY) {
          if (deltaX > 0) {
            // Swipe right - go to previous card
            performAction("prev");
            flashControl("prev");
          } else {
            // Swipe left - go to next card
            performAction("next");
            flashControl("next");
          }
          event.preventDefault();
        }

        // Reset touch coordinates
        touchStartX = 0;
        touchStartY = 0;
        touchEndX = 0;
        touchEndY = 0;
      });
    }

    loadRatings();
    updateShuffleToggle();
    updateHideMemorizedToggle();
    updateDebugToggle();
    refreshActiveCards();
    syncFullscreenFromDocument();

    // Initialize the UI
    updateProgress();

    // Load ratings from the server to sync with backend state
    loadRatingsFromServer();
  });
})();
