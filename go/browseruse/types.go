package browseruse

type Target struct {
	TargetID   string `json:"targetId"`
	TargetType string `json:"type"`
	URL        string `json:"url"`
	Title      string `json:"title"`
}

type CDPSession struct {
	TargetID  string
	SessionID string
}
