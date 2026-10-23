"""Trusted evaluate guards with bounded DOM observations.

The isolated-world request guard covers selected direct APIs called by the
evaluate realm. It is not a network policy: requests made through page event
handlers, workers, WebSockets, or other browser contexts are outside this guard,
and it does not provide server-side authorization. Direct GET, HEAD, and OPTIONS
requests are allowed and may still have server-side effects.

If a matched disabled or readonly control changes to an unrestricted state
between the evaluate snapshots, browser-use records an unattributed transition
and blocks later actions. It does not call that a confirmed violation. Normal
user input performed through browser actions outside evaluate is not treated as
such a transition. Page handlers can still change readonly values without
changing the restriction state, which the current snapshots do not detect.

Direct value setters, setRangeText, and the supported value-attribute mutation
APIs are guarded for readonly inputs and textareas in the evaluate isolated
world. The guard also blocks form.reset() when that form contains a restricted
control. Other control-specific APIs and DOM writes may remain outside coverage.

This is not a sandbox for arbitrary JavaScript: page-world script injection and
fresh frame contexts can execute outside these wrappers. Existing child frames
are refused; a frame created during evaluate is detected only afterwards, when
effects may already have occurred. Unawaited callbacks can also run after the
action's final counter read, so their later blocked attempts are not guaranteed
to appear in the action result. Only open shadow roots are traversed; closed
shadow roots are outside the snapshot and replacement checks.
"""

from __future__ import annotations

import json
import weakref
from typing import Any

from browser_use.agent.views import ConfirmedPolicyViolation, ControlStateChangeObservation

_WORLD_NAME = '__browser_use_evaluate_policy_guard__'
_GUARD_KEY = '__browser_use_evaluate_policy_guard_v1__'

_GUARD_BOOTSTRAP = r"""
(() => {
	const key = '__browser_use_evaluate_policy_guard_v1__';
	if (this[key]) {
		return true;
	}

	const apply = Reflect.apply;
	const defineProperty = Object.defineProperty;
	const getOwnPropertyDescriptor = Object.getOwnPropertyDescriptor;
	const freeze = Object.freeze;
	const setPrototypeOf = Object.setPrototypeOf;
	const stringify = JSON.stringify;
	const NativeTypeError = TypeError;
	const toString = String;
	const toBoolean = Boolean;
	const nativeToLowerCase = String.prototype.toLowerCase;
	const nativeToUpperCase = String.prototype.toUpperCase;
	const arrayPush = Array.prototype.push;
	const NativeWeakMap = WeakMap;
	const weakMapGet = WeakMap.prototype.get;
	const weakMapSet = WeakMap.prototype.set;
	const setHas = Set.prototype.has;
	const nativeNodeType = getOwnPropertyDescriptor(Node.prototype, 'nodeType').get;
	const nativeParentNode = getOwnPropertyDescriptor(Node.prototype, 'parentNode').get;
	const nativeFirstElementChild = getOwnPropertyDescriptor(Element.prototype, 'firstElementChild').get;
	const nativeNextElementSibling = getOwnPropertyDescriptor(Element.prototype, 'nextElementSibling').get;
	const nativeCreateTreeWalker = Document.prototype.createTreeWalker;
	const nativeTreeWalkerNextNode = TreeWalker.prototype.nextNode;
	const nativeGetRootNode = Node.prototype.getRootNode;
	const nativeRangeCommonAncestor = getOwnPropertyDescriptor(Range.prototype, 'commonAncestorContainer').get;
	const nativeRangeIntersectsNode = Range.prototype.intersectsNode;
	const nativeRangeCompareBoundaryPoints = Range.prototype.compareBoundaryPoints;
	const nativeRangeSelectNode = Range.prototype.selectNode;
	const nativeDocumentCreateRange = Document.prototype.createRange;
	const nativeSelectionRangeCount = getOwnPropertyDescriptor(Selection.prototype, 'rangeCount').get;
	const nativeSelectionGetRangeAt = Selection.prototype.getRangeAt;
	const nativeDocumentGetSelection = Document.prototype.getSelection;
	const observedDocument = document;
	const nativeMatches = Element.prototype.matches;
	const nativeHasAttribute = Element.prototype.hasAttribute;
	const nativeLocalName = getOwnPropertyDescriptor(Element.prototype, 'localName').get;
	const nativeShadowRoot = getOwnPropertyDescriptor(Element.prototype, 'shadowRoot').get;
	const nativeAttributeName = getOwnPropertyDescriptor(Attr.prototype, 'name').get;
	const nativeAttributeOwner = getOwnPropertyDescriptor(Attr.prototype, 'ownerElement').get;
	const nativeFormElements = getOwnPropertyDescriptor(HTMLFormElement.prototype, 'elements').get;
	const nativeCollectionLength = getOwnPropertyDescriptor(HTMLCollection.prototype, 'length').get;
	const nativeCollectionItem = HTMLCollection.prototype.item;
	const NativeRequest = Request;
	const nativeRequestMethod = getOwnPropertyDescriptor(NativeRequest.prototype, 'method').get;
	const MAX_WALKED_ELEMENTS = 20000;
	const MAX_SNAPSHOT_CONTROLS = 5000;
	const counts = Object.create(null);
	const ids = new NativeWeakMap();
	const namedNodeMapOwners = new NativeWeakMap();
	let nextId = 0;
	const xhrMethods = new NativeWeakMap();
	const formControlTags = new Set(['button', 'input', 'select', 'textarea', 'option', 'optgroup', 'fieldset']);
	// This direct-call allowlist does not imply that these methods are safe on a server.
	const safeRequestMethods = new Set(['GET', 'HEAD', 'OPTIONS']);

	function blocked(code) {
		counts[code] = (counts[code] || 0) + 1;
		const error = new NativeTypeError('[Browser Use policy guard] blocked ' + code);
		error.name = 'SecurityError';
		throw error;
	}

	function isRestricted(element, kind) {
		if (!element || apply(nativeNodeType, element, []) !== 1) return false;
		try {
			if (kind === 'disabled') return apply(nativeMatches, element, [':disabled']);
			const tag = apply(nativeToLowerCase, toString(apply(nativeLocalName, element, []) || ''), []);
			return (tag === 'input' || tag === 'textarea') && apply(nativeHasAttribute, element, ['readonly']);
		} catch (_) {
			return false;
		}
	}

	function isRestrictedSubtree(node) {
		if (!node) return false;
		const nodeType = apply(nativeNodeType, node, []);
		if (nodeType === 1 && apply(setHas, formControlTags, [apply(nativeToLowerCase, toString(apply(nativeLocalName, node, []) || ''), [])])) {
			if (isRestricted(node, 'disabled') || isRestricted(node, 'readonly')) return true;
		}
		if (nodeType !== 1 && nodeType !== 9 && nodeType !== 11) return false;
		const budget = {count: 0, exceeded: false};
		try {
			const found = visitElements(node, budget, (element) => isRestricted(element, 'disabled') || isRestricted(element, 'readonly'));
			return budget.exceeded ? null : found;
		} catch (_) {
			// A failed walk is ambiguous, so callers must block and disclose uncertainty.
			return null;
		}
	}

	function visitElements(root, budget, visit) {
		const roots = [root];
		if (apply(nativeNodeType, root, []) === 1) {
			const rootShadow = apply(nativeShadowRoot, root, []);
			if (rootShadow) apply(arrayPush, roots, [rootShadow]);
		}
		let rootIndex = 0;
		while (rootIndex < roots.length) {
			const currentRoot = roots[rootIndex++];
			const walker = apply(nativeCreateTreeWalker, observedDocument, [currentRoot, 1]);
			let element = apply(nativeTreeWalkerNextNode, walker, []);
			while (element) {
				if (budget.count >= MAX_WALKED_ELEMENTS) {
					budget.exceeded = true;
					return false;
				}
				budget.count += 1;
				if (visit(element)) return true;
				const shadowRoot = apply(nativeShadowRoot, element, []);
				if (shadowRoot) apply(arrayPush, roots, [shadowRoot]);
				element = apply(nativeTreeWalkerNextNode, walker, []);
			}
		}
		return false;
	}

	function guardRestrictedReplacement(target) {
		const restricted = isRestrictedSubtree(target);
		if (restricted === true) blocked('restricted_control_replacement');
		if (restricted === null) blocked('guard_enforcement_unavailable');
	}

	function isFirstLegendChild(fieldset, element) {
		let firstLegend = null;
		let child = apply(nativeFirstElementChild, fieldset, []);
		while (child) {
			if (apply(nativeToLowerCase, toString(apply(nativeLocalName, child, []) || ''), []) === 'legend') {
				firstLegend = child;
				break;
			}
			child = apply(nativeNextElementSibling, child, []);
		}
		if (!firstLegend) return false;

		let current = element;
		while (current && current !== fieldset) {
			const parent = apply(nativeParentNode, current, []);
			if (parent === fieldset) return current === firstLegend;
			current = parent;
		}
		return false;
	}

	function hasDisabledAncestorWithin(root, element) {
		if (root === element) return false;
		let ancestor = apply(nativeParentNode, element, []);
		while (ancestor) {
			if (apply(nativeNodeType, ancestor, []) === 1) {
				const tag = apply(nativeToLowerCase, toString(apply(nativeLocalName, ancestor, []) || ''), []);
				if (tag === 'fieldset' && apply(nativeHasAttribute, ancestor, ['disabled']) && !isFirstLegendChild(ancestor, element)) return true;
				if (tag === 'optgroup' && apply(nativeHasAttribute, ancestor, ['disabled'])) return true;
			}
			if (ancestor === root) break;
			ancestor = apply(nativeParentNode, ancestor, []);
		}
		return false;
	}

	function guardRestrictedTransfer(node, violationCode = 'disabled_control_transfer') {
		if (!node) return;
		const budget = {count: 0, exceeded: false};
		const isUnsafeTransfer = (element) => {
			if (!isRestricted(element, 'disabled') || apply(nativeHasAttribute, element, ['disabled'])) return false;
			return !hasDisabledAncestorWithin(node, element);
		};
		if (apply(nativeNodeType, node, []) === 1 && isUnsafeTransfer(node)) blocked(violationCode);
		const hasUnsafeTransfer = visitElements(node, budget, isUnsafeTransfer);
		if (budget.exceeded) blocked('guard_enforcement_unavailable');
		if (hasUnsafeTransfer) blocked(violationCode);
	}

	function guardTransferredArguments(args) {
		for (let index = 0; index < args.length; index += 1) {
			const argument = args[index];
			let nodeType;
			try {
				nodeType = apply(nativeNodeType, argument, []);
			} catch (_) {
				// Non-node arguments are valid for ParentNode APIs and need no transfer check.
				continue;
			}
			if (nodeType > 0) guardRestrictedTransfer(argument);
		}
	}

	function guardRangeMutation(range) {
		let root;
		try {
			const commonAncestor = apply(nativeRangeCommonAncestor, range, []);
			root = apply(nativeGetRootNode, commonAncestor, []);
		} catch (_) {
			blocked('guard_enforcement_unavailable');
		}
		const rootType = apply(nativeNodeType, root, []);
		if (rootType === 1 && (isRestricted(root, 'disabled') || isRestricted(root, 'readonly'))) {
			blocked('restricted_control_replacement');
		}
		if (rootType !== 1 && rootType !== 9 && rootType !== 11) blocked('guard_enforcement_unavailable');
		const budget = {count: 0, exceeded: false};
		let intersectsRestrictedControl;
		try {
			intersectsRestrictedControl = visitElements(root, budget, (element) => {
				if (!isRestricted(element, 'disabled') && !isRestricted(element, 'readonly')) return false;
				try {
					return apply(nativeRangeIntersectsNode, range, [element]);
				} catch (_) {
					return false;
				}
			});
		} catch (_) {
			blocked('guard_enforcement_unavailable');
		}
		if (budget.exceeded) blocked('guard_enforcement_unavailable');
		if (intersectsRestrictedControl) blocked('restricted_control_replacement');
	}

	function rangeContainsNode(range, node) {
		try {
			const nodeRange = apply(nativeDocumentCreateRange, observedDocument, []);
			apply(nativeRangeSelectNode, nodeRange, [node]);
			return apply(nativeRangeCompareBoundaryPoints, range, [0, nodeRange]) <= 0 &&
				apply(nativeRangeCompareBoundaryPoints, range, [2, nodeRange]) >= 0;
		} catch (_) {
			return false;
		}
	}

	function guardRangeClone(range) {
		let root;
		try {
			const commonAncestor = apply(nativeRangeCommonAncestor, range, []);
			root = apply(nativeGetRootNode, commonAncestor, []);
		} catch (_) {
			blocked('guard_enforcement_unavailable');
		}
		const rootType = apply(nativeNodeType, root, []);
		if (rootType !== 1 && rootType !== 9 && rootType !== 11) blocked('guard_enforcement_unavailable');
		const budget = {count: 0, exceeded: false};
		let duplicatesInheritedRestriction = false;
		visitElements(root, budget, (element) => {
			if (!isRestricted(element, 'disabled') || apply(nativeHasAttribute, element, ['disabled'])) return false;
			let intersects;
			try {
				intersects = apply(nativeRangeIntersectsNode, range, [element]);
			} catch (_) {
				return false;
			}
			if (!intersects) return false;

			let ancestor = apply(nativeParentNode, element, []);
			let preservedByIncludedAncestor = false;
			while (ancestor) {
				if (apply(nativeNodeType, ancestor, []) === 1) {
					const tag = apply(nativeToLowerCase, toString(apply(nativeLocalName, ancestor, []) || ''), []);
					const disabledFieldset = tag === 'fieldset' && apply(nativeHasAttribute, ancestor, ['disabled']);
					const disabledOptGroup = tag === 'optgroup' && apply(nativeHasAttribute, ancestor, ['disabled']);
					const applies = disabledFieldset
						? !isFirstLegendChild(ancestor, element)
						: disabledOptGroup;
					if (applies && rangeContainsNode(range, ancestor)) {
						preservedByIncludedAncestor = true;
						break;
					}
				}
				ancestor = apply(nativeParentNode, ancestor, []);
			}
			if (!preservedByIncludedAncestor) {
				duplicatesInheritedRestriction = true;
				return true;
			}
			return false;
		});
		if (budget.exceeded) blocked('guard_enforcement_unavailable');
		if (duplicatesInheritedRestriction) blocked('disabled_control_duplication');
	}

	function guardSelectionMutation(selection) {
		const rangeCount = apply(nativeSelectionRangeCount, selection, []);
		for (let index = 0; index < rangeCount; index += 1) {
			guardRangeMutation(apply(nativeSelectionGetRangeAt, selection, [index]));
		}
	}

	function patchMethod(prototype, name, wrap) {
		const descriptor = getOwnPropertyDescriptor(prototype, name);
		if (!descriptor || typeof descriptor.value !== 'function' || descriptor.configurable !== true) return false;
		defineProperty(prototype, name, {
			value: wrap(descriptor.value),
			enumerable: descriptor.enumerable,
			writable: false,
			configurable: false,
		});
		return true;
	}

	function patchOptionalMethod(prototype, name, wrap) {
		if (!getOwnPropertyDescriptor(prototype, name)) return true;
		return patchMethod(prototype, name, wrap);
	}

	function patchSetter(prototype, name, wrap) {
		const descriptor = getOwnPropertyDescriptor(prototype, name);
		if (!descriptor || typeof descriptor.set !== 'function' || descriptor.configurable !== true) return false;
		defineProperty(prototype, name, {
			get: descriptor.get,
			set: wrap(descriptor.set),
			enumerable: descriptor.enumerable,
			configurable: false,
		});
		return true;
	}

	function patchGetter(prototype, name, wrap) {
		const descriptor = getOwnPropertyDescriptor(prototype, name);
		if (!descriptor || typeof descriptor.get !== 'function' || descriptor.configurable !== true) return false;
		defineProperty(prototype, name, {
			get: wrap(descriptor.get),
			set: descriptor.set,
			enumerable: descriptor.enumerable,
			configurable: false,
		});
		return true;
	}

	function patchRestrictedSetter(prototype, name, kind, code) {
		return patchSetter(prototype, name, (nativeSetter) => function(value) {
			if (!toBoolean(value) && isRestricted(this, kind)) blocked(code);
			return apply(nativeSetter, this, [value]);
		});
	}

	function normalizeAttributeName(name) {
		return apply(nativeToLowerCase, toString(name), []);
	}

	function attributeRestriction(element, name) {
		const attribute = normalizeAttributeName(name);
		if (attribute === 'disabled' && isRestricted(element, 'disabled')) return 'disabled_control_bypass';
		if (attribute === 'readonly' && isRestricted(element, 'readonly')) return 'readonly_control_bypass';
		if (attribute === 'value' && isRestricted(element, 'readonly')) return 'readonly_control_bypass';
		return null;
	}

	function valueAttributeRestriction(element, name) {
		return normalizeAttributeName(name) === 'value' && isRestricted(element, 'readonly')
			? 'readonly_control_bypass'
			: null;
	}

	function namedNodeMapValueRestriction(map, attribute) {
		const owner = apply(weakMapGet, namedNodeMapOwners, [map]);
		const name = attribute ? apply(nativeAttributeName, attribute, []) : null;
		return owner && name ? valueAttributeRestriction(owner, name) : null;
	}

	function guardFormReset(form) {
		let controls;
		let length;
		try {
			controls = apply(nativeFormElements, form, []);
			length = apply(nativeCollectionLength, controls, []);
		} catch (_) {
			blocked('guard_enforcement_unavailable');
		}
		if (length > MAX_WALKED_ELEMENTS) blocked('guard_enforcement_unavailable');
		for (let index = 0; index < length; index += 1) {
			let control;
			try {
				control = apply(nativeCollectionItem, controls, [index]);
			} catch (_) {
				blocked('guard_enforcement_unavailable');
			}
			const tag = apply(nativeToLowerCase, toString(apply(nativeLocalName, control, []) || ''), []);
			if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') continue;
			if (isRestricted(control, 'disabled')) blocked('disabled_control_bypass');
			if (isRestricted(control, 'readonly')) blocked('readonly_control_bypass');
		}
	}

	const required = [];
	required.push(patchMethod(HTMLFormElement.prototype, 'reset', (native) => function() {
		guardFormReset(this);
		return apply(native, this, arguments);
	}));
	required.push(patchGetter(Element.prototype, 'attributes', (native) => function() {
		const attributes = apply(native, this, []);
		apply(weakMapSet, namedNodeMapOwners, [attributes, this]);
		return attributes;
	}));
	for (const type of [HTMLButtonElement, HTMLInputElement, HTMLSelectElement, HTMLTextAreaElement,
		HTMLOptionElement, HTMLOptGroupElement, HTMLFieldSetElement]) {
		if (type && type.prototype && getOwnPropertyDescriptor(type.prototype, 'disabled')) {
			required.push(patchRestrictedSetter(type.prototype, 'disabled', 'disabled', 'disabled_control_bypass'));
		} else if (type) {
			required.push(false);
		}
	}
	for (const type of [HTMLInputElement, HTMLTextAreaElement]) {
		if (type && type.prototype && getOwnPropertyDescriptor(type.prototype, 'readOnly')) {
			required.push(patchRestrictedSetter(type.prototype, 'readOnly', 'readonly', 'readonly_control_bypass'));
		} else if (type) {
			required.push(false);
		}
	}
	for (const type of [HTMLInputElement, HTMLTextAreaElement]) {
		if (type && type.prototype && getOwnPropertyDescriptor(type.prototype, 'value')) {
			required.push(patchSetter(type.prototype, 'value', (nativeSetter) => function(value) {
				if (isRestricted(this, 'readonly')) blocked('readonly_control_bypass');
				return apply(nativeSetter, this, [value]);
			}));
		} else if (type) {
			required.push(false);
		}
		if (type && type.prototype && getOwnPropertyDescriptor(type.prototype, 'defaultValue')) {
			required.push(patchSetter(type.prototype, 'defaultValue', (nativeSetter) => function(value) {
				if (isRestricted(this, 'readonly')) blocked('readonly_control_bypass');
				return apply(nativeSetter, this, [value]);
			}));
		} else if (type) {
			required.push(false);
		}
		required.push(type && type.prototype
			? patchMethod(type.prototype, 'setRangeText', (native) => function(...args) {
				if (isRestricted(this, 'readonly')) blocked('readonly_control_bypass');
				return apply(native, this, args);
			})
			: false);
	}
	for (const name of ['valueAsNumber', 'valueAsDate']) {
		required.push(patchSetter(HTMLInputElement.prototype, name, (nativeSetter) => function(value) {
			if (isRestricted(this, 'readonly')) blocked('readonly_control_bypass');
			return apply(nativeSetter, this, [value]);
		}));
	}
	for (const method of ['stepUp', 'stepDown']) {
		required.push(patchMethod(HTMLInputElement.prototype, method, (native) => function(...args) {
			if (isRestricted(this, 'readonly')) blocked('readonly_control_bypass');
			return apply(native, this, args);
		}));
	}
	required.push(patchMethod(Element.prototype, 'setAttribute', (native) => function(name, value) {
		const attributeName = toString(name);
		const code = valueAttributeRestriction(this, attributeName);
		if (code) blocked(code);
		return apply(native, this, [attributeName, value]);
	}));
	required.push(patchMethod(Element.prototype, 'setAttributeNS', (native) => function(namespace, qualifiedName, value) {
		const namespaceName = namespace == null ? null : toString(namespace);
		const attributeName = toString(qualifiedName);
		const code = namespaceName === null || namespaceName === ''
			? valueAttributeRestriction(this, attributeName)
			: null;
		if (code) blocked(code);
		return apply(native, this, [namespaceName, attributeName, value]);
	}));
	for (const method of ['setAttributeNode', 'setAttributeNodeNS']) {
		required.push(patchMethod(Element.prototype, method, (native) => function(attribute) {
			const name = attribute ? apply(nativeAttributeName, attribute, []) : null;
			const code = name ? valueAttributeRestriction(this, name) : null;
			if (code) blocked(code);
			return apply(native, this, arguments);
		}));
	}
	required.push(patchSetter(Attr.prototype, 'value', (nativeSetter) => function(value) {
		const owner = apply(nativeAttributeOwner, this, []);
		const name = apply(nativeAttributeName, this, []);
		const code = owner ? valueAttributeRestriction(owner, name) : null;
		if (code) blocked(code);
		return apply(nativeSetter, this, [value]);
	}));
	required.push(patchSetter(Node.prototype, 'nodeValue', (nativeSetter) => function(value) {
		if (apply(nativeNodeType, this, []) === 2) {
			const owner = apply(nativeAttributeOwner, this, []);
			const name = apply(nativeAttributeName, this, []);
			const code = owner ? valueAttributeRestriction(owner, name) : null;
			if (code) blocked(code);
		}
		return apply(nativeSetter, this, [value]);
	}));

	required.push(patchMethod(Element.prototype, 'removeAttribute', (native) => function(name) {
		const attributeName = toString(name);
		const code = attributeRestriction(this, attributeName);
		if (code) blocked(code);
		return apply(native, this, [attributeName]);
	}));
	required.push(patchMethod(Element.prototype, 'removeAttributeNS', (native) => function(namespace, localName) {
		const namespaceName = namespace == null ? null : toString(namespace);
		const attributeName = toString(localName);
		const code = namespaceName === null || namespaceName === '' ? attributeRestriction(this, attributeName) : null;
		if (code) blocked(code);
		return apply(native, this, [namespaceName, attributeName]);
	}));
	required.push(patchMethod(Element.prototype, 'toggleAttribute', (native) => function(name, force) {
		const attribute = toString(name);
		const exists = apply(nativeHasAttribute, this, [attribute]);
		const removes = exists && (arguments.length < 2 || !toBoolean(force));
		const adds = !exists && (arguments.length < 2 || toBoolean(force));
		const code = removes
			? attributeRestriction(this, attribute)
			: adds
				? valueAttributeRestriction(this, attribute)
				: null;
		if (code) blocked(code);
		return apply(native, this, arguments.length < 2 ? [attribute] : [attribute, force]);
	}));
	for (const method of ['setNamedItem', 'setNamedItemNS']) {
		required.push(patchMethod(NamedNodeMap.prototype, method, (native) => function(attribute) {
			const code = namedNodeMapValueRestriction(this, attribute);
			if (code) blocked(code);
			return apply(native, this, arguments);
		}));
	}
	required.push(patchMethod(Element.prototype, 'removeAttributeNode', (native) => function(attribute) {
		const name = attribute ? apply(nativeAttributeName, attribute, []) : null;
		const code = name ? attributeRestriction(this, name) : null;
		if (code) blocked(code);
		return apply(native, this, [attribute]);
	}));

	const nativeGetNamedItem = NamedNodeMap.prototype.getNamedItem;
	const nativeGetNamedItemNS = NamedNodeMap.prototype.getNamedItemNS;
	required.push(patchMethod(NamedNodeMap.prototype, 'removeNamedItem', (native) => function(name) {
		const itemName = toString(name);
		const attribute = apply(nativeGetNamedItem, this, [itemName]);
		const owner = attribute ? apply(nativeAttributeOwner, attribute, []) : null;
		const attributeName = attribute ? apply(nativeAttributeName, attribute, []) : null;
		const code = owner ? attributeRestriction(owner, attributeName) : null;
		if (code) blocked(code);
		return apply(native, this, [itemName]);
	}));
	required.push(patchMethod(NamedNodeMap.prototype, 'removeNamedItemNS', (native) => function(namespace, localName) {
		const namespaceName = namespace == null ? null : toString(namespace);
		const itemName = toString(localName);
		const attribute = apply(nativeGetNamedItemNS, this, [namespaceName, itemName]);
		const owner = attribute ? apply(nativeAttributeOwner, attribute, []) : null;
		const name = attribute ? apply(nativeAttributeName, attribute, []) : null;
		const code = owner ? attributeRestriction(owner, name) : null;
		if (code) blocked(code);
		return apply(native, this, [namespaceName, itemName]);
	}));

	for (const [prototype, method, guard] of [
		[Node.prototype, 'cloneNode', (target) => guardRestrictedTransfer(target, 'disabled_control_duplication')],
		[Node.prototype, 'removeChild', (_target, args) => guardRestrictedReplacement(args[0])],
		[Node.prototype, 'replaceChild', (_target, args) => {
			guardRestrictedReplacement(args[1]);
			guardRestrictedTransfer(args[0]);
		}],
		[Node.prototype, 'appendChild', (_target, args) => guardRestrictedTransfer(args[0])],
		[Node.prototype, 'insertBefore', (_target, args) => guardRestrictedTransfer(args[0])],
		[Element.prototype, 'replaceWith', (target, args) => {
			guardRestrictedReplacement(target);
			guardTransferredArguments(args);
		}],
		[Element.prototype, 'replaceChildren', (target, args) => {
			guardRestrictedReplacement(target);
			guardTransferredArguments(args);
		}],
		[Element.prototype, 'append', (_target, args) => guardTransferredArguments(args)],
		[Element.prototype, 'prepend', (_target, args) => guardTransferredArguments(args)],
		[Element.prototype, 'before', (_target, args) => guardTransferredArguments(args)],
		[Element.prototype, 'after', (_target, args) => guardTransferredArguments(args)],
		[DocumentFragment.prototype, 'replaceChildren', (target, args) => {
			guardRestrictedReplacement(target);
			guardTransferredArguments(args);
		}],
		[DocumentFragment.prototype, 'append', (_target, args) => guardTransferredArguments(args)],
		[DocumentFragment.prototype, 'prepend', (_target, args) => guardTransferredArguments(args)],
		[Document.prototype, 'replaceChildren', (target, args) => {
			guardRestrictedReplacement(target);
			guardTransferredArguments(args);
		}],
		[Document.prototype, 'append', (_target, args) => guardTransferredArguments(args)],
		[Document.prototype, 'prepend', (_target, args) => guardTransferredArguments(args)],
	]) {
		required.push(patchMethod(prototype, method, (native) => function(...args) {
			guard(this, args);
			return apply(native, this, args);
		}));
	}
	required.push(patchMethod(Document.prototype, 'adoptNode', (native) => function(node) {
		guardRestrictedTransfer(node);
		return apply(native, this, arguments);
	}));
	required.push(patchMethod(Document.prototype, 'importNode', (native) => function(node, deep) {
		guardRestrictedTransfer(node, 'disabled_control_duplication');
		return apply(native, this, arguments);
	}));
	required.push(patchMethod(Element.prototype, 'insertAdjacentElement', (native) => function(position, element) {
		guardRestrictedTransfer(element);
		return apply(native, this, [position, element]);
	}));

	for (const name of ['innerHTML', 'outerHTML', 'textContent']) {
		const prototype = name === 'textContent' ? Node.prototype : Element.prototype;
		required.push(patchSetter(prototype, name, (nativeSetter) => function(value) {
			if (name === 'textContent' && apply(nativeNodeType, this, []) === 2) {
				const owner = apply(nativeAttributeOwner, this, []);
				const attributeName = apply(nativeAttributeName, this, []);
				const code = owner ? valueAttributeRestriction(owner, attributeName) : null;
				if (code) blocked(code);
			} else {
				guardRestrictedReplacement(this);
			}
			return apply(nativeSetter, this, [value]);
		}));
	}
	required.push(patchSetter(ShadowRoot.prototype, 'innerHTML', (nativeSetter) => function(value) {
		guardRestrictedReplacement(this);
		return apply(nativeSetter, this, [value]);
	}));
	for (const prototype of [Element.prototype, ShadowRoot.prototype]) {
		for (const method of ['setHTML', 'setHTMLUnsafe']) {
			required.push(patchOptionalMethod(prototype, method, (native) => function(...args) {
				guardRestrictedReplacement(this);
				return apply(native, this, args);
			}));
		}
	}
	required.push(patchMethod(Element.prototype, 'remove', (native) => function() {
		guardRestrictedReplacement(this);
		return apply(native, this, arguments);
	}));
	for (const method of ['open', 'write', 'writeln']) {
		required.push(patchMethod(Document.prototype, method, (native) => function(...args) {
			guardRestrictedReplacement(observedDocument);
			return apply(native, this, args);
		}));
	}
	for (const method of ['deleteContents', 'extractContents', 'surroundContents']) {
		required.push(patchMethod(Range.prototype, method, (native) => function(...args) {
			guardRangeMutation(this);
			return apply(native, this, args);
		}));
	}
	required.push(patchMethod(Range.prototype, 'cloneContents', (native) => function() {
		guardRangeClone(this);
		return apply(native, this, arguments);
	}));
	required.push(patchMethod(Range.prototype, 'insertNode', (native) => function(node) {
		guardRestrictedTransfer(node);
		return apply(native, this, arguments);
	}));
	required.push(patchMethod(Selection.prototype, 'deleteFromDocument', (native) => function() {
		guardSelectionMutation(this);
		return apply(native, this, arguments);
	}));
	required.push(patchMethod(Document.prototype, 'execCommand', (native) => function(command, ...args) {
		const normalizedCommand = apply(nativeToLowerCase, toString(command), []);
		if (normalizedCommand === 'delete' || normalizedCommand === 'cut') {
			const selection = apply(nativeDocumentGetSelection, observedDocument, []);
			if (selection) guardSelectionMutation(selection);
		}
		return apply(native, this, [command, ...args]);
	}));

	function isSafeRequestMethod(method) {
		return apply(setHas, safeRequestMethods, [apply(nativeToUpperCase, toString(method), [])]);
	}

	const nativeFetch = globalThis.fetch;
	const fetchDescriptor = getOwnPropertyDescriptor(globalThis, 'fetch');
	if (typeof nativeFetch === 'function' && fetchDescriptor && fetchDescriptor.configurable === true) {
		defineProperty(globalThis, 'fetch', {
			value: function(input, init) {
				const request = new NativeRequest(input, init);
				const method = apply(nativeRequestMethod, request, []);
				if (!isSafeRequestMethod(method)) blocked('direct_state_change_request');
				return apply(nativeFetch, globalThis, [request]);
			},
			enumerable: fetchDescriptor.enumerable,
			writable: false,
			configurable: false,
		});
	} else {
		required.push(false);
	}

	required.push(patchMethod(XMLHttpRequest.prototype, 'open', (native) => function(method) {
		const normalizedMethod = apply(nativeToUpperCase, toString(method), []);
		arguments[0] = normalizedMethod;
		// A failed reopen can leave the previous native request active. Commit
		// the tracked method only after the native call succeeds.
		const result = apply(native, this, arguments);
		apply(weakMapSet, xhrMethods, [this, normalizedMethod]);
		return result;
	}));
	required.push(patchMethod(XMLHttpRequest.prototype, 'send', (native) => function() {
		if (!isSafeRequestMethod(apply(weakMapGet, xhrMethods, [this]))) blocked('direct_state_change_request');
		return apply(native, this, arguments);
	}));
	required.push(patchMethod(Navigator.prototype, 'sendBeacon', (native) => function() {
		blocked('direct_state_change_request');
	}));
	required.push(patchMethod(HTMLFormElement.prototype, 'submit', (native) => function() {
		blocked('direct_state_change_request');
	}));
	required.push(patchMethod(HTMLFormElement.prototype, 'requestSubmit', (native) => function() {
		blocked('direct_state_change_request');
	}));

	function snapshot() {
		// Null prototypes prevent evaluated code's toJSON hooks from forging trusted data.
		const controls = setPrototypeOf([], null);
		const nodeBudget = {count: 0, exceeded: false};
		visitElements(observedDocument, nodeBudget, (element) => {
			const tag = apply(nativeToLowerCase, toString(apply(nativeLocalName, element, []) || ''), []);
			if (!apply(setHas, formControlTags, [tag])) return false;
			if (controls.length >= MAX_SNAPSHOT_CONTROLS) {
				nodeBudget.exceeded = true;
				return true;
			}
			const disabled = apply(nativeMatches, element, [':disabled']);
			const readonly = isRestricted(element, 'readonly');
			let id = apply(weakMapGet, ids, [element]);
			if (id === undefined) {
				id = ++nextId;
				apply(weakMapSet, ids, [element, id]);
			}
			apply(arrayPush, controls, [setPrototypeOf({key: toString(id), disabled, readonly}, null)]);
			return false;
		});
		return setPrototypeOf({
			controls,
			complete: !nodeBudget.exceeded,
		}, null);
	}
	for (const installed of required) {
		if (installed !== true) return false;
	}

	const guard = freeze({
		readState: () => stringify(setPrototypeOf({counts, snapshot: snapshot()}, null)),
	});
	defineProperty(globalThis, key, {value: guard, enumerable: false, writable: false, configurable: false});
	return true;
})()
"""

_READ_GUARD_STATE = f"this['{_GUARD_KEY}'].readState()"


def _control_index(controls: list[Any]) -> tuple[dict[str, dict[str, Any]], int]:
	"""Index unique snapshot identities and count restricted controls with ambiguous identities."""
	key_counts: dict[str, int] = {}
	for control in controls:
		if isinstance(control, dict) and isinstance(control.get('key'), str):
			key = control['key']
			key_counts[key] = key_counts.get(key, 0) + 1

	indexed: dict[str, dict[str, Any]] = {}
	unmatched_restricted = 0
	for control in controls:
		if not isinstance(control, dict):
			continue
		key = control.get('key')
		restricted = control.get('disabled') is True or control.get('readonly') is True
		if not isinstance(key, str) or key_counts.get(key) != 1:
			if restricted:
				unmatched_restricted += 1
			continue
		indexed[key] = control
	return indexed, unmatched_restricted


def compare_control_snapshots(before: dict[str, Any], after: dict[str, Any]) -> ControlStateChangeObservation | None:
	"""Describe restricted-control snapshot changes without assigning causality."""
	before_controls = before.get('controls', [])
	after_controls = after.get('controls', [])
	before_by_key, before_unmatched = _control_index(before_controls)
	after_by_key, after_unmatched = _control_index(after_controls)
	before_restricted = {
		key for key, control in before_by_key.items() if control.get('disabled') is True or control.get('readonly') is True
	}
	after_restricted = {
		key for key, control in after_by_key.items() if control.get('disabled') is True or control.get('readonly') is True
	}
	if before.get('identity') != after.get('identity'):
		unmatched = len(before_restricted) + len(after_restricted) + before_unmatched + after_unmatched
		return ControlStateChangeObservation(restricted_controls_unmatched=unmatched) if unmatched else None

	unmatched = (
		len(before_restricted - after_by_key.keys())
		+ len(after_restricted - before_by_key.keys())
		+ before_unmatched
		+ after_unmatched
	)
	disabled_to_enabled = 0
	readonly_to_editable = 0
	for key in before_by_key.keys() & after_by_key.keys():
		previous = before_by_key[key]
		current = after_by_key[key]
		if previous.get('disabled') is True and current.get('disabled') is False:
			disabled_to_enabled += 1
		if previous.get('readonly') is True and current.get('readonly') is False:
			readonly_to_editable += 1
	if not (disabled_to_enabled or readonly_to_editable or unmatched):
		return None
	return ControlStateChangeObservation(
		disabled_to_enabled=disabled_to_enabled,
		readonly_to_editable=readonly_to_editable,
		restricted_controls_unmatched=unmatched,
	)


class EvaluatePolicyGuard:
	"""Create and query a protected isolated world for each frame loader."""

	def __init__(self) -> None:
		self._contexts: weakref.WeakKeyDictionary[Any, dict[str, tuple[str, int]]] = weakref.WeakKeyDictionary()

	async def has_child_frames(self, cdp_session: Any) -> bool:
		"""Return whether the current page has nested frames outside this guard boundary."""
		frame_tree = await cdp_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)
		children = frame_tree.get('frameTree', {}).get('childFrames', [])
		return bool(children)

	async def context_for(self, cdp_session: Any) -> tuple[str, int] | None:
		"""Return a cached main-frame isolated world, recreating it after navigation."""
		client = cdp_session.cdp_client
		session_id = cdp_session.session_id
		frame_tree = await client.send.Page.getFrameTree(session_id=session_id)
		frame = frame_tree.get('frameTree', {}).get('frame', {})
		frame_id = frame.get('id')
		loader_id = frame.get('loaderId')
		if not isinstance(frame_id, str) or not isinstance(loader_id, str):
			return None

		contexts = self._contexts.setdefault(client, {})
		cached = contexts.get(session_id)
		if cached is not None and cached[0] == loader_id:
			return frame_id, cached[1]

		world = await client.send.Page.createIsolatedWorld(
			params={'frameId': frame_id, 'worldName': _WORLD_NAME, 'grantUniveralAccess': False},
			session_id=session_id,
		)
		context_id = world.get('executionContextId')
		if not isinstance(context_id, int):
			return None
		contexts[session_id] = (loader_id, context_id)
		return frame_id, context_id

	async def install(self, cdp_session: Any, context_id: int) -> bool:
		"""Install immutable guards in the isolated world before agent code runs."""
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': _GUARD_BOOTSTRAP,
				'contextId': context_id,
				'returnByValue': True,
				'timeout': 1000,
			},
			session_id=cdp_session.session_id,
		)
		if result.get('exceptionDetails'):
			details = result['exceptionDetails']
			message = details.get('exception', {}).get('description') or details.get('text', 'Unknown error')
			raise RuntimeError(f'Evaluate policy guard bootstrap failed: {message}')
		value = result.get('result', {}).get('value')
		return value is True

	async def read_state(self, cdp_session: Any, frame_id: str, context_id: int) -> dict[str, Any] | None:
		"""Read guard counters and a bounded control snapshot from the isolated world."""
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': _READ_GUARD_STATE,
				'contextId': context_id,
				'returnByValue': True,
				'timeout': 500,
			},
			session_id=cdp_session.session_id,
		)
		if result.get('exceptionDetails'):
			return None
		value = result.get('result', {}).get('value')
		if not isinstance(value, str):
			return None
		try:
			value = json.loads(value)
		except (ValueError, TypeError):
			return None
		if not isinstance(value, dict) or not isinstance(value.get('counts'), dict):
			return None
		snapshot = value.get('snapshot')
		if not isinstance(snapshot, dict) or not isinstance(snapshot.get('controls'), list):
			return None
		if not isinstance(snapshot.get('complete'), bool):
			return None
		snapshot['identity'] = f'{frame_id}:{context_id}'
		return {'identity': frame_id, 'counts': value['counts'], 'snapshot': snapshot}


def violations_since(before: dict[str, Any], after: dict[str, Any]) -> list[ConfirmedPolicyViolation]:
	"""Convert only guard-owned monotonic counters into trusted typed markers."""
	previous = before.get('counts', {})
	current = after.get('counts', {})
	violations: list[ConfirmedPolicyViolation] = []
	for code in (
		'disabled_control_bypass',
		'readonly_control_bypass',
		'direct_state_change_request',
		'restricted_control_replacement',
		'disabled_control_transfer',
		'disabled_control_duplication',
	):
		old_count = previous.get(code, 0)
		new_count = current.get(code, 0)
		if isinstance(old_count, int) and isinstance(new_count, int) and new_count > old_count:
			violations.append(ConfirmedPolicyViolation(code=code, attempts=new_count - old_count))
	return violations


def enforcement_unavailable_since(before: dict[str, Any], after: dict[str, Any]) -> bool:
	"""Detect guard-owned outcomes blocked because the DOM scan was ambiguous."""
	previous = before.get('counts', {}).get('guard_enforcement_unavailable', 0)
	current = after.get('counts', {}).get('guard_enforcement_unavailable', 0)
	return isinstance(previous, int) and isinstance(current, int) and current > previous
