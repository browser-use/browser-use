import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { AgentTool } from "@earendil-works/pi-agent-core";
import { Type } from "typebox";
import type { Browser } from "./browser.js";

const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_TIMEOUT_MS = 10 * 60_000;
const MAX_TEXT_CHARS = 30_000;
const AsyncFunction = (async () => {}).constructor as new (
  ...args: string[]
) => (...injected: unknown[]) => Promise<unknown>;

const parameters = Type.Object({
  code: Type.String({ description: "JavaScript to execute with the persistent CDP `session` and per-call `console` in scope" }),
  timeout: Type.Optional(Type.Number({ description: "Timeout in milliseconds", minimum: 250, maximum: MAX_TIMEOUT_MS })),
  description: Type.String({ description: "A clear 3-7 word description of the snippet" }),
});

export type BrowserExecuteDetails = {
  output: string;
  result: string;
  screenshots: number;
};

export function createBrowserExecuteTool(browser: Browser): AgentTool<typeof parameters, BrowserExecuteDetails> {
  return {
    name: "browser_execute",
    label: "Browser Execute",
    description: "Execute JavaScript against the already-connected persistent browser CDP session. Screenshots attach automatically.",
    parameters,
    executionMode: "sequential",
    async execute(_toolCallId, args, signal, onUpdate) {
      if (!browser.session) throw new Error("Browser is not started");
      if (signal?.aborted) throw new Error("browser_execute cancelled");
      let output = "";
      const screenshots: Array<{ mimeType: "image/png" | "image/jpeg" | "image/webp"; data: string }> = [];
      const write = (...values: unknown[]) => {
        output += `${values.map(serializeConsole).join(" ")}\n`;
        const preview = truncate(output);
        onUpdate?.({
          content: [{ type: "text", text: preview }],
          details: { output: preview, result: "", screenshots: screenshots.length },
        });
      };
      const snippetConsole = Object.assign(Object.create(console), {
        log: write,
        error: write,
        warn: write,
        info: write,
        debug: write,
      });
      const unsubscribe = browser.onCallResult((method, params, result) => {
        if (method !== "Page.captureScreenshot" || typeof result.data !== "string") return;
        const format = typeof params.format === "string" ? params.format : "png";
        const mimeType = format === "jpeg" ? "image/jpeg" : format === "webp" ? "image/webp" : "image/png";
        screenshots.push({ mimeType, data: result.data });
      });
      try {
        const wrapped = new AsyncFunction("session", "console", args.code);
        const timeoutMs = Math.min(args.timeout ?? DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS);
        const result = await raceWithTimeout(wrapped(browser.session, snippetConsole), timeoutMs, signal);
        const serialized = serialize(result);
        await dumpScreenshots(screenshots);
        const text = [truncate(output).trimEnd(), serialized === "null" ? "" : `=> ${serialized}`]
          .filter(Boolean)
          .join("\n\n");
        return {
          content: [
            ...(text ? [{ type: "text" as const, text }] : []),
            ...screenshots.map((screenshot) => ({ type: "image" as const, ...screenshot })),
          ],
          details: { output: truncate(output), result: serialized, screenshots: screenshots.length },
        };
      } finally {
        unsubscribe();
      }
    },
  };
}

function serialize(value: unknown): string {
  if (value === undefined) return "null";
  try {
    return JSON.stringify(value, (_key, item) => typeof item === "bigint" ? item.toString() : item, 2) ?? "null";
  } catch {
    return JSON.stringify(String(value));
  }
}

function serializeConsole(value: unknown): string {
  return typeof value === "string" ? value : serialize(value);
}

function truncate(value: string): string {
  if (value.length <= MAX_TEXT_CHARS) return value;
  return `... ${value.length - MAX_TEXT_CHARS} earlier characters omitted ...\n${value.slice(-MAX_TEXT_CHARS)}`;
}

async function raceWithTimeout<T>(promise: Promise<T>, timeoutMs: number, signal?: AbortSignal): Promise<T> {
  return await new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`browser_execute timed out after ${timeoutMs}ms`)), timeoutMs);
    const abort = () => reject(new Error("browser_execute cancelled"));
    signal?.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    });
  });
}

async function dumpScreenshots(screenshots: Array<{ mimeType: string; data: string }>): Promise<void> {
  const directory = process.env.BROWSER_USE_JS_SCREENSHOT_DIR;
  if (!directory || screenshots.length === 0) return;
  await mkdir(directory, { recursive: true });
  const stamp = Date.now();
  await Promise.all(screenshots.map(async (screenshot, index) => {
    const extension = screenshot.mimeType === "image/jpeg" ? "jpg" : screenshot.mimeType === "image/webp" ? "webp" : "png";
    await writeFile(path.join(directory, `${stamp}-${String(index).padStart(3, "0")}.${extension}`), Buffer.from(screenshot.data, "base64"));
  }));
}
