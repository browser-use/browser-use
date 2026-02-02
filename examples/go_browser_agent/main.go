package main

import (
	"bufio"
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"browseruse/browseruse"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/openai/openai-go/v3/shared"
)

func main() {
	cdpURL := os.Getenv("CDP_URL")
	if cdpURL == "" {
		log.Fatal("CDP_URL is required (example: http://localhost:9222)")
	}
	apiKey := os.Getenv("OPENAI_API_KEY")
	if apiKey == "" {
		log.Fatal("OPENAI_API_KEY is required")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	session := browseruse.NewBrowserSession(cdpURL, nil)
	if err := session.Connect(ctx); err != nil {
		log.Fatalf("connect failed: %v", err)
	}
	defer func() {
		if err := session.Close(); err != nil {
			log.Printf("close failed: %v", err)
		}
	}()

	client := openai.NewClient(option.WithAPIKey(apiKey))
	agent, err := browseruse.NewAgent(browseruse.AgentConfig{
		Task:    "Visit https://duckduckgo.com and search for \"browser-use founders\"",
		Model:   "gpt-5.2",
		Session: session,
		Client:  &client,
		Reasoning: &shared.ReasoningParam{
			Effort: shared.ReasoningEffortMedium,
		},
		LogRequests: true,
	})
	if err != nil {
		log.Fatalf("agent init failed: %v", err)
	}

	result, err := agent.Run(ctx)
	if err != nil {
		log.Fatalf("agent run failed: %v", err)
	}
	fmt.Printf("Agent result:\n%s\n", result)

	fmt.Print("Press Enter to close...")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
}
