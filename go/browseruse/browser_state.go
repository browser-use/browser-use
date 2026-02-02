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
		shot, err := page.Screenshot(ctx, "webp", nil, 1280, 720)
		if err == nil {
			dpr := page.DevicePixelRatio(ctx)
			highlighted, highlightErr := highlightScreenshot(shot, indexed, dpr)
			if highlightErr == nil {
				state.Screenshot = highlighted
			} else {
				state.Screenshot = shot
			}
		}
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
  const baseSelector = 'a[href],button,input,select,textarea,summary,details,[role],[contenteditable="true"],[tabindex]';
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
    if (['button','input','select','textarea','summary'].includes(tag)) return true;
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
