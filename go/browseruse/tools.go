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
	ExtractedContent string         `json:"extracted_content,omitempty"`
	Error            string         `json:"error,omitempty"`
	Metadata         map[string]any `json:"metadata,omitempty"`
	LongTermMemory   string         `json:"long_term_memory,omitempty"`
	Screenshot       string         `json:"screenshot,omitempty"`
	FilesToDisplay   []string       `json:"files_to_display,omitempty"`
}

func DefaultTools() []responses.ToolUnionParam {
	return []responses.ToolUnionParam{
		functionTool(
			"search",
			"Search the web with a given engine and query",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"query":  map[string]any{"type": "string"},
					"engine": map[string]any{"type": "string"},
				},
				"required": []string{"query"},
			},
		),
		functionTool(
			"navigate",
			"Navigate to a URL in the current tab or a new tab",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"url":     map[string]any{"type": "string"},
					"new_tab": map[string]any{"type": "boolean"},
				},
				"required": []string{"url"},
			},
		),
		functionTool(
			"go_back",
			"Go back in browser history",
			responses.FunctionParameters{"type": "object"},
		),
		functionTool(
			"wait",
			"Wait for a number of seconds",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"seconds": map[string]any{"type": "number"},
				},
			},
		),
		functionTool(
			"click",
			"Click an element by index or coordinate",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"index":        map[string]any{"type": "integer"},
					"coordinate_x": map[string]any{"type": "integer"},
					"coordinate_y": map[string]any{"type": "integer"},
				},
			},
		),
		functionTool(
			"input",
			"Input text into an element by index",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"index": map[string]any{"type": "integer"},
					"text":  map[string]any{"type": "string"},
					"clear": map[string]any{"type": "boolean"},
				},
				"required": []string{"index", "text"},
			},
		),
		functionTool(
			"upload_file",
			"Upload a file to a file input element by index",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"index": map[string]any{"type": "integer"},
					"path":  map[string]any{"type": "string"},
				},
				"required": []string{"index", "path"},
			},
		),
		functionTool(
			"switch",
			"Switch to a tab by id",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"tab_id": map[string]any{"type": "string"},
				},
				"required": []string{"tab_id"},
			},
		),
		functionTool(
			"close",
			"Close a tab by id",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"tab_id": map[string]any{"type": "string"},
				},
				"required": []string{"tab_id"},
			},
		),
		functionTool(
			"extract",
			"Extract structured information from the page",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"query":           map[string]any{"type": "string"},
					"extract_links":   map[string]any{"type": "boolean"},
					"start_from_char": map[string]any{"type": "integer"},
					"output_schema":   map[string]any{"type": "object"},
				},
				"required": []string{"query"},
			},
		),
		functionTool(
			"search_page",
			"Search for text or pattern in the current page",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"pattern":        map[string]any{"type": "string"},
					"regex":          map[string]any{"type": "boolean"},
					"case_sensitive": map[string]any{"type": "boolean"},
					"context_chars":  map[string]any{"type": "integer"},
					"css_scope":      map[string]any{"type": "string"},
					"max_results":    map[string]any{"type": "integer"},
				},
				"required": []string{"pattern"},
			},
		),
		functionTool(
			"find_elements",
			"Find elements by CSS selector",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"selector":     map[string]any{"type": "string"},
					"attributes":   map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
					"max_results":  map[string]any{"type": "integer"},
					"include_text": map[string]any{"type": "boolean"},
				},
				"required": []string{"selector"},
			},
		),
		functionTool(
			"scroll",
			"Scroll the page",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"down":  map[string]any{"type": "boolean"},
					"pages": map[string]any{"type": "number"},
					"index": map[string]any{"type": "integer"},
				},
			},
		),
		functionTool(
			"send_keys",
			"Send key presses",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"keys": map[string]any{"type": "string"},
				},
				"required": []string{"keys"},
			},
		),
		functionTool(
			"find_text",
			"Scroll to text on the page",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"text": map[string]any{"type": "string"},
				},
				"required": []string{"text"},
			},
		),
		functionTool(
			"screenshot",
			"Capture a screenshot of the current page",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"file_name": map[string]any{"type": "string"},
				},
			},
		),
		functionTool(
			"dropdown_options",
			"Get dropdown options by element index",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"index": map[string]any{"type": "integer"},
				},
				"required": []string{"index"},
			},
		),
		functionTool(
			"select_dropdown",
			"Select dropdown option by text",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"index": map[string]any{"type": "integer"},
					"text":  map[string]any{"type": "string"},
				},
				"required": []string{"index", "text"},
			},
		),
		functionTool(
			"write_file",
			"Write a file to the filesystem",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"file_name":       map[string]any{"type": "string"},
					"content":         map[string]any{"type": "string"},
					"append":          map[string]any{"type": "boolean"},
					"trailing_newline": map[string]any{"type": "boolean"},
					"leading_newline":  map[string]any{"type": "boolean"},
				},
				"required": []string{"file_name", "content"},
			},
		),
		functionTool(
			"replace_file",
			"Replace a string in a file",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"file_name": map[string]any{"type": "string"},
					"old_str":   map[string]any{"type": "string"},
					"new_str":   map[string]any{"type": "string"},
				},
				"required": []string{"file_name", "old_str", "new_str"},
			},
		),
		functionTool(
			"read_file",
			"Read a file from the filesystem",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"file_name": map[string]any{"type": "string"},
				},
				"required": []string{"file_name"},
			},
		),
		functionTool(
			"evaluate",
			"Run JavaScript in the page context",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"code": map[string]any{"type": "string"},
				},
				"required": []string{"code"},
			},
		),
		functionTool(
			"done",
			"Finish the task",
			responses.FunctionParameters{
				"type": "object",
				"properties": map[string]any{
					"text":             map[string]any{"type": "string"},
					"success":          map[string]any{"type": "boolean"},
					"files_to_display": map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
					"data":             map[string]any{"type": "object"},
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
