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

    const clozeStateByCard = new Map();

    cardElements.forEach((card) => {
      setupCardMedia(card);
      setupClozeCard(card);
    });

    const cardById = new Map(cardElements.map((card) => [card.dataset.cardId, card]));
    const counterEl = viewer.querySelector('[data-role="counter"]');
    const progressLabel = viewer.querySelector('[data-role="progress-percent"]');
    const progressBar = viewer.querySelector(".progress-bar");
    const progressBarInner = viewer.querySelector(".progress-bar__inner");
    const knownCountEl = viewer.querySelector('[data-role="known-count"]');
    const emptyState = viewer.querySelector('[data-role="empty-state"]');
    const helpToggleButton = viewer.querySelector('[data-action="toggle-help"]');
    const helpOverlay = document.querySelector('[data-role="shortcut-overlay"]');

    const viewedKey = `deck-${deckId}-viewed`;
    const knownKey = `deck-${deckId}-known`;

    const viewedSet = readSet(viewedKey);
    const knownSet = readSet(knownKey);

    function getOrCreateClozeState(card) {
      if (!card || card.dataset.cardType !== "cloze") {
        return null;
      }
      const cardId = card.dataset.cardId;
      if (!cardId) {
        return null;
      }
      let state = clozeStateByCard.get(cardId);
      if (!state) {
        state = {
          endpoint: card.dataset.cardEndpoint || "",
          loaded: false,
          loading: false,
          promise: null,
          text: "",
          contentByNum: new Map(),
          revealed: new Set(),
          error: null,
        };
        clozeStateByCard.set(cardId, state);
      }
      return state;
    }

    function getFallbackClozeContent(card, identifier) {
      if (!identifier) {
        return null;
      }
      const selector = `.question-revealed [data-cloze="${identifier}"]`;
      const fallback = card.querySelector(selector);
      if (fallback instanceof HTMLElement) {
        return fallback.innerHTML;
      }
      return null;
    }

    function loadClozeData(card, state) {
      if (!state) {
        return Promise.resolve(null);
      }
      if (state.loaded) {
        return state.promise ? state.promise : Promise.resolve(state);
      }
      if (state.loading && state.promise) {
        return state.promise;
      }
      if (!state.endpoint) {
        state.loaded = true;
        if (!(state.contentByNum instanceof Map)) {
          state.contentByNum = new Map();
        }
        state.promise = Promise.resolve(state);
        return state.promise;
      }
      state.loading = true;
      state.promise = fetch(state.endpoint, { headers: { Accept: "application/json" } })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Failed to load cloze data (${response.status})`);
          }
          return response.json();
        })
        .then((data) => {
          if (data && data.type === "cloze") {
            state.text = typeof data.text === "string" ? data.text : "";
            const items = Array.isArray(data.clozes) ? data.clozes : [];
            state.contentByNum = new Map(
              items
                .filter((item) => Object.prototype.hasOwnProperty.call(item, "num"))
                .map((item) => [String(item.num), item.content])
            );
          } else {
            state.contentByNum = new Map();
          }
          state.loaded = true;
          state.error = null;
          return state;
        })
        .catch((error) => {
          console.warn("Unable to load cloze data for card", card.dataset.cardId, error);
          state.error = error;
          state.loaded = true;
          if (!(state.contentByNum instanceof Map)) {
            state.contentByNum = new Map();
          }
          return state;
        })
        .finally(() => {
          state.loading = false;
        });
      return state.promise;
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

    function revealClozeSpan(card, span) {
      const state = getOrCreateClozeState(card);
      if (!state) {
        return;
      }
      loadClozeData(card, state).then(() => {
        if (!(span instanceof HTMLElement) || !span.classList.contains("cloze-hidden")) {
          return;
        }
        const identifier = span.dataset.cloze ? String(span.dataset.cloze) : "";
        let content = identifier ? state.contentByNum.get(identifier) : undefined;
        if (!content) {
          content = getFallbackClozeContent(card, identifier);
        }
        if (!content) {
          return;
        }
        span.classList.remove("cloze-hidden");
        span.classList.add("cloze-revealed");
        span.innerHTML = content;
        span.setAttribute("aria-pressed", "true");
        span.dataset.revealed = "true";
        if (identifier) {
          state.revealed.add(identifier);
        }
      });
    }

    function setupClozeCard(card) {
      if (!card || card.dataset.cardType !== "cloze" || card.dataset.clozeSetup === "true") {
        return;
      }
      const questionFront = card.querySelector(".question-front");
      if (!questionFront) {
        return;
      }
      const state = getOrCreateClozeState(card);
      if (state && !(state.contentByNum instanceof Map)) {
        state.contentByNum = new Map();
      }
      const spans = questionFront.querySelectorAll(".cloze");
      spans.forEach((span) => {
        if (!(span instanceof HTMLElement)) {
          return;
        }
        if (!span.dataset.originalHtml) {
          span.dataset.originalHtml = span.innerHTML;
        }
        if (span.classList.contains("cloze-hidden")) {
          span.tabIndex = 0;
          span.setAttribute("role", "button");
          span.setAttribute("aria-pressed", "false");
        }
      });

      questionFront.addEventListener("click", (event) => {
        const rawTarget = event.target;
        if (!(rawTarget instanceof HTMLElement)) {
          return;
        }
        const target = rawTarget.closest(".cloze");
        if (!(target instanceof HTMLElement) || !target.classList.contains("cloze-hidden")) {
          return;
        }
        event.preventDefault();
        revealClozeSpan(card, target);
      });

      questionFront.addEventListener("keydown", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement) || !target.classList.contains("cloze-hidden")) {
          return;
        }
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }
        event.preventDefault();
        revealClozeSpan(card, target);
      });

      card.dataset.clozeSetup = "true";
    }

    function resetClozeForCard(card) {
      if (!card || card.dataset.cardType !== "cloze") {
        return;
      }
      const questionFront = card.querySelector(".question-front");
      if (!questionFront) {
        return;
      }
      const spans = questionFront.querySelectorAll(".cloze");
      spans.forEach((span) => {
        if (!(span instanceof HTMLElement)) {
          return;
        }
        const original = span.dataset.originalHtml;
        if (span.classList.contains("cloze-revealed")) {
          span.classList.remove("cloze-revealed");
          span.classList.add("cloze-hidden");
          if (original) {
            span.innerHTML = original;
          }
        }
        if (span.classList.contains("cloze-hidden")) {
          span.tabIndex = 0;
          span.setAttribute("role", "button");
          span.setAttribute("aria-pressed", "false");
          span.removeAttribute("data-revealed");
        } else {
          span.setAttribute("aria-pressed", "true");
        }
      });
      const state = getOrCreateClozeState(card);
      if (state) {
        state.revealed.clear();
      }
    }

    let activeCardIds = cardElements
      .map((card) => card.dataset.cardId)
      .filter((cardId) => {
        const isKnown = knownSet.has(cardId);
        const card = cardById.get(cardId);
        if (card) {
          card.classList.toggle("is-known", isKnown);
        }
        return !isKnown;
      });

    let currentIndex = activeCardIds.length > 0 ? 0 : -1;

    const keyToAction = new Map([
      [" ", "flip"],
      ["Enter", "flip"],
      ["ArrowRight", "next"],
      ["n", "next"],
      ["N", "next"],
      ["ArrowLeft", "prev"],
      ["p", "prev"],
      ["P", "prev"],
      ["r", "random"],
      ["R", "random"],
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
      cardElements.forEach((card) => {
        const isActive = card.dataset.cardId === cardId;
        card.classList.toggle("is-active", isActive);
        if (!isActive) {
          card.classList.remove("revealed");
        }
        updateQuestionVisibility(card);
      });
      if (cardId) {
        markViewed(cardId);
      }
    }

    function updateCounter() {
      if (!counterEl) {
        return;
      }
      if (activeCardIds.length === 0) {
        counterEl.textContent = "All cards marked as known";
        return;
      }
      counterEl.textContent = `Card ${currentIndex + 1} of ${activeCardIds.length}`;
    }

    function updateKnownCount() {
      if (!knownCountEl) {
        return;
      }
      const count = knownSet.size;
      if (count === 0) {
        knownCountEl.textContent = "No cards marked as known";
      } else if (count === 1) {
        knownCountEl.textContent = "1 card marked as known";
      } else {
        knownCountEl.textContent = `${count} cards marked as known`;
      }
    }

    function updateProgress() {
      if (!progressBar || !progressBarInner || !progressLabel) {
        return;
      }
      const percent = totalCards === 0 ? 0 : Math.round((viewedSet.size / totalCards) * 100);
      progressBarInner.style.width = `${percent}%`;
      progressBar.setAttribute("aria-valuenow", String(percent));
      progressLabel.textContent = `${percent}% viewed`;
    }

    function updateControlsState() {
      const hasCards = activeCardIds.length > 0;
      const buttons = viewer.querySelectorAll("[data-action]");
      buttons.forEach((button) => {
        const action = button.getAttribute("data-action");
        if (!action || action === "toggle-help" || action === "close-help") {
          return;
        }
        if (action === "reset-progress") {
          button.disabled = cardElements.length === 0;
          return;
        }
        button.disabled = !hasCards;
      });
      if (helpToggleButton) {
        helpToggleButton.disabled = false;
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
        resetClozeForCard(card);
      }
      activeCardIds = activeCardIds.filter((id) => id !== cardId);
      updateKnownCount();
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
      activeCardIds = cardElements.map((card) => {
        card.classList.remove("is-known", "revealed");
        updateQuestionVisibility(card);
        resetClozeForCard(card);
        return card.dataset.cardId;
      });
      updateProgress();
      updateKnownCount();
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
        case "mark-known":
          markCurrentCardKnown();
          break;
        case "reset-progress":
          resetProgress();
          break;
        case "toggle-help":
          toggleHelp();
          break;
        case "close-help":
          closeHelp();
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
      if (action) {
        event.preventDefault();
        performAction(action);
        flashControl(action);
      }
    });

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

    // Initialize the UI
    updateProgress();
    updateKnownCount();
    showCardByIndex(currentIndex);
  });
})();
