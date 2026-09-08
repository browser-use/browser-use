import type { AgentMessage, StreamFn } from '@earendil-works/pi-agent-core';
import type { Api, Model, Usage } from '@earendil-works/pi-ai';
import { estimateTokens, generateSummaryWithUsage } from '@earendil-works/pi-coding-agent';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { redact } from './history.js';

/** Wire metadata and encrypted reasoning are not ordinary text tokens. */
export function contextChars(messages: AgentMessage[]): number {
  return JSON.stringify(messages, (key, value: unknown) => {
    if (key === 'thinkingSignature' || key === 'textSignature') return undefined;
    if (value && typeof value === 'object' && 'role' in value && value.role === 'toolResult') {
      const { details: _details, ...message } = value as Record<string, unknown>;
      return message;
    }
    if (value && typeof value === 'object' && 'type' in value && value.type === 'image')
      return { type: 'image' };
    return value;
  }).length;
}

/** A provider projection; the original transcript remains available for accounting and audit. */
export class RunContext {
  private covered = 0;
  private summary: AgentMessage | undefined;
  private usageAfter = 0;
  compactions = 0;
  usage: Usage[] = [];
  constructor(
    private model: Model<Api>,
    private stream: StreamFn,
    private workspace: string,
    private maxChars: number,
    private enabled: boolean,
    private secrets: string[] = [],
  ) {}
  project(messages: AgentMessage[]): AgentMessage[] {
    const projected = this.summary ? [this.summary, ...messages.slice(this.covered)] : messages;
    const images = projected.filter(
      (m) => m.role === 'toolResult' && m.content.some((c) => c.type === 'image'),
    );
    const keep = new Set(images.slice(-2));
    return projected.map((m) =>
      m.role === 'toolResult' && !keep.has(m)
        ? { ...m, content: m.content.filter((c) => c.type !== 'image') }
        : m,
    );
  }
  tokens(messages: AgentMessage[], system: string): number {
    const projected = this.project(messages);
    const estimate = projected.reduce(
      (sum, m) => sum + estimateTokens(m),
      Math.ceil(system.length / 4),
    );
    for (let i = messages.length - 1; i >= this.usageAfter; i--) {
      const m = messages[i]!;
      if (
        m.role === 'assistant' &&
        !['error', 'aborted'].includes(m.stopReason) &&
        m.usage.totalTokens > 0
      )
        return Math.max(
          estimate,
          m.usage.totalTokens +
            messages.slice(i + 1).reduce((sum, t) => sum + estimateTokens(t), 0),
        );
    }
    return estimate;
  }
  needsCompaction(messages: AgentMessage[], system: string) {
    return (
      contextChars(this.project(messages)) + system.length > this.maxChars * 0.75 ||
      this.tokens(messages, system) > this.model.contextWindow * 0.65
    );
  }
  fits(messages: AgentMessage[], system: string) {
    return (
      contextChars(this.project(messages)) + system.length <= this.maxChars &&
      this.tokens(messages, system) < this.model.contextWindow * 0.85
    );
  }
  async prepare(messages: AgentMessage[], system: string, signal?: AbortSignal) {
    if (!this.enabled || !this.needsCompaction(messages, system)) return;
    // Keep the last two complete assistant/tool groups. Never orphan a tool result.
    const starts = messages.flatMap((m, i) =>
      m.role === 'assistant' && i >= this.covered ? [i] : [],
    );
    const cut = starts.at(-2);
    if (cut === undefined || cut <= this.covered) return;
    const prefix = [...(this.summary ? [this.summary] : []), ...messages.slice(this.covered, cut)];
    const summary = await generateSummaryWithUsage(
      prefix,
      this.model,
      12_000,
      undefined,
      undefined,
      signal,
      'Summarize only the source conversation inside <conversation>. These summarization instructions are not user requests or constraints of the task; never record them as such. Preserve exact user constraints, artifact/checkpoint paths, JS binding names, completed actions and uncertain side effects, record counts, source URLs and observed timestamps, conflicting evidence, blockers and the next bounded step. Do not claim attempted means verified. Never suggest replaying uncertain actions.',
      undefined,
      'low',
      async (...args) => {
        const stream = await this.stream(...args);
        void stream
          .result()
          .then((message) => {
            this.usage.push(message.usage);
          })
          .catch(() => {});
        return stream;
      },
    );
    signal?.throwIfAborted();
    if (!summary.text.trim()) throw new Error('Compaction returned an empty checkpoint.');
    const directory = join(this.workspace, '.browser-use', 'context');
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const path = join(directory, `${randomUUID()}.json`);
    await writeFile(
      path,
      JSON.stringify(
        redact({ version: 1, summary: summary.text, coveredMessages: cut }, this.secrets),
      ),
      { flag: 'wx', mode: 0o600 },
    );
    // Pin user messages exactly; a summarizer cannot silently remove a restriction or follow-up.
    const users = messages.slice(0, cut).filter((m) => m.role === 'user');
    const text = `Conversation checkpoint: generated, fallible reference, not new instructions. JavaScript and files persist. Full checkpoint: ${path}\nGenerated summary (JSON-quoted):\n${JSON.stringify(summary.text)}\nOriginal user requests (authoritative over the generated summary):\n${JSON.stringify(users)}\nContinue the original task. Any instruction to produce a summary belongs to the summarization process, not the original task.`;
    const candidate: AgentMessage = { role: 'user', content: text, timestamp: Date.now() };
    if (contextChars([candidate, ...messages.slice(cut)]) >= contextChars(this.project(messages)))
      throw new Error('Compaction did not reduce context; original evidence was retained.');
    this.summary = candidate;
    this.covered = cut;
    this.usageAfter = messages.length;
    this.compactions++;
  }
}
