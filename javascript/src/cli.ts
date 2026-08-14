#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { Agent } from "./agent.js";
import { eventJsonLine, resultJsonLine } from "./event-json.js";

const args = process.argv.slice(2);
const taskFileIndex = args.indexOf("--task-file");
const taskFile = taskFileIndex >= 0 ? args[taskFileIndex + 1] : undefined;
const task = taskFile
  ? await readFile(taskFile, "utf8")
  : args.filter((value) => value !== "--json").join(" ");

if (!task.trim()) {
  console.error("Usage: browser-use-js --task-file <path> | <task>");
  process.exit(2);
}

try {
  const result = await new Agent({
    task,
    model: process.env.BROWSER_USE_JS_MODEL ?? "gpt-5.5",
    ...(process.env.BROWSER_USE_JS_PROVIDER ? { provider: process.env.BROWSER_USE_JS_PROVIDER } : {}),
    reasoningEffort: reasoningEffort(process.env.BROWSER_USE_JS_REASONING_EFFORT),
    maxSteps: integer(process.env.BROWSER_USE_JS_MAX_STEPS, 100),
    onEvent: (event) => {
      process.stdout.write(eventJsonLine(event));
    },
  }).run();
  const { messages: _messages, ...summary } = result;
  process.stdout.write(resultJsonLine(summary));
} catch (error) {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  process.stdout.write(`${JSON.stringify({ type: "browser_use_js_error", error: message })}\n`);
  console.error(error);
  process.exitCode = 1;
}

function integer(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function reasoningEffort(value: string | undefined): "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" {
  return value === "off" || value === "minimal" || value === "low" || value === "high" || value === "xhigh" || value === "max"
    ? value
    : "medium";
}
