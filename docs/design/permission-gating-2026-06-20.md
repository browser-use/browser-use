# Deterministic Permission Gating for Browser Actions

**Date:** 2026-06-20
**Author:** Adapted from proposal #5063
**Status:** Draft for discussion

## 1. Problem Statement

browser-use agents control a real browser — they navigate, click, fill forms, and extract data. Currently, any agent with browser access can perform any browser action. There is no mechanism to say "the product scraper agent may GET pages but not POST forms" or "the QA agent may click buttons but not navigate to non-whitelisted domains."

The `agchk` audit (#4739) flagged this: `capability_policy` at HIGH, noting that "Permission policy is not enforced on all dispatch paths."

### Specific risks

- **Domain escalation:** An agent tasked with scraping `example.com/docs` navigates to `example.com/admin`
- **Action escalation:** An agent allowed to read page content instead submits forms or triggers downloads
- **Data exfiltration:** An agent fills forms with sensitive data and submits to external endpoints
- **Indirect prompt injection:** An agent navigates to a page with hidden instructions that redirect its behavior

## 2. Existing Security Infrastructure

Before designing new policy gating, we must understand what already exists:

| Component | Location | What it does |
|---|---|---|
| `SecurityWatchdog` | `browser_use/browser/watchdogs/security_watchdog.py` | Filters allowed/prohibited domains before navigation |
| `DomainFilter` | `browser_use/agent/security/domain_filter.py` | URL pattern matching against allow/deny lists |
| `DownloadContainment` | `browser_use/agent/security/download_filename_sanitization.py` | Sanitizes downloaded filenames |
| `IPBlocking` | `browser_use/agent/security/ip_blocking.py` | Blocks IP-based navigation |
| `SensitiveDataFilter` | `browser_use/agent/security/sensitive_data.py` | Redacts sensitive data from LLM context |
| `MCPAllowedDomains` | `browser_use/agent/security/mcp_allowed_domains.py` | Restricts MCP server domain access |
| `message_compaction` | Agent config | Limits prompt growth |
| `max_history_items` | Agent config | Limits token costs |

**Key observation:** The domain-level checks exist (`allowed_domains`, `prohibited_domains`), but there is no action-level gating. The existing `SecurityWatchdog` only intercepts navigation — it doesn't gate `click`, `fill_form`, `submit`, `download`, or `execute_js`.

## 3. Proposal: `BrowserPolicy` Configuration

Add an optional `BrowserPolicy` model to the `Agent` constructor that evaluates **deterministically** before every browser action dispatch.

### 3.1 Policy Model

```python
from pydantic import BaseModel, Field
from typing import Literal


class BrowserPolicy(BaseModel):
    """Deterministic permission rules for browser actions.
    
    All checks are binary pass/fail — no LLM in the enforcement path.
    Evaluation order: denied_actions → allowed_actions → require_approval_for.
    """
    
    # Action namespace: actions match the agent's registered action names
    # e.g. "navigate", "click_element", "input_text", "scroll_down",
    #      "extract_content", "screenshot", "download_file", "execute_javascript"
    
    allowed_actions: list[str] | None = Field(
        default=None,
        description="If set, ONLY these actions are permitted. None = all actions allowed (subject to denied_actions).",
    )
    
    denied_actions: list[str] = Field(
        default_factory=list,
        description="Actions that are ALWAYS rejected with a clear error message.",
    )
    
    require_approval_for: list[str] = Field(
        default_factory=list,
        description="Actions that require human approval before execution. "
                    "If no human is available (headless/CI), these actions are DENIED.",
    )
    
    allowed_domains: list[str] | None = Field(
        default=None,
        description="Glob patterns for allowed navigation targets. "
                    "Overrides BrowserSession.allowed_domains when set at the Agent level. "
                    "None defers to BrowserSession's domain config.",
    )
    
    max_consecutive_same_action: int = Field(
        default=0, ge=0,
        description="Max times the same action type can repeat consecutively before denial. "
                    "0 = unlimited.",
    )
```

### 3.2 Usage Example

```python
agent = Agent(
    task="Scrape product pages on example.com",
    browser_policy=BrowserPolicy(
        allowed_actions=["navigate", "extract_content", "screenshot"],
        denied_actions=["download_file", "execute_javascript"],
        require_approval_for=["input_text", "click_element"],
        allowed_domains=["example.com/products/*"],
        max_consecutive_same_action=5,
    ),
)
```

### 3.3 Enforcement Point

The single centralized enforcement point is in `Agent.step()`, right before dispatching the action:

```python
# In Agent.step(), before executing the chosen action:
if self.browser_policy:
    result = self.browser_policy.enforce(
        action_name=action_name,
        action_params=action_params,
        history=self.history,
    )
    if result is not None:  # None = allowed
        return result  # ActionResult with error or approval-requested
```

**Why centralized here?** All action dispatch flows through `step()`. This single point ensures no action bypasses the policy, avoids scattering checks across watchdog handlers, and makes the policy easy to audit.

### 3.4 Integration with Existing Security

| Existing check | Relationship |
|---|---|
| `allowed_domains` / `prohibited_domains` in `BrowserSession` | Kept as-is. When `BrowserPolicy.allowed_domains` is set, it supplements (not replaces) the session-level domains. Both must pass. |
| `SecurityWatchdog` | Unchanged. It continues to handle domain-level filtering at navigation time. The policy layer adds action-level gating **before** navigation is even scheduled. |
| `message_compaction` / `max_history_items` | Unchanged — these control prompt size, not agent capabilities. |

### 3.5 Headless/CI Behavior

When `require_approval_for` includes actions but no human is available to approve:
- The action is **denied** with an `ActionResult` containing `error="Action requires human approval but no interactive session is available"`
- The agent receives this as a tool error and will typically self-correct
- This prevents agents from hanging indefinitely waiting for input

The `Agent` detects interactive mode by checking `sys.stdin.isatty()` or an explicit `interactive: bool` flag.

## 4. Implementation Plan

### Phase 1: Model + Enforcement (est. 2-3 days)

1. **Create `browser_use/agent/browser_policy.py`** — `BrowserPolicy` model with `enforce()` method
2. **Add `browser_policy` field to `AgentSettings`** (in `agent/views.py`)
3. **Integrate enforcement call in `Agent.step()`** — the single centralized dispatch point
4. **Add tests** — unit tests for policy evaluation logic, integration test for step-level enforcement

### Phase 2: Repo-level Default Policies (est. 1 day, optional)

Support a `BROWSER_USE.yml` at the repo root that defines default policies for common agent types:

```yaml
# BROWSER_USE.yml
policies:
  scraper:
    allowed_actions: [navigate, extract_content, screenshot]
    denied_actions: [input_text, click_element, download_file, execute_javascript]
  form_filler:
    allowed_actions: [navigate, click_element, input_text, extract_content]
    require_approval_for: [submit]
```

### Phase 3: Audit & Documentation (est. 1 day)

1. Review all registered actions in the action registry to ensure complete coverage
2. Write documentation with examples
3. Add a `--dry-run` mode that logs what _would_ be denied without actually blocking

## 5. Open Questions for Discussion

1. **Per-action vs per-parameter granularity?** E.g., should we allow `navigate` but only to `example.com/*`? (Proposal: start with action-level, add parameter-level in a future iteration.)
2. **Session-level or Agent-level?** Policy lives on the `Agent`, not `BrowserSession`, because different agents using the same browser may have different permissions. (Proposal: Agent-level, as shown above.)
3. **Should `allowed_domains` at the policy level override or supplement the session-level domains?** (Proposal: supplement — both must pass. Users who want to bypass session domains can leave them unset.)
4. **Should `require_approval_for` blocking be reported as a tool error or stop the agent entirely?** (Proposal: tool error — the agent re-plans naturally.)

## 6. Non-Goals

- **LLM-based policy evaluation** — all checks are deterministic, no LLM calls
- **Realtime policy changes** — policy is set at agent creation and immutable for the agent's lifetime
- **Per-user policy inheritance** — no RBAC or multi-tenant policy hierarchies
- **Audit logging** — covered by the existing `History` system; no separate audit trail needed

## 7. References

- Issue #5063: Original proposal
- Issue #4739: agchk audit (flagged `capability_policy` at HIGH)
- `browser_use/agent/security/` directory — existing security modules
- `browser_use/browser/watchdogs/security_watchdog.py` — existing domain filter
