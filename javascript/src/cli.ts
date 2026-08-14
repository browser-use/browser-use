#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { Agent } from "./agent.js";

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
      process.stdout.write(`${JSON.stringify(sanitize(event))}\n`);
    },
  }).run();
  const { messages: _messages, ...summary } = result;
  process.stdout.write(`${JSON.stringify({ type: "browser_use_js_result", result: sanitize(summary) })}\n`);
} catch (error) {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  process.stdout.write(`${JSON.stringify({ type: "browser_use_js_error", error: message })}\n`);
  console.error(error);
  process.exitCode = 1;
}

function sanitize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitize);
  if (!value || typeof value !== "object") {
    return typeof value === "string" && value.length > 30_000
      ? `${value.slice(0, 30_000)}... <${value.length - 30_000} chars omitted>`
      : value;
  }
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    result[key] = key === "data" && typeof item === "string" && item.length > 10_000
      ? `<image:${item.length} chars>`
      : sanitize(item);
  }
  return result;
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
