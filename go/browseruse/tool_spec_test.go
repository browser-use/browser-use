package browseruse

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"testing"
)

func loadToolSpec(t *testing.T) []string {
	_, filename, _, _ := runtime.Caller(0)
	fixturePath := filepath.Join(filepath.Dir(filename), "..", "..", "tests", "fixtures", "browser_use_tool_spec.json")
	data, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatalf("failed to read tool spec: %v", err)
	}
	var tools []string
	if err := json.Unmarshal(data, &tools); err != nil {
		t.Fatalf("failed to parse tool spec: %v", err)
	}
	sort.Strings(tools)
	return tools
}

func TestDefaultToolsMatchSpec(t *testing.T) {
	expected := loadToolSpec(t)
	tools := DefaultTools()
	actual := make([]string, 0, len(tools))
	for _, tool := range tools {
		if tool.OfFunction == nil {
			continue
		}
		actual = append(actual, tool.OfFunction.Name)
	}
	sort.Strings(actual)
	if len(actual) != len(expected) {
		t.Fatalf("tool count mismatch: expected %d got %d", len(expected), len(actual))
	}
	for i := range expected {
		if expected[i] != actual[i] {
			t.Fatalf("tool list mismatch at %d: expected %s got %s", i, expected[i], actual[i])
		}
	}
}
