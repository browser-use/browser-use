package browseruse

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

type IndexedElement struct {
	Index    int               `json:"index"`
	Selector string            `json:"selector"`
	Tag      string            `json:"tag"`
	Text     string            `json:"text"`
	Depth    int               `json:"depth"`
	Attrs    map[string]string `json:"attrs"`
	Bounding BoundingBox       `json:"rect"`
	IsNew    bool              `json:"is_new"`
}

type BrowserStateSummary struct {
	URL        string
	Title      string
	Tabs       []Target
	Elements   []IndexedElement
	PageText   string
	Screenshot string
}

type browserStatePayload struct {
	URL      string           `json:"url"`
	Title    string           `json:"title"`
	Text     string           `json:"text"`
	Elements []IndexedElement `json:"elements"`
}

func (bs *BrowserSession) GetBrowserStateSummary(ctx context.Context, includeScreenshot bool) (*BrowserStateSummary, error) {
	page := bs.GetCurrentPage()
	if page == nil {
		return nil, fmt.Errorf("no current page")
	}
	raw, err := page.Evaluate(ctx, collectInteractiveElementsJS)
	if err != nil {
		return nil, err
	}
	payload := browserStatePayload{}
	raw = strings.TrimSpace(raw)
	if raw != "" {
		if err := json.Unmarshal([]byte(raw), &payload); err != nil {
			payload = bs.fallbackBrowserStatePayload(ctx, page)
		}
	} else {
		payload = bs.fallbackBrowserStatePayload(ctx, page)
	}

	selectors := make(map[string]struct{})
	indexed := make([]IndexedElement, 0, len(payload.Elements))
	bs.elementsByIndex = make(map[int]IndexedElement)
	for i, element := range payload.Elements {
		index := i + 1
		selector := strings.TrimSpace(element.Selector)
		if selector == "" {
			continue
		}
		element.Index = index
		element.Selector = selector
		if _, ok := bs.lastSelectors[selector]; !ok {
			element.IsNew = true
		}
		selectors[selector] = struct{}{}
		indexed = append(indexed, element)
		bs.elementsByIndex[index] = element
	}
	bs.lastSelectors = selectors

	state := &BrowserStateSummary{
		URL:      payload.URL,
		Title:    payload.Title,
		Tabs:     bs.sessionManagerTargets(),
		Elements: indexed,
		PageText: payload.Text,
	}
	if includeScreenshot {
		if len(indexed) > 0 {
			if _, err := page.Evaluate(ctx, addHighlightOverlayJS, indexed); err == nil {
				defer func() {
					_, _ = page.Evaluate(ctx, removeHighlightOverlayJS)
				}()
			}
		}
		shot, err := page.Screenshot(ctx, "webp", nil, 1280, 720)
		if err != nil {
			return nil, err
		}
		state.Screenshot = shot
	}

	bs.lastBrowserState = state
	return state, nil
}

func (bs *BrowserSession) fallbackBrowserStatePayload(ctx context.Context, page *Page) browserStatePayload {
	return browserStatePayload{
		URL:   safeEvaluateString(ctx, page, "window.location.href"),
		Title: safeEvaluateString(ctx, page, "document.title"),
		Text:  safeEvaluateString(ctx, page, "(document.body && document.body.innerText || '').slice(0, 4000)"),
	}
}

func safeEvaluateString(ctx context.Context, page *Page, expression string) string {
	value, err := page.Evaluate(ctx, expression)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(value)
}

func (bs *BrowserSession) sessionManagerTargets() []Target {
	if bs.sessionManager == nil {
		return nil
	}
	raw := bs.sessionManager.GetAllPageTargets()
	targets := make([]Target, 0, len(raw))
	for _, target := range raw {
		if target == nil {
			continue
		}
		targets = append(targets, *target)
	}
	return targets
}

func (bs *BrowserSession) SelectorForIndex(index int) (string, bool) {
	if element, ok := bs.elementsByIndex[index]; ok {
		return element.Selector, true
	}
	return "", false
}

func (bs *BrowserSession) BrowserStateText() string {
	if bs.lastBrowserState == nil {
		return ""
	}
	state := bs.lastBrowserState
	var builder strings.Builder
	builder.WriteString("Current URL: ")
	builder.WriteString(state.URL)
	builder.WriteString("\n")
	if len(state.Tabs) > 0 {
		builder.WriteString("Open Tabs:\n")
		for _, tab := range state.Tabs {
			builder.WriteString(fmt.Sprintf("- [%s] %s\n", tab.TargetID, strings.TrimSpace(tab.Title)))
		}
	}
	builder.WriteString("Interactive Elements:\n")
	for _, element := range state.Elements {
		prefix := "["
		if element.IsNew {
			prefix = "*["
		}
		indent := strings.Repeat("\t", element.Depth)
		text := element.Text
		if text == "" {
			if label, ok := element.Attrs["aria-label"]; ok {
				text = label
			}
		}
		builder.WriteString(fmt.Sprintf("%s%s%d]<%s>%s</%s>\n", indent, prefix, element.Index, element.Tag, sanitizeText(text), element.Tag))
	}
	if state.PageText != "" {
		builder.WriteString("Page Text:\n")
		builder.WriteString(strings.TrimSpace(state.PageText))
		builder.WriteString("\n")
	}
	return builder.String()
}

func sanitizeText(text string) string {
	text = strings.ReplaceAll(text, "\n", " ")
	text = strings.ReplaceAll(text, "\t", " ")
	text = strings.TrimSpace(text)
	if len(text) > 200 {
		return text[:200] + "..."
	}
	return text
}

const collectInteractiveElementsJS = `(function(){
  const interactiveRoles = new Set([
    'button','link','checkbox','radio','tab','menuitem','menuitemcheckbox','menuitemradio',
    'option','switch','slider','textbox','combobox','listbox','searchbox','spinbutton'
  ]);
  const baseSelector = 'a[href],button,input,select,textarea,summary,details,canvas,iframe,video,[role],[contenteditable="true"],[tabindex]';
  const candidates = [];
  const seen = new Set();
  const addCandidate = (el) => {
    if (!el || el.nodeType !== 1) return;
    if (seen.has(el)) return;
    seen.add(el);
    candidates.push(el);
  };
  document.querySelectorAll(baseSelector).forEach(addCandidate);
  const all = Array.from(document.querySelectorAll('*'));
  const isInteractive = (el) => {
    const tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (tag === 'a' && el.hasAttribute('href')) return true;
    if (['button','input','select','textarea','summary','details','canvas','iframe','video'].includes(tag)) return true;
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (interactiveRoles.has(role)) return true;
    if (el.isContentEditable) return true;
    const tabindex = el.getAttribute('tabindex');
    if (tabindex !== null && parseInt(tabindex, 10) >= 0) return true;
    if (typeof el.onclick === 'function' || el.getAttribute('onclick')) return true;
    const style = window.getComputedStyle(el);
    if (style && style.cursor === 'pointer') return true;
    return false;
  };
  all.forEach((el) => {
    if (isInteractive(el)) addCandidate(el);
    if (el.shadowRoot) {
      el.shadowRoot.querySelectorAll('*').forEach((node) => {
        if (isInteractive(node)) addCandidate(node);
      });
    }
  });
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (!style) return false;
    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') <= 0) return false;
    return rect.width > 1 && rect.height > 1;
  };
  const cssEscape = (value) => {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
    return value.replace(/([ #;?%&,.+*~\":'!^$\[\]()=>|\/])/g,'\\$1');
  };
  const buildPath = (el) => {
    if (!el || el.nodeType !== 1) return "";
    const parts = [];
    while (el && parts.length < 8) {
      let part = el.tagName.toLowerCase();
      if (el.id) {
        part += "#" + cssEscape(el.id);
        parts.unshift(part);
        break;
      }
      let sibling = el;
      let index = 1;
      while ((sibling = sibling.previousElementSibling)) {
        if (sibling.tagName === el.tagName) index++;
      }
      part += ':nth-of-type(' + index + ')';
      parts.unshift(part);
      el = el.parentElement;
    }
    return parts.join(" > ");
  };
  const getText = (el) => {
    const value = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || "").trim();
    return value.slice(0, 200);
  };
  const getDepth = (el) => {
    let depth = 0;
    let current = el.parentElement;
    while (current && depth < 6) {
      depth++;
      current = current.parentElement;
    }
    return depth;
  };
  const maxElements = 200;
  const payload = candidates.filter(isVisible).slice(0, maxElements).map((el) => {
    const rect = el.getBoundingClientRect();
    const attrs = {};
    ['aria-label','placeholder','type','role','name','value','title','alt','tabindex'].forEach((attr) => {
      const val = el.getAttribute(attr);
      if (val) attrs[attr] = val;
    });
    return {
      selector: buildPath(el),
      tag: el.tagName.toLowerCase(),
      text: getText(el),
      depth: getDepth(el),
      attrs,
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
    };
  });
  return JSON.stringify({url: window.location.href, title: document.title, text: (document.body && document.body.innerText || '').slice(0, 4000), elements: payload});
})();`

const addHighlightOverlayJS = `(elements) => {
  const overlayId = '__browseruse_highlight_overlay';
  const existing = document.getElementById(overlayId);
  if (existing) existing.remove();
  const container = document.createElement('div');
  container.id = overlayId;
  container.style.position = 'fixed';
  container.style.left = '0';
  container.style.top = '0';
  container.style.width = '100%';
  container.style.height = '100%';
  container.style.zIndex = '2147483647';
  container.style.pointerEvents = 'none';
  container.style.fontFamily = 'Arial, sans-serif';
  container.style.fontSize = '12px';
  const colors = {
    button: '#FF6B6B',
    input: '#4ECDC4',
    select: '#45B7D1',
    a: '#96CEB4',
    textarea: '#FF8C42',
    default: '#DDA0DD'
  };
  const pickColor = (el) => {
    if (!el) return colors.default;
    if (el.tag === 'input' && el.attrs && (el.attrs.type === 'button' || el.attrs.type === 'submit')) {
      return colors.button;
    }
    return colors[el.tag] || colors.default;
  };
  const root = document.body || document.documentElement;
  if (!root) return false;
  (elements || []).forEach((el) => {
    if (!el || !el.rect) return;
    const rect = el.rect;
    if (!rect || rect.width < 2 || rect.height < 2) return;
    const color = pickColor(el);
    const box = document.createElement('div');
    box.style.position = 'fixed';
    box.style.left = rect.x + 'px';
    box.style.top = rect.y + 'px';
    box.style.width = rect.width + 'px';
    box.style.height = rect.height + 'px';
    box.style.border = '2px solid ' + color;
    box.style.boxSizing = 'border-box';
    box.style.pointerEvents = 'none';
    const label = document.createElement('div');
    label.textContent = String(el.index || '');
    label.style.position = 'absolute';
    label.style.left = '0';
    label.style.top = '0';
    label.style.background = color;
    label.style.color = '#000';
    label.style.padding = '1px 4px';
    label.style.borderRadius = '2px';
    label.style.fontSize = '12px';
    label.style.fontWeight = 'bold';
    label.style.lineHeight = '14px';
    box.appendChild(label);
    container.appendChild(box);
  });
  root.appendChild(container);
  return true;
};`

const removeHighlightOverlayJS = `() => {
  const existing = document.getElementById('__browseruse_highlight_overlay');
  if (existing) existing.remove();
  return true;
};`
