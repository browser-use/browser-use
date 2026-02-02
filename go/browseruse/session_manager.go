package browseruse

import (
	"context"
	"encoding/json"
	"sync"
	"time"
)

type SessionManager struct {
	client         *CDPClient
	targets        map[string]*Target
	sessions       map[string]*CDPSession
	targetSessions map[string]map[string]struct{}
	attachWaiters  map[string][]chan *CDPSession
	mu             sync.Mutex
}

func NewSessionManager(client *CDPClient) *SessionManager {
	return &SessionManager{
		client:         client,
		targets:        make(map[string]*Target),
		sessions:       make(map[string]*CDPSession),
		targetSessions: make(map[string]map[string]struct{}),
		attachWaiters:  make(map[string][]chan *CDPSession),
	}
}

func (sm *SessionManager) StartMonitoring(ctx context.Context) error {
	sm.client.Register("Target.attachedToTarget", sm.handleTargetAttached)
	sm.client.Register("Target.detachedFromTarget", sm.handleTargetDetached)
	sm.client.Register("Target.targetInfoChanged", sm.handleTargetInfoChanged)

	_, err := sm.client.Send(ctx, "Target.setDiscoverTargets", map[string]any{
		"discover": true,
		"filter": []map[string]string{
			{"type": "page"},
			{"type": "iframe"},
		},
	}, "")
	if err != nil {
		return err
	}
	return sm.initializeExistingTargets(ctx)
}

func (sm *SessionManager) initializeExistingTargets(ctx context.Context) error {
	result, err := sm.client.Send(ctx, "Target.getTargets", nil, "")
	if err != nil {
		return err
	}
	infosRaw, ok := result["targetInfos"]
	if !ok {
		return nil
	}
	infosJSON, _ := json.Marshal(infosRaw)
	var infos []Target
	if err := json.Unmarshal(infosJSON, &infos); err != nil {
		return err
	}
	for _, info := range infos {
		if info.TargetType != "page" && info.TargetType != "iframe" {
			continue
		}
		sm.storeTarget(&info)
		_, _ = sm.client.Send(ctx, "Target.attachToTarget", map[string]any{
			"targetId": info.TargetID,
			"flatten":  true,
		}, "")
	}
	return nil
}

func (sm *SessionManager) handleTargetAttached(event CDPEvent) {
	var payload struct {
		SessionID  string `json:"sessionId"`
		TargetInfo Target `json:"targetInfo"`
	}
	if err := json.Unmarshal(event.Params, &payload); err != nil {
		return
	}
	if payload.SessionID == "" || payload.TargetInfo.TargetID == "" {
		return
	}
	session := &CDPSession{TargetID: payload.TargetInfo.TargetID, SessionID: payload.SessionID}
	// Enable monitoring for page targets
	if payload.TargetInfo.TargetType == "page" || payload.TargetInfo.TargetType == "tab" {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		_, _ = sm.client.Send(ctx, "Page.enable", nil, payload.SessionID)
		_, _ = sm.client.Send(ctx, "Page.setLifecycleEventsEnabled", map[string]any{"enabled": true}, payload.SessionID)
		_, _ = sm.client.Send(ctx, "Network.enable", nil, payload.SessionID)
		cancel()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	_, _ = sm.client.Send(ctx, "Target.setAutoAttach", map[string]any{"autoAttach": true, "waitForDebuggerOnStart": false, "flatten": true}, payload.SessionID)
	cancel()

	sm.mu.Lock()
	sm.storeTarget(&payload.TargetInfo)
	sm.sessions[payload.SessionID] = session
	if sm.targetSessions[payload.TargetInfo.TargetID] == nil {
		sm.targetSessions[payload.TargetInfo.TargetID] = make(map[string]struct{})
	}
	sm.targetSessions[payload.TargetInfo.TargetID][payload.SessionID] = struct{}{}
	waiters := sm.attachWaiters[payload.TargetInfo.TargetID]
	delete(sm.attachWaiters, payload.TargetInfo.TargetID)
	sm.mu.Unlock()

	for _, waiter := range waiters {
		waiter <- session
	}
}

func (sm *SessionManager) handleTargetDetached(event CDPEvent) {
	var payload struct {
		SessionID string `json:"sessionId"`
		TargetID  string `json:"targetId"`
	}
	if err := json.Unmarshal(event.Params, &payload); err != nil {
		return
	}
	sm.mu.Lock()
	defer sm.mu.Unlock()
	delete(sm.sessions, payload.SessionID)
	if payload.TargetID != "" {
		if sessions := sm.targetSessions[payload.TargetID]; sessions != nil {
			delete(sessions, payload.SessionID)
			if len(sessions) == 0 {
				delete(sm.targetSessions, payload.TargetID)
				delete(sm.targets, payload.TargetID)
			}
		}
	}
}

func (sm *SessionManager) handleTargetInfoChanged(event CDPEvent) {
	var payload struct {
		TargetInfo Target `json:"targetInfo"`
	}
	if err := json.Unmarshal(event.Params, &payload); err != nil {
		return
	}
	sm.mu.Lock()
	sm.storeTarget(&payload.TargetInfo)
	sm.mu.Unlock()
}

func (sm *SessionManager) storeTarget(target *Target) {
	if target == nil || target.TargetID == "" {
		return
	}
	copyTarget := *target
	sm.targets[target.TargetID] = &copyTarget
}

func (sm *SessionManager) GetAllPageTargets() []*Target {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	var targets []*Target
	for _, target := range sm.targets {
		if target.TargetType == "page" || target.TargetType == "tab" {
			targets = append(targets, target)
		}
	}
	return targets
}

func (sm *SessionManager) GetSessionForTarget(targetID string) *CDPSession {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	for sessionID := range sm.targetSessions[targetID] {
		return sm.sessions[sessionID]
	}
	return nil
}

func (sm *SessionManager) WaitForSession(targetID string, timeout time.Duration) (*CDPSession, error) {
	ch := make(chan *CDPSession, 1)
	sm.mu.Lock()
	sm.attachWaiters[targetID] = append(sm.attachWaiters[targetID], ch)
	sm.mu.Unlock()
	select {
	case session := <-ch:
		return session, nil
	case <-time.After(timeout):
		return nil, context.DeadlineExceeded
	}
}

func (sm *SessionManager) GetTarget(targetID string) *Target {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	return sm.targets[targetID]
}
