package browseruse

type Tool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

type Action struct {
	Name       string         `json:"name"`
	Parameters map[string]any `json:"parameters"`
}

type ActionResult struct {
	Text       string `json:"text,omitempty"`
	Screenshot string `json:"screenshot,omitempty"`
}

func DefaultTools() []Tool {
	return []Tool{
		{
			Name:        "navigate",
			Description: "Navigate to a URL in the current tab",
			Parameters: map[string]any{
				"type":       "object",
				"properties": map[string]any{"url": map[string]any{"type": "string"}},
				"required":   []string{"url"},
			},
		},
		{
			Name:        "click_selector",
			Description: "Click the first element matching a CSS selector",
			Parameters: map[string]any{
				"type":       "object",
				"properties": map[string]any{"selector": map[string]any{"type": "string"}},
				"required":   []string{"selector"},
			},
		},
		{
			Name:        "input_text",
			Description: "Fill the first element matching selector with text",
			Parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"selector": map[string]any{"type": "string"},
					"text":     map[string]any{"type": "string"},
					"clear":    map[string]any{"type": "boolean"},
				},
				"required": []string{"selector", "text"},
			},
		},
		{
			Name:        "screenshot",
			Description: "Capture a screenshot of the current page",
			Parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"format":  map[string]any{"type": "string"},
					"quality": map[string]any{"type": "integer"},
				},
			},
		},
		{
			Name:        "evaluate",
			Description: "Run JavaScript in the page context",
			Parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_function": map[string]any{"type": "string"},
					"args":          map[string]any{"type": "array"},
				},
				"required": []string{"page_function"},
			},
		},
		{
			Name:        "new_tab",
			Description: "Open a new tab (optionally with URL)",
			Parameters: map[string]any{
				"type":       "object",
				"properties": map[string]any{"url": map[string]any{"type": "string"}},
			},
		},
	}
}
