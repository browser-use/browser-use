from __future__ import annotations

import json

SEARCH_PAGE_JS_BODY = """\
try {
	var scope = CSS_SCOPE ? document.querySelector(CSS_SCOPE) : document.body;
	if (!scope) {
		return {error: 'CSS scope selector not found: ' + CSS_SCOPE, matches: [], total: 0};
	}
	var walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
	var fullText = '';
	var nodeOffsets = [];
	while (walker.nextNode()) {
		var node = walker.currentNode;
		var text = node.textContent;
		if (text && text.trim()) {
			nodeOffsets.push({offset: fullText.length, length: text.length, node: node});
			fullText += text;
		}
	}
	var re;
	try {
		var flags = CASE_SENSITIVE ? 'g' : 'gi';
		if (IS_REGEX) {
			re = new RegExp(PATTERN, flags);
		} else {
			re = new RegExp(PATTERN.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'), flags);
		}
	} catch (e) {
		return {error: 'Invalid regex pattern: ' + e.message, matches: [], total: 0};
	}
	var matches = [];
	var match;
	var totalFound = 0;
	while ((match = re.exec(fullText)) !== null) {
		totalFound++;
		if (matches.length < MAX_RESULTS) {
			var start = Math.max(0, match.index - CONTEXT_CHARS);
			var end = Math.min(fullText.length, match.index + match[0].length + CONTEXT_CHARS);
			var context = fullText.slice(start, end);
			var elementPath = '';
			for (var i = 0; i < nodeOffsets.length; i++) {
				var no = nodeOffsets[i];
				if (no.offset <= match.index && no.offset + no.length > match.index) {
					elementPath = _getPath(no.node.parentElement);
					break;
				}
			}
			matches.push({
				match_text: match[0],
				context: (start > 0 ? '...' : '') + context + (end < fullText.length ? '...' : ''),
				element_path: elementPath,
				char_position: match.index
			});
		}
		if (match[0].length === 0) re.lastIndex++;
	}
	return {matches: matches, total: totalFound, has_more: totalFound > MAX_RESULTS};
} catch (e) {
	return {error: 'search_page error: ' + e.message, matches: [], total: 0};
}
function _getPath(el) {
	var parts = [];
	var current = el;
	while (current && current !== document.body && current !== document) {
		var desc = current.tagName ? current.tagName.toLowerCase() : '';
		if (!desc) break;
		if (current.id) desc += '#' + current.id;
		else if (current.className && typeof current.className === 'string') {
			var classes = current.className.trim().split(/\\s+/).slice(0, 2).join('.');
			if (classes) desc += '.' + classes;
		}
		parts.unshift(desc);
		current = current.parentElement;
	}
	return parts.join(' > ');
}
"""

FIND_ELEMENTS_JS_BODY = """\
try {
	var elements;
	try {
		elements = document.querySelectorAll(SELECTOR);
	} catch (e) {
		return {error: 'Invalid CSS selector: ' + e.message, elements: [], total: 0};
	}
	var total = elements.length;
	var limit = Math.min(total, MAX_RESULTS);
	var results = [];
	for (var i = 0; i < limit; i++) {
		var el = elements[i];
		var item = {index: i, tag: el.tagName.toLowerCase()};
		if (INCLUDE_TEXT) {
			var text = (el.textContent || '').trim();
			item.text = text.length > 300 ? text.slice(0, 300) + '...' : text;
		}
		if (ATTRIBUTES && ATTRIBUTES.length > 0) {
			item.attrs = {};
			for (var j = 0; j < ATTRIBUTES.length; j++) {
				var attrName = ATTRIBUTES[j];
				var val;
				// Use resolved DOM property for src/href to get absolute URLs
				if ((attrName === 'src' || attrName === 'href') && typeof el[attrName] === 'string' && el[attrName] !== '') {
					val = el[attrName];
				} else {
					val = el.getAttribute(attrName);
				}
				if (val !== null) {
					item.attrs[attrName] = val.length > 500 ? val.slice(0, 500) + '...' : val;
				}
			}
		}
		item.children_count = el.children.length;
		results.push(item);
	}
	return {elements: results, total: total, showing: limit};
} catch (e) {
	return {error: 'find_elements error: ' + e.message, elements: [], total: 0};
}
"""


def build_search_page_js(
	pattern: str,
	regex: bool,
	case_sensitive: bool,
	context_chars: int,
	css_scope: str | None,
	max_results: int,
) -> str:
	"""Build JS IIFE for search_page with safe parameter injection."""
	params_js = (
		f'var PATTERN = {json.dumps(pattern)};\n'
		f'var IS_REGEX = {json.dumps(regex)};\n'
		f'var CASE_SENSITIVE = {json.dumps(case_sensitive)};\n'
		f'var CONTEXT_CHARS = {json.dumps(context_chars)};\n'
		f'var CSS_SCOPE = {json.dumps(css_scope)};\n'
		f'var MAX_RESULTS = {json.dumps(max_results)};\n'
	)
	return '(function() {\n' + params_js + SEARCH_PAGE_JS_BODY + '\n})()'


def build_find_elements_js(
	selector: str,
	attributes: list[str] | None,
	max_results: int,
	include_text: bool,
) -> str:
	"""Build JS IIFE for find_elements with safe parameter injection."""
	params_js = (
		f'var SELECTOR = {json.dumps(selector)};\n'
		f'var ATTRIBUTES = {json.dumps(attributes)};\n'
		f'var MAX_RESULTS = {json.dumps(max_results)};\n'
		f'var INCLUDE_TEXT = {json.dumps(include_text)};\n'
	)
	return '(function() {\n' + params_js + FIND_ELEMENTS_JS_BODY + '\n})()'
