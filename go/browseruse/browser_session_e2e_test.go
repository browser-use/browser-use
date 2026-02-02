package browseruse

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

func TestInteractiveElementsE2E(t *testing.T) {
	if os.Getenv("BROWSERUSE_E2E") == "" {
		t.Skip("set BROWSERUSE_E2E=1 to run")
	}
	baseURL := os.Getenv("BROWSERUSE_CDP_URL")
	if baseURL == "" {
		baseURL = "http://127.0.0.1:9222"
	}
	if err := waitForCDP(baseURL, 5*time.Second); err != nil {
		t.Fatalf("cdp not ready at %s: %v", baseURL, err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	session := NewBrowserSession(baseURL, nil)
	if err := session.Connect(ctx); err != nil {
		t.Fatalf("connect failed: %v", err)
	}

	page := session.GetCurrentPage()
	if page == nil {
		t.Fatalf("expected current page")
	}

	html := `<button id="btn">Click</button><a href="https://example.com">Link</a><div tabindex="0">Focusable</div><canvas id="board"></canvas>`
	setDOM := fmt.Sprintf(`() => { if (!document.body) { document.documentElement.appendChild(document.createElement(body)); } document.body.innerHTML = %q; }`, html)
	if _, err := page.Evaluate(ctx, setDOM); err != nil {
		t.Fatalf("failed to set DOM: %v", err)
	}

	state, err := session.GetBrowserStateSummary(ctx, false)
	if err != nil {
		t.Fatalf("GetBrowserStateSummary failed: %v", err)
	}
	if len(state.Elements) == 0 {
		t.Fatalf("expected interactive elements, got 0")
	}

	var tags []string
	for _, el := range state.Elements {
		tags = append(tags, el.Tag)
	}
	tagsJoined := strings.Join(tags, ",")
	if !strings.Contains(tagsJoined, "button") && !strings.Contains(tagsJoined, "a") {
		t.Fatalf("expected button or link in elements, got %s", tagsJoined)
	}
}

func waitForCDP(baseURL string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	url := baseURL + "/json/version"
	for time.Now().Before(deadline) {
		resp, err := http.Get(url)
		if err == nil {
			_ = resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}
		time.Sleep(150 * time.Millisecond)
	}
	return fmt.Errorf("timeout waiting for %s", url)
}
