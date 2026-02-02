package browseruse

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

type mockCDPServer struct {
	server                 *httptest.Server
	wsURL                  string
	methods                []string
	lastEvaluateExpression string
	mu                     sync.Mutex
}

func newMockCDPServer(t *testing.T) *mockCDPServer {
	ms := &mockCDPServer{}
	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	mux := http.NewServeMux()
	mux.HandleFunc("/json/version", func(w http.ResponseWriter, r *http.Request) {
		payload := map[string]string{"webSocketDebuggerUrl": ms.wsURL}
		_ = json.NewEncoder(w).Encode(payload)
	})
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		go ms.handleConn(conn)
	})
	ms.server = httptest.NewServer(mux)
	ms.wsURL = "ws" + ms.server.URL[len("http"):] + "/ws"
	return ms
}

func (ms *mockCDPServer) Close() {
	ms.server.Close()
}

func (ms *mockCDPServer) handleConn(conn *websocket.Conn) {
	defer conn.Close()
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			return
		}
		var payload map[string]any
		if err := json.Unmarshal(data, &payload); err != nil {
			continue
		}
		method, _ := payload["method"].(string)
		if method != "" {
			ms.mu.Lock()
			ms.methods = append(ms.methods, method)
			ms.mu.Unlock()
		}
		id, ok := payload["id"].(float64)
		if !ok {
			continue
		}
		result := map[string]any{}
		switch method {
		case "Target.getTargets":
			result = map[string]any{
				"targetInfos": []map[string]any{{"targetId": "page-1", "type": "page", "url": "https://example.com", "title": "Example"}},
			}
		case "Target.attachToTarget":
			result = map[string]any{"sessionId": "session-1"}
			event := map[string]any{
				"method": "Target.attachedToTarget",
				"params": map[string]any{
					"sessionId":  "session-1",
					"targetInfo": map[string]any{"targetId": "page-1", "type": "page", "url": "https://example.com", "title": "Example"},
				},
			}
			_ = conn.WriteJSON(event)
		case "Runtime.evaluate":
			params, _ := payload["params"].(map[string]any)
			if params != nil {
				if expr, ok := params["expression"].(string); ok {
					ms.mu.Lock()
					ms.lastEvaluateExpression = expr
					ms.mu.Unlock()
				}
			}
			result = map[string]any{"result": map[string]any{"value": "ok"}}
		}
		_ = conn.WriteJSON(map[string]any{"id": id, "result": result})
	}
}

func (ms *mockCDPServer) Methods() []string {
	ms.mu.Lock()
	defer ms.mu.Unlock()
	copyMethods := make([]string, len(ms.methods))
	copy(copyMethods, ms.methods)
	return copyMethods
}

func (ms *mockCDPServer) LastExpression() string {
	ms.mu.Lock()
	defer ms.mu.Unlock()
	return ms.lastEvaluateExpression
}

func loadExpectedSequence(t *testing.T) []string {
	_, filename, _, _ := runtime.Caller(0)
	fixturePath := filepath.Join(filepath.Dir(filename), "..", "..", "tests", "fixtures", "cdp_connect_sequence.json")
	data, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatalf("failed to read fixture: %v", err)
	}
	var sequence []string
	if err := json.Unmarshal(data, &sequence); err != nil {
		t.Fatalf("failed to decode fixture: %v", err)
	}
	return sequence
}

func TestBrowserSessionConnectSequence(t *testing.T) {
	server := newMockCDPServer(t)
	defer server.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	session := NewBrowserSession(server.server.URL, nil)
	if err := session.Connect(ctx); err != nil {
		t.Fatalf("connect failed: %v", err)
	}

	expected := loadExpectedSequence(t)
	methods := server.Methods()
	if len(methods) < len(expected) {
		t.Fatalf("expected at least %d methods, got %d", len(expected), len(methods))
	}
	for i, method := range expected {
		if methods[i] != method {
			t.Fatalf("method mismatch at %d: expected %s got %s", i, method, methods[i])
		}
	}
}

func TestPageEvaluateFormat(t *testing.T) {
	server := newMockCDPServer(t)
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	session := NewBrowserSession(server.server.URL, nil)
	if err := session.Connect(ctx); err != nil {
		t.Fatalf("connect failed: %v", err)
	}

	page := session.GetCurrentPage()
	if page == nil {
		t.Fatalf("expected current page")
	}
	if _, err := page.Evaluate(ctx, "document.title"); err == nil {
		t.Fatalf("expected error for invalid evaluate format")
	}
	result, err := page.Evaluate(ctx, "() => \"ok\"")
	if err != nil {
		t.Fatalf("evaluate failed: %v", err)
	}
	if result != "ok" {
		t.Fatalf("expected ok, got %s", result)
	}
	if server.LastExpression() == "" {
		t.Fatalf("expected expression recorded")
	}
}
