import assert from "node:assert/strict";
import test from "node:test";
import { BROWSER_AGENT_PROMPT } from "../dist/prompt.js";

test("browser prompt keeps the one-tool contract concise", () => {
  assert.match(BROWSER_AGENT_PROMPT, /browser_execute/);
  assert.match(BROWSER_AGENT_PROMPT, /FINAL ANSWER:/);
  assert.ok(BROWSER_AGENT_PROMPT.length < 4_000);
});
