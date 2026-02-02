package browseruse

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

type CDPError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type CDPResponse struct {
	ID        int64           `json:"id"`
	Result    json.RawMessage `json:"result"`
	Error     *CDPError       `json:"error"`
	SessionID string          `json:"sessionId"`
}

type CDPEvent struct {
	Method    string          `json:"method"`
	Params    json.RawMessage `json:"params"`
	SessionID string          `json:"sessionId"`
}

type EventHandler func(event CDPEvent)

type CDPClient struct {
	url      string
	headers  http.Header
	conn     *websocket.Conn
	pending  map[int64]chan CDPResponse
	handlers map[string][]EventHandler
	mu       sync.Mutex
	writeMu  sync.Mutex
	nextID   int64
	closed   chan struct{}
}

func NewCDPClient(url string, headers http.Header) *CDPClient {
	return &CDPClient{
		url:      url,
		headers:  headers,
		pending:  make(map[int64]chan CDPResponse),
		handlers: make(map[string][]EventHandler),
		closed:   make(chan struct{}),
	}
}

func (c *CDPClient) Start(ctx context.Context) error {
	dialer := websocket.DefaultDialer
	conn, _, err := dialer.DialContext(ctx, c.url, c.headers)
	if err != nil {
		return err
	}
	c.conn = conn
	go c.readLoop()
	return nil
}

func (c *CDPClient) Stop() error {
	c.mu.Lock()
	select {
	case <-c.closed:
		c.mu.Unlock()
		return nil
	default:
		close(c.closed)
	}
	c.mu.Unlock()
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

func (c *CDPClient) Register(method string, handler EventHandler) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.handlers[method] = append(c.handlers[method], handler)
}

func (c *CDPClient) Send(ctx context.Context, method string, params map[string]any, sessionID string) (map[string]any, error) {
	if c.conn == nil {
		return nil, errors.New("cdp client not started")
	}
	id := atomic.AddInt64(&c.nextID, 1)
	payload := map[string]any{
		"id":     id,
		"method": method,
	}
	if params != nil {
		payload["params"] = params
	}
	if sessionID != "" {
		payload["sessionId"] = sessionID
	}
	message, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	respCh := make(chan CDPResponse, 1)
	c.mu.Lock()
	c.pending[id] = respCh
	c.mu.Unlock()

	c.writeMu.Lock()
	writeErr := c.conn.WriteMessage(websocket.TextMessage, message)
	c.writeMu.Unlock()
	if writeErr != nil {
		c.mu.Lock()
		delete(c.pending, id)
		c.mu.Unlock()
		return nil, writeErr
	}

	select {
	case resp := <-respCh:
		if resp.Error != nil {
			return nil, errors.New(resp.Error.Message)
		}
		var result map[string]any
		if len(resp.Result) > 0 {
			if err := json.Unmarshal(resp.Result, &result); err != nil {
				return nil, err
			}
		}
		return result, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-c.closed:
		return nil, errors.New("cdp client closed")
	}
}

func (c *CDPClient) readLoop() {
	for {
		_, data, err := c.conn.ReadMessage()
		if err != nil {
			_ = c.Stop()
			return
		}
		var raw map[string]json.RawMessage
		if err := json.Unmarshal(data, &raw); err != nil {
			continue
		}
		if rawID, ok := raw["id"]; ok {
			var resp CDPResponse
			if err := json.Unmarshal(data, &resp); err != nil {
				continue
			}
			var id int64
			if err := json.Unmarshal(rawID, &id); err == nil {
				resp.ID = id
			}
			c.mu.Lock()
			ch := c.pending[resp.ID]
			delete(c.pending, resp.ID)
			c.mu.Unlock()
			if ch != nil {
				ch <- resp
			}
			continue
		}

		var event CDPEvent
		if err := json.Unmarshal(data, &event); err != nil {
			continue
		}
		if event.Method == "" {
			continue
		}
		c.mu.Lock()
		handlers := append([]EventHandler{}, c.handlers[event.Method]...)
		c.mu.Unlock()
		for _, handler := range handlers {
			h := handler
			go h(event)
		}
	}
}

func (c *CDPClient) SendWithTimeout(method string, params map[string]any, sessionID string, timeout time.Duration) (map[string]any, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return c.Send(ctx, method, params, sessionID)
}
