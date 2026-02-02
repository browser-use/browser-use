package browseruse

import (
	"strings"

	"browseruse/browseruse/prompts"
)

type PromptStyle string

const (
	PromptStyleDefault     PromptStyle = "default"
	PromptStyleNoThinking  PromptStyle = "no_thinking"
	PromptStyleFlash       PromptStyle = "flash"
)

type PromptConfig struct {
	Style             PromptStyle
	MaxActionsPerStep int
	IsAnthropic       bool
	IsBrowserUseModel bool
	ModelName         string
}

func DefaultSystemPrompt(maxActions int) string {
	prompt, _ := SystemPrompt(PromptConfig{Style: PromptStyleDefault, MaxActionsPerStep: maxActions})
	return prompt
}

func SystemPrompt(cfg PromptConfig) (string, error) {
	if cfg.MaxActionsPerStep <= 0 {
		cfg.MaxActionsPerStep = 1
	}
	name := selectPromptName(cfg)
	prompt, err := prompts.Load(name, cfg.MaxActionsPerStep)
	if err != nil {
		return "", err
	}
	return prompt, nil
}

func selectPromptName(cfg PromptConfig) string {
	style := cfg.Style
	if style == "" {
		style = PromptStyleDefault
	}
	if cfg.IsBrowserUseModel {
		switch style {
		case PromptStyleFlash:
			return "system_prompt_browser_use_flash.md"
		case PromptStyleNoThinking:
			return "system_prompt_browser_use_no_thinking.md"
		default:
			return "system_prompt_browser_use.md"
		}
	}
	if cfg.IsAnthropic && style == PromptStyleFlash {
		if DetectAnthropic45Model(cfg.ModelName) {
			return "system_prompt_anthropic_flash.md"
		}
		return "system_prompt_flash_anthropic.md"
	}
	switch style {
	case PromptStyleFlash:
		return "system_prompt_flash.md"
	case PromptStyleNoThinking:
		return "system_prompt_no_thinking.md"
	default:
		return "system_prompt.md"
	}
}

func DetectBrowserUseModel(model string) bool {
	model = strings.ToLower(model)
	return strings.Contains(model, "browser-use") || strings.Contains(model, "browser_use")
}

func DetectAnthropicModel(model string) bool {
	model = strings.ToLower(model)
	return strings.Contains(model, "claude") || strings.Contains(model, "anthropic")
}

func DetectAnthropic45Model(model string) bool {
	model = strings.ToLower(model)
	if model == "" {
		return false
	}
	isOpus := strings.Contains(model, "opus") && (strings.Contains(model, "4.5") || strings.Contains(model, "4-5"))
	isHaiku := strings.Contains(model, "haiku") && (strings.Contains(model, "4.5") || strings.Contains(model, "4-5"))
	return isOpus || isHaiku
}
