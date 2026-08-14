import assert from "node:assert/strict";
import test from "node:test";

import { normalizeFinalOutput } from "../dist/agent.js";

test("final output drops rejected pseudo-tool text before the deliverable", () => {
  assert.equal(
    normalizeFinalOutput("attempted tool syntax\nFINAL ANSWER:\n{\"ok\":true}"),
    'FINAL ANSWER:\n{"ok":true}',
  );
  assert.equal(normalizeFinalOutput("ordinary answer"), "ordinary answer");
});
