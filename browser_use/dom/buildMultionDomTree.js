(
  args = {
    doHighlightElements: true,
    focusHighlightIndex: -1,
    viewportExpansion: 0,
    debugMode: false,
  }
) => {
  const { doHighlightElements, focusHighlightIndex, viewportExpansion, debugMode } = args;
  let highlightIndex = 0; // Reset highlight index

  // Add timing stack to handle recursion
  const TIMING_STACK = {
    nodeProcessing: [],
    treeTraversal: [],
    highlighting: [],
    current: null
  };

  function popTiming(type) {
    const start = TIMING_STACK[type].pop();
    const duration = performance.now() - start;
    return duration;
  }

  // Only initialize performance tracking if in debug mode
  let PERF_METRICS = debugMode ? {
    buildMultionDomTreeCalls: 0,
    timings: {
      buildMultionDomTree: 0,
      highlightElement: 0,
      isInteractiveElement: 0,
      isElementVisible: 0,
      isTopElement: 0,
      isInExpandedViewport: 0,
      isTextNodeVisible: 0,
      getEffectiveScroll: 0,
    },
    cacheMetrics: {
      boundingRectCacheHits: 0,
      boundingRectCacheMisses: 0,
      computedStyleCacheHits: 0,
      computedStyleCacheMisses: 0,
      getBoundingClientRectTime: 0,
      getComputedStyleTime: 0,
      boundingRectHitRate: 0,
      computedStyleHitRate: 0,
      overallHitRate: 0,
    },
    nodeMetrics: {
      totalNodes: 0,
      processedNodes: 0,
      skippedNodes: 0,
    },
    buildMultionDomTreeBreakdown: {
      totalTime: 0,
      totalSelfTime: 0,
      buildMultionDomTreeCalls: 0,
      domOperations: {
        getBoundingClientRect: 0,
        getComputedStyle: 0,
      },
      domOperationCounts: {
        getBoundingClientRect: 0,
        getComputedStyle: 0,
      }
    }
  } : null;

  // Simple timing helper that only runs in debug mode
  function measureTime(fn) {
    if (!debugMode) return fn;
    return function(...args) {
      const start = performance.now();
      const result = fn.apply(this, args);
      const duration = performance.now() - start;
      return result;
    };
  }

  // Helper to measure DOM operations
  function measureDomOperation(operation, name) {
    if (!debugMode) return operation();
    
    const start = performance.now();
    const result = operation();
    const duration = performance.now() - start;
    
    if (PERF_METRICS && name in PERF_METRICS.buildMultionDomTreeBreakdown.domOperations) {
      PERF_METRICS.buildMultionDomTreeBreakdown.domOperations[name] += duration;
      PERF_METRICS.buildMultionDomTreeBreakdown.domOperationCounts[name]++;
    }
    
    return result;
  }

  // Add caching mechanisms at the top level
  const DOM_CACHE = {
    boundingRects: new WeakMap(),
    computedStyles: new WeakMap(),
    clearCache: () => {
      DOM_CACHE.boundingRects = new WeakMap();
      DOM_CACHE.computedStyles = new WeakMap();
    }
  };

  // Cache helper functions
  function getCachedBoundingRect(element) {
    if (!element) return null;
    
    if (DOM_CACHE.boundingRects.has(element)) {
      if (debugMode && PERF_METRICS) {
        PERF_METRICS.cacheMetrics.boundingRectCacheHits++;
      }
      return DOM_CACHE.boundingRects.get(element);
    }

    if (debugMode && PERF_METRICS) {
      PERF_METRICS.cacheMetrics.boundingRectCacheMisses++;
    }
    
    let rect;
    if (debugMode) {
      const start = performance.now();
      rect = element.getBoundingClientRect();
      const duration = performance.now() - start;
      if (PERF_METRICS) {
        PERF_METRICS.buildMultionDomTreeBreakdown.domOperations.getBoundingClientRect += duration;
        PERF_METRICS.buildMultionDomTreeBreakdown.domOperationCounts.getBoundingClientRect++;
      }
    } else {
      rect = element.getBoundingClientRect();
    }
    
    if (rect) {
      DOM_CACHE.boundingRects.set(element, rect);
    }
    return rect;
  }

  function getCachedComputedStyle(element) {
    if (!element) return null;
    
    if (DOM_CACHE.computedStyles.has(element)) {
      if (debugMode && PERF_METRICS) {
        PERF_METRICS.cacheMetrics.computedStyleCacheHits++;
      }
      return DOM_CACHE.computedStyles.get(element);
    }

    if (debugMode && PERF_METRICS) {
      PERF_METRICS.cacheMetrics.computedStyleCacheMisses++;
    }
    
    let style;
    if (debugMode) {
      const start = performance.now();
      style = window.getComputedStyle(element);
      const duration = performance.now() - start;
      if (PERF_METRICS) {
        PERF_METRICS.buildMultionDomTreeBreakdown.domOperations.getComputedStyle += duration;
        PERF_METRICS.buildMultionDomTreeBreakdown.domOperationCounts.getComputedStyle++;
      }
    } else {
      style = window.getComputedStyle(element);
    }
    
    if (style) {
      DOM_CACHE.computedStyles.set(element, style);
    }
    return style;
  }

  /**
   * Hash map of DOM nodes indexed by their highlight index.
   *
   * @type {Object<string, any>}
   */
  const DOM_HASH_MAP = {};

  const ID = { current: 0 };

  const HIGHLIGHT_CONTAINER_ID = "playwright-highlight-container";

  /**
   * Highlights an element in the DOM and returns the index of the next element.
   */
  function highlightElement(element, index, parentIframe = null) {
    if (!element) return index;

    try {
      // Create or get highlight container
      let container = document.getElementById(HIGHLIGHT_CONTAINER_ID);
      if (!container) {
          container = document.createElement("div");
          container.id = HIGHLIGHT_CONTAINER_ID;
          container.style.position = "fixed";
          container.style.pointerEvents = "none";
          container.style.top = "0";
          container.style.left = "0";
          container.style.width = "100%";
          container.style.height = "100%";
          container.style.zIndex = "2147483647";
          document.body.appendChild(container);
      }

      // Get element position
      const rect = measureDomOperation(
        () => element.getBoundingClientRect(),
        'getBoundingClientRect'
      );
      
      if (!rect) return index;

      // Generate a color based on the index
      const colors = [
        "#FF0000",
        "#00FF00",
        "#0000FF",
        "#FFA500",
        "#800080",
        "#008080",
        "#FF69B4",
        "#4B0082",
        "#FF4500",
        "#2E8B57",
        "#DC143C",
        "#4682B4",
      ];
      const colorIndex = index % colors.length;
      const baseColor = colors[colorIndex];
      const backgroundColor = baseColor + "1A"; // 10% opacity version of the color

      // Create highlight overlay
      const overlay = document.createElement("div");
      overlay.style.position = "fixed";
      overlay.style.border = `2px solid ${baseColor}`;
      overlay.style.backgroundColor = backgroundColor;
      overlay.style.pointerEvents = "none";
      overlay.style.boxSizing = "border-box";

      // Get element position
      let iframeOffset = { x: 0, y: 0 };

      // If element is in an iframe, calculate iframe offset
      if (parentIframe && parentIframe instanceof HTMLElement) {
          const iframeRect = parentIframe.getBoundingClientRect();
          iframeOffset.x = iframeRect.left;
          iframeOffset.y = iframeRect.top;
      }

      // Calculate position
      const top = rect.top + iframeOffset.y;
      const left = rect.left + iframeOffset.x;

      overlay.style.top = `${top}px`;
      overlay.style.left = `${left}px`;
      overlay.style.width = `${rect.width}px`;
      overlay.style.height = `${rect.height}px`;

      // Create and position label
      const label = document.createElement("div");
      label.className = "playwright-highlight-label";
      label.style.position = "fixed";
      label.style.background = baseColor;
      label.style.color = "white";
      label.style.padding = "1px 4px";
      label.style.borderRadius = "4px";
      label.style.fontSize = `${Math.min(12, Math.max(8, rect.height / 2))}px`;
      label.textContent = index;

      const labelWidth = 20;
      const labelHeight = 16;

      let labelTop = top + 2;
      let labelLeft = left + rect.width - labelWidth - 2;

      if (rect.width < labelWidth + 4 || rect.height < labelHeight + 4) {
          labelTop = top - labelHeight - 2;
          labelLeft = left + rect.width - labelWidth;
      }

      label.style.top = `${labelTop}px`;
      label.style.left = `${labelLeft}px`;

      // Add to container
      container.appendChild(overlay);
      container.appendChild(label);

      // Update positions on scroll
      const updatePositions = () => {
          const newRect = element.getBoundingClientRect();
          let newIframeOffset = { x: 0, y: 0 };
          
          if (parentIframe && parentIframe instanceof HTMLElement) {
              const iframeRect = parentIframe.getBoundingClientRect();
              newIframeOffset.x = iframeRect.left;
              newIframeOffset.y = iframeRect.top;
          }

          const newTop = newRect.top + newIframeOffset.y;
          const newLeft = newRect.left + newIframeOffset.x;

          overlay.style.top = `${newTop}px`;
          overlay.style.left = `${newLeft}px`;
          overlay.style.width = `${newRect.width}px`;
          overlay.style.height = `${newRect.height}px`;

          let newLabelTop = newTop + 2;
          let newLabelLeft = newLeft + newRect.width - labelWidth - 2;

          if (newRect.width < labelWidth + 4 || newRect.height < labelHeight + 4) {
              newLabelTop = newTop - labelHeight - 2;
              newLabelLeft = newLeft + newRect.width - labelWidth;
          }

          label.style.top = `${newLabelTop}px`;
          label.style.left = `${newLabelLeft}px`;
      };

      window.addEventListener('scroll', updatePositions);
      window.addEventListener('resize', updatePositions);

      return index + 1;
    } finally {
      popTiming('highlighting');
    }
  }

  /**
   * Returns an XPath tree string for an element.
   */
  function getXPathTree(element, stopAtBoundary = true) {
    const segments = [];
    let currentElement = element;

    while (currentElement && currentElement.nodeType === Node.ELEMENT_NODE) {
      // Stop if we hit a shadow root or iframe
      if (
        stopAtBoundary &&
        (currentElement.parentNode instanceof ShadowRoot ||
          currentElement.parentNode instanceof HTMLIFrameElement)
      ) {
        break;
      }

      let index = 0;
      let sibling = currentElement.previousSibling;
      while (sibling) {
        if (
          sibling.nodeType === Node.ELEMENT_NODE &&
          sibling.nodeName === currentElement.nodeName
        ) {
          index++;
        }
        sibling = sibling.previousSibling;
      }

      const tagName = currentElement.nodeName.toLowerCase();
      const xpathIndex = index > 0 ? `[${index + 1}]` : "";
      segments.unshift(`${tagName}${xpathIndex}`);

      currentElement = currentElement.parentNode;
    }

    return segments.join("/");
  }

  /**
   * Checks if a text node is visible.
   */
  function isTextNodeVisible(textNode) {
    try {
      const range = document.createRange();
      range.selectNodeContents(textNode);
      const rect = range.getBoundingClientRect();
      
      // Simple size check
      if (rect.width === 0 || rect.height === 0) {
          return false;
      }

      // Simple viewport check without scroll calculations
      const isInViewport = !(
          rect.bottom < -viewportExpansion ||
          rect.top > window.innerHeight + viewportExpansion ||
          rect.right < -viewportExpansion ||
          rect.left > window.innerWidth + viewportExpansion
      );

      // Check parent visibility
      const parentElement = textNode.parentElement;
      if (!parentElement) return false;

      try {
        return isInViewport && parentElement.checkVisibility({
          checkOpacity: true,
          checkVisibilityCSS: true,
        });
      } catch (e) {
        // Fallback if checkVisibility is not supported
        const style = window.getComputedStyle(parentElement);
        return isInViewport && 
                style.display !== 'none' && 
                style.visibility !== 'hidden' &&
                style.opacity !== '0';
      }
    } catch (e) {
      console.warn('Error checking text node visibility:', e);
      return false;
    }
  }

  // Helper function to check if element is accepted
  function isElementAccepted(element) {
    if (!element || !element.tagName) return false;
    
    // Always accept body and common container elements
    const alwaysAccept = new Set([
      "body", "div", "main", "article", "section", "nav", "header", "footer"
    ]);
    const tagName = element.tagName.toLowerCase();
    
    if (alwaysAccept.has(tagName)) return true;

    const leafElementDenyList = new Set([
      "svg",
      "script",
      "style",
      "link",
      "meta",
      "noscript",
      "template",
    ]);
    
    return !leafElementDenyList.has(tagName);
  }

  /**
   * Checks if an element is visible.
   */
  function isElementVisible(element) {
    const style = getCachedComputedStyle(element);
    return (
        element.offsetWidth > 0 &&
        element.offsetHeight > 0 &&
        style.visibility !== "hidden" &&
        style.display !== "none"
    );
  }

  /**
   * Checks if an element is interactive.
   */
  function isInteractiveElement(element) {
    const { scrollX, scrollY } = getEffectiveScroll(element);
    const rect = element.getBoundingClientRect();
    
    // Base interactive elements and roles
    const interactiveElements = new Set([
      "a",
      "button",
      "details",
      "embed",
      "input",
      "menu",
      "menuitem",
      "object",
      "select",
      "textarea",
      "canvas",
      "summary"
    ]);

    const interactiveRoles = new Set([
      "button",
      "menu",
      "menuitem",
      "link",
      "checkbox",
      "radio",
      "slider",
      "tab",
      "tabpanel",
      "textbox",
      "combobox",
      "grid",
      "listbox",
      "option",
      "progressbar",
      "scrollbar",
      "searchbox",
      "switch",
      "tree",
      "treeitem",
      "spinbutton",
      "tooltip",
      "a-button-inner",
      "a-dropdown-button",
      "click",
      "menuitemcheckbox",
      "menuitemradio",
      "a-button-text",
      "button-text",
      "button-icon",
      "button-icon-only",
      "button-text-icon-only",
      "dropdown",
      "combobox",
    ]);

    const tagName = element.tagName.toLowerCase();
    const role = element.getAttribute("role");
    const ariaRole = element.getAttribute("aria-role");
    const tabIndex = element.getAttribute("tabindex");

    // Add check for specific class
    const hasAddressInputClass = element.classList.contains(
      "address-input__container__input"
    );

    // Basic role/attribute checks
    const hasInteractiveRole =
      hasAddressInputClass ||
      interactiveElements.has(tagName) ||
      interactiveRoles.has(role) ||
      interactiveRoles.has(ariaRole) ||
      (tabIndex !== null &&
        tabIndex !== "-1" &&
        element.parentElement?.tagName.toLowerCase() !== "body") ||
      element.getAttribute("data-action") === "a-dropdown-select" ||
      element.getAttribute("data-action") === "a-dropdown-button";

    if (hasInteractiveRole) return true;

    // Get computed style
    const style = window.getComputedStyle(element);

    // Check for event listeners
    const hasClickHandler =
      element.onclick !== null ||
      element.getAttribute("onclick") !== null ||
      element.hasAttribute("ng-click") ||
      element.hasAttribute("@click") ||
      element.hasAttribute("v-on:click");

    // Helper function to safely get event listeners
    function getEventListeners(el) {
      try {
        return window.getEventListeners?.(el) || {};
      } catch (e) {
        const listeners = {};
        const eventTypes = [
          "click",
          "mousedown",
          "mouseup",
          "touchstart",
          "touchend",
          "keydown",
          "keyup",
          "focus",
          "blur",
        ];

        for (const type of eventTypes) {
          const handler = el[`on${type}`];
          if (handler) {
            listeners[type] = [{ listener: handler, useCapture: false }];
          }
        }
        return listeners;
      }
    }

    // Check for click-related events
    const listeners = getEventListeners(element);
    const hasClickListeners =
      listeners &&
      (listeners.click?.length > 0 ||
        listeners.mousedown?.length > 0 ||
        listeners.mouseup?.length > 0 ||
        listeners.touchstart?.length > 0 ||
        listeners.touchend?.length > 0);

    // Check for ARIA properties
    const hasAriaProps =
      element.hasAttribute("aria-expanded") ||
      element.hasAttribute("aria-pressed") ||
      element.hasAttribute("aria-selected") ||
      element.hasAttribute("aria-checked");

    const isContentEditable = element.getAttribute("contenteditable") === "true" || 
      element.isContentEditable ||
      element.id === "tinymce" ||
      element.classList.contains("mce-content-body") ||
      (element.tagName.toLowerCase() === "body" && element.getAttribute("data-id")?.startsWith("mce_"));

    // Check if element is draggable
    const isDraggable =
      element.draggable || element.getAttribute("draggable") === "true";

    return (
      hasAriaProps ||
      hasClickHandler ||
      hasClickListeners ||
      isDraggable ||
      isContentEditable
    );
  }

  /**
   * Checks if an element is the topmost element at its position.
   */
  function isTopElement(element) {
    const rect = getCachedBoundingRect(element);
    
    // If element is not in viewport, consider it top
    const isInViewport = (
        rect.left < window.innerWidth &&
        rect.right > 0 &&
        rect.top < window.innerHeight &&
        rect.bottom > 0
    );

    if (!isInViewport) {
        return true;
    }

    // Find the correct document context and root element
    let doc = element.ownerDocument;

    // If we're in an iframe, elements are considered top by default
    if (doc !== window.document) {
        return true;
    }

    // For shadow DOM, we need to check within its own root context
    const shadowRoot = element.getRootNode();
    if (shadowRoot instanceof ShadowRoot) {
        const centerX = rect.left + rect.width/2;
        const centerY = rect.top + rect.height/2;

        try {
            const topEl = measureDomOperation(
                () => shadowRoot.elementFromPoint(centerX, centerY),
                'elementFromPoint'
            );
            if (!topEl) return false;

            let current = topEl;
            while (current && current !== shadowRoot) {
                if (current === element) return true;
                current = current.parentElement;
            }
            return false;
        } catch (e) {
            return true;
        }
    }

    // For elements in viewport, check if they're topmost
    const centerX = rect.left + rect.width/2;
    const centerY = rect.top + rect.height/2;
    
    try {
        const topEl = document.elementFromPoint(centerX, centerY);
        if (!topEl) return false;

        let current = topEl;
        while (current && current !== document.documentElement) {
            if (current === element) return true;
            current = current.parentElement;
        }
        return false;
    } catch (e) {
        return true;
    }
  }

  /**
   * Checks if an element is within the expanded viewport.
   */
  function isInExpandedViewport(element, viewportExpansion) {
    if (viewportExpansion === -1) {
        return true;
    }

    const rect = getCachedBoundingRect(element);
    
    // Simple viewport check without scroll calculations
    return !(
        rect.bottom < -viewportExpansion ||
        rect.top > window.innerHeight + viewportExpansion ||
        rect.right < -viewportExpansion ||
        rect.left > window.innerWidth + viewportExpansion
    );
  }

  // Add this new helper function
  function getEffectiveScroll(element) {
    let currentEl = element;
    let scrollX = 0;
    let scrollY = 0;
    
    return measureDomOperation(() => {
      while (currentEl && currentEl !== document.documentElement) {
          if (currentEl.scrollLeft || currentEl.scrollTop) {
              scrollX += currentEl.scrollLeft;
              scrollY += currentEl.scrollTop;
          }
          currentEl = currentEl.parentElement;
      }

      scrollX += window.scrollX;
      scrollY += window.scrollY;

      return { scrollX, scrollY };
    }, 'scrollOperations');
  }

  // Add these helper functions at the top level
  function isInteractiveCandidate(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

    const tagName = element.tagName.toLowerCase();
    
    // Fast-path for common interactive elements
    const interactiveElements = new Set([
      "a", "button", "input", "select", "textarea", "details", "summary"
    ]);
    
    if (interactiveElements.has(tagName)) return true;

    // Quick attribute checks without getting full lists
    const hasQuickInteractiveAttr = element.hasAttribute("onclick") || 
      element.hasAttribute("role") ||
      element.hasAttribute("tabindex") ||
      element.hasAttribute("aria-") ||
      element.hasAttribute("data-action");

    return hasQuickInteractiveAttr;
  }

  function quickVisibilityCheck(element) {
    // Fast initial check before expensive getComputedStyle
    return element.offsetWidth > 0 && 
            element.offsetHeight > 0 && 
            !element.hasAttribute("hidden") &&
            element.style.display !== "none" &&
            element.style.visibility !== "hidden";
  }

  // Add new constants and helper functions
  const HIDE_NOT_IN_VIEWPOINT = true;
  const HIDE_ARIA_HIDDEN = true;

  let black_listed_elements = new Set([
    "html", "head", "title", "meta", "body", "script", "style", "path", "br",
    "::marker", "#comment", "code", "noscript"
  ]);

  const INPUT_ATTRIBUTE_KEYS = [
    "id", "name", "type", "role", "placeholder", "aria-label", "title", "alt", "value"
  ];

  const GENERAL_ATTRIBUTE_KEYS = [
    "id", "name", "type", "role", "href", "placeholder", "aria-label", "title",
    "alt", "disabled", "src", "data-test", "color", "value"
  ];

  function isElementNode(node) {
    return node && node.nodeType === Node.ELEMENT_NODE;
  }

  function getRelevantAttributes(node, keys) {
    let results = {};
    if (isElementNode(node)) {
      for (const key of keys) {
        const val = node.getAttribute(key);
        if (val !== null) {
          results[key] = val;
        }
      }
    }
    return results;
  }

  // Add these new hash trees and ancestry trackers
  const anchor_ancestry = {};
  const button_ancestry = {};
  const option_ancestry = {};
  const select_ancestry = {};
  const contenteditable_ancestry = {};
  const textarea_ancestry = {};
  const para_ancestry = {};
  const modal_ancestry = {};
  const z_index_ancestry = {};
  const li_ancestry = {};
  const input_ancestry = {};
  const div_ancestry = {};
  const aria_hidden_ancestry = {};

  function add_to_hash_tree(hash_tree, tag, node_name, current_node, element_attributes) {
    if (!current_node) {
      console.error("Attempted to add undefined node to hash tree");
      return [false, null];
    }

    if (current_node.multion_idx in hash_tree) {
      return hash_tree[current_node.multion_idx];
    }

    let node_parent = current_node.parentNode;

    if (
      node_parent &&
      node_parent.multion_idx !== undefined &&
      !(node_parent.multion_idx in hash_tree) &&
      node_parent.nodeName
    ) {
      let parent_name = node_parent.nodeName.toLowerCase();
      add_to_hash_tree(hash_tree, tag, parent_name, node_parent, getRelevantAttributes(node_parent, GENERAL_ATTRIBUTE_KEYS));
    }

    let parent_result = node_parent && node_parent.multion_idx !== undefined
      ? (hash_tree[node_parent.multion_idx] || [false, null])
      : [false, null];
    let [is_parent_desc_anchor, anchor_node] = parent_result;

    let value = [false, null];

    if (tag === "z_index") {
      if (!isElementNode(current_node)) {
        value = parent_result;
      } else {
        const style = window.getComputedStyle(current_node);
        const currentZIndex = style.getPropertyValue("z-index");

        if (currentZIndex && currentZIndex !== "auto") {
          value = [parseInt(currentZIndex, 10), current_node];
        } else {
          value = parent_result;
        }
      }
    } else if (
      node_name === tag ||
      element_attributes["role"] === tag ||
      (tag === "contenteditable" && element_attributes["contenteditable"] === "true") ||
      (tag === "modal" && isModalOrOverlay(node_name, element_attributes))
    ) {
      if (tag === "a" && !("href" in element_attributes)) {
        value = [false, null];
      } else {
        value = [true, current_node];
      }
    } else if (is_parent_desc_anchor) {
      if (
        (tag === "span" || tag === "p") &&
        node_name !== "#text" &&
        node_name !== "b" &&
        node_name !== "i" &&
        node_name !== "u" &&
        node_name !== "em" &&
        node_name !== "strong" &&
        node_name !== "code"
      ) {
        value = [false, null];
      } else {
        value = [true, anchor_node];
      }
    } else {
      value = [false, null];
    }

    hash_tree[current_node.multion_idx] = value;
    return value;
  }

  function add_to_hash_tree_with_cond(hash_tree, current_node, cond) {
    if (current_node.multion_idx in hash_tree) {
      return hash_tree[current_node.multion_idx] || [false, null];
    }

    let node_parent = current_node.parentNode;

    if (!(node_parent?.multion_idx in hash_tree)) {
      if (node_parent) {
        add_to_hash_tree_with_cond(hash_tree, node_parent, cond);
      }
    }

    let parent_result = hash_tree[node_parent?.multion_idx] || [false, null];
    let [is_parent_desc_anchor, anchor_node] = parent_result;

    let value = [false, null];

    // Check if the node is an element before calling getAttribute
    if (current_node.nodeType === Node.ELEMENT_NODE) {
      if (cond(current_node)) {
        value = [true, current_node];
      } else if (is_parent_desc_anchor) {
        value = [true, anchor_node];
      }
    }

    hash_tree[current_node.multion_idx] = value;
    return value;
  }

  function isModalOrOverlay(node_name, element_attributes) {
    if (!node_name) return false;
    if (node_name === "modal" || element_attributes["aria-modal"] === "true") {
      return true;
    }
    if (node_name === "dialog" || element_attributes["role"] === "dialog") {
      return true;
    }
    return false;
  }

  function determineVisibility(node, context) {
    if (!quickVisibilityCheck(node)) return false;
    if (!isInExpandedViewport(node, context.viewportExpansion)) return false;
    return isElementVisible(node);
  }

  function determineInteractivity(node, context) {
    if (!isInteractiveCandidate(node)) return false;
    return isInteractiveElement(node);
  }

  function determineZIndex(node, context) {
    if (!node || node.multion_idx === undefined) {
      return 0; // Default z-index
    }
    const [zIndex, _] = add_to_hash_tree(z_index_ancestry, "z_index", node.nodeName.toLowerCase(), node, getRelevantAttributes(node, GENERAL_ATTRIBUTE_KEYS));
    return zIndex !== false ? zIndex : 0;
  }

  function processSpecialElement(node, nodeData, context) {
    const nodeName = node.nodeName.toLowerCase();
    if (nodeName === "input" || nodeName === "textarea") {
      nodeData.value = node.value;
    } else if (nodeName === "select") {
      nodeData.value = node.options[node.selectedIndex]?.text || "";
    }
  }

  function updateParentBasedOnChild(parentData, childData) {
    if (childData.isInteractive) parentData.hasInteractiveDescendant = true;
    if (childData.isVisible) parentData.hasVisibleDescendant = true;
    parentData.maxDescendantZIndex = Math.max(parentData.maxDescendantZIndex || 0, childData.zIndex || 0);
  }

  function propagateAttributes(node, ancestryData) {
    const propagatedAttributes = ['aria-hidden', 'disabled', 'inert'];
    for (const attr of propagatedAttributes) {
      if (node.getAttribute(attr) !== null) {
        ancestryData[attr] = node.getAttribute(attr);
      }
    }
    return ancestryData;
  }

  function isVisibleConsideringAncestry(node, ancestryData) {
    if (ancestryData['aria-hidden'] === 'true' || ancestryData['inert'] === 'true') {
      return false;
    }
    return isElementVisible(node);
  }

  function isInteractiveConsideringAncestry(node, ancestryData) {
    if (ancestryData['disabled'] === 'true' || ancestryData['aria-hidden'] === 'true' || ancestryData['inert'] === 'true') {
      return false;
    }
    return isInteractiveElement(node);
  }

  function getStackingContext(node) {
    const style = window.getComputedStyle(node);
    return {
      zIndex: style.zIndex !== 'auto' ? parseInt(style.zIndex, 10) : 0,
      opacity: parseFloat(style.opacity),
      position: style.position
    };
  }

  function isElementObscured(node, stackingContexts) {
    const rect = node.getBoundingClientRect();
    for (const context of stackingContexts) {
      if (context.node !== node && context.zIndex > node.zIndex) {
        const contextRect = context.node.getBoundingClientRect();
        if (
          rect.left < contextRect.right &&
          rect.right > contextRect.left &&
          rect.top < contextRect.bottom &&
          rect.bottom > contextRect.top
        ) {
          return true;
        }
      }
    }
    return false;
  }

  function buildMultionDomTree(
    node,
    context = {
      viewportExpansion: 0,
      debugMode: false,
      ancestryData: {},
      stackingContexts: []
    },
    parentIframe = null,
  ) {
    const { viewportExpansion, debugMode } = context;
    let { ancestryData, stackingContexts } = context;
    
    if (debugMode) PERF_METRICS.nodeMetrics.totalNodes++;

    if (!node || node.id === HIGHLIGHT_CONTAINER_ID) {
      if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
      return null;
    }

    // Assign a unique integer index to each node if it doesn't have one
    if (node.multion_idx === undefined) {
      node.multion_idx = String(ID.current++);
    }

    const node_name = node.nodeName.toLowerCase();
    // Create nodeData object for all nodes
    let nodeData = {
      tagName: node_name,
      attributes: {},
      xpath: node === document.body ? '/body' : getXPathTree(node, true),
      children: [],
      multion_idx: String(node.multion_idx),
      highlightIndex: String(node.multion_idx),
    };

    // Special handling for text nodes
    if (node.nodeType === Node.TEXT_NODE) {
      const textContent = node.textContent.trim();
      if (!textContent) {
        if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
        return null;
      }
      nodeData.type = "TEXT_NODE";
      nodeData.text = textContent;
      nodeData.isVisible = isTextNodeVisible(node)
      DOM_HASH_MAP[String(node.multion_idx)] = nodeData;
      if (debugMode) PERF_METRICS.nodeMetrics.processedNodes++;
      return nodeData;
    }

    // Handle element nodes
    if (node.nodeType === Node.ELEMENT_NODE) {
      // First check if element should be accepted
      if (!isElementAccepted(node)) {
        if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
        return null;
      }

      // Get attributes
      const attributeKeys = node_name === "input" ? INPUT_ATTRIBUTE_KEYS : GENERAL_ATTRIBUTE_KEYS;
      nodeData.attributes = getRelevantAttributes(node, attributeKeys);

      // Ancestry checks
      const ancestryChecks = [
        { tree: anchor_ancestry, tag: "a" },
        { tree: button_ancestry, tag: "button" },
        { tree: option_ancestry, tag: "option" },
        { tree: select_ancestry, tag: "select" },
        { tree: contenteditable_ancestry, tag: "contenteditable" },
        { tree: textarea_ancestry, tag: "span" },
        { tree: para_ancestry, tag: "p" },
        { tree: li_ancestry, tag: "li" },
        { tree: input_ancestry, tag: "input" },
        { tree: div_ancestry, tag: "div" },
        { tree: modal_ancestry, tag: "modal" },
      ];

      for (const check of ancestryChecks) {
        const [hasAncestor, ancestorNode] = add_to_hash_tree(check.tree, check.tag, node_name, node, nodeData.attributes);
        nodeData[`has_ancestor_${check.tag}`] = hasAncestor;
        nodeData[`${check.tag}_ancestor_node`] = ancestorNode;
      }

      let [has_aria_hidden, _] = add_to_hash_tree_with_cond(
        aria_hidden_ancestry,
        node,
        (node) => node.nodeType === Node.ELEMENT_NODE && node.getAttribute("aria-hidden") === "true"
      );
      nodeData.has_aria_hidden = has_aria_hidden;

      // Get stacking context information
      const style = getCachedComputedStyle(node);
      const stackingContext = style ? {
        position: style.position,
        zIndex: style.zIndex !== 'auto' ? parseInt(style.zIndex, 10) : 0,
        opacity: parseFloat(style.opacity)
      } : null;

      // Process children first
      const childContext = {
        ...context,
        ancestryData: {...ancestryData, ...propagateAttributes(node, ancestryData)},
        stackingContexts: stackingContext && stackingContext.position !== 'static' 
          ? [...stackingContexts, {node, ...stackingContext}] 
          : stackingContexts,
        parentIframe: node.tagName.toLowerCase() === "iframe" ? node : parentIframe
      };

      // Process children
      for (const child of node.childNodes) {
        const childElement = buildMultionDomTree(child, childContext, parentIframe);
        if (childElement !== null) {
          nodeData.children.push(childElement);
          updateParentBasedOnChild(nodeData, childElement);
        }
      }

      // Now check visibility and interactivity after processing children
      nodeData.isVisible = isElementVisible(node);
      nodeData.isInteractive = isInteractiveElement(node) && isInteractiveConsideringAncestry(node, context);
      nodeData.isInViewport = isInExpandedViewport(node, viewportExpansion);
      nodeData.zIndex = determineZIndex(node, context);

      // Only check if element is top if it's visible and in viewport
      if (nodeData.isVisible) {
        nodeData.isTopElement = isTopElement(node);
        if (nodeData.isTopElement && nodeData.isInViewport) {
          nodeData.highlightIndex = highlightIndex++;

          if (doHighlightElements) {
            if (focusHighlightIndex >= 0) {
              if (focusHighlightIndex === nodeData.highlightIndex) {
                highlightElement(node, nodeData.highlightIndex, parentIframe);
              }
            } else {
              highlightElement(node, nodeData.highlightIndex, parentIframe);
            }
          }
        }
      }

      // Process special elements
      if (isInteractiveCandidate(node)) {
        processSpecialElement(node, nodeData, context);
      }
    }

    // Ensure we always return a valid node object for the root (body)
    if (node === document.body) {
      nodeData.isRoot = true;
      nodeData.isVisible = true;
      nodeData.isInViewport = true;
    }

    DOM_HASH_MAP[String(node.multion_idx)] = nodeData;
    if (debugMode) PERF_METRICS.nodeMetrics.processedNodes++;
    return nodeData;
  }

  // After all functions are defined, wrap them with performance measurement
  // Remove buildMultionDomTree from here as we measure it separately
  highlightElement = measureTime(highlightElement);
  isInteractiveElement = measureTime(isInteractiveElement);
  isElementVisible = measureTime(isElementVisible);
  isTopElement = measureTime(isTopElement);
  isInExpandedViewport = measureTime(isInExpandedViewport);
  isTextNodeVisible = measureTime(isTextNodeVisible);
  getEffectiveScroll = measureTime(getEffectiveScroll);

  const rootContext = {
    ...args,
    ancestryData: {},
    stackingContexts: []
  };

  let rootNode = buildMultionDomTree(document.body, rootContext, null);

  // Ensure rootNode is always returned, even if it's empty
  if (!rootNode) {
    console.warn("Root node (body) was not processed. Creating a placeholder.");
    rootNode = {
      tagName: 'body',
      attributes: {},
      xpath: '/body',
      children: [],
      isRoot: true,
      isVisible: true,
      isInViewport: true,
      multion_idx: String(ID.current++)
    };
    DOM_HASH_MAP[String(rootNode.multion_idx)] = rootNode;
  }

  // Clear the cache before starting
  DOM_CACHE.clearCache();

  // Only process metrics in debug mode
  if (debugMode && PERF_METRICS) {
    // Convert timings to seconds and add useful derived metrics
    Object.keys(PERF_METRICS.timings).forEach(key => {
      PERF_METRICS.timings[key] = PERF_METRICS.timings[key] / 1000;
    });
    
    Object.keys(PERF_METRICS.buildMultionDomTreeBreakdown).forEach(key => {
      if (typeof PERF_METRICS.buildMultionDomTreeBreakdown[key] === 'number') {
        PERF_METRICS.buildMultionDomTreeBreakdown[key] = PERF_METRICS.buildMultionDomTreeBreakdown[key] / 1000;
      }
    });

    // Add some useful derived metrics
    if (PERF_METRICS.buildMultionDomTreeBreakdown.buildMultionDomTreeCalls > 0) {
      PERF_METRICS.buildMultionDomTreeBreakdown.averageTimePerNode = 
        PERF_METRICS.buildMultionDomTreeBreakdown.totalTime / PERF_METRICS.buildMultionDomTreeBreakdown.buildMultionDomTreeCalls;
    }

    PERF_METRICS.buildMultionDomTreeBreakdown.timeInChildCalls = 
    PERF_METRICS.buildMultionDomTreeBreakdown.totalTime - PERF_METRICS.buildMultionDomTreeBreakdown.totalSelfTime;

    // Add average time per operation to the metrics
    Object.keys(PERF_METRICS.buildMultionDomTreeBreakdown.domOperations).forEach(op => {
      const time = PERF_METRICS.buildMultionDomTreeBreakdown.domOperations[op];
      const count = PERF_METRICS.buildMultionDomTreeBreakdown.domOperationCounts[op];
      if (count > 0) {
        PERF_METRICS.buildMultionDomTreeBreakdown.domOperations[`${op}Average`] = time / count;
      }
    });

    // Calculate cache hit rates
    const boundingRectTotal = PERF_METRICS.cacheMetrics.boundingRectCacheHits + PERF_METRICS.cacheMetrics.boundingRectCacheMisses;
    const computedStyleTotal = PERF_METRICS.cacheMetrics.computedStyleCacheHits + PERF_METRICS.cacheMetrics.computedStyleCacheMisses;
    
    if (boundingRectTotal > 0) {
      PERF_METRICS.cacheMetrics.boundingRectHitRate = PERF_METRICS.cacheMetrics.boundingRectCacheHits / boundingRectTotal;
    }
    
    if (computedStyleTotal > 0) {
      PERF_METRICS.cacheMetrics.computedStyleHitRate = PERF_METRICS.cacheMetrics.computedStyleCacheHits / computedStyleTotal;
    }
    
    if ((boundingRectTotal + computedStyleTotal) > 0) {
      PERF_METRICS.cacheMetrics.overallHitRate = 
        (PERF_METRICS.cacheMetrics.boundingRectCacheHits + PERF_METRICS.cacheMetrics.computedStyleCacheHits) /
        (boundingRectTotal + computedStyleTotal);
    }
  }

  try {
    return debugMode ? 
      { rootId: String(rootNode.multion_idx), rootNode, map: DOM_HASH_MAP, perfMetrics: PERF_METRICS } : 
      { rootId: String(rootNode.multion_idx), rootNode, map: DOM_HASH_MAP };
  } catch (error) {
    console.error('Error in buildMultionDomTree:', error);
    console.error('Node:', node);
    console.error('Context:', context);
    // You can add more detailed logging here
    throw error; // Re-throw the error after logging
  }
};
