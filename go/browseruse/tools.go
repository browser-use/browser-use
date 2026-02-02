package browseruse

import (
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/responses"
)

type Action struct {
	Name       string         `json:"name"`
	Parameters map[string]any `json:"parameters"`
}

type ActionResult struct {
	Text       string `json:"text,omitempty"`
	Screenshot string `json:"screenshot,omitempty"`
}

func DefaultTools() []responses.ToolUnionParam {
	return []responses.ToolUnionParam{
		functionTool(
			"navigate",
			"Navigate to a URL in the current tab",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"url": map[string]any{"type": "string"},
				},
				"required": []string{"url"},
			},
		),
		functionTool(
			"click_selector",
			"Click the first element matching a CSS selector",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"selector": map[string]any{"type": "string"},
				},
				"required": []string{"selector"},
			},
		),
		functionTool(
			"input_text",
			"Fill the first element matching selector with text",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"selector": map[string]any{"type": "string"},
					"text":     map[string]any{"type": "string"},
					"clear":    map[string]any{"type": "boolean"},
				},
				"required": []string{"selector", "text"},
			},
		),
		functionTool(
			"screenshot",
			"Capture a screenshot of the current page",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"format":     map[string]any{"type": "string"},
					"quality":    map[string]any{"type": "integer"},
					"max_width":  map[string]any{"type": "integer"},
					"max_height": map[string]any{"type": "integer"},
				},
			},
		),
		functionTool(
			"evaluate",
			"Run JavaScript in the page context",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"page_function": map[string]any{"type": "string"},
					"args": map[string]any{
						"type":  "array",
						"items": map[string]any{},
					},
				},
				"required": []string{"page_function"},
			},
		),
		functionTool(
			"new_tab",
			"Open a new tab (optionally with URL)",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"url": map[string]any{"type": "string"},
				},
			},
		),
	}
}

func functionTool(name, description string, params responses.FunctionParameters) responses.ToolUnionParam {
	return responses.ToolUnionParam{
		OfFunction: &responses.FunctionToolParam{
			Name:        name,
			Description: openai.String(description),
			Parameters:  params,
		},
	}
}
