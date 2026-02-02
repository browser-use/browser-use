package browseruse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/openai/openai-go/v3/packages/param"
	"github.com/openai/openai-go/v3/responses"
	"github.com/openai/openai-go/v3/shared"
)

type AgentConfig struct {
	Task         string
	Model        string
	Session      *BrowserSession
	Client       *openai.Client
	Tools        []responses.ToolUnionParam
	MaxSteps     int
	SystemPrompt string
	LogRequests  bool
	Reasoning    *shared.ReasoningParam
	Logger       *log.Logger
}

type Agent struct {
	task         string
	model        string
	session      *BrowserSession
	client       *openai.Client
	tools        []responses.ToolUnionParam
	maxSteps     int
	systemPrompt string
	reasoning    *shared.ReasoningParam
	logRequests  bool
	logger       *log.Logger
}

func NewAgent(cfg AgentConfig) (*Agent, error) {
	if cfg.Task == "" {
		return nil, errors.New("task required")
	}
	if cfg.Session == nil {
		return nil, errors.New("browser session required")
	}
	client := cfg.Client
	if client == nil {
		apiKey := os.Getenv("OPENAI_API_KEY")
		if apiKey == "" {
			return nil, errors.New("OPENAI_API_KEY is required")
		}
		newClient := openai.NewClient(option.WithAPIKey(apiKey))
		client = &newClient
	}
	model := cfg.Model
	if model == "" {
		model = openai.ChatModelGPT4_1Mini
	}
	tools := cfg.Tools
	if len(tools) == 0 {
		tools = DefaultTools()
	}
	maxSteps := cfg.MaxSteps
	if maxSteps <= 0 {
		maxSteps = 10
	}
	prompt := cfg.SystemPrompt
	if prompt == "" {
		prompt = DefaultSystemPrompt(3)
	}
	reasoning := cfg.Reasoning
	logRequests := cfg.LogRequests
	logger := cfg.Logger
	if logger == nil {
		logger = log.New(os.Stdout, "", log.LstdFlags)
	}
	return &Agent{
		task:         cfg.Task,
		model:        model,
		session:      cfg.Session,
		client:       client,
		tools:        tools,
		maxSteps:     maxSteps,
		systemPrompt: prompt,
		reasoning:    reasoning,
		logRequests:  logRequests,
		logger:       logger,
	}, nil
}

func (a *Agent) Run(ctx context.Context) (string, error) {
	if a.session.client == nil {
		if err := a.session.Connect(ctx); err != nil {
			return "", err
		}
	}
	input := responses.ResponseNewParamsInputUnion{OfString: openai.String(a.task)}
	var previousResponseID string
	var finalText string
	for step := 0; step < a.maxSteps; step++ {
		params := responses.ResponseNewParams{
			Model:        a.model,
			Input:        input,
			Tools:        a.tools,
			Instructions: openai.String(a.systemPrompt),
		}
		if a.reasoning != nil {
			params.Reasoning = *a.reasoning
		}
		if previousResponseID != "" {
			params.PreviousResponseID = openai.String(previousResponseID)
		}
		if a.logRequests {
			a.logRequest(params)
		}
		resp, err := a.client.Responses.New(ctx, params)
		if err != nil {
			return finalText, err
		}
		previousResponseID = resp.ID

		toolCalls := extractFunctionCalls(resp.Output)
		finalText = strings.TrimSpace(finalText + "\n" + extractOutputText(resp.Output))
		if len(toolCalls) == 0 {
			if finalText == "" {
				finalText = "no output"
			}
			return strings.TrimSpace(finalText), nil
		}

		inputItems := responses.ResponseInputParam{}
		for _, call := range toolCalls {
			output := a.executeToolCall(ctx, call)
			inputItems = append(inputItems, responses.ResponseInputItemParamOfFunctionCallOutput(call.CallID, output))
		}
		input = responses.ResponseNewParamsInputUnion{OfInputItemList: inputItems}
	}
	return strings.TrimSpace(finalText), fmt.Errorf("max steps reached")
}

type functionCall struct {
	Name      string
	Arguments string
	CallID    string
}

func extractFunctionCalls(items []responses.ResponseOutputItemUnion) []functionCall {
	var calls []functionCall
	for _, item := range items {
		if item.Type != "function_call" {
			continue
		}
		calls = append(calls, functionCall{
			Name:      item.Name,
			Arguments: item.Arguments,
			CallID:    item.CallID,
		})
	}
	return calls
}

func extractOutputText(items []responses.ResponseOutputItemUnion) string {
	var builder strings.Builder
	for _, item := range items {
		if item.Type != "message" {
			continue
		}
		for _, content := range item.Content {
			switch content.Type {
			case "output_text":
				builder.WriteString(content.Text)
			case "refusal":
				builder.WriteString(content.Refusal)
			}
		}
	}
	return builder.String()
}

func (a *Agent) executeToolCall(ctx context.Context, call functionCall) string {
	params := map[string]any{}
	if call.Arguments != "" {
		if err := json.Unmarshal([]byte(call.Arguments), &params); err != nil {
			a.logger.Printf("failed to parse tool arguments: %v", err)
		}
	}
	result, err := ExecuteAction(ctx, a.session, Action{Name: call.Name, Parameters: params})
	if err != nil {
		a.logger.Printf("tool %s failed: %v", call.Name, err)
	}
	return formatToolOutput(result, err)
}

func formatToolOutput(result ActionResult, err error) string {
	payload := map[string]any{}
	if result.Text != "" {
		payload["text"] = truncateText(result.Text, 2000)
	}
	if result.Screenshot != "" {
		payload["screenshot"] = result.Screenshot
		payload["screenshot_length"] = len(result.Screenshot)
	}
	if err != nil {
		payload["error"] = err.Error()
	}
	data, marshalErr := json.Marshal(payload)
	if marshalErr != nil {
		return fmt.Sprintf("{\"error\":%q}", marshalErr.Error())
	}
	return string(data)
}

func truncateText(text string, max int) string {
	if max <= 0 || len(text) <= max {
		return text
	}
	return text[:max] + "...<truncated>"
}

func (a *Agent) logRequest(params responses.ResponseNewParams) {
	summary := map[string]any{
		"model": params.Model,
		"tools": toolNames(params.Tools),
	}
	if !param.IsOmitted(params.Input.OfString) {
		value := params.Input.OfString.Value
		summary["input_type"] = "string"
		summary["input_length"] = len(value)
		summary["input_preview"] = truncateText(value, 200)
	} else if !param.IsOmitted(params.Input.OfInputItemList) {
		summary["input_type"] = "input_items"
		summary["items"] = summarizeInputItems(params.Input.OfInputItemList)
	}
	if a.reasoning != nil {
		summary["reasoning_effort"] = a.reasoning.Effort
		if a.reasoning.Summary != "" {
			summary["reasoning_summary"] = a.reasoning.Summary
		}
	}
	data, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		a.logger.Printf("OpenAI payload summary marshal error: %v", err)
		return
	}
	a.logger.Printf("OpenAI payload summary:\n%s", string(data))
}

func toolNames(tools []responses.ToolUnionParam) []string {
	names := make([]string, 0, len(tools))
	for _, tool := range tools {
		switch {
		case tool.OfFunction != nil:
			names = append(names, tool.OfFunction.Name)
		case tool.OfWebSearch != nil:
			names = append(names, "web_search")
		case tool.OfWebSearchPreview != nil:
			names = append(names, "web_search_preview")
		case tool.OfComputerUsePreview != nil:
			names = append(names, "computer_use_preview")
		case tool.OfCodeInterpreter != nil:
			names = append(names, "code_interpreter")
		case tool.OfImageGeneration != nil:
			names = append(names, "image_generation")
		case tool.OfFileSearch != nil:
			names = append(names, "file_search")
		case tool.OfLocalShell != nil:
			names = append(names, "local_shell")
		case tool.OfMcp != nil:
			names = append(names, "mcp")
		case tool.OfCustom != nil:
			names = append(names, "custom")
		default:
			names = append(names, "unknown")
		}
	}
	return names
}

func summarizeInputItems(items responses.ResponseInputParam) []map[string]any {
	summaries := make([]map[string]any, 0, len(items))
	for _, item := range items {
		summary := map[string]any{}
		switch {
		case item.OfFunctionCallOutput != nil:
			summary["type"] = "function_call_output"
			summary["call_id"] = item.OfFunctionCallOutput.CallID
			if !param.IsOmitted(item.OfFunctionCallOutput.Output.OfString) {
				output := item.OfFunctionCallOutput.Output.OfString.Value
				summary["output_length"] = len(output)
				summary["output_preview"] = truncateText(output, 120)
			} else {
				summary["output_type"] = "structured"
			}
		case item.OfInputMessage != nil:
			summary["type"] = "input_message"
			summary["role"] = item.OfInputMessage.Role
		case item.OfMessage != nil:
			summary["type"] = "message"
		default:
			summary["type"] = "unknown"
		}
		summaries = append(summaries, summary)
	}
	return summaries
}
