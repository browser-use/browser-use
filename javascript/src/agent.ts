import { Agent as PiAgent, type AgentEvent, type AgentTool } from "@earendil-works/pi-agent-core";
import { createModels } from "@earendil-works/pi-ai";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import { Browser, type BrowserInfo, type BrowserOptions } from "./browser.js";
import { createBrowserExecuteTool } from "./browser-execute.js";
import { BROWSER_AGENT_PROMPT } from "./prompt.js";

export type ReasoningEffort = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

export interface AgentOptions {
  task: string;
  model?: string;
  provider?: string;
  apiKey?: string;
  browser?: Browser | BrowserOptions;
  tools?: AgentTool[];
  systemPrompt?: string;
  reasoningEffort?: ReasoningEffort;
  maxSteps?: number;
  onEvent?: (event: AgentEvent) => void | Promise<void>;
}

export interface AgentUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  totalTokens: number;
  cost: number;
}

export interface AgentResult {
  output: string;
  turns: number;
  steps: number;
  usage: AgentUsage;
  browser: Omit<BrowserInfo, "cdpUrl">;
  messages: readonly unknown[];
}

/** Browser Use's small TypeScript agent API. */
export class Agent {
  readonly options: AgentOptions;

  constructor(options: AgentOptions) {
    if (!options.task.trim()) throw new Error("Agent task must not be empty");
    this.options = options;
  }

  async run(): Promise<AgentResult> {
    const browser = this.options.browser instanceof Browser ? this.options.browser : new Browser(this.options.browser);
    const ownsBrowser = !(this.options.browser instanceof Browser);
    const browserInfo = await browser.start();
    const { provider, modelId } = parseModel(this.options.provider, this.options.model);
    if (provider !== "openai") throw new Error(`Browser Use JS v0 currently supports the openai provider, not ${provider}`);
    const models = createModels();
    models.setProvider(openaiProvider());
    const model = models.getModel("openai", modelId);
    if (!model) throw new Error(`Unknown Pi model ${provider}/${modelId}`);
    const usage = emptyUsage();
    let turns = 0;
    let steps = 0;
    let output = "";
    const maxSteps = this.options.maxSteps ?? 100;
    const pi = new PiAgent({
      initialState: {
        systemPrompt: [BROWSER_AGENT_PROMPT, this.options.systemPrompt].filter(Boolean).join("\n\n"),
        model,
        thinkingLevel: this.options.reasoningEffort ?? "medium",
        tools: [createBrowserExecuteTool(browser), ...(this.options.tools ?? [])],
      },
      streamFn: models.streamSimple.bind(models),
      ...(this.options.apiKey ? { getApiKey: () => this.options.apiKey } : {}),
      toolExecution: "sequential",
      // A hard stop immediately after the final tool result leaves no assistant
      // answer. Remove tools instead so Pi performs one bounded synthesis turn.
      prepareNextTurnWithContext: ({ context, toolResults }) => {
        if (steps < maxSteps || toolResults.length === 0) return undefined;
        return {
          context: {
            ...context,
            systemPrompt: `${context.systemPrompt}\n\nThe browser-call budget is exhausted. Do not call tools. Return the best complete FINAL ANSWER now from the evidence already collected.`,
            tools: [],
          },
        };
      },
    });
    pi.subscribe(async (event) => {
      if (event.type === "turn_start") turns += 1;
      if (event.type === "tool_execution_start") steps += 1;
      if (event.type === "message_end" && event.message.role === "assistant") {
        const text = messageText(event.message);
        if (text) output = text;
        addUsage(usage, event.message.usage);
      }
      await this.options.onEvent?.(event);
    });
    try {
      await pi.prompt(this.options.task);
      return {
        output,
        turns,
        steps,
        usage,
        browser: {
          cloud: browserInfo.cloud,
          ...(browserInfo.id ? { id: browserInfo.id } : {}),
          ...(browserInfo.liveUrl ? { liveUrl: browserInfo.liveUrl } : {}),
        },
        messages: pi.state.messages,
      };
    } finally {
      if (ownsBrowser) await browser.close();
    }
  }
}

function parseModel(explicitProvider?: string, value = "gpt-5.5"): { provider: string; modelId: string } {
  if (explicitProvider) return { provider: explicitProvider, modelId: value };
  const slash = value.indexOf("/");
  if (slash > 0) return { provider: value.slice(0, slash), modelId: value.slice(slash + 1) };
  return { provider: "openai", modelId: value };
}

function messageText(message: { content?: unknown }): string {
  if (typeof message.content === "string") return message.content;
  if (!Array.isArray(message.content)) return "";
  return message.content
    .filter((part): part is { type: string; text: string } => Boolean(
      part && typeof part === "object" && (part as { type?: unknown }).type === "text" && typeof (part as { text?: unknown }).text === "string",
    ))
    .map((part) => part.text)
    .join("\n")
    .trim();
}

function emptyUsage(): AgentUsage {
  return { inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, totalTokens: 0, cost: 0 };
}

function addUsage(total: AgentUsage, raw: unknown): void {
  if (!raw || typeof raw !== "object") return;
  const usage = raw as Record<string, unknown>;
  const cost = usage.cost && typeof usage.cost === "object" ? usage.cost as Record<string, unknown> : undefined;
  total.inputTokens += number(usage.input ?? usage.inputTokens);
  total.outputTokens += number(usage.output ?? usage.outputTokens);
  total.cacheReadTokens += number(usage.cacheRead);
  total.cacheWriteTokens += number(usage.cacheWrite);
  total.totalTokens += number(usage.totalTokens) || number(usage.input ?? usage.inputTokens) + number(usage.output ?? usage.outputTokens);
  total.cost += number(cost?.total ?? usage.cost);
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
