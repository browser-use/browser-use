package prompts

import (
	"embed"
	"fmt"
	"strings"
)

//go:embed *.md
var promptFS embed.FS

func Load(name string, maxActions int) (string, error) {
	data, err := promptFS.ReadFile(name)
	if err != nil {
		return "", err
	}
	prompt := string(data)
	prompt = strings.ReplaceAll(prompt, "{max_actions}", fmt.Sprintf("%d", maxActions))
	return prompt, nil
}
