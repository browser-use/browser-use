(domElement) => {
  // Utility functions
  function escapeAttribute(str) {
    return str.replace(/"/g, '\\"');
  }

  function getElementTagName(element) {
    return element.localName.toLowerCase();
  }

  // Dynamic ID/attribute detection
  function isDynamicId(id) {
    const dynamicPatterns = [
      /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i, // UUID
      /^[a-f0-9]{24}$/i, // MongoDB ObjectId
      /^[a-f0-9]{32}$/i, // MD5
      /^[0-9]+$/, // Pure numbers
      /^[a-f0-9]{8,}$/i, // Long hex strings
      /^[a-z0-9]{8,}$/i, // Long alphanumeric strings
      /^[a-z0-9]+[-_][a-z0-9]+[-_][a-z0-9]+/i, // Multiple segments with random parts
    ];
    return dynamicPatterns.some((pattern) => pattern.test(id));
  }

  function isDynamicAttr(attrName, attrValue) {
    return isDynamicId(attrValue);
  }

  // Selector uniqueness checking
  function isUniqueCSSSelector(element, selector, logErrors = false) {
    try {
      const matches = document.querySelectorAll(selector);
      return matches.length === 1 && matches[0] === element;
    } catch (error) {
      if (logErrors) {
        console.error(`Invalid selector: ${selector}`, error);
      }
      return false;
    }
  }

  function isUniqueXPathSelector(element, xpath, logErrors = false) {
    try {
      const result = document.evaluate(
        xpath,
        document,
        null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
        null
      );
      return result.snapshotLength === 1 && result.snapshotItem(0) === element;
    } catch (error) {
      if (logErrors) {
        console.error(`Invalid XPath: ${xpath}`, error);
      }
      return false;
    }
  }

  // Text selector utilities
  const EXCLUDE_TEXT_SELECTOR_TAGS = ["svg", "path", "desc"];

  function getElementsByText(str, tag) {
    return Array.prototype.slice
      .call(document.getElementsByTagName(tag))
      .filter((el) => el.textContent.trim() === str.trim());
  }

  function isUniqueTextContent(element, text) {
    const tagName = getElementTagName(element);
    const elements = getElementsByText(text, tagName);
    return elements.length === 1 && elements[0] === element;
  }

  // CSS selector generation
  function getAttributeSelector(element, attributes, includeTag = true) {
    if (!attributes) return null;

    for (const attrName of attributes) {
      const attrValue = element.getAttribute(attrName);
      if (attrValue && !isDynamicAttr(attrName, attrValue)) {
        const attrSelector = `[${attrName}="${escapeAttribute(attrValue)}"]`;
        const selector = includeTag
          ? `${getElementTagName(element)}${attrSelector}`
          : attrSelector;
        if (isUniqueCSSSelector(element, selector)) {
          return selector;
        }
      }
    }
    return null;
  }

  function getElementSelector(element, options) {
    const { dataAttributes, nameAttributes, customAttrFallback } = options;

    // Try using ID
    if (element.id && !isDynamicId(element.id)) {
      const idSelector = `#${CSS.escape(element.id)}`;
      if (isUniqueCSSSelector(element, idSelector)) {
        return idSelector;
      }
    }

    // Try using a single stable data attribute
    const dataAttributeSelector = getAttributeSelector(element, dataAttributes);
    if (dataAttributeSelector) {
      return dataAttributeSelector;
    }

    // Try using a single stable aria or name attribute
    const otherAttributes = [
      ...(nameAttributes || []),
      ...(customAttrFallback || []),
    ];
    const otherAttributeSelector = getAttributeSelector(
      element,
      otherAttributes
    );
    if (otherAttributeSelector) {
      return otherAttributeSelector;
    }

    return null;
  }

  function getNthOfTypeSelector(element) {
    const parent = element.parentElement;
    if (!parent) return getElementTagName(element);

    const tagName = getElementTagName(element);
    const siblings = Array.from(parent.children);
    const sameTypeSiblings = siblings.filter(
      (child) => getElementTagName(child) === tagName
    );

    if (sameTypeSiblings.length === 1) {
      return tagName;
    }

    const index = sameTypeSiblings.indexOf(element) + 1;
    return `${tagName}:nth-of-type(${index})`;
  }

  // XPath selector generation
  function getUniqueAttributeXPathSelector(
    element,
    allAttributes,
    logErrors = false
  ) {
    for (const attrName of allAttributes) {
      const attrValue = element.getAttribute(attrName);
      if (attrValue && !isDynamicAttr(attrName, attrValue)) {
        const selector = `[@${attrName}="${escapeAttribute(attrValue)}"]`;
        if (isUniqueXPathSelector(element, `//*${selector}`, logErrors)) {
          return selector;
        }
      }
    }
    return null;
  }

  function getXPath(element, options) {
    const steps = [];
    let currentElement = element;

    while (currentElement && currentElement.nodeType === Node.ELEMENT_NODE) {
      let step = currentElement.localName.toLowerCase();

      // Check for id attribute
      const id = currentElement.getAttribute("id");
      if (id && !isDynamicId(id)) {
        step = `*[@id="${escapeAttribute(id)}"]`;
        steps.unshift(step);
        break;
      }

      // Handle attributes
      const allAttributes = [
        ...(options.dataAttributes || []),
        ...(options.nameAttributes || []),
        ...(options.customAttrFallback || []),
      ];
      const uniqueAttributeSelector = getUniqueAttributeXPathSelector(
        currentElement,
        allAttributes,
        options.logErrors
      );
      if (uniqueAttributeSelector) {
        step += uniqueAttributeSelector;
        steps.unshift(step);
        break;
      }

      // Calculate position among siblings
      const siblings = currentElement.parentNode
        ? Array.from(currentElement.parentNode.children)
        : [];
      const similiarSiblings = siblings.filter(
        (sibling) => sibling.localName === currentElement.localName
      );

      if (similiarSiblings.length > 1) {
        const index = similiarSiblings.indexOf(currentElement) + 1;
        step += `[${index}]`;
      }

      steps.unshift(step);
      currentElement = currentElement.parentNode;
    }

    // Remove the last step if it is an SVG element to ensure the selector is clickable
    if (steps.length === 1 && steps[0].startsWith("svg")) {
      return "//" + steps[0];
    } else if (steps.length > 1 && steps[steps.length - 1].startsWith("svg")) {
      steps.pop();
    }

    return "//" + steps.join("/");
  }

  // Main selector functions
  function getUniqueSelector(element, options = {}) {
    if (!(element instanceof Element)) return null;

    const defaultOptions = {
      maxDepth: 6,
      dataAttributes: ["data-test-id", "data-testid", "data-test", "data-qa"],
      nameAttributes: [
        "name",
        "title",
        "placeholder",
        "alt",
        "type",
        "href",
        "value",
        "role",
      ],
      includeTag: true,
      logErrors: false,
      customAttrFallback: [
        "data-pixel-component",
        "data-row-col",
        "data-name",
        "data-icon-name",
        "data-icon",
        "data-cy",
        "data-node-key",
        "data-id",
        "data-menu-xmlid",
      ],
    };

    options = { ...defaultOptions, ...options };
    let currentElement = element;
    let depth = 0;
    const selectors = [];

    // Try CSS selectors first
    while (currentElement && depth < options.maxDepth) {
      const selector = getElementSelector(currentElement, options);
      if (selector) {
        if (isUniqueCSSSelector(element, selector, options.logErrors)) {
          return selector;
        }
        selectors.unshift(selector);
      } else {
        const nthOfTypeSelector = getNthOfTypeSelector(currentElement);
        selectors.unshift(nthOfTypeSelector);
      }

      const combinedSelector = selectors.join(" > ");
      if (isUniqueCSSSelector(element, combinedSelector, options.logErrors)) {
        return combinedSelector;
      }

      const parent = currentElement.parentElement;
      if (!parent) break;
      currentElement = parent;
      depth++;
    }

    // Try text selector if CSS selector fails
    if (
      !EXCLUDE_TEXT_SELECTOR_TAGS.includes(element.tagName.toLowerCase()) &&
      !element.closest("svg")
    ) {
      const textContent = element.textContent?.trim();
      if (
        textContent &&
        textContent.length > 0 &&
        textContent.length < 100 &&
        isUniqueTextContent(element, textContent)
      ) {
        return `text=${escapeAttribute(textContent)}`;
      }
    }

    // Try XPath as last resort
    const xpathSelector = getXPath(element, options);
    if (xpathSelector) {
      return `xpath=${xpathSelector}`;
    }

    return null;
  }

  function getAllUniqueSelectors(element, options = {}) {
    if (!(element instanceof Element)) return [];

    const defaultOptions = {
      maxDepth: 6,
      dataAttributes: ["data-test-id", "data-testid", "data-test", "data-qa"],
      nameAttributes: [
        "name",
        "title",
        "placeholder",
        "alt",
        "type",
        "href",
        "value",
        "role",
      ],
      includeTag: true,
      logErrors: false,
      customAttrFallback: [
        "data-pixel-component",
        "data-row-col",
        "data-name",
        "data-icon-name",
        "data-icon",
        "data-cy",
        "data-node-key",
        "data-id",
        "data-menu-xmlid",
      ],
    };

    options = { ...defaultOptions, ...options };
    const allSelectors = new Set();

    // Get CSS selectors
    let currentElement = element;
    let depth = 0;
    const selectorPaths = [[]];

    while (currentElement && depth < options.maxDepth) {
      const newPaths = [];

      for (const path of selectorPaths) {
        const selector = getElementSelector(currentElement, options);
        if (selector) {
          const newPath = [selector, ...path];
          const combinedSelector = newPath.join(" > ");
          if (
            isUniqueCSSSelector(element, combinedSelector, options.logErrors)
          ) {
            allSelectors.add(combinedSelector);
          }
          newPaths.push(newPath);
        }

        const nthTypeSelector = getNthOfTypeSelector(currentElement);
        const nthTypePath = [nthTypeSelector, ...path];
        const nthTypeCombined = nthTypePath.join(" > ");
        if (isUniqueCSSSelector(element, nthTypeCombined, options.logErrors)) {
          allSelectors.add(nthTypeCombined);
        }
        newPaths.push(nthTypePath);
      }

      selectorPaths.push(...newPaths);
      const parent = currentElement.parentElement;
      if (!parent) break;
      currentElement = parent;
      depth++;
    }

    // Add text selector if applicable
    if (
      !EXCLUDE_TEXT_SELECTOR_TAGS.includes(element.tagName.toLowerCase()) &&
      !element.closest("svg")
    ) {
      const textContent = element.textContent?.trim();
      if (
        textContent &&
        textContent.length > 0 &&
        textContent.length < 100 &&
        isUniqueTextContent(element, textContent)
      ) {
        allSelectors.add(`text=${escapeAttribute(textContent)}`);
      }
    }

    // Add XPath selector
    const xpathSelector = getXPath(element, options);
    if (xpathSelector) {
      allSelectors.add(`xpath=${xpathSelector}`);
    }

    return Array.from(allSelectors).map((selector) => ({
      locatorValue: selector,
      isSelected: false,
    }));
  }

  const locator = getUniqueSelector(domElement);
  let allUniqueLocators = [];
  if (locator) {
    allUniqueLocators = getAllUniqueSelectors(domElement);
    if (allUniqueLocators.length > 0) {
      allUniqueLocators.forEach((otherLocator) => {
        if (otherLocator.locatorValue === locator) {
          otherLocator.isSelected = true;
        }
      });
    }
  }

  // Return public API
  return {
    locator,
    allUniqueLocators,
  };
};
