package browseruse

import (
	"context"
	"encoding/json"
	"errors"
	"math"
)

type Element struct {
	browser       *BrowserSession
	backendNodeID int
	sessionID     string
}

type BoundingBox struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

func NewElement(browser *BrowserSession, backendNodeID int, sessionID string) *Element {
	return &Element{browser: browser, backendNodeID: backendNodeID, sessionID: sessionID}
}

func (e *Element) getNodeID(ctx context.Context) (int, error) {
	result, err := e.browser.client.Send(ctx, "DOM.pushNodesByBackendIdsToFrontend", map[string]any{"backendNodeIds": []int{e.backendNodeID}}, e.sessionID)
	if err != nil {
		return 0, err
	}
	ids, ok := result["nodeIds"].([]any)
	if !ok || len(ids) == 0 {
		return 0, errors.New("nodeIds missing")
	}
	return int(ids[0].(float64)), nil
}

func (e *Element) resolveObjectID(ctx context.Context) (string, error) {
	nodeID, err := e.getNodeID(ctx)
	if err != nil {
		return "", err
	}
	result, err := e.browser.client.Send(ctx, "DOM.resolveNode", map[string]any{"nodeId": nodeID}, e.sessionID)
	if err != nil {
		return "", err
	}
	obj, ok := result["object"].(map[string]any)
	if !ok {
		return "", errors.New("object missing")
	}
	objID, _ := obj["objectId"].(string)
	if objID == "" {
		return "", errors.New("objectId missing")
	}
	return objID, nil
}

func (e *Element) Focus(ctx context.Context) error {
	nodeID, err := e.getNodeID(ctx)
	if err != nil {
		return err
	}
	_, err = e.browser.client.Send(ctx, "DOM.focus", map[string]any{"nodeId": nodeID}, e.sessionID)
	return err
}

func (e *Element) Hover(ctx context.Context) error {
	layout, err := e.browser.client.Send(ctx, "Page.getLayoutMetrics", nil, e.sessionID)
	if err != nil {
		return err
	}
	viewport := layout["layoutViewport"].(map[string]any)
	viewportWidth := viewport["clientWidth"].(float64)
	viewportHeight := viewport["clientHeight"].(float64)
	result, err := e.browser.client.Send(ctx, "DOM.getContentQuads", map[string]any{"backendNodeId": e.backendNodeID}, e.sessionID)
	if err != nil {
		return err
	}
	quads, ok := result["quads"].([]any)
	if !ok || len(quads) == 0 {
		return errors.New("quads missing")
	}
	quad := quads[0].([]any)
	centerX := (quad[0].(float64) + quad[2].(float64) + quad[4].(float64) + quad[6].(float64)) / 4
	centerY := (quad[1].(float64) + quad[3].(float64) + quad[5].(float64) + quad[7].(float64)) / 4
	if centerX < 0 {
		centerX = 0
	}
	if centerY < 0 {
		centerY = 0
	}
	if centerX > viewportWidth-1 {
		centerX = viewportWidth - 1
	}
	if centerY > viewportHeight-1 {
		centerY = viewportHeight - 1
	}
	_, err = e.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mouseMoved", "x": centerX, "y": centerY}, e.sessionID)
	return err
}

func (e *Element) Fill(ctx context.Context, text string, clear bool) error {
	objectID, err := e.resolveObjectID(ctx)
	if err != nil {
		return err
	}
	params := map[string]any{
		"functionDeclaration": "function(value, clear) { if (clear) { this.value = ''; } this.focus(); this.value = clear ? value : (this.value || '') + value; this.dispatchEvent(new Event('input', {bubbles:true})); this.dispatchEvent(new Event('change', {bubbles:true})); }",
		"objectId":            objectID,
		"arguments": []map[string]any{
			{"value": text},
			{"value": clear},
		},
	}
	_, err = e.browser.client.Send(ctx, "Runtime.callFunctionOn", params, e.sessionID)
	return err
}

func (e *Element) Click(ctx context.Context) error {
	layout, err := e.browser.client.Send(ctx, "Page.getLayoutMetrics", nil, e.sessionID)
	if err != nil {
		return err
	}
	viewport := layout["layoutViewport"].(map[string]any)
	viewportWidth := viewport["clientWidth"].(float64)
	viewportHeight := viewport["clientHeight"].(float64)

	result, err := e.browser.client.Send(ctx, "DOM.getContentQuads", map[string]any{"backendNodeId": e.backendNodeID}, e.sessionID)
	if err != nil {
		return err
	}
	quads, ok := result["quads"].([]any)
	if !ok || len(quads) == 0 {
		objectID, err := e.resolveObjectID(ctx)
		if err != nil {
			return err
		}
		_, err = e.browser.client.Send(ctx, "Runtime.callFunctionOn", map[string]any{"functionDeclaration": "function() { this.click(); }", "objectId": objectID}, e.sessionID)
		return err
	}
	quad := quads[0].([]any)
	if len(quad) < 8 {
		return errors.New("quad missing")
	}
	var sumX, sumY float64
	for i := 0; i < 8; i += 2 {
		sumX += quad[i].(float64)
		sumY += quad[i+1].(float64)
	}
	centerX := sumX / 4
	centerY := sumY / 4
	centerX = math.Max(0, math.Min(viewportWidth-1, centerX))
	centerY = math.Max(0, math.Min(viewportHeight-1, centerY))
	_, err = e.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mousePressed", "x": centerX, "y": centerY, "button": "left", "clickCount": 1}, e.sessionID)
	if err != nil {
		return err
	}
	_, err = e.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mouseReleased", "x": centerX, "y": centerY, "button": "left", "clickCount": 1}, e.sessionID)
	return err
}

func (e *Element) Evaluate(ctx context.Context, function string, args ...any) (string, error) {
	objectID, err := e.resolveObjectID(ctx)
	if err != nil {
		return "", err
	}
	argList := make([]map[string]any, 0, len(args))
	for _, arg := range args {
		argList = append(argList, map[string]any{"value": arg})
	}
	result, err := e.browser.client.Send(ctx, "Runtime.callFunctionOn", map[string]any{"functionDeclaration": function, "objectId": objectID, "arguments": argList, "returnByValue": true}, e.sessionID)
	if err != nil {
		return "", err
	}
	res, ok := result["result"].(map[string]any)
	if !ok {
		return "", nil
	}
	value, ok := res["value"]
	if !ok || value == nil {
		return "", nil
	}
	if str, ok := value.(string); ok {
		return str, nil
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", nil
	}
	return string(encoded), nil
}

func (e *Element) ScrollIntoView(ctx context.Context) error {
	objectID, err := e.resolveObjectID(ctx)
	if err != nil {
		return err
	}
	_, err = e.browser.client.Send(ctx, "Runtime.callFunctionOn", map[string]any{
		"functionDeclaration": "function() { this.scrollIntoView({block:'center', inline:'center'}); }",
		"objectId":            objectID,
	}, e.sessionID)
	return err
}

func (e *Element) SetFileInputFiles(ctx context.Context, paths []string) error {
	nodeID, err := e.getNodeID(ctx)
	if err != nil {
		return err
	}
	_, err = e.browser.client.Send(ctx, "DOM.setFileInputFiles", map[string]any{"nodeId": nodeID, "files": paths}, e.sessionID)
	return err
}

func (e *Element) GetAttribute(ctx context.Context, name string) (string, error) {
	nodeID, err := e.getNodeID(ctx)
	if err != nil {
		return "", err
	}
	result, err := e.browser.client.Send(ctx, "DOM.getAttributes", map[string]any{"nodeId": nodeID}, e.sessionID)
	if err != nil {
		return "", err
	}
	attrs, ok := result["attributes"].([]any)
	if !ok {
		return "", nil
	}
	for i := 0; i+1 < len(attrs); i += 2 {
		if attrs[i].(string) == name {
			return attrs[i+1].(string), nil
		}
	}
	return "", nil
}

func (e *Element) GetBoundingBox(ctx context.Context) (*BoundingBox, error) {
	result, err := e.browser.client.Send(ctx, "DOM.getBoxModel", map[string]any{"backendNodeId": e.backendNodeID}, e.sessionID)
	if err != nil {
		return nil, err
	}
	model, ok := result["model"].(map[string]any)
	if !ok {
		return nil, errors.New("box model missing")
	}
	content, ok := model["content"].([]any)
	if !ok || len(content) < 8 {
		return nil, errors.New("content quad missing")
	}
	minX := content[0].(float64)
	minY := content[1].(float64)
	maxX := content[0].(float64)
	maxY := content[1].(float64)
	for i := 0; i < 8; i += 2 {
		x := content[i].(float64)
		y := content[i+1].(float64)
		if x < minX {
			minX = x
		}
		if y < minY {
			minY = y
		}
		if x > maxX {
			maxX = x
		}
		if y > maxY {
			maxY = y
		}
	}
	return &BoundingBox{X: minX, Y: minY, Width: maxX - minX, Height: maxY - minY}, nil
}
