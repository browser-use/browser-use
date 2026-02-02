package browseruse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/responses"
)

type ActionContext struct {
	Session    *BrowserSession
	FileSystem *FileSystem
	Client     *openai.Client
	Model      string
}

func ExecuteAction(ctx context.Context, action Action, actionCtx ActionContext) (ActionResult, error) {
	session := actionCtx.Session
	if session == nil {
		return ActionResult{}, errors.New("session is nil")
	}
	page := session.GetCurrentPage()
	if page == nil {
		return ActionResult{}, errors.New("no current page")
	}
	params := action.Parameters
	switch action.Name {
	case "search":
		query, _ := params["query"].(string)
		engine, _ := params["engine"].(string)
		if engine == "" {
			engine = "duckduckgo"
		}
		url := buildSearchURL(query, engine)
		if url == "" {
			return ActionResult{Error: "unsupported search engine"}, nil
		}
		err := page.Goto(ctx, url)
		return ActionResult{ExtractedContent: fmt.Sprintf("Searched %s for '%s'", engine, query), LongTermMemory: fmt.Sprintf("Searched %s for '%s'", engine, query)}, err
	case "navigate":
		url, _ := params["url"].(string)
		newTab, _ := params["new_tab"].(bool)
		if url == "" {
			return ActionResult{}, errors.New("url required")
		}
		if newTab {
			newPage, err := session.NewPage(ctx, url)
			if err != nil {
				return ActionResult{}, err
			}
			if newPage != nil {
				session.AgentFocusTarget = newPage.targetID
			}
			return ActionResult{ExtractedContent: "Opened new tab"}, nil
		}
		err := page.Goto(ctx, url)
		return ActionResult{}, err
	case "go_back":
		err := page.GoBack(ctx)
		return ActionResult{ExtractedContent: "Navigated back"}, err
	case "wait":
		seconds := toFloat(params["seconds"], 3)
		if seconds < 0 {
			seconds = 0
		}
		if seconds > 30 {
			seconds = 30
		}
		time.Sleep(time.Duration(seconds * float64(time.Second)))
		return ActionResult{ExtractedContent: fmt.Sprintf("Waited for %.1f seconds", seconds), LongTermMemory: fmt.Sprintf("Waited for %.1f seconds", seconds)}, nil
	case "click":
		if coordX, okX := toInt(params["coordinate_x"]); okX {
			if coordY, okY := toInt(params["coordinate_y"]); okY {
				mouse, err := page.Mouse(ctx)
				if err != nil {
					return ActionResult{}, err
				}
				err = mouse.Click(ctx, coordX, coordY, "left", 1)
				return ActionResult{ExtractedContent: fmt.Sprintf("Clicked on coordinate %d,%d", coordX, coordY)}, err
			}
		}
		index, ok := toInt(params["index"])
		if !ok {
			return ActionResult{}, errors.New("index required")
		}
		selector, ok := session.SelectorForIndex(index)
		if !ok {
			return ActionResult{}, fmt.Errorf("no element for index %d", index)
		}
		element, err := page.WaitForSelector(ctx, selector, 5*time.Second)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: fmt.Sprintf("Clicked element %d", index)}, element.Click(ctx)
	case "input":
		index, ok := toInt(params["index"])
		if !ok {
			return ActionResult{}, errors.New("index required")
		}
		text, _ := params["text"].(string)
		clear := toBool(params["clear"], true)
		selector, ok := session.SelectorForIndex(index)
		if !ok {
			return ActionResult{}, fmt.Errorf("no element for index %d", index)
		}
		element, err := page.WaitForSelector(ctx, selector, 5*time.Second)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: fmt.Sprintf("Input text into element %d", index)}, element.Fill(ctx, text, clear)
	case "upload_file":
		index, ok := toInt(params["index"])
		if !ok {
			return ActionResult{}, errors.New("index required")
		}
		path, _ := params["path"].(string)
		if path == "" {
			return ActionResult{}, errors.New("path required")
		}
		selector, ok := session.SelectorForIndex(index)
		if !ok {
			return ActionResult{}, fmt.Errorf("no element for index %d", index)
		}
		element, err := page.WaitForSelector(ctx, selector, 5*time.Second)
		if err != nil {
			return ActionResult{}, err
		}
		resolvedPath, err := resolveUploadPath(path)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: fmt.Sprintf("Uploaded file %s", filepath.Base(resolvedPath))}, element.SetFileInputFiles(ctx, []string{resolvedPath})
	case "switch":
		tabID, _ := params["tab_id"].(string)
		if tabID == "" {
			return ActionResult{}, errors.New("tab_id required")
		}
		_, err := session.client.Send(ctx, "Target.activateTarget", map[string]any{"targetId": tabID}, "")
		if err != nil {
			return ActionResult{}, err
		}
		session.AgentFocusTarget = tabID
		return ActionResult{ExtractedContent: fmt.Sprintf("Switched to tab %s", tabID)}, nil
	case "close":
		tabID, _ := params["tab_id"].(string)
		if tabID == "" {
			return ActionResult{}, errors.New("tab_id required")
		}
		return ActionResult{ExtractedContent: fmt.Sprintf("Closed tab %s", tabID)}, session.ClosePage(ctx, tabID)
	case "extract":
		query, _ := params["query"].(string)
		if query == "" {
			return ActionResult{}, errors.New("query required")
		}
		start := int(toFloat(params["start_from_char"], 0))
		pageText, err := page.Evaluate(ctx, "() => document.body ? document.body.innerText : ''")
		if err != nil {
			return ActionResult{}, err
		}
		if start > 0 && start < len(pageText) {
			pageText = pageText[start:]
		}
		outputSchema, _ := params["output_schema"].(map[string]any)
		resultText, err := runExtraction(ctx, actionCtx, query, pageText, outputSchema)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: resultText}, nil
	case "search_page":
		pattern, _ := params["pattern"].(string)
		regex := toBool(params["regex"], false)
		caseSensitive := toBool(params["case_sensitive"], false)
		contextChars := int(toFloat(params["context_chars"], 150))
		cssScope, _ := params["css_scope"].(string)
		maxResults := int(toFloat(params["max_results"], 25))
		resultText, err := page.Evaluate(ctx, buildSearchPageJS(pattern, regex, caseSensitive, contextChars, cssScope, maxResults))
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: resultText}, nil
	case "find_elements":
		selector, _ := params["selector"].(string)
		if selector == "" {
			return ActionResult{}, errors.New("selector required")
		}
		attrs := toStringSlice(params["attributes"])
		maxResults := int(toFloat(params["max_results"], 50))
		includeText := toBool(params["include_text"], true)
		resultText, err := page.Evaluate(ctx, buildFindElementsJS(selector, attrs, maxResults, includeText))
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: resultText}, nil
	case "scroll":
		down := toBool(params["down"], true)
		pages := toFloat(params["pages"], 1.0)
		if index, ok := toInt(params["index"]); ok {
			selector, ok := session.SelectorForIndex(index)
			if ok {
				element, err := page.WaitForSelector(ctx, selector, 5*time.Second)
				if err == nil {
					_ = element.ScrollIntoView(ctx)
					return ActionResult{ExtractedContent: fmt.Sprintf("Scrolled to element %d", index)}, nil
				}
			}
		}
		mult := pages
		if !down {
			mult = -pages
		}
		_, err := page.Evaluate(ctx, fmt.Sprintf("window.scrollBy(0, %f * window.innerHeight);", mult))
		return ActionResult{ExtractedContent: "Scrolled page"}, err
	case "send_keys":
		keys, _ := params["keys"].(string)
		if keys == "" {
			return ActionResult{}, errors.New("keys required")
		}
		if strings.Contains(keys, "+") || len(keys) <= 4 {
			return ActionResult{ExtractedContent: fmt.Sprintf("Sent keys %s", keys)}, page.Press(ctx, keys)
		}
		err := page.InsertText(ctx, keys)
		return ActionResult{ExtractedContent: fmt.Sprintf("Sent keys %s", keys)}, err
	case "find_text":
		text, _ := params["text"].(string)
		if text == "" {
			return ActionResult{}, errors.New("text required")
		}
		_, err := page.Evaluate(ctx, buildFindTextJS(text))
		return ActionResult{ExtractedContent: fmt.Sprintf("Searched for text '%s'", text)}, err
	case "screenshot":
		fileName, _ := params["file_name"].(string)
		shot, err := page.Screenshot(ctx, "webp", nil, 1280, 720)
		if err != nil {
			return ActionResult{}, err
		}
		if fileName != "" {
			fs := actionCtx.FileSystem
			if fs == nil {
				return ActionResult{}, errors.New("filesystem not available")
			}
			if err := fs.WriteFile(fileName, shot, false, false, false); err != nil {
				return ActionResult{}, err
			}
			return ActionResult{ExtractedContent: fmt.Sprintf("Saved screenshot to %s", fileName), FilesToDisplay: []string{fileName}}, nil
		}
		return ActionResult{Screenshot: shot, ExtractedContent: "Captured screenshot"}, nil
	case "dropdown_options":
		index, ok := toInt(params["index"])
		if !ok {
			return ActionResult{}, errors.New("index required")
		}
		selector, ok := session.SelectorForIndex(index)
		if !ok {
			return ActionResult{}, fmt.Errorf("no element for index %d", index)
		}
		resultText, err := page.Evaluate(ctx, buildDropdownOptionsJS(selector))
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: resultText}, nil
	case "select_dropdown":
		index, ok := toInt(params["index"])
		if !ok {
			return ActionResult{}, errors.New("index required")
		}
		text, _ := params["text"].(string)
		if text == "" {
			return ActionResult{}, errors.New("text required")
		}
		selector, ok := session.SelectorForIndex(index)
		if !ok {
			return ActionResult{}, fmt.Errorf("no element for index %d", index)
		}
		resultText, err := page.Evaluate(ctx, buildSelectDropdownJS(selector, text))
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: resultText}, nil
	case "write_file":
		fs := actionCtx.FileSystem
		if fs == nil {
			return ActionResult{}, errors.New("filesystem not available")
		}
		name, _ := params["file_name"].(string)
		content, _ := params["content"].(string)
		appendMode := toBool(params["append"], false)
		trailing := toBool(params["trailing_newline"], true)
		leading := toBool(params["leading_newline"], false)
		if err := fs.WriteFile(name, content, appendMode, trailing, leading); err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: fmt.Sprintf("Wrote file %s", name)}, nil
	case "replace_file":
		fs := actionCtx.FileSystem
		if fs == nil {
			return ActionResult{}, errors.New("filesystem not available")
		}
		name, _ := params["file_name"].(string)
		oldStr, _ := params["old_str"].(string)
		newStr, _ := params["new_str"].(string)
		if err := fs.ReplaceFile(name, oldStr, newStr); err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: fmt.Sprintf("Replaced content in %s", name)}, nil
	case "read_file":
		fs := actionCtx.FileSystem
		if fs == nil {
			return ActionResult{}, errors.New("filesystem not available")
		}
		name, _ := params["file_name"].(string)
		content, err := fs.ReadFile(name)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: content, FilesToDisplay: []string{name}}, nil
	case "evaluate":
		code, _ := params["code"].(string)
		if code == "" {
			return ActionResult{}, errors.New("code required")
		}
		value, err := page.Evaluate(ctx, code)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{ExtractedContent: value}, nil
	case "done":
		text, _ := params["text"].(string)
		success := toBool(params["success"], true)
		files := toStringSlice(params["files_to_display"])
		metadata := map[string]any{"success": success}
		if data, ok := params["data"].(map[string]any); ok {
			metadata["data"] = data
		}
		return ActionResult{ExtractedContent: text, FilesToDisplay: files, Metadata: metadata}, nil
	default:
		return ActionResult{}, fmt.Errorf("unknown action %s", action.Name)
	}
}

func buildSearchURL(query, engine string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}
	encoded := strings.ReplaceAll(urlQueryEscape(query), "+", "%20")
	switch strings.ToLower(engine) {
	case "", "duckduckgo":
		return "https://duckduckgo.com/?q=" + encoded
	case "google":
		return "https://www.google.com/search?q=" + encoded + "&udm=14"
	case "bing":
		return "https://www.bing.com/search?q=" + encoded
	default:
		return ""
	}
}

func urlQueryEscape(value string) string {
	return url.QueryEscape(value)
}

func resolveUploadPath(path string) (string, error) {
	if path == "" {
		return "", errors.New("path required")
	}
	if filepath.IsAbs(path) {
		if _, err := os.Stat(path); err != nil {
			return "", err
		}
		return path, nil
	}
	cwd, _ := os.Getwd()
	resolved := filepath.Join(cwd, path)
	if _, err := os.Stat(resolved); err != nil {
		return "", err
	}
	return resolved, nil
}

func toFloat(value any, fallback float64) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case string:
		if v == "" {
			return fallback
		}
		if parsed, err := strconv.ParseFloat(v, 64); err == nil {
			return parsed
		}
	}
	return fallback
}

func toInt(value any) (int, bool) {
	switch v := value.(type) {
	case float64:
		return int(v), true
	case int:
		return v, true
	case int64:
		return int(v), true
	case string:
		if v == "" {
			return 0, false
		}
		parsed, err := strconv.Atoi(v)
		if err == nil {
			return parsed, true
		}
	}
	return 0, false
}

func toBool(value any, fallback bool) bool {
	switch v := value.(type) {
	case bool:
		return v
	case string:
		if v == "true" {
			return true
		}
		if v == "false" {
			return false
		}
	}
	return fallback
}

func toStringSlice(value any) []string {
	if value == nil {
		return nil
	}
	if list, ok := value.([]any); ok {
		out := make([]string, 0, len(list))
		for _, item := range list {
			if s, ok := item.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}
	if list, ok := value.([]string); ok {
		return list
	}
	return nil
}

func runExtraction(ctx context.Context, actionCtx ActionContext, query, text string, schema map[string]any) (string, error) {
	if actionCtx.Client == nil {
		return text, nil
	}
	prompt := fmt.Sprintf("Extract the following information: %s\n\nContent:\n%s", query, text)
	params := responses.ResponseNewParams{
		Model: actionCtx.Model,
		Input: responses.ResponseNewParamsInputUnion{OfString: openai.String(prompt)},
	}
	resp, err := actionCtx.Client.Responses.New(ctx, params)
	if err != nil {
		return "", err
	}
	output := strings.TrimSpace(extractOutputText(resp.Output))
	if len(schema) > 0 {
		return output, nil
	}
	return output, nil
}

func buildSearchPageJS(pattern string, regex, caseSensitive bool, contextChars int, cssScope string, maxResults int) string {
	pattern = strings.ReplaceAll(pattern, "`", "\\`")
	scope := "document.body"
	if cssScope != "" {
		scope = fmt.Sprintf("document.querySelector(`%s`)", cssScope)
	}
	return fmt.Sprintf(`(function(){
  const root = %s;
  if (!root) return "[]";
  const text = root.innerText || "";
  const results = [];
  const maxResults = %d;
  const contextChars = %d;
  const regex = %v;
  const caseSensitive = %v;
  const pattern = %q;
  if (regex) {
    const flags = caseSensitive ? "g" : "gi";
    const re = new RegExp(pattern, flags);
    let match;
    while ((match = re.exec(text)) && results.length < maxResults) {
      const start = Math.max(0, match.index - contextChars);
      const end = Math.min(text.length, match.index + match[0].length + contextChars);
      results.push({match: match[0], context: text.slice(start, end), index: match.index});
    }
  } else {
    const haystack = caseSensitive ? text : text.toLowerCase();
    const needle = caseSensitive ? pattern : pattern.toLowerCase();
    let index = haystack.indexOf(needle);
    while (index !== -1 && results.length < maxResults) {
      const start = Math.max(0, index - contextChars);
      const end = Math.min(text.length, index + needle.length + contextChars);
      results.push({match: text.slice(index, index + needle.length), context: text.slice(start, end), index});
      index = haystack.indexOf(needle, index + needle.length);
    }
  }
  return JSON.stringify(results);
})();`, scope, maxResults, contextChars, regex, caseSensitive, pattern)
}

func buildFindElementsJS(selector string, attrs []string, maxResults int, includeText bool) string {
	encodedAttrs, _ := json.Marshal(attrs)
	return fmt.Sprintf(`(function(){
  const selector = %q;
  const includeText = %v;
  const attrs = %s;
  const elements = Array.from(document.querySelectorAll(selector)).slice(0, %d);
  return JSON.stringify(elements.map(el => {
    const out = {tag: el.tagName.toLowerCase()};
    if (includeText) out.text = (el.innerText || '').trim();
    const attributes = {};
    attrs.forEach(attr => {
      const val = el.getAttribute(attr);
      if (val !== null) attributes[attr] = val;
    });
    out.attributes = attributes;
    return out;
  }));
})();`, selector, includeText, string(encodedAttrs), maxResults)
}

func buildFindTextJS(text string) string {
	return fmt.Sprintf(`(function(){
  const needle = %q;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.nodeValue && node.nodeValue.includes(needle)) {
      const parent = node.parentElement;
      if (parent) {
        parent.scrollIntoView({block:'center', inline:'center'});
        return true;
      }
    }
  }
  return false;
})();`, text)
}

func buildDropdownOptionsJS(selector string) string {
	return fmt.Sprintf(`(function(){
  const el = document.querySelector(%q);
  if (!el) return "[]";
  if (el.tagName.toLowerCase() === 'select') {
    return JSON.stringify(Array.from(el.options).map(o => o.text));
  }
  const options = el.querySelectorAll('[role=option]');
  return JSON.stringify(Array.from(options).map(o => o.innerText.trim()));
})();`, selector)
}

func buildSelectDropdownJS(selector, text string) string {
	return fmt.Sprintf(`(function(){
  const el = document.querySelector(%q);
  if (!el) return "not found";
  const targetText = %q;
  if (el.tagName.toLowerCase() === 'select') {
    const option = Array.from(el.options).find(o => o.text.trim() === targetText || o.value === targetText);
    if (option) {
      el.value = option.value;
      el.dispatchEvent(new Event('change', {bubbles:true}));
      return 'selected';
    }
    return 'option not found';
  }
  const options = Array.from(el.querySelectorAll('[role=option]'));
  const option = options.find(o => o.innerText.trim() === targetText);
  if (option) {
    option.click();
    return 'selected';
  }
  return 'option not found';
})();`, selector, text)
}
