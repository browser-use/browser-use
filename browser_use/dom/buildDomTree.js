(
  args = {
    doHighlightElements: true,
    focusHighlightIndex: -1,
    viewportExpansion: 0,
  }
) => {
  const { doHighlightElements, focusHighlightIndex, viewportExpansion } = args;
  let highlightIndex = 0; // Reset highlight index

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
    const backgroundColor = `${baseColor}1A`; // 10% opacity version of the color

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

    // Add scroll listeners
    let currentEl = element;
    while (currentEl) {
        if (currentEl.scrollHeight > currentEl.clientHeight || 
            currentEl.scrollWidth > currentEl.clientWidth) {
            currentEl.addEventListener('scroll', updatePositions);
        }
        currentEl = currentEl.parentElement;
    }

    window.addEventListener('scroll', updatePositions);

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
   * Checks if an element is interactive.
   */
  function isInteractiveElement(element) {
    const { scrollX, scrollY } = getEffectiveScroll(element);
    const rect = element.getBoundingClientRect();
    
    // Use effective scroll for any position-based checks
    const absTop = rect.top + scrollY;
    const absLeft = rect.left + scrollX;
    const absBottom = rect.bottom + scrollY;
    const absRight = rect.right + scrollX;

    // Immediately return false for body tag
    // if (element.tagName.toLowerCase() === "body") {
    //   return false;
    // }

    // Base interactive elements and roles
    const interactiveElements = new Set([
      "a",
      "button",
      "details",
      "embed",
      "input",
      // "label",
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

    // Check if element has click-like styling
    // const hasClickStyling = style.cursor === 'pointer' ||
    //     element.style.cursor === 'pointer' ||
    //     style.pointerEvents !== 'none';

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
        // Try to get listeners using Chrome DevTools API
        return window.getEventListeners?.(el) || {};
      } catch (e) {
        // Fallback: check for common event properties
        const listeners = {};

        // List of common event types to check
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
            listeners[type] = [
              {
                listener: handler,
                useCapture: false,
              },
            ];
          }
        }

        return listeners;
      }
    }

    // Check for click-related events on the element itself
    const listeners = getEventListeners(element);
    const hasClickListeners =
      listeners &&
      (listeners.click?.length > 0 ||
        listeners.mousedown?.length > 0 ||
        listeners.mouseup?.length > 0 ||
        listeners.touchstart?.length > 0 ||
        listeners.touchend?.length > 0);

    // Check for ARIA properties that suggest interactivity
    const hasAriaProps =
      element.hasAttribute("aria-expanded") ||
      element.hasAttribute("aria-pressed") ||
      element.hasAttribute("aria-selected") ||
      element.hasAttribute("aria-checked");


    const isContentEditable = element.getAttribute("contenteditable") === "true" || element.isContentEditable ||
      element.id === "tinymce" ||
      element.classList.contains("mce-content-body") ||
      (element.tagName.toLowerCase() === "body" && element.getAttribute("data-id")?.startsWith("mce_"));

    // Check for form-related functionality
    const isFormRelated =
      element.form !== undefined ||
      element.hasAttribute("contenteditable") ||
      style.userSelect !== "none";

    // Check if element is draggable
    const isDraggable =
      element.draggable || element.getAttribute("draggable") === "true";

    // // Additional check to prevent body from being marked as interactive
    // if (
    //   element.tagName.toLowerCase() === "body" ||
    //   element.parentElement?.tagName.toLowerCase() === "body"
    // ) {
    //   return false;
    // }

    return (
      hasAriaProps ||
      // hasClickStyling ||
      hasClickHandler ||
      hasClickListeners ||
      // isFormRelated ||
      isDraggable ||
      isContentEditable
    );
  }

  /**
   * Checks if an element is visible.
   */
  function isElementVisible(element) {
    const style = window.getComputedStyle(element);
    return (
        element.offsetWidth > 0 &&
        element.offsetHeight > 0 &&
        style.visibility !== "hidden" &&
        style.display !== "none"
    );
  }

  /**
   * Checks if an element is the topmost element at its position.
   */
  function isTopElement(element) {
    const { scrollX, scrollY } = getEffectiveScroll(element);
    const rect = element.getBoundingClientRect();
    
    // Use effective scroll for center point calculation
    const centerX = rect.left + rect.width/2 + scrollX;
    const centerY = rect.top + rect.height/2 + scrollY;

    // Find the correct document context and root element
    let doc = element.ownerDocument;

    // If we're in an iframe, elements are considered top by default
    if (doc !== window.document) {
      return true;
    }

    // For shadow DOM, we need to check within its own root context
    const shadowRoot = element.getRootNode();
    if (shadowRoot instanceof ShadowRoot) {
      const point = {
        x: centerX,
        y: centerY,
      };

      try {
        // Use shadow root's elementFromPoint to check within shadow DOM context
        const topEl = shadowRoot.elementFromPoint(point.x, point.y);
        if (!topEl) return false;

        // Check if the element or any of its parents match our target element
        let current = topEl;
        while (current && current !== shadowRoot) {
          if (current === element) return true;
          current = current.parentElement;
        }
        return false;
      } catch (e) {
        return true; // If we can't determine, consider it visible
      }
    }

    // Regular DOM elements
    try {
      // If the element is not in viewport, we need to scroll to it temporarily
      const isInViewport = (
        centerX >= 0 &&
        centerX <= window.innerWidth &&
        centerY >= 0 &&
        centerY <= window.innerHeight
      );

      if (!isInViewport) {
        // Save current scroll position
        const originalScrollX = window.scrollX;
        const originalScrollY = window.scrollY;

        // Calculate scroll position to bring element into view
        const scrollX = originalScrollX + rect.left - (window.innerWidth / 4);
        const scrollY = originalScrollY + rect.top - (window.innerHeight / 4);

        // Temporarily scroll to the element
        window.scrollTo(scrollX, scrollY);

        // Get new coordinates after scroll
        const newRect = element.getBoundingClientRect();
        const newCenterX = newRect.left + newRect.width / 2;
        const newCenterY = newRect.top + newRect.height / 2;

        // Check if element is top at new position
        const topEl = document.elementFromPoint(newCenterX, newCenterY);

        // Restore original scroll position
        window.scrollTo(originalScrollX, originalScrollY);

        if (!topEl) return true; // If no element found, consider it top

        // Check if the found element is our target or one of its parents
        let current = topEl;
        while (current && current !== document.documentElement) {
          if (current === element) return true;
          current = current.parentElement;
        }
        return false;
      }

      // For elements in viewport, use original logic
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
    const { scrollX, scrollY } = getEffectiveScroll(element);  // Use effective scroll

    // Calculate expanded viewport boundaries including effective scroll
    const viewportTop = -viewportExpansion + scrollY;
    const viewportLeft = -viewportExpansion + scrollX;
    const viewportBottom = window.innerHeight + viewportExpansion + scrollY;
    const viewportRight = window.innerWidth + viewportExpansion + scrollX;

    // Get absolute element position using effective scroll
    const absTop = rect.top + scrollY;
    const absLeft = rect.left + scrollX;
    const absBottom = rect.bottom + scrollY;
    const absRight = rect.right + scrollX;

    return !(
      absBottom < viewportTop ||
      absTop > viewportBottom ||
      absRight < viewportLeft ||
      absLeft > viewportRight
    );
  }



  /**
   * Checks if a text node is visible.
   */
  function isTextNodeVisible(textNode) {
    const range = document.createRange();
    range.selectNodeContents(textNode);
    const rect = range.getBoundingClientRect();
    
    // Get effective scroll for the text node's parent element
    const { scrollX, scrollY } = getEffectiveScroll(textNode.parentElement);

    // Calculate expanded viewport boundaries including effective scroll
    const viewportTop = -viewportExpansion + scrollY;
    const viewportLeft = -viewportExpansion + scrollX;
    const viewportBottom = window.innerHeight + viewportExpansion + scrollY;
    const viewportRight = window.innerWidth + viewportExpansion + scrollX;

    // Get absolute text node position using effective scroll
    const absTop = rect.top + scrollY;
    const absLeft = rect.left + scrollX;
    const absBottom = rect.bottom + scrollY;
    const absRight = rect.right + scrollX;

    // Check if text node is within expanded viewport
    const isInExpandedViewport = !(
      absBottom < viewportTop ||
      absTop > viewportBottom ||
      absRight < viewportLeft ||
      absLeft > viewportRight
    );

    return (
      rect.width !== 0 &&
      rect.height !== 0 &&
      isInExpandedViewport &&
      textNode.parentElement?.checkVisibility({
        checkOpacity: true,
        checkVisibilityCSS: true,
      })
    );
  }

  // Add this new helper function
  function getEffectiveScroll(element) {
    let currentEl = element;
    let scrollX = 0;
    let scrollY = 0;

    while (currentEl && currentEl !== document.documentElement) {
        // Add scroll of any scrollable container
        if (currentEl.scrollLeft || currentEl.scrollTop) {
            scrollX += currentEl.scrollLeft;
            scrollY += currentEl.scrollTop;
        }
        currentEl = currentEl.parentElement;
    }

    // Add main window scroll
    scrollX += window.scrollX;
    scrollY += window.scrollY;

    return { scrollX, scrollY };
  }

  /**
   * Creates a node data object for a given node and its descendants and returns
   * the identifier of the node in the hash map or null if the node is not accepted.
   */
  function buildDomTree(node, parentIframe = null) {
    if (!node) {
      return null;
    }

    // NOTE: We skip highlight container nodes from the DOM tree
    //       by ignoring the container element itself and all its children.
    if (node.id === HIGHLIGHT_CONTAINER_ID) {
      return null;
    }

    // Special case for text nodes
    if (node.nodeType === Node.TEXT_NODE) {
      const textContent = node.textContent.trim();
      if (textContent ) { // 
        const id = `${ID.current++}`;

        DOM_HASH_MAP[id] = {
          type: "TEXT_NODE",
          text: textContent,
          isVisible: isTextNodeVisible(node),
        };

        return id;
      }
      return null;
    }

    // Check if element is accepted
    if (node.nodeType === Node.ELEMENT_NODE && !isElementAccepted(node)) {
      return null;
    }

    const nodeData = {
      tagName: node.tagName ? node.tagName.toLowerCase() : null,
      attributes: {},
      xpath:
        node.nodeType === Node.ELEMENT_NODE ? getXPathTree(node, true) : null,
      children: [],
    };

    // Add coordinates for element nodes
    if (node.nodeType === Node.ELEMENT_NODE) {
      const rect = node.getBoundingClientRect();
      const { scrollX, scrollY } = getEffectiveScroll(node);

      // Viewport-relative coordinates (can be negative when scrolled)
      nodeData.viewportCoordinates = {
        topLeft: {
          x: Math.round(rect.left),
          y: Math.round(rect.top),
        },
        topRight: {
          x: Math.round(rect.right),
          y: Math.round(rect.top),
        },
        bottomLeft: {
          x: Math.round(rect.left),
          y: Math.round(rect.bottom),
        },
        bottomRight: {
          x: Math.round(rect.right),
          y: Math.round(rect.bottom),
        },
        center: {
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2),
        },
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };

      // Page-relative coordinates (always positive, relative to page origin)
      nodeData.pageCoordinates = {
        topLeft: {
          x: Math.round(rect.left + scrollX),
          y: Math.round(rect.top + scrollY),
        },
        topRight: {
          x: Math.round(rect.right + scrollX),
          y: Math.round(rect.top + scrollY),
        },
        bottomLeft: {
          x: Math.round(rect.left + scrollX),
          y: Math.round(rect.bottom + scrollY),
        },
        bottomRight: {
          x: Math.round(rect.right + scrollX),
          y: Math.round(rect.bottom + scrollY),
        },
        center: {
          x: Math.round(rect.left + rect.width / 2 + scrollX),
          y: Math.round(rect.top + rect.height / 2 + scrollY),
        },
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };

      // Add viewport and scroll information using effective scroll
      nodeData.viewport = {
        scrollX: Math.round(scrollX),
        scrollY: Math.round(scrollY),
        width: window.innerWidth,
        height: window.innerHeight,
      };
    }

    // Copy all attributes if the node is an element
    if (node.nodeType === Node.ELEMENT_NODE && node.attributes) {
      // Use getAttributeNames() instead of directly iterating attributes
      const attributeNames = node.getAttributeNames?.() || [];
      for (const name of attributeNames) {
        nodeData.attributes[name] = node.getAttribute(name);
      }
    }

    if (node.nodeType === Node.ELEMENT_NODE) {
      const isInteractive = isInteractiveElement(node);
      const isVisible = isElementVisible(node);
      const isTop = isTopElement(node);
      const isInViewport = isInExpandedViewport(node, viewportExpansion);
      nodeData.isInteractive = isInteractive;
      nodeData.isVisible = isVisible;
      nodeData.isTopElement = isTop;
      nodeData.isInViewport = isInViewport;
      // Highlight if element meets all criteria and highlighting is enabled
      if (isInteractive && isVisible && isTop && isInViewport) {
        nodeData.highlightIndex = highlightIndex++;
        // console.log('highlightIndex', highlightIndex)
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

    // Only add iframeContext if we're inside an iframe
    // if (parentIframe) {
    //     nodeData.iframeContext = `iframe[src="${parentIframe.src || ''}"]`;
    // }

    // Only add shadowRoot field if it exists
    if (node.shadowRoot) {
      nodeData.shadowRoot = true;
    }

    // Handle shadow DOM
    if (node.shadowRoot) {
      for (const child of node.shadowRoot.childNodes) {
        const domElement = buildDomTree(child, parentIframe);
        if (domElement) {
          nodeData.children.push(domElement);
        }
      }
    }

    // Handle iframes
    if (node.tagName && node.tagName.toLowerCase() === "iframe") {
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
    } else {
      for (const child of node.childNodes) {
        const domElement = buildDomTree(child, parentIframe);
        if (domElement) {
          nodeData.children.push(domElement);
        }
      }
      // If it's an <a> element and has no visible content, return null
      if (nodeData.tagName === 'a' && nodeData.children.length === 0) {
        return null;
      }
    }

    // NOTE: We register the node to the hash map.
    const id = `${ID.current++}`;
    DOM_HASH_MAP[id] = nodeData;

    return id;
  }

  const rootId = buildDomTree(document.body);

  return { rootId, map: DOM_HASH_MAP };
};
