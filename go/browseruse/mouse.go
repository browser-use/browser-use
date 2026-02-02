package browseruse

import (
	"context"
	"fmt"
)

// ... rest with fix

type Mouse struct {
	browser   *BrowserSession
	sessionID string
	targetID  string
}

func (m *Mouse) Click(ctx context.Context, x, y int, button string, clickCount int) error {
	if button == "" {
		button = "left"
	}
	if clickCount == 0 {
		clickCount = 1
	}
	_, err := m.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mousePressed", "x": x, "y": y, "button": button, "clickCount": clickCount}, m.sessionID)
	if err != nil {
		return err
	}
	_, err = m.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mouseReleased", "x": x, "y": y, "button": button, "clickCount": clickCount}, m.sessionID)
	return err
}

func (m *Mouse) Down(ctx context.Context, button string, clickCount int) error {
	if button == "" {
		button = "left"
	}
	_, err := m.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mousePressed", "x": 0, "y": 0, "button": button, "clickCount": clickCount}, m.sessionID)
	return err
}

func (m *Mouse) Up(ctx context.Context, button string, clickCount int) error {
	if button == "" {
		button = "left"
	}
	_, err := m.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mouseReleased", "x": 0, "y": 0, "button": button, "clickCount": clickCount}, m.sessionID)
	return err
}

func (m *Mouse) Move(ctx context.Context, x, y int) error {
	_, err := m.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mouseMoved", "x": x, "y": y}, m.sessionID)
	return err
}

func (m *Mouse) Scroll(ctx context.Context, x, y int, deltaX, deltaY int) error {
	_, err := m.browser.client.Send(ctx, "Input.dispatchMouseEvent", map[string]any{"type": "mouseWheel", "x": x, "y": y, "deltaX": deltaX, "deltaY": deltaY}, m.sessionID)
	if err == nil {
		return nil
	}
	_, err = m.browser.client.Send(ctx, "Input.synthesizeScrollGesture", map[string]any{"x": x, "y": y, "xDistance": deltaX, "yDistance": deltaY}, m.sessionID)
	if err == nil {
		return nil
	}
	_, err = m.browser.client.Send(ctx, "Runtime.evaluate", map[string]any{"expression": fmt.Sprintf("window.scrollBy(%d, %d)", deltaX, deltaY), "returnByValue": true}, m.sessionID)
	return err
}
