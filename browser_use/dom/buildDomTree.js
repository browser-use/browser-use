(
  args = {
    doHighlightElements: true,
    focusHighlightIndex: -1,
    viewportExpansion: 0,
  }
) => {
  const { doHighlightElements, focusHighlightIndex, viewportExpansion } = args;
  let highlightIndex = 0; // Reset highlight index

  // Add performance tracking
  const PERF_METRICS = {
    buildDomTreeCalls: 0,
    highlightElementCalls: 0,
    isInteractiveElementCalls: 0,
    isElementVisibleCalls: 0,
    isTopElementCalls: 0,
    isInExpandedViewportCalls: 0,
    isTextNodeVisibleCalls: 0,
    getEffectiveScrollCalls: 0,
    buildDomTreeBreakdown: {
      textNodeProcessing: 0,
      elementNodeProcessing: 0,
      iframeProcessing: 0,
      childrenProcessing: 0,
      attributeProcessing: 0,
      interactivityChecks: 0,
      domHashMapOperations: 0,
      xpathCalculation: 0,
      totalSelfTime: 0,  // Time spent in buildDomTree itself, excluding child calls
      totalTime: 0,      // Total time including all recursive calls
      depth: 0,          // Current recursion depth
      maxDepth: 0,      // Maximum recursion depth reached
      domOperations: {
        getBoundingClientRect: 0,
        getComputedStyle: 0,
        getAttribute: 0,
        getAttributeNames: 0,
        scrollOperations: 0,
        elementFromPoint: 0,
        checkVisibility: 0,
        createRange: 0,
      },
      domOperationCounts: {
        getBoundingClientRect: 0,
        getComputedStyle: 0,
        getAttribute: 0,
        getAttributeNames: 0,
        scrollOperations: 0,
        elementFromPoint: 0,
        checkVisibility: 0,
        createRange: 0,
      }
    },
    timings: {
      buildDomTree: 0,
      highlightElement: 0,
      isInteractiveElement: 0,
      isElementVisible: 0,
      isTopElement: 0,
      isInExpandedViewport: 0,
      isTextNodeVisible: 0,
      getEffectiveScroll: 0,
    }
  };

  // Helper to measure function execution time
  function measureTime(fn, metricName) {
    return function (...args) {
      PERF_METRICS[`${metricName}Calls`]++;
      const start = performance.now();
      const result = fn.apply(this, args);
      const duration = performance.now() - start;
      if (metricName !== 'buildDomTree') {  // Skip buildDomTree as we measure it separately
        PERF_METRICS.timings[metricName] += duration;
      }
      return result;
    };
  }

  // Helper to measure specific parts of buildDomTree
  function measureBuildDomTreePart(part, fn) {
    const start = performance.now();
    const result = fn();
    const duration = performance.now() - start;
    PERF_METRICS.buildDomTreeBreakdown[part] += duration;
    PERF_METRICS.buildDomTreeBreakdown.totalSelfTime += duration;
    return result;
  }

  // Helper to measure DOM operations
  function measureDomOperation(operation, name) {
    const start = performance.now();
    const result = operation();
    const duration = performance.now() - start;
    PERF_METRICS.buildDomTreeBreakdown.domOperations[name] += duration;
    PERF_METRICS.buildDomTreeBreakdown.domOperationCounts[name]++;
    return result;
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
    const rect = element.getBoundingClientRect();
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

  // Helper function to check if element is accepted
  function isElementAccepted(element) {
    const leafElementDenyList = new Set([
      "svg",
      "script",
      "style",
      "link",
      "meta",
    ]);
    return !leafElementDenyList.has(element.tagName.toLowerCase());
  }

  /**
   * Checks if an element is visible.
   */
  function isElementVisible(element) {
    const style = measureDomOperation(() => window.getComputedStyle(element), 'getComputedStyle');
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
    // const { scrollX, scrollY } = getEffectiveScroll(element);
    // const rect = element.getBoundingClientRect();
    
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
    const rect = measureDomOperation(() => element.getBoundingClientRect(), 'getBoundingClientRect');
    
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

    const rect = element.getBoundingClientRect();
    
    // Simple viewport check without scroll calculations
    return !(
        rect.bottom < -viewportExpansion ||
        rect.top > window.innerHeight + viewportExpansion ||
        rect.right < -viewportExpansion ||
        rect.left > window.innerWidth + viewportExpansion
    );
  }

  /**
   * Checks if a text node is visible.
   */
  function isTextNodeVisible(textNode) {
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

    return isInViewport && textNode.parentElement?.checkVisibility({
        checkOpacity: true,
        checkVisibilityCSS: true,
    });
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

  /**
   * Creates a node data object for a given node and its descendants and returns
   * the identifier of the node in the hash map or null if the node is not accepted.
   */
  function buildDomTree(node, parentIframe = null) {
    PERF_METRICS.buildDomTreeBreakdown.depth++;
    PERF_METRICS.buildDomTreeBreakdown.maxDepth = Math.max(
      PERF_METRICS.buildDomTreeBreakdown.maxDepth,
      PERF_METRICS.buildDomTreeBreakdown.depth
    );

    const start = performance.now();
    let result;

    try {
      if (!node) {
        return null;
      }

      // NOTE: We skip highlight container nodes from the DOM tree
      if (node.id === HIGHLIGHT_CONTAINER_ID) {
        return null;
      }

      // Special case for text nodes
      if (node.nodeType === Node.TEXT_NODE) {
        return measureBuildDomTreePart('textNodeProcessing', () => {
          const textContent = node.textContent.trim();
          if (textContent) {
            const id = `${ID.current++}`;
            DOM_HASH_MAP[id] = {
              type: "TEXT_NODE",
              text: textContent,
              isVisible: isTextNodeVisible(node),
            };
            return id;
          }
          return null;
        });
      }

      // Check if element is accepted
      if (node.nodeType === Node.ELEMENT_NODE && !isElementAccepted(node)) {
        return null;
      }

      const nodeData = measureBuildDomTreePart('elementNodeProcessing', () => ({
        tagName: node.tagName ? node.tagName.toLowerCase() : null,
        attributes: {},
        xpath: node.nodeType === Node.ELEMENT_NODE ? getXPathTree(node, true) : null,
        children: [],
      }));

      // Add coordinates for element nodes
      if (node.nodeType === Node.ELEMENT_NODE) {
        measureBuildDomTreePart('attributeProcessing', () => {
          const rect = measureDomOperation(() => node.getBoundingClientRect(), 'getBoundingClientRect');
          
          // Only store minimal viewport info
          nodeData.viewport = {
            width: window.innerWidth,
            height: window.innerHeight
          };
        });
      }

      // Measure attribute operations
      measureBuildDomTreePart('attributeProcessing', () => {
        const attributeNames = measureDomOperation(
          () => node.getAttributeNames?.() || [],
          'getAttributeNames'
        );
        for (const name of attributeNames) {
          nodeData.attributes[name] = measureDomOperation(
            () => node.getAttribute(name),
            'getAttribute'
          );
        }
      });

      if (node.nodeType === Node.ELEMENT_NODE) {
        measureBuildDomTreePart('interactivityChecks', () => {
          // Initialize all flags to false by default
          nodeData.isInteractive = false;
          nodeData.isVisible = false;
          nodeData.isTopElement = false;
          nodeData.isInViewport = false;

          // Check visibility first as it's the fastest check
          const isVisible = isElementVisible(node);
          if (!isVisible) return;
          nodeData.isVisible = true;

          // Check interactivity next as it's the second fastest
          const isInteractive = isInteractiveElement(node);
          if (!isInteractive) return;
          nodeData.isInteractive = true;

          // Check if element is top as third fastest
          const isTop = isTopElement(node);
          if (!isTop) return;
          nodeData.isTopElement = true;

          // Check viewport last as it's the most expensive
          const isInViewport = isInExpandedViewport(node, viewportExpansion);
          if (!isInViewport) return;
          nodeData.isInViewport = true;

          // Only if all checks pass, do we handle highlighting
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
        });
      }

      // Handle shadow DOM and iframes
      measureBuildDomTreePart('childrenProcessing', () => {
        if (node.shadowRoot) {
          nodeData.shadowRoot = true;
          for (const child of node.shadowRoot.childNodes) {
            const domElement = buildDomTree(child, parentIframe);
            if (domElement) {
              nodeData.children.push(domElement);
            }
          }
        }

        if (node.tagName && node.tagName.toLowerCase() === "iframe") {
          measureBuildDomTreePart('iframeProcessing', () => {
            try {
              const iframeDoc = node.contentDocument || node.contentWindow.document;
              if (iframeDoc) {
                for (const child of iframeDoc.childNodes) {
                  const domElement = buildDomTree(child, node);
                  if (domElement) {
                    nodeData.children.push(domElement);
                  }
                }
              }
            } catch (e) {
              console.warn("Unable to access iframe:", node);
            }
          });
        } else {
          for (const child of node.childNodes) {
            const domElement = buildDomTree(child, parentIframe);
            if (domElement) {
              nodeData.children.push(domElement);
            }
          }
        }

        if (nodeData.tagName === 'a' && nodeData.children.length === 0) {
          return null;
        }
      });

      result = measureBuildDomTreePart('domHashMapOperations', () => {
        const id = `${ID.current++}`;
        DOM_HASH_MAP[id] = nodeData;
        return id;
      });
    } finally {
      const duration = performance.now() - start;
      PERF_METRICS.buildDomTreeBreakdown.totalTime += duration;
      PERF_METRICS.buildDomTreeBreakdown.depth--;
    }

    return result;
  }

  // After all functions are defined, wrap them with performance measurement
  // Remove buildDomTree from here as we measure it separately
  highlightElement = measureTime(highlightElement, 'highlightElement');
  isInteractiveElement = measureTime(isInteractiveElement, 'isInteractiveElement');
  isElementVisible = measureTime(isElementVisible, 'isElementVisible');
  isTopElement = measureTime(isTopElement, 'isTopElement');
  isInExpandedViewport = measureTime(isInExpandedViewport, 'isInExpandedViewport');
  isTextNodeVisible = measureTime(isTextNodeVisible, 'isTextNodeVisible');
  getEffectiveScroll = measureTime(getEffectiveScroll, 'getEffectiveScroll');

  const rootId = buildDomTree(document.body);

  // Convert timings to seconds and add some useful derived metrics
  Object.keys(PERF_METRICS.timings).forEach(key => {
    PERF_METRICS.timings[key] = PERF_METRICS.timings[key] / 1000;
  });
  
  Object.keys(PERF_METRICS.buildDomTreeBreakdown).forEach(key => {
    if (typeof PERF_METRICS.buildDomTreeBreakdown[key] === 'number') {
      PERF_METRICS.buildDomTreeBreakdown[key] = PERF_METRICS.buildDomTreeBreakdown[key] / 1000;
    }
  });

  // Add some useful derived metrics
  PERF_METRICS.buildDomTreeBreakdown.averageTimePerNode = 
    PERF_METRICS.buildDomTreeBreakdown.totalTime / PERF_METRICS.buildDomTreeCalls;
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

  return { rootId, map: DOM_HASH_MAP, perfMetrics: PERF_METRICS };
};
