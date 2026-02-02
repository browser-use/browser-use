package browseruse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

type Page struct {
	browser   *BrowserSession
	targetID  string
	sessionID string
	mouse     *Mouse
}

func (p *Page) ensureSession(ctx context.Context) (string, error) {
	if p.sessionID != "" {
		return p.sessionID, nil
	}
	session, err := p.browser.GetOrCreateSession(ctx, p.targetID, false)
	if err != nil {
		return "", err
	}
	p.sessionID = session.SessionID
	return p.sessionID, nil
}

func (p *Page) Goto(ctx context.Context, url string) error {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return err
	}
	_, err = p.browser.client.Send(ctx, "Page.navigate", map[string]any{"url": url}, sessionID)
	if err != nil {
		return err
	}
	return p.WaitForReadyState(ctx, 10*time.Second)
}

func (p *Page) GoBack(ctx context.Context) error {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return err
	}
	history, err := p.browser.client.Send(ctx, "Page.getNavigationHistory", nil, sessionID)
	if err != nil {
		return err
	}
	currentIndex, ok := history["currentIndex"].(float64)
	if !ok {
		return errors.New("navigation history missing")
	}
	entries, ok := history["entries"].([]any)
	if !ok || len(entries) == 0 {
		return errors.New("navigation entries missing")
	}
	idx := int(currentIndex) - 1
	if idx < 0 {
		return nil
	}
	entry := entries[idx].(map[string]any)
	entryID, ok := entry["id"].(float64)
	if !ok {
		return errors.New("entry id missing")
	}
	_, err = p.browser.client.Send(ctx, "Page.navigateToHistoryEntry", map[string]any{"entryId": int(entryID)}, sessionID)
	return err
}

func (p *Page) Reload(ctx context.Context) error {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return err
	}
	_, err = p.browser.client.Send(ctx, "Page.reload", nil, sessionID)
	return err
}

func (p *Page) Evaluate(ctx context.Context, pageFunction string, args ...any) (string, error) {
	pageFunction = strings.TrimSpace(pageFunction)
	var expression string
	if strings.HasPrefix(pageFunction, "(") && strings.Contains(pageFunction, "=>") {
		if len(args) > 0 {
			argStrings := make([]string, 0, len(args))
			for _, arg := range args {
				encoded, err := json.Marshal(arg)
				if err != nil {
					return "", err
				}
				argStrings = append(argStrings, string(encoded))
			}
			expression = fmt.Sprintf("(%s)(%s)", pageFunction, strings.Join(argStrings, ", "))
		} else {
			expression = fmt.Sprintf("(%s)()", pageFunction)
		}
	} else {
		if len(args) > 0 {
			argStrings := make([]string, 0, len(args))
			for _, arg := range args {
				encoded, err := json.Marshal(arg)
				if err != nil {
					return "", err
				}
				argStrings = append(argStrings, string(encoded))
			}
			expression = fmt.Sprintf("(function(...args){ return (%s); })(%s)", pageFunction, strings.Join(argStrings, ", "))
		} else {
			expression = pageFunction
		}
	}
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return "", err
	}
	result, err := p.browser.client.Send(ctx, "Runtime.evaluate", map[string]any{"expression": expression, "returnByValue": true, "awaitPromise": true}, sessionID)
	if err != nil {
		return "", err
	}
	if result == nil {
		return "", nil
	}
	resValue, ok := result["result"].(map[string]any)
	if !ok {
		return "", nil
	}
	value, ok := resValue["value"]
	if !ok || value == nil {
		return "", nil
	}
	switch v := value.(type) {
	case string:
		return v, nil
	case float64, int, bool:
		return fmt.Sprintf("%v", v), nil
	default:
		encoded, err := json.Marshal(v)
		if err != nil {
			return fmt.Sprintf("%v", v), nil
		}
		return string(encoded), nil
	}
}

func (p *Page) WaitForReadyState(ctx context.Context, timeout time.Duration) error {
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline.C:
			return context.DeadlineExceeded
		case <-ticker.C:
			state, err := p.Evaluate(ctx, "document.readyState")
			if err != nil {
				continue
			}
			if state == "complete" || state == "interactive" {
				return nil
			}
		}
	}
}

func (p *Page) WaitForSelector(ctx context.Context, selector string, timeout time.Duration) (*Element, error) {
	if selector == "" {
		return nil, errors.New("selector required")
	}
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-deadline.C:
			return nil, errors.New("no elements found")
		case <-ticker.C:
			elements, err := p.GetElementsByCSSSelector(ctx, selector)
			if err != nil {
				continue
			}
			if len(elements) > 0 {
				return elements[0], nil
			}
		}
	}
}

func (p *Page) Screenshot(ctx context.Context, format string, quality *int, maxWidth, maxHeight int) (string, error) {
	if format == "" {
		format = "webp"
	}
	if maxWidth <= 0 {
		maxWidth = 1280
	}
	if maxHeight <= 0 {
		maxHeight = 720
	}
	if quality == nil {
		formatLower := strings.ToLower(format)
		if formatLower == "jpeg" || formatLower == "webp" {
			q := 60
			quality = &q
		}
	}
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return "", err
	}
	params := map[string]any{
		"format":                format,
		"captureBeyondViewport": false,
	}
	if quality != nil {
		formatLower := strings.ToLower(format)
		if formatLower == "jpeg" || formatLower == "webp" {
			params["quality"] = *quality
		}
	}
	if metrics, err := p.browser.client.Send(ctx, "Page.getLayoutMetrics", nil, sessionID); err == nil {
		if viewport, ok := metrics["layoutViewport"].(map[string]any); ok {
			widthVal, widthOk := viewport["clientWidth"].(float64)
			heightVal, heightOk := viewport["clientHeight"].(float64)
			if widthOk && heightOk {
				width := int(widthVal)
				height := int(heightVal)
				if width > maxWidth {
					width = maxWidth
				}
				if height > maxHeight {
					height = maxHeight
				}
				if width > 0 && height > 0 {
					params["clip"] = map[string]any{
						"x":      0,
						"y":      0,
						"width":  width,
						"height": height,
						"scale":  1,
					}
				}
			}
		}
	}
	result, err := p.browser.client.Send(ctx, "Page.captureScreenshot", params, sessionID)
	if err != nil {
		return "", err
	}
	data, ok := result["data"].(string)
	if !ok {
		return "", errors.New("screenshot data missing")
	}
	return data, nil
}

func (p *Page) InsertText(ctx context.Context, text string) error {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return err
	}
	_, err = p.browser.client.Send(ctx, "Input.insertText", map[string]any{"text": text}, sessionID)
	return err
}

func (p *Page) Press(ctx context.Context, key string) error {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return err
	}
	if key == "" {
		return nil
	}
	parts := strings.Split(key, "+")
	if len(parts) == 1 {
		_, err := p.browser.client.Send(ctx, "Input.dispatchKeyEvent", map[string]any{"type": "keyDown", "key": key}, sessionID)
		if err != nil {
			return err
		}
		_, err = p.browser.client.Send(ctx, "Input.dispatchKeyEvent", map[string]any{"type": "keyUp", "key": key}, sessionID)
		return err
	}
	for _, modifier := range parts[:len(parts)-1] {
		_, err := p.browser.client.Send(ctx, "Input.dispatchKeyEvent", map[string]any{"type": "keyDown", "key": modifier}, sessionID)
		if err != nil {
			return err
		}
	}
	mainKey := parts[len(parts)-1]
	_, err = p.browser.client.Send(ctx, "Input.dispatchKeyEvent", map[string]any{"type": "keyDown", "key": mainKey}, sessionID)
	if err != nil {
		return err
	}
	_, err = p.browser.client.Send(ctx, "Input.dispatchKeyEvent", map[string]any{"type": "keyUp", "key": mainKey}, sessionID)
	if err != nil {
		return err
	}
	for i := len(parts) - 2; i >= 0; i-- {
		modifier := parts[i]
		_, err = p.browser.client.Send(ctx, "Input.dispatchKeyEvent", map[string]any{"type": "keyUp", "key": modifier}, sessionID)
		if err != nil {
			return err
		}
	}
	return nil
}

func (p *Page) SetViewportSize(ctx context.Context, width, height int) error {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return err
	}
	params := map[string]any{"width": width, "height": height, "deviceScaleFactor": 1, "mobile": false}
	_, err = p.browser.client.Send(ctx, "Emulation.setDeviceMetricsOverride", params, sessionID)
	return err
}

func (p *Page) GetURL(ctx context.Context) (string, error) {
	result, err := p.Evaluate(ctx, "() => window.location.href")
	return result, err
}

func (p *Page) GetTitle(ctx context.Context) (string, error) {
	result, err := p.Evaluate(ctx, "() => document.title")
	return result, err
}

func (p *Page) GetElementsByCSSSelector(ctx context.Context, selector string) ([]*Element, error) {
	sessionID, err := p.ensureSession(ctx)
	if err != nil {
		return nil, err
	}
	result, err := p.browser.client.Send(ctx, "DOM.getDocument", map[string]any{"depth": 1}, sessionID)
	if err != nil {
		return nil, err
	}
	root, ok := result["root"].(map[string]any)
	if !ok {
		return nil, errors.New("root missing")
	}
	nodeIDFloat, ok := root["nodeId"].(float64)
	if !ok {
		return nil, errors.New("nodeId missing")
	}
	nodeID := int(nodeIDFloat)
	queryResult, err := p.browser.client.Send(ctx, "DOM.querySelectorAll", map[string]any{"nodeId": nodeID, "selector": selector}, sessionID)
	if err != nil {
		return nil, err
	}
	nodeIDsAny, ok := queryResult["nodeIds"].([]any)
	if !ok {
		return nil, nil
	}
	var elements []*Element
	for _, nodeAny := range nodeIDsAny {
		nID := int(nodeAny.(float64))
		desc, err := p.browser.client.Send(ctx, "DOM.describeNode", map[string]any{"nodeId": nID}, sessionID)
		if err != nil {
			continue
		}
		node, ok := desc["node"].(map[string]any)
		if !ok {
			continue
		}
		backendIDFloat, ok := node["backendNodeId"].(float64)
		if !ok {
			continue
		}
		backendID := int(backendIDFloat)
		elements = append(elements, &Element{browser: p.browser, backendNodeID: backendID, sessionID: sessionID})
	}
	return elements, nil
}

func (p *Page) GetElementByCSSSelector(ctx context.Context, selector string) (*Element, error) {
	elements, err := p.GetElementsByCSSSelector(ctx, selector)
	if err != nil {
		return nil, err
	}
	if len(elements) == 0 {
		return nil, errors.New("no elements found")
	}
	return elements[0], nil
}

func (p *Page) Mouse(ctx context.Context) (*Mouse, error) {
	if p.mouse != nil {
		return p.mouse, nil
	}
	_, err := p.ensureSession(ctx)
	if err != nil {
		return nil, err
	}
	p.mouse = &Mouse{browser: p.browser, sessionID: p.sessionID, targetID: p.targetID}
	return p.mouse, nil
}
