(
    args = { doHighlightElements: true, focusHighlightIndex: -1, viewportExpansion: 0 }
) => {
    const { doHighlightElements, focusHighlightIndex, viewportExpansion } = args;
    let highlightIndex = 0; // Reset highlight index

    // Quick check to confirm the script receives focusHighlightIndex
    console.log('focusHighlightIndex:', focusHighlightIndex);

    function highlightElement(element, index, parentIframe = null) {
        // Create or get highlight container
        let container = document.getElementById('playwright-highlight-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'playwright-highlight-container';
            container.style.position = 'absolute';
            container.style.pointerEvents = 'none';
            container.style.top = '0';
            container.style.left = '0';
            container.style.width = '100%';
            container.style.height = '100%';
            container.style.zIndex = '2147483647'; // Maximum z-index value
            document.body.appendChild(container);        }

        // Generate a color based on the index
        const colors = [
            '#FF0000', '#00FF00', '#0000FF', '#FFA500',
            '#800080', '#008080', '#FF69B4', '#4B0082',
            '#FF4500', '#2E8B57', '#DC143C', '#4682B4'
        ];
        const colorIndex = index % colors.length;
        const baseColor = colors[colorIndex];
        const backgroundColor = `${baseColor}1A`; // 10% opacity version of the color

        // Create highlight overlay
        const overlay = document.createElement('div');
        overlay.style.position = 'absolute';
        overlay.style.border = `2px solid ${baseColor}`;
        overlay.style.backgroundColor = backgroundColor;
        overlay.style.pointerEvents = 'none';
        overlay.style.boxSizing = 'border-box';

        // Position overlay based on element, including scroll position
        const rect = element.getBoundingClientRect();
        let top = rect.top + window.scrollY;
        let left = rect.left + window.scrollX;

        // Adjust position if element is inside an iframe
        if (parentIframe) {
            const iframeRect = parentIframe.getBoundingClientRect();
            top += iframeRect.top;
            left += iframeRect.left;
        }

        overlay.style.top = `${top}px`;
        overlay.style.left = `${left}px`;
        overlay.style.width = `${rect.width}px`;
        overlay.style.height = `${rect.height}px`;

        // Create label
        const label = document.createElement('div');
        label.className = 'playwright-highlight-label';
        label.style.position = 'absolute';
        label.style.background = baseColor;
        label.style.color = 'white';
        label.style.padding = '1px 4px';
        label.style.borderRadius = '4px';
        label.style.fontSize = `${Math.min(12, Math.max(8, rect.height / 2))}px`; // Responsive font size
        label.textContent = index;

        // Calculate label position
        const labelWidth = 20; // Approximate width
        const labelHeight = 16; // Approximate height

        // Default position (top-right corner inside the box)
        let labelTop = top + 2;
        let labelLeft = left + rect.width - labelWidth - 2;

        // Adjust if box is too small
        if (rect.width < labelWidth + 4 || rect.height < labelHeight + 4) {
            // Position outside the box if it's too small
            labelTop = top - labelHeight - 2;
            labelLeft = left + rect.width - labelWidth;
        }


        label.style.top = `${labelTop}px`;
        label.style.left = `${labelLeft}px`;

        // Add to container
        container.appendChild(overlay);
        container.appendChild(label);

        // Store reference for cleanup
        element.setAttribute('browser-user-highlight-id', `playwright-highlight-${index}`);

        return index + 1;
    }


    // Helper function to generate XPath as a tree
    function getXPathTree(element, stopAtBoundary = true) {
        const segments = [];
        let currentElement = element;

        while (currentElement && currentElement.nodeType === Node.ELEMENT_NODE) {
            // Stop if we hit a shadow root or iframe
            if (stopAtBoundary && (currentElement.parentNode instanceof ShadowRoot || currentElement.parentNode instanceof HTMLIFrameElement)) {
                break;
            }

            let index = 0;
            let sibling = currentElement.previousSibling;
            while (sibling) {
                if (sibling.nodeType === Node.ELEMENT_NODE &&
                    sibling.nodeName === currentElement.nodeName) {
                    index++;
                }
                sibling = sibling.previousSibling;
            }

            const tagName = currentElement.nodeName.toLowerCase();
            const xpathIndex = index > 0 ? `[${index + 1}]` : '';
            segments.unshift(`${tagName}${xpathIndex}`);

            currentElement = currentElement.parentNode;
        }

        return segments.join('/');
    }

    // Helper function to check if element is accepted
    function isElementAccepted(element) {
        const leafElementDenyList = new Set(['svg', 'script', 'style', 'link', 'meta']);
        return !leafElementDenyList.has(element.tagName.toLowerCase());
    }

    // Helper function to check if element is interactive
    function isInteractiveElement(element) {
        // Immediately return false for body tag
        if (element.tagName.toLowerCase() === 'body') {
            return false;
        }

        // Base interactive elements and roles
        const interactiveElements = new Set([
            'a', 'button', 'details', 'embed', 'input', 'label',
            'menu', 'menuitem', 'object', 'select', 'textarea', 'summary'
        ]);

        const interactiveRoles = new Set([
            'button', 'menu', 'menuitem', 'link', 'checkbox', 'radio',
            'slider', 'tab', 'tabpanel', 'textbox', 'combobox', 'grid',
            'listbox', 'option', 'progressbar', 'scrollbar', 'searchbox',
            'switch', 'tree', 'treeitem', 'spinbutton', 'tooltip', 'a-button-inner', 'a-dropdown-button', 'click', 
            'menuitemcheckbox', 'menuitemradio', 'a-button-text', 'button-text', 'button-icon', 'button-icon-only', 'button-text-icon-only', 'dropdown', 'combobox'
        ]);

        const tagName = element.tagName.toLowerCase();
        const role = element.getAttribute('role');
        const ariaRole = element.getAttribute('aria-role');
        const tabIndex = element.getAttribute('tabindex');

        // Add check for specific class
        const hasAddressInputClass = element.classList.contains('address-input__container__input');

        // Basic role/attribute checks
        const hasInteractiveRole = hasAddressInputClass ||
            interactiveElements.has(tagName) ||
            interactiveRoles.has(role) ||
            interactiveRoles.has(ariaRole) ||
            (tabIndex !== null && tabIndex !== '-1' && element.parentElement?.tagName.toLowerCase() !== 'body') ||
            element.getAttribute('data-action') === 'a-dropdown-select' ||
            element.getAttribute('data-action') === 'a-dropdown-button';

        if (hasInteractiveRole) return true;

        // Get computed style
        const style = window.getComputedStyle(element);

        // Check if element has click-like styling
        // const hasClickStyling = style.cursor === 'pointer' ||
        //     element.style.cursor === 'pointer' ||
        //     style.pointerEvents !== 'none';

        // Check for event listeners
        const hasClickHandler = element.onclick !== null ||
            element.getAttribute('onclick') !== null ||
            element.hasAttribute('ng-click') ||
            element.hasAttribute('@click') ||
            element.hasAttribute('v-on:click');

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
                    'click', 'mousedown', 'mouseup',
                    'touchstart', 'touchend',
                    'keydown', 'keyup', 'focus', 'blur'
                ];

                for (const type of eventTypes) {
                    const handler = el[`on${type}`];
                    if (handler) {
                        listeners[type] = [{
                            listener: handler,
                            useCapture: false
                        }];
                    }
                }

                return listeners;
            }
        }

        // Check for click-related events on the element itself
        const listeners = getEventListeners(element);
        const hasClickListeners = listeners && (
            listeners.click?.length > 0 ||
            listeners.mousedown?.length > 0 ||
            listeners.mouseup?.length > 0 ||
            listeners.touchstart?.length > 0 ||
            listeners.touchend?.length > 0
        );

        // Check for ARIA properties that suggest interactivity
        const hasAriaProps = element.hasAttribute('aria-expanded') ||
            element.hasAttribute('aria-pressed') ||
            element.hasAttribute('aria-selected') ||
            element.hasAttribute('aria-checked');

        // Check for form-related functionality
        const isFormRelated = element.form !== undefined ||
            element.hasAttribute('contenteditable') ||
            style.userSelect !== 'none';

        // Check if element is draggable
        const isDraggable = element.draggable ||
            element.getAttribute('draggable') === 'true';

        // Additional check to prevent body from being marked as interactive
        if (element.tagName.toLowerCase() === 'body' || element.parentElement?.tagName.toLowerCase() === 'body') {
            return false;
        }

        return hasAriaProps ||
            // hasClickStyling ||
            hasClickHandler ||
            hasClickListeners ||
            // isFormRelated ||
            isDraggable;
    }

    // Helper function to check if element is visible
    function isElementVisible(element) {
        const style = window.getComputedStyle(element);
        return element.offsetWidth > 0 &&
            element.offsetHeight > 0 &&
            style.visibility !== 'hidden' &&
            style.display !== 'none';
    }

    // Helper function to check if element is the top element at its position
    function isTopElement(element) {
        // Find the correct document context and root element
        let doc = element.ownerDocument;

        // If we're in an iframe, elements are considered top by default
        if (doc !== window.document) {
            return true;
        }

        // For shadow DOM, we need to check within its own root context
        const shadowRoot = element.getRootNode();
        if (shadowRoot instanceof ShadowRoot) {
            const rect = element.getBoundingClientRect();
            const point = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };

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
        const rect = element.getBoundingClientRect();

        // If viewportExpansion is -1, check if element is the top one at its position
        if (viewportExpansion === -1) {
            return true; // Consider all elements as top elements when expansion is -1
        }

        // Calculate expanded viewport boundaries including scroll position
        const scrollX = window.scrollX;
        const scrollY = window.scrollY;
        const viewportTop = -viewportExpansion + scrollY;
        const viewportLeft = -viewportExpansion + scrollX;
        const viewportBottom = window.innerHeight + viewportExpansion + scrollY;
        const viewportRight = window.innerWidth + viewportExpansion + scrollX;

        // Get absolute element position
        const absTop = rect.top + scrollY;
        const absLeft = rect.left + scrollX;
        const absBottom = rect.bottom + scrollY;
        const absRight = rect.right + scrollX;

        // Skip if element is completely outside expanded viewport
        if (absBottom < viewportTop || 
            absTop > viewportBottom || 
            absRight < viewportLeft || 
            absLeft > viewportRight) {
            return false;
        }

        // For elements within expanded viewport, check if they're the top element
        try {
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            
            // Only clamp the point if it's outside the actual document
            const point = {
                x: centerX,
                y: centerY
            };
            
            if (point.x < 0 || point.x >= window.innerWidth || 
                point.y < 0 || point.y >= window.innerHeight) {
                return true; // Consider elements with center outside viewport as visible
            }

            const topEl = document.elementFromPoint(point.x, point.y);
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

    // Helper function to check if text node is visible
    function isTextNodeVisible(textNode) {
        const range = document.createRange();
        range.selectNodeContents(textNode);
        const rect = range.getBoundingClientRect();

        return rect.width !== 0 &&
            rect.height !== 0 &&
            rect.top >= 0 &&
            rect.top <= window.innerHeight &&
            textNode.parentElement?.checkVisibility({
                checkOpacity: true,
                checkVisibilityCSS: true
            });
    }


    // Function to traverse the DOM and create nested JSON
    function buildDomTree(node, parentIframe = null) {
        if (!node) return null;

        // Special case for text nodes
        if (node.nodeType === Node.TEXT_NODE) {
            const textContent = node.textContent.trim();
            if (textContent && isTextNodeVisible(node)) {
                return {
                    type: "TEXT_NODE",
                    text: textContent,
                    isVisible: true,
                };
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
            xpath: node.nodeType === Node.ELEMENT_NODE ? getXPathTree(node, true) : null,
            children: [],
        };

        // Add coordinates for element nodes
        if (node.nodeType === Node.ELEMENT_NODE) {
            const rect = node.getBoundingClientRect();
            const scrollX = window.scrollX;
            const scrollY = window.scrollY;
            
            // Viewport-relative coordinates (can be negative when scrolled)
            nodeData.viewportCoordinates = {
                topLeft: {
                    x: Math.round(rect.left),
                    y: Math.round(rect.top)
                },
                topRight: {
                    x: Math.round(rect.right),
                    y: Math.round(rect.top)
                },
                bottomLeft: {
                    x: Math.round(rect.left),
                    y: Math.round(rect.bottom)
                },
                bottomRight: {
                    x: Math.round(rect.right),
                    y: Math.round(rect.bottom)
                },
                center: {
                    x: Math.round(rect.left + rect.width/2),
                    y: Math.round(rect.top + rect.height/2)
                },
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            };
            
            // Page-relative coordinates (always positive, relative to page origin)
            nodeData.pageCoordinates = {
                topLeft: {
                    x: Math.round(rect.left + scrollX),
                    y: Math.round(rect.top + scrollY)
                },
                topRight: {
                    x: Math.round(rect.right + scrollX),
                    y: Math.round(rect.top + scrollY)
                },
                bottomLeft: {
                    x: Math.round(rect.left + scrollX),
                    y: Math.round(rect.bottom + scrollY)
                },
                bottomRight: {
                    x: Math.round(rect.right + scrollX),
                    y: Math.round(rect.bottom + scrollY)
                },
                center: {
                    x: Math.round(rect.left + rect.width/2 + scrollX),
                    y: Math.round(rect.top + rect.height/2 + scrollY)
                },
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            };

            // Add viewport and scroll information
            nodeData.viewport = {
                scrollX: Math.round(scrollX),
                scrollY: Math.round(scrollY),
                width: window.innerWidth,
                height: window.innerHeight
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

            nodeData.isInteractive = isInteractive;
            nodeData.isVisible = isVisible;
            nodeData.isTopElement = isTop;

            // Highlight if element meets all criteria and highlighting is enabled
            if (isInteractive && isVisible && isTop) {
                nodeData.highlightIndex = highlightIndex++;
                if (doHighlightElements) {
                    if(focusHighlightIndex >= 0){
                        if(focusHighlightIndex === nodeData.highlightIndex){
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
            const shadowChildren = Array.from(node.shadowRoot.childNodes).map(child =>
                buildDomTree(child, parentIframe)
            );
            nodeData.children.push(...shadowChildren);
        }

        // Handle iframes
        if (node.tagName === 'IFRAME') {
            try {
                const iframeDoc = node.contentDocument || node.contentWindow.document;
                if (iframeDoc) {
                    const iframeChildren = Array.from(iframeDoc.body.childNodes).map(child =>
                        buildDomTree(child, node)
                    );
                    nodeData.children.push(...iframeChildren);
                }
            } catch (e) {
                console.warn('Unable to access iframe:', node);
            }
        } else {
            const children = Array.from(node.childNodes).map(child =>
                buildDomTree(child, parentIframe)
            );
            nodeData.children.push(...children);
        }

        return nodeData;
    }


    return buildDomTree(document.body);
}
