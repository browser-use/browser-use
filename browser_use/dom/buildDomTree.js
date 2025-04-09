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

  function pushTiming(type) {
    TIMING_STACK[type] = TIMING_STACK[type] || [];
    TIMING_STACK[type].push(performance.now());
  }

  function popTiming(type) {
    const start = TIMING_STACK[type].pop();
    const duration = performance.now() - start;
    return duration;
  }

  // Only initialize performance tracking if in debug mode
  const PERF_METRICS = debugMode ? {
    buildDomTreeCalls: 0,
    timings: {
      buildDomTree: 0,
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
    buildDomTreeBreakdown: {
      totalTime: 0,
      totalSelfTime: 0,
      buildDomTreeCalls: 0,
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
    return function (...args) {
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

    if (PERF_METRICS && name in PERF_METRICS.buildDomTreeBreakdown.domOperations) {
      PERF_METRICS.buildDomTreeBreakdown.domOperations[name] += duration;
      PERF_METRICS.buildDomTreeBreakdown.domOperationCounts[name]++;
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
        PERF_METRICS.buildDomTreeBreakdown.domOperations.getBoundingClientRect += duration;
        PERF_METRICS.buildDomTreeBreakdown.domOperationCounts.getBoundingClientRect++;
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
        PERF_METRICS.buildDomTreeBreakdown.domOperations.getComputedStyle += duration;
        PERF_METRICS.buildDomTreeBreakdown.domOperationCounts.getComputedStyle++;
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
      if (parentIframe) {
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

        if (parentIframe) {
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
      ) || viewportExpansion === -1;

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
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    // Define interactive cursors
    const interactiveCursors = new Set([
      'pointer',    // Link/clickable elements
      'move',       // Movable elements
      'text',       // Text selection
      'grab',       // Grabbable elements
      'grabbing',   // Currently grabbing
      'cell',       // Table cell selection
      'copy',       // Copy operation
      'alias',      // Alias creation
      'all-scroll', // Scrollable content
      'col-resize', // Column resize
      'context-menu', // Context menu available
      'crosshair',  // Precise selection
      'e-resize',   // East resize
      'ew-resize',  // East-west resize
      'help',       // Help available
      'n-resize',   // North resize
      'ne-resize',  // Northeast resize
      'nesw-resize', // Northeast-southwest resize
      'ns-resize',  // North-south resize
      'nw-resize',  // Northwest resize
      'nwse-resize', // Northwest-southeast resize
      'row-resize', // Row resize
      's-resize',   // South resize
      'se-resize',  // Southeast resize
      'sw-resize',  // Southwest resize
      'vertical-text', // Vertical text selection
      'w-resize',   // West resize
      'zoom-in',    // Zoom in
      'zoom-out'    // Zoom out
    ]);

    // Define non-interactive cursors
    const nonInteractiveCursors = new Set([
      'not-allowed', // Action not allowed
      'no-drop',     // Drop not allowed
      'wait',        // Processing
      'progress',    // In progress
      'initial',     // Initial value
      'inherit'      // Inherited value
      //? Let's just include all potentially clickable elements that are not specifically blocked
      // 'none',        // No cursor
      // 'default',     // Default cursor 
      // 'auto',        // Browser default
    ]);

    function doesElementHaveInteractivePointer(element) {
      if (element.tagName.toLowerCase() === "html") return false;
      const style = getCachedComputedStyle(element);

      if (interactiveCursors.has(style.cursor)) return true;

      return false;
    }

    let isInteractiveCursor = doesElementHaveInteractivePointer(element);

    // Genius fix for almost all interactive elements
    if (isInteractiveCursor) {
      return true;
    }

    const interactiveElements = new Set([
      "a",          // Links
      "button",     // Buttons
      "input",      // All input types (text, checkbox, radio, etc.)
      "select",     // Dropdown menus
      "textarea",   // Text areas
      "details",    // Expandable details
      "summary",    // Summary element (clickable part of details)
      "label",      // Form labels (often clickable)
      "option",     // Select options
      "optgroup",   // Option groups
      "fieldset",   // Form fieldsets (can be interactive with legend)
      "legend",     // Fieldset legends
    ]);

    // Define explicit disable attributes and properties
    const explicitDisableTags = new Set([
      'disabled',           // Standard disabled attribute
      // 'aria-disabled',      // ARIA disabled state
      'readonly',          // Read-only state
      // 'aria-readonly',     // ARIA read-only state
      // 'aria-hidden',       // Hidden from accessibility
      // 'hidden',            // Hidden attribute
      // 'inert',             // Inert attribute
      // 'aria-inert',        // ARIA inert state
      // 'tabindex="-1"',     // Removed from tab order
      // 'aria-hidden="true"' // Hidden from screen readers
    ]);

    // handle inputs, select, checkbox, radio, textarea, button and make sure they are not cursor style disabled/not-allowed
    if (interactiveElements.has(element.tagName.toLowerCase())) {
      const style = getCachedComputedStyle(element);

      // Check for non-interactive cursor
      if (nonInteractiveCursors.has(style.cursor)) {
        return false;
      }

      // Check for explicit disable attributes
      for (const disableTag of explicitDisableTags) {
        if (element.hasAttribute(disableTag) ||
          element.getAttribute(disableTag) === 'true' ||
          element.getAttribute(disableTag) === '') {
          return false;
        }
      }

      // Check for disabled property on form elements
      if (element.disabled) {
        return false;
      }

      // Check for readonly property on form elements
      if (element.readOnly) {
        return false;
      }

      // Check for inert property
      if (element.inert) {
        return false;
      }

      return true;
    }

    // return false



    const tagName = element.tagName.toLowerCase();
    const role = element.getAttribute("role");
    const ariaRole = element.getAttribute("aria-role");
    const tabIndex = element.getAttribute("tabindex");

    // Add check for specific class
    // const hasAddressInputClass = element.classList && (
    //   element.classList.contains("address-input__container__input") ||
    //   element.classList.contains("nav-btn") ||
    //   element.classList.contains("pull-left")
    // );

    // Added enhancement to capture dropdown interactive elements
    if (element.classList && (
      element.classList.contains("button") ||
      element.classList.contains('dropdown-toggle') ||
      element.getAttribute('data-index') ||
      element.getAttribute('data-toggle') === 'dropdown' ||
      element.getAttribute('aria-haspopup') === 'true'
    )) {
      return true;
    }

    // return false

    const interactiveRoles = new Set([
      'button',           // Directly clickable element
      // 'link',            // Clickable link
      'menuitem',        // Clickable menu item
      'menuitemradio',   // Radio-style menu item (selectable)
      'menuitemcheckbox', // Checkbox-style menu item (toggleable)
      'radio',           // Radio button (selectable)
      'checkbox',        // Checkbox (toggleable)
      'tab',             // Tab (clickable to switch content)
      'switch',          // Toggle switch (clickable to change state)
      'slider',          // Slider control (draggable)
      'spinbutton',      // Number input with up/down controls
      'combobox',        // Dropdown with text input
      'searchbox',       // Search input field
      'textbox',         // Text input field
      'listbox',         // Selectable list
      'option',          // Selectable option in a list
      'scrollbar'        // Scrollable control
    ]);

    // Basic role/attribute checks
    const hasInteractiveRole =
      interactiveElements.has(tagName) ||
      interactiveRoles.has(role) ||
      interactiveRoles.has(ariaRole);

    if (hasInteractiveRole) return true;

    return false



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
      // hasAriaProps ||
      // hasClickHandler ||
      // hasClickListeners ||
      // isDraggable ||
      // isContentEditable ||
      false
    );
  }


  /**
   * Checks if an element is the topmost element at its position.
   */
  function isTopElement(element) {
    const rect = getCachedBoundingRect(element);

    if (viewportExpansion <= 0) {
      if (rect.bottom < 0 ||
        rect.top > window.innerHeight ||
        rect.right < 0 ||
        rect.left > window.innerWidth) {
        return false;
      }
    } else {
      // For positive viewportExpansion, only expand in Y direction
      if (rect.bottom < -viewportExpansion ||
        rect.top > window.innerHeight + viewportExpansion ||
        rect.right < 0 ||
        rect.left > window.innerWidth) {
        return false;
      }
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
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;

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
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

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
      element.hasAttribute("data-action") ||
      element.getAttribute("contenteditable") == "true";

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

  /**
   * Creates a node data object for a given node and its descendants.
   */
  function buildDomTree(node, parentIframe = null) {
    if (debugMode) PERF_METRICS.nodeMetrics.totalNodes++;

    if (!node || node.id === HIGHLIGHT_CONTAINER_ID) {
      if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
      return null;
    }

    // Special handling for root node (body)
    if (node === document.body) {
      const nodeData = {
        tagName: 'body',
        attributes: {},
        xpath: '/body',
        children: [],
      };

      // Process children of body
      for (const child of node.childNodes) {
        const domElement = buildDomTree(child, parentIframe);
        if (domElement) nodeData.children.push(domElement);
      }

      const id = `${ID.current++}`;
      DOM_HASH_MAP[id] = nodeData;
      if (debugMode) PERF_METRICS.nodeMetrics.processedNodes++;
      return id;
    }

    // Early bailout for non-element nodes except text
    if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.TEXT_NODE) {
      if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
      return null;
    }

    // Process text nodes
    if (node.nodeType === Node.TEXT_NODE) {
      const textContent = node.textContent.trim();
      if (!textContent) {
        if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
        return null;
      }

      // Only check visibility for text nodes that might be visible
      const parentElement = node.parentElement;
      if (!parentElement || parentElement.tagName.toLowerCase() === 'script') {
        if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
        return null;
      }

      const id = `${ID.current++}`;
      DOM_HASH_MAP[id] = {
        type: "TEXT_NODE",
        text: textContent,
        isVisible: isTextNodeVisible(node),
      };
      if (debugMode) PERF_METRICS.nodeMetrics.processedNodes++;
      return id;
    }

    // Quick checks for element nodes
    if (node.nodeType === Node.ELEMENT_NODE && !isElementAccepted(node)) {
      if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
      return null;
    }

    // Early viewport check - only filter out elements clearly outside viewport
    if (viewportExpansion !== -1) {
      const rect = getCachedBoundingRect(node);
      const style = getCachedComputedStyle(node);

      // Skip viewport check for fixed/sticky elements as they may appear anywhere
      const isFixedOrSticky = style && (style.position === 'fixed' || style.position === 'sticky');

      // Check if element has actual dimensions
      const hasSize = node.offsetWidth > 0 || node.offsetHeight > 0;

      if (!rect || (!isFixedOrSticky && !hasSize && (
        rect.bottom < -viewportExpansion ||
        rect.top > window.innerHeight + viewportExpansion ||
        rect.right < -viewportExpansion ||
        rect.left > window.innerWidth + viewportExpansion
      ))) {
        if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
        return null;
      }
    }

    // Process element node
    const nodeData = {
      tagName: node.tagName.toLowerCase(),
      attributes: {},
      xpath: getXPathTree(node, true),
      children: [],
    };

    // Get attributes for interactive elements or potential text containers
    if (isInteractiveCandidate(node) || node.tagName.toLowerCase() === 'iframe' || node.tagName.toLowerCase() === 'body') {
      const attributeNames = node.getAttributeNames?.() || [];
      for (const name of attributeNames) {
        nodeData.attributes[name] = node.getAttribute(name);
      }
    }

    // if (isInteractiveCandidate(node)) {

    // Check interactivity
    if (node.nodeType === Node.ELEMENT_NODE) {
      nodeData.isVisible = isElementVisible(node);
      if (nodeData.isVisible) {
        nodeData.isTopElement = isTopElement(node);
        if (nodeData.isTopElement) {
          nodeData.isInteractive = isInteractiveElement(node);
          if (nodeData.isInteractive) {
            nodeData.isInViewport = true;
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
      }
    }

    // Process children, with special handling for iframes and rich text editors
    if (node.tagName) {
      const tagName = node.tagName.toLowerCase();

      // Handle iframes
      if (tagName === "iframe") {
        try {
          const iframeDoc = node.contentDocument || node.contentWindow?.document;
          if (iframeDoc) {
            for (const child of iframeDoc.childNodes) {
              const domElement = buildDomTree(child, node);
              if (domElement) nodeData.children.push(domElement);
            }
          }
        } catch (e) {
          console.warn("Unable to access iframe:", e);
        }
      }
      // Handle rich text editors and contenteditable elements
      else if (
        node.isContentEditable ||
        node.getAttribute("contenteditable") === "true" ||
        node.id === "tinymce" ||
        node.classList.contains("mce-content-body") ||
        (tagName === "body" && node.getAttribute("data-id")?.startsWith("mce_"))
      ) {
        // Process all child nodes to capture formatted text
        for (const child of node.childNodes) {
          const domElement = buildDomTree(child, parentIframe);
          if (domElement) nodeData.children.push(domElement);
        }
      }
      else {
        // Handle shadow DOM
        if (node.shadowRoot) {
          nodeData.shadowRoot = true;
          for (const child of node.shadowRoot.childNodes) {
            const domElement = buildDomTree(child, parentIframe);
            if (domElement) nodeData.children.push(domElement);
          }
        }
        // Handle regular elements
        for (const child of node.childNodes) {
          const domElement = buildDomTree(child, parentIframe);
          if (domElement) nodeData.children.push(domElement);
        }
      }
    }

    // Skip empty anchor tags
    if (nodeData.tagName === 'a' && nodeData.children.length === 0 && !nodeData.attributes.href) {
      if (debugMode) PERF_METRICS.nodeMetrics.skippedNodes++;
      return null;
    }

    const id = `${ID.current++}`;
    DOM_HASH_MAP[id] = nodeData;
    if (debugMode) PERF_METRICS.nodeMetrics.processedNodes++;
    return id;
  }

  // After all functions are defined, wrap them with performance measurement
  // Remove buildDomTree from here as we measure it separately
  highlightElement = measureTime(highlightElement);
  isInteractiveElement = measureTime(isInteractiveElement);
  isElementVisible = measureTime(isElementVisible);
  isTopElement = measureTime(isTopElement);
  isInExpandedViewport = measureTime(isInExpandedViewport);
  isTextNodeVisible = measureTime(isTextNodeVisible);
  getEffectiveScroll = measureTime(getEffectiveScroll);

  const rootId = buildDomTree(document.body);

  // Clear the cache before starting
  DOM_CACHE.clearCache();

  // Only process metrics in debug mode
  if (debugMode && PERF_METRICS) {
    // Convert timings to seconds and add useful derived metrics
    Object.keys(PERF_METRICS.timings).forEach(key => {
      PERF_METRICS.timings[key] = PERF_METRICS.timings[key] / 1000;
    });

    Object.keys(PERF_METRICS.buildDomTreeBreakdown).forEach(key => {
      if (typeof PERF_METRICS.buildDomTreeBreakdown[key] === 'number') {
        PERF_METRICS.buildDomTreeBreakdown[key] = PERF_METRICS.buildDomTreeBreakdown[key] / 1000;
      }
    });

    // Add some useful derived metrics
    if (PERF_METRICS.buildDomTreeBreakdown.buildDomTreeCalls > 0) {
      PERF_METRICS.buildDomTreeBreakdown.averageTimePerNode =
        PERF_METRICS.buildDomTreeBreakdown.totalTime / PERF_METRICS.buildDomTreeBreakdown.buildDomTreeCalls;
    }

    PERF_METRICS.buildDomTreeBreakdown.timeInChildCalls =
      PERF_METRICS.buildDomTreeBreakdown.totalTime - PERF_METRICS.buildDomTreeBreakdown.totalSelfTime;

    // Add average time per operation to the metrics
    Object.keys(PERF_METRICS.buildDomTreeBreakdown.domOperations).forEach(op => {
      const time = PERF_METRICS.buildDomTreeBreakdown.domOperations[op];
      const count = PERF_METRICS.buildDomTreeBreakdown.domOperationCounts[op];
      if (count > 0) {
        PERF_METRICS.buildDomTreeBreakdown.domOperations[`${op}Average`] = time / count;
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

  return debugMode ?
    { rootId, map: DOM_HASH_MAP, perfMetrics: PERF_METRICS } :
    { rootId, map: DOM_HASH_MAP };
};
