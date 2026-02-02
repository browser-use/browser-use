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
	Task               string
	Model              string
	Session            *BrowserSession
	Client             *openai.Client
	Tools              []responses.ToolUnionParam
	MaxSteps           int
	MaxActionsPerStep  int
	SystemPrompt       string
	PromptStyle        PromptStyle
	UseToolCalls       bool
	UseVision          string
	LogRequests        bool
	LogResponses       bool
	Reasoning          *shared.ReasoningParam
	Logger             *log.Logger
}

type Agent struct {
	task              string
	model             string
	session           *BrowserSession
	client            *openai.Client
	tools             []responses.ToolUnionParam
	maxSteps          int
	maxActionsPerStep int
	systemPrompt      string
	promptStyle       PromptStyle
	useToolCalls      bool
	useVision         string
	reasoning         *shared.ReasoningParam
	logRequests       bool
	logResponses      bool
	logger            *log.Logger
	history           []stepRecord
	lastReadState     string
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
	maxActions := cfg.MaxActionsPerStep
	if maxActions <= 0 {
		maxActions = 1
	}
	useToolCalls := cfg.UseToolCalls
	useVision := cfg.UseVision
	if useVision == "" {
		useVision = "auto"
	}
	promptStyle := cfg.PromptStyle
	prompt := cfg.SystemPrompt
	if prompt == "" {
		defaultPrompt, err := SystemPrompt(PromptConfig{
			Style:             promptStyle,
			MaxActionsPerStep: maxActions,
			IsBrowserUseModel: DetectBrowserUseModel(model),
			IsAnthropic:       DetectAnthropicModel(model),
			ModelName:         model,
		})
		if err == nil {
			prompt = defaultPrompt
		}
	}
	reasoning := cfg.Reasoning
	logRequests := cfg.LogRequests
	logResponses := cfg.LogResponses
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
		maxSteps:          maxSteps,
		maxActionsPerStep: maxActions,
		systemPrompt:      prompt,
		promptStyle:       promptStyle,
		useToolCalls:      useToolCalls,
		useVision:         useVision,
		reasoning:         reasoning,
		logRequests:       logRequests,
		logResponses:      logResponses,
		logger:            logger,
	}, nil
}

func (a *Agent) Run(ctx context.Context) (string, error) {
	if a.session.client == nil {
		if err := a.session.Connect(ctx); err != nil {
			return "", err
		}
	}
	if a.useToolCalls {
		return a.runToolCalls(ctx)
	}
	return a.runBrowserUse(ctx)
}

func (a *Agent) runToolCalls(ctx context.Context) (string, error) {
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
		if a.logResponses {
			a.logResponse(resp)
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

func (a *Agent) runBrowserUse(ctx context.Context) (string, error) {
	var finalText string
	for step := 0; step < a.maxSteps; step++ {
		includeScreenshot := a.useVision == "always"
		if a.useVision == "auto" && a.lastReadState == "screenshot" {
			includeScreenshot = true
		}
		state, err := a.session.GetBrowserStateSummary(ctx, includeScreenshot)
		if err != nil {
			return finalText, err
		}
		stateMessage := a.buildStateMessage(step, includeScreenshot)
		inputItems := responses.ResponseInputParam{}
		inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(a.systemPrompt, responses.EasyInputMessageRoleSystem))
		if includeScreenshot && state.Screenshot != "" {
			content := responses.ResponseInputMessageContentListParam{
				{OfInputText: &responses.ResponseInputTextParam{Text: stateMessage, Type: "input_text"}},
				{OfInputImage: &responses.ResponseInputImageParam{ImageURL: openai.String("data:image/webp;base64," + state.Screenshot), Detail: responses.ResponseInputImageDetailAuto, Type: "input_image"}},
			}
			inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(content, responses.EasyInputMessageRoleUser))
		} else {
			inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(stateMessage, responses.EasyInputMessageRoleUser))
		}
		params := responses.ResponseNewParams{
			Model: a.model,
			Input: responses.ResponseNewParamsInputUnion{OfInputItemList: inputItems},
		}
		if a.reasoning != nil {
			params.Reasoning = *a.reasoning
		}
		if a.logRequests {
			a.logBrowserUseRequest(stateMessage)
		}
		resp, err := a.client.Responses.New(ctx, params)
		if err != nil {
			return finalText, err
		}
		outputText := strings.TrimSpace(extractOutputText(resp.Output))
		if outputText == "" {
			outputText = "{}"
		}
		parsed, actions, err := parseAgentOutput(outputText)
		if err != nil {
			return finalText, err
		}
		if a.logResponses {
			a.logBrowserUseResponse(outputText, actions)
		}
		finalText = parsed.Memory
		a.history = append(a.history, stepRecord{
			Step:         step + 1,
			Evaluation:   parsed.EvaluationPreviousGoal,
			Memory:       parsed.Memory,
			NextGoal:     parsed.NextGoal,
			ActionOutput: nil,
		})
		if len(actions) == 0 {
			return parsed.Memory, nil
		}
		if len(actions) > a.maxActionsPerStep {
			actions = actions[:a.maxActionsPerStep]
		}
		results := make([]string, 0, len(actions))
		actionCtx := ActionContext{
			Session:    a.session,
			FileSystem: a.session.FileSystem(),
			Client:     a.client,
			Model:      a.model,
		}
		for _, action := range actions {
			result, err := ExecuteAction(ctx, action, actionCtx)
			if err != nil {
				results = append(results, fmt.Sprintf("%s error: %v", action.Name, err))
				break
			}
			if action.Name == "done" {
				return result.ExtractedContent, nil
			}
			if action.Name == "read_file" || action.Name == "extract" {
				a.lastReadState = result.ExtractedContent
			} else if action.Name == "screenshot" {
				a.lastReadState = "screenshot"
			} else {
				a.lastReadState = ""
			}
			if result.Error != "" {
				results = append(results, fmt.Sprintf("%s error: %s", action.Name, result.Error))
				break
			}
			if result.ExtractedContent != "" {
				results = append(results, fmt.Sprintf("%s: %s", action.Name, truncateText(result.ExtractedContent, 200)))
			}
		}
		if a.logResponses {
			a.logBrowserUseToolResults(actions, results)
		}
		if len(a.history) > 0 {
			a.history[len(a.history)-1].ActionOutput = results
		}
	}
	return finalText, fmt.Errorf("max steps reached")
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
	result, err := ExecuteAction(ctx, Action{Name: call.Name, Parameters: params}, ActionContext{
		Session:    a.session,
		FileSystem: a.session.FileSystem(),
		Client:     a.client,
		Model:      a.model,
	})
	if err != nil {
		a.logger.Printf("tool %s failed: %v", call.Name, err)
	}
	return formatToolOutput(result, err)
}

func formatToolOutput(result ActionResult, err error) string {
	payload := map[string]any{}
	if result.ExtractedContent != "" {
		payload["text"] = truncateText(result.ExtractedContent, 2000)
	}
	if result.Screenshot != "" {
		payload["screenshot"] = result.Screenshot
		payload["screenshot_length"] = len(result.Screenshot)
	}
	if result.Error != "" {
		payload["error"] = result.Error
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
		summary["message_payload"] = truncateText(value, 500)
		summary["message_length"] = len(value)
	} else if !param.IsOmitted(params.Input.OfInputItemList) {
		summary["tool_outputs"] = summarizeToolOutputs(params.Input.OfInputItemList)
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
	a.logger.Printf("OpenAI request summary:\n%s", string(data))
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

func summarizeToolOutputs(items responses.ResponseInputParam) []map[string]any {
	summaries := make([]map[string]any, 0, len(items))
	for _, item := range items {
		if item.OfFunctionCallOutput == nil {
			continue
		}
		summary := map[string]any{
			"call_id": item.OfFunctionCallOutput.CallID,
		}
		if !param.IsOmitted(item.OfFunctionCallOutput.Output.OfString) {
			output := item.OfFunctionCallOutput.Output.OfString.Value
			summary["output_length"] = len(output)
			summary["output_preview"] = truncateText(output, 200)
		} else {
			summary["output_type"] = "structured"
		}
		summaries = append(summaries, summary)
	}
	return summaries
}

func (a *Agent) logResponse(resp *responses.Response) {
	toolCalls := make([]map[string]any, 0)
	messages := make([]string, 0)
	for _, item := range resp.Output {
		switch item.Type {
		case "function_call":
			toolCalls = append(toolCalls, map[string]any{
				"call_id":          item.CallID,
				"name":             item.Name,
				"arguments_length": len(item.Arguments),
				"arguments":        truncateText(item.Arguments, 500),
			})
		case "message":
			var builder strings.Builder
			for _, content := range item.Content {
				switch content.Type {
				case "output_text":
					builder.WriteString(content.Text)
				case "refusal":
					builder.WriteString(content.Refusal)
				}
			}
			text := strings.TrimSpace(builder.String())
			if text != "" {
				messages = append(messages, truncateText(text, 500))
			}
		}
	}
	summary := map[string]any{
		"id":    resp.ID,
		"model": resp.Model,
	}
	if len(toolCalls) > 0 {
		summary["tool_calls"] = toolCalls
	}
	if len(messages) > 0 {
		summary["messages"] = messages
	}
	data, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		a.logger.Printf("OpenAI response summary marshal error: %v", err)
		return
	}
	a.logger.Printf("OpenAI response summary:\n%s", string(data))
}

func (a *Agent) logBrowserUseRequest(stateMessage string) {
	summary := map[string]any{
		"system_prompt_length": len(a.systemPrompt),
		"message_length":       len(stateMessage),
		"message_payload":      truncateText(stateMessage, 1000),
	}
	data, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		a.logger.Printf("BrowserUse request summary marshal error: %v", err)
		return
	}
	a.logger.Printf("BrowserUse request summary:\n%s", string(data))
	a.logger.Printf("BrowserUse request payload (decoded):\n%s", stateMessage)
}

func (a *Agent) logBrowserUseResponse(outputText string, actions []Action) {
	toolCalls := make([]map[string]any, 0, len(actions))
	for _, action := range actions {
		toolCalls = append(toolCalls, map[string]any{
			"name":       action.Name,
			"parameters": truncateParams(action.Parameters, 200),
		})
	}
	summary := map[string]any{
		"agent_output": truncateText(outputText, 800),
	}
	if len(toolCalls) > 0 {
		summary["tool_calls"] = toolCalls
	}
	data, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		a.logger.Printf("BrowserUse response summary marshal error: %v", err)
		return
	}
	a.logger.Printf("BrowserUse response summary:\n%s", string(data))
	a.logger.Printf("BrowserUse response payload (decoded):\n%s", outputText)
}

func (a *Agent) logBrowserUseToolResults(actions []Action, results []string) {
	toolNames := make([]string, 0, len(actions))
	for _, action := range actions {
		toolNames = append(toolNames, action.Name)
	}
	summary := map[string]any{
		"tool_calls":   toolNames,
		"tool_results": results,
	}
	data, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		a.logger.Printf("BrowserUse tool result summary marshal error: %v", err)
		return
	}
	a.logger.Printf("BrowserUse tool results:\n%s", string(data))
}

func truncateParams(params map[string]any, max int) map[string]any {
	if params == nil {
		return nil
	}
	out := make(map[string]any, len(params))
	for key, value := range params {
		switch v := value.(type) {
		case string:
			out[key] = truncateText(v, max)
		case []any:
			if len(v) > 10 {
				out[key] = append(v[:10], "...truncated")
			} else {
				out[key] = v
			}
		default:
			out[key] = v
		}
	}
	return out
}
