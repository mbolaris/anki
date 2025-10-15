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
    const knownKey = `deck-${deckId}-known`;

    const viewedSet = readSet(viewedKey);
    const knownSet = readSet(knownKey);

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

    let activeCardIds = [];
    let currentIndex = -1;
    let isShuffled = false;

    const keyToAction = new Map([
      [" ", "flip"],
      ["f", "flip"],
      ["F", "flip"],
      ["ArrowRight", "next"],
      ["ArrowLeft", "prev"],
      ["r", "random"],
      ["R", "random"],
      ["k", "mark-known"],
      ["K", "mark-known"],
      ["d", "toggle-debug"],
      ["D", "toggle-debug"],
    ]);

    function persistViewed() {
      writeSet(viewedKey, viewedSet);
    }

    function persistKnown() {
      writeSet(knownKey, knownSet);
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
        if (!isActive) {
          card.classList.remove("revealed");
        } else {
          activeCard = card;
        }
        updateQuestionVisibility(card);
      });
      if (cardId) {
        markViewed(cardId);
      }
      updateCardTypeIndicator(activeCard);
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

    function updateShuffleButton() {
      if (!shuffleToggleButton) {
        return;
      }
      shuffleToggleButton.setAttribute("aria-pressed", isShuffled ? "true" : "false");
      shuffleToggleButton.setAttribute(
        "title",
        isShuffled ? "Restore original order" : "Shuffle order"
      );
      const label = shuffleToggleButton.querySelector(".toolbar-button__label");
      if (label) {
        label.textContent = isShuffled ? "Unshuffle" : "Shuffle";
      }
    }

    function rebuildActiveCardIds(preserveCardId) {
      const available = baseOrder.filter((cardId) => {
        if (!cardId) {
          return false;
        }
        const isKnown = knownSet.has(cardId);
        const card = cardById.get(cardId);
        if (card) {
          card.classList.toggle("is-known", isKnown);
          if (isKnown) {
            card.classList.remove("revealed");
            updateQuestionVisibility(card);
          }
        }
        return !isKnown;
      });

      activeCardIds = isShuffled ? shuffleArray(available) : available;

      if (preserveCardId && activeCardIds.includes(preserveCardId)) {
        currentIndex = activeCardIds.indexOf(preserveCardId);
      } else if (activeCardIds.length === 0) {
        currentIndex = -1;
      } else {
        if (currentIndex < 0 || currentIndex >= activeCardIds.length) {
          currentIndex = 0;
        }
      }
    }

    function setShuffleState(shuffled, preserveCardId) {
      isShuffled = Boolean(shuffled);
      updateShuffleButton();
      rebuildActiveCardIds(preserveCardId);
      showCardByIndex(currentIndex);
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
        return;
      }
      const normalizedIndex = ((index % activeCardIds.length) + activeCardIds.length) % activeCardIds.length;
      currentIndex = normalizedIndex;
      const cardId = activeCardIds[currentIndex];
      setCardActive(cardId);
      showEmptyStateIfNeeded();
      updateCounter();
      updateControlsState();
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

    function markCurrentCardKnown() {
      if (activeCardIds.length === 0) {
        return;
      }
      const cardId = activeCardIds[currentIndex];
      knownSet.add(cardId);
      persistKnown();
      const card = cardById.get(cardId);
      if (card) {
        card.classList.add("is-known");
        card.classList.remove("is-active", "revealed");
        updateQuestionVisibility(card);
      }
      activeCardIds = activeCardIds.filter((id) => id !== cardId);
      if (activeCardIds.length === 0) {
        showCardByIndex(0);
        return;
      }
      const nextIndex = currentIndex >= activeCardIds.length ? 0 : currentIndex;
      showCardByIndex(nextIndex);
    }

    function resetProgress() {
      viewedSet.clear();
      knownSet.clear();
      removeFromStorage(viewedKey);
      removeFromStorage(knownKey);
      cardElements.forEach((card) => {
        card.classList.remove("is-known", "revealed");
        updateQuestionVisibility(card);
      });
      updateProgress();
      isShuffled = false;
      updateShuffleButton();
      rebuildActiveCardIds();
      showCardByIndex(0);
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
      const activeCard = getActiveCardElement();
      if (!activeCard) {
        return;
      }
      const debugPanel = activeCard.querySelector('[data-role="debug-panel"]');
      if (!debugPanel) {
        return;
      }
      debugPanel.hidden = !debugPanel.hidden;
      if (!debugPanel.hidden) {
        debugPanel.setAttribute("open", "");
      } else {
        debugPanel.removeAttribute("open");
      }
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
        case "mark-known":
          markCurrentCardKnown();
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

    updateShuffleButton();
    rebuildActiveCardIds();
    syncFullscreenFromDocument();

    // Initialize the UI
    updateProgress();
    showCardByIndex(currentIndex);
  });
})();
