package browseruse

import "strings"
import "testing"

func TestHighlightOverlayScriptsPresent(t *testing.T) {
	if !strings.Contains(addHighlightOverlayJS, "__browseruse_highlight_overlay") {
		t.Fatalf("addHighlightOverlayJS missing overlay id")
	}
	if !strings.Contains(removeHighlightOverlayJS, "__browseruse_highlight_overlay") {
		t.Fatalf("removeHighlightOverlayJS missing overlay id")
	}
}
