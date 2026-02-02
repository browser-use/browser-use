package browseruse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"
)

type BrowserSession struct {
	CDPURL            string
	Headers           map[string]string
	client            *CDPClient
	sessionManager    *SessionManager
	AgentFocusTarget   string
	connectTimeoutSec  int
	fileSystem         *FileSystem
	lastBrowserState   *BrowserStateSummary
	lastSelectors      map[string]struct{}
	elementsByIndex    map[int]IndexedElement
}

func NewBrowserSession(cdpURL string, headers map[string]string) *BrowserSession {
	fs, _ := NewFileSystem("")
	return &BrowserSession{
		CDPURL:            cdpURL,
		Headers:           headers,
		connectTimeoutSec: 10,
		fileSystem:        fs,
		lastSelectors:     make(map[string]struct{}),
		elementsByIndex:   make(map[int]IndexedElement),
	}
}

func (bs *BrowserSession) Connect(ctx context.Context) error {
	if bs.CDPURL == "" {
		return errors.New("cdp url required")
	}
	resolvedURL, err := bs.resolveWebSocketURL(ctx, bs.CDPURL)
	if err != nil {
		return err
	}
	bs.CDPURL = resolvedURL
	headers := http.Header{}
	for key, value := range bs.Headers {
		headers.Set(key, value)
	}
	bs.client = NewCDPClient(resolvedURL, headers)
	if err := bs.client.Start(ctx); err != nil {
		return err
	}
	bs.sessionManager = NewSessionManager(bs.client)
	if err := bs.sessionManager.StartMonitoring(ctx); err != nil {
		return err
	}
	_, err = bs.client.Send(ctx, "Target.setAutoAttach", map[string]any{"autoAttach": true, "waitForDebuggerOnStart": false, "flatten": true}, "")
	if err != nil {
		return err
	}

	pageTargets := bs.sessionManager.GetAllPageTargets()
	if len(pageTargets) == 0 {
		result, err := bs.client.Send(ctx, "Target.createTarget", map[string]any{"url": "about:blank"}, "")
		if err != nil {
			return err
		}
		if targetID, ok := result["targetId"].(string); ok {
			_, err = bs.GetOrCreateSession(ctx, targetID, true)
			return err
		}
		return errors.New("failed to create target")
	}
	_, err = bs.GetOrCreateSession(ctx, pageTargets[0].TargetID, true)
	return err
}

func (bs *BrowserSession) resolveWebSocketURL(ctx context.Context, cdpURL string) (string, error) {
	if strings.HasPrefix(cdpURL, "ws") {
		return cdpURL, nil
	}
	parsed, err := url.Parse(cdpURL)
	if err != nil {
		return "", err
	}
	parsed.Path = strings.TrimSuffix(parsed.Path, "/")
	if !strings.HasSuffix(parsed.Path, "/json/version") {
		parsed.Path = path.Join(parsed.Path, "/json/version")
	}
	client := &http.Client{Timeout: 5 * time.Second}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
	if err != nil {
		return "", err
	}
	for key, value := range bs.Headers {
		request.Header.Set(key, value)
	}
	resp, err := client.Do(request)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var payload struct {
		WebSocketDebuggerURL string `json:"webSocketDebuggerUrl"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return "", err
	}
	if payload.WebSocketDebuggerURL == "" {
		return "", fmt.Errorf("webSocketDebuggerUrl missing from response")
	}
	return payload.WebSocketDebuggerURL, nil
}

func (bs *BrowserSession) GetOrCreateSession(ctx context.Context, targetID string, focus bool) (*CDPSession, error) {
	if bs.sessionManager == nil {
		return nil, errors.New("session manager not initialized")
	}
	if targetID == "" {
		return nil, errors.New("target id required")
	}
	if session := bs.sessionManager.GetSessionForTarget(targetID); session != nil {
		if focus {
			bs.AgentFocusTarget = targetID
			_, _ = bs.client.Send(ctx, "Target.activateTarget", map[string]any{"targetId": targetID}, "")
		}
		return session, nil
	}
	if waited, err := bs.sessionManager.WaitForSession(targetID, 500*time.Millisecond); err == nil {
		if focus {
			bs.AgentFocusTarget = targetID
			_, _ = bs.client.Send(ctx, "Target.activateTarget", map[string]any{"targetId": targetID}, "")
		}
		return waited, nil
	}
	_, err := bs.client.Send(ctx, "Target.attachToTarget", map[string]any{"targetId": targetID, "flatten": true}, "")
	if err != nil {
		return nil, err
	}
	waited, err := bs.sessionManager.WaitForSession(targetID, 2*time.Second)
	if err != nil {
		return nil, err
	}
	if focus {
		bs.AgentFocusTarget = targetID
		_, _ = bs.client.Send(ctx, "Target.activateTarget", map[string]any{"targetId": targetID}, "")
	}
	return waited, nil
}

func (bs *BrowserSession) NewPage(ctx context.Context, url string) (*Page, error) {
	if url == "" {
		url = "about:blank"
	}
	result, err := bs.client.Send(ctx, "Target.createTarget", map[string]any{"url": url}, "")
	if err != nil {
		return nil, err
	}
	targetID, _ := result["targetId"].(string)
	if targetID == "" {
		return nil, errors.New("targetId missing")
	}
	return &Page{browser: bs, targetID: targetID}, nil
}

func (bs *BrowserSession) GetPages() []*Page {
	var pages []*Page
	if bs.sessionManager == nil {
		return pages
	}
	for _, target := range bs.sessionManager.GetAllPageTargets() {
		pages = append(pages, &Page{browser: bs, targetID: target.TargetID})
	}
	return pages
}

func (bs *BrowserSession) GetCurrentPage() *Page {
	if bs.AgentFocusTarget == "" {
		return nil
	}
	return &Page{browser: bs, targetID: bs.AgentFocusTarget}
}

func (bs *BrowserSession) ClosePage(ctx context.Context, targetID string) error {
	_, err := bs.client.Send(ctx, "Target.closeTarget", map[string]any{"targetId": targetID}, "")
	return err
}

func (bs *BrowserSession) FileSystem() *FileSystem {
	return bs.fileSystem
}

func (bs *BrowserSession) SetFileSystem(fs *FileSystem) {
	bs.fileSystem = fs
}

func (bs *BrowserSession) Close() error {
	if bs.client == nil {
		return nil
	}
	return bs.client.Stop()
}

func (bs *BrowserSession) Kill() error {
	return bs.Close()
}
