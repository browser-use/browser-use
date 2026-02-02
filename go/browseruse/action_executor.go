package browseruse

import (
	"context"
	"errors"
	"fmt"
)

func ExecuteAction(ctx context.Context, session *BrowserSession, action Action) (ActionResult, error) {
	if session == nil {
		return ActionResult{}, errors.New("session is nil")
	}
	page := session.GetCurrentPage()
	if page == nil {
		return ActionResult{}, errors.New("no current page")
	}
	params := action.Parameters
	switch action.Name {
	case "navigate":
		url, _ := params["url"].(string)
		if url == "" {
			return ActionResult{}, errors.New("url required")
		}
		return ActionResult{}, page.Goto(ctx, url)
	case "click_selector":
		selector, _ := params["selector"].(string)
		if selector == "" {
			return ActionResult{}, errors.New("selector required")
		}
		element, err := page.GetElementByCSSSelector(ctx, selector)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{}, element.Click(ctx)
	case "input_text":
		selector, _ := params["selector"].(string)
		text, _ := params["text"].(string)
		clear, _ := params["clear"].(bool)
		if selector == "" {
			return ActionResult{}, errors.New("selector required")
		}
		element, err := page.GetElementByCSSSelector(ctx, selector)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{}, element.Fill(ctx, text, clear)
	case "screenshot":
		format, _ := params["format"].(string)
		var quality *int
		if rawQuality, ok := params["quality"].(float64); ok {
			q := int(rawQuality)
			quality = &q
		}
		data, err := page.Screenshot(ctx, format, quality)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{Screenshot: data}, nil
	case "evaluate":
		pageFn, _ := params["page_function"].(string)
		argsAny, _ := params["args"].([]any)
		var args []any
		if len(argsAny) > 0 {
			args = argsAny
		}
		value, err := page.Evaluate(ctx, pageFn, args...)
		if err != nil {
			return ActionResult{}, err
		}
		return ActionResult{Text: value}, nil
	case "new_tab":
		url, _ := params["url"].(string)
		newPage, err := session.NewPage(ctx, url)
		if err != nil {
			return ActionResult{}, err
		}
		if newPage != nil {
			session.AgentFocusTarget = newPage.targetID
		}
		return ActionResult{Text: "new tab opened"}, nil
	default:
		return ActionResult{}, fmt.Errorf("unknown action %s", action.Name)
	}
}
