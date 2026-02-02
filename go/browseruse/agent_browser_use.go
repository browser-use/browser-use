package browseruse

import (
	"encoding/json"
	"fmt"
	"strings"
)

type stepRecord struct {
	Step         int
	Evaluation   string
	Memory       string
	NextGoal     string
	ActionOutput []string
}

type parsedAgentOutput struct {
	Thinking               string
	EvaluationPreviousGoal string
	Memory                 string
	NextGoal               string
}

func parseAgentOutput(text string) (parsedAgentOutput, []Action, error) {
	jsonText := extractJSON(text)
	parsed, actions, err := parseAgentOutputJSON(jsonText)
	if err == nil {
		return parsed, actions, nil
	}
	if repaired := balanceJSONDelimiters(jsonText); repaired != jsonText {
		if parsed, actions, err := parseAgentOutputJSON(repaired); err == nil {
			return parsed, actions, nil
		}
	}
	if candidate := findBalancedJSONObject(jsonText); candidate != "" && candidate != jsonText {
		if parsed, actions, err := parseAgentOutputJSON(candidate); err == nil {
			return parsed, actions, nil
		}
	}
	return parsedAgentOutput{Memory: strings.TrimSpace(text)}, nil, nil
}

func parseAgentOutputJSON(jsonText string) (parsedAgentOutput, []Action, error) {
	var raw struct {
		Thinking               string                       `json:"thinking"`
		EvaluationPreviousGoal string                       `json:"evaluation_previous_goal"`
		Memory                 string                       `json:"memory"`
		NextGoal               string                       `json:"next_goal"`
		Action                 []map[string]json.RawMessage `json:"action"`
	}
	if err := json.Unmarshal([]byte(jsonText), &raw); err != nil {
		return parsedAgentOutput{}, nil, err
	}
	actions := make([]Action, 0)
	for _, actionObj := range raw.Action {
		for name, payload := range actionObj {
			params := map[string]any{}
			if len(payload) > 0 {
				_ = json.Unmarshal(payload, &params)
			}
			actions = append(actions, Action{Name: name, Parameters: params})
		}
	}
	return parsedAgentOutput{
		Thinking:               raw.Thinking,
		EvaluationPreviousGoal: raw.EvaluationPreviousGoal,
		Memory:                 raw.Memory,
		NextGoal:               raw.NextGoal,
	}, actions, nil
}

func extractJSON(text string) string {
	trimmed := strings.TrimSpace(text)
	if strings.HasPrefix(trimmed, "```") {
		trimmed = strings.TrimPrefix(trimmed, "```")
		trimmed = strings.TrimPrefix(trimmed, "json")
		trimmed = strings.TrimSpace(trimmed)
		if idx := strings.LastIndex(trimmed, "```"); idx > 0 {
			trimmed = trimmed[:idx]
		}
		trimmed = strings.TrimSpace(trimmed)
	}
	if candidate := findBalancedJSONObject(trimmed); candidate != "" {
		return candidate
	}
	start := strings.Index(trimmed, "{")
	if start >= 0 {
		return strings.TrimSpace(trimmed[start:])
	}
	return trimmed
}

func findBalancedJSONObject(text string) string {
	start := -1
	depth := 0
	inString := false
	escape := false
	for i, r := range text {
		if start == -1 {
			if r == '{' {
				start = i
				depth = 1
			}
			continue
		}
		if inString {
			if escape {
				escape = false
				continue
			}
			if r == '\\' {
				escape = true
				continue
			}
			if r == '"' {
				inString = false
			}
			continue
		}
		switch r {
		case '"':
			inString = true
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return text[start : i+1]
			}
		}
	}
	if start >= 0 {
		return text[start:]
	}
	return ""
}

func balanceJSONDelimiters(text string) string {
	braceDepth := 0
	bracketDepth := 0
	inString := false
	escape := false
	for _, r := range text {
		if inString {
			if escape {
				escape = false
				continue
			}
			if r == '\\' {
				escape = true
				continue
			}
			if r == '"' {
				inString = false
			}
			continue
		}
		switch r {
		case '"':
			inString = true
		case '{':
			braceDepth++
		case '}':
			if braceDepth > 0 {
				braceDepth--
			}
		case '[':
			bracketDepth++
		case ']':
			if bracketDepth > 0 {
				bracketDepth--
			}
		}
	}
	if braceDepth == 0 && bracketDepth == 0 {
		return text
	}
	var builder strings.Builder
	builder.WriteString(text)
	for i := 0; i < bracketDepth; i++ {
		builder.WriteByte(']')
	}
	for i := 0; i < braceDepth; i++ {
		builder.WriteByte('}')
	}
	return builder.String()
}

func (a *Agent) buildStateMessage(step int, includeScreenshot bool) string {
	var builder strings.Builder
	builder.WriteString("<agent_history>\n")
	for _, record := range a.history {
		builder.WriteString(fmt.Sprintf("<step_%d>:\n", record.Step))
		builder.WriteString(fmt.Sprintf("Evaluation of Previous Step: %s\n", record.Evaluation))
		builder.WriteString(fmt.Sprintf("Memory: %s\n", record.Memory))
		builder.WriteString(fmt.Sprintf("Next Goal: %s\n", record.NextGoal))
		if len(record.ActionOutput) > 0 {
			builder.WriteString("Action Results: \n")
			for _, result := range record.ActionOutput {
				builder.WriteString("- " + result + "\n")
			}
		}
		builder.WriteString(fmt.Sprintf("</step_%d>\n", record.Step))
	}
	builder.WriteString("</agent_history>\n")
	builder.WriteString("<agent_state>\n")
	builder.WriteString("<user_request>\n")
	builder.WriteString(fmt.Sprintf("USER REQUEST: %s\n", a.task))
	builder.WriteString("</user_request>\n")
	builder.WriteString("<step_info>\n")
	builder.WriteString(fmt.Sprintf("Step %d of %d\n", step+1, a.maxSteps))
	builder.WriteString("</step_info>\n")
	if fs := a.session.FileSystem(); fs != nil {
		if files, err := fs.ListFiles(); err == nil && len(files) > 0 {
			builder.WriteString("<file_system>\n")
			builder.WriteString("Files: " + strings.Join(files, ", ") + "\n")
			builder.WriteString("</file_system>\n")
		}
		if todo, err := fs.ReadFile("todo.md"); err == nil && strings.TrimSpace(todo) != "" {
			builder.WriteString("<todo_contents>\n")
			builder.WriteString(truncateText(todo, 2000))
			builder.WriteString("\n</todo_contents>\n")
		}
	}
	builder.WriteString("</agent_state>\n")
	builder.WriteString("<browser_state>\n")
	builder.WriteString(a.session.BrowserStateText())
	builder.WriteString("</browser_state>\n")
	if includeScreenshot {
		builder.WriteString("<browser_vision>Screenshot attached.</browser_vision>\n")
	}
	if a.lastReadState != "" && a.lastReadState != "screenshot" {
		builder.WriteString("<read_state>\n")
		builder.WriteString(truncateText(a.lastReadState, 2000))
		builder.WriteString("\n</read_state>\n")
	}
	return builder.String()
}
