package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"browseruse/browseruse"
)

func main() {
	cdpURL := os.Getenv("CDP_URL")
	if cdpURL == "" {
		log.Fatal("CDP_URL is required (example: http://localhost:9222)")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	session := browseruse.NewBrowserSession(cdpURL, nil)
	if err := session.Connect(ctx); err != nil {
		log.Fatalf("connect failed: %v", err)
	}

	fmt.Println("System prompt:\n", browseruse.DefaultSystemPrompt(3))
	toolsJSON, _ := json.MarshalIndent(browseruse.DefaultTools(), "", "  ")
	fmt.Println("Available tools:\n", string(toolsJSON))

	_, err := browseruse.ExecuteAction(ctx, session, browseruse.Action{
		Name: "navigate",
		Parameters: map[string]any{
			"url": "https://example.com",
		},
	})
	if err != nil {
		log.Fatalf("navigate failed: %v", err)
	}

	result, err := browseruse.ExecuteAction(ctx, session, browseruse.Action{
		Name:       "screenshot",
		Parameters: map[string]any{"format": "png"},
	})
	if err != nil {
		log.Fatalf("screenshot failed: %v", err)
	}

	fmt.Printf("Screenshot bytes (base64 length): %d\n", len(result.Screenshot))
}
