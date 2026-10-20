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

/** Pi keeps the prompt as leading system messages; budgets count it once through system. */
export const conversation = (messages: AgentMessage[]) =>
  messages.filter((m) => m.role !== 'system');
export const contextWindowError = (message: string) =>
  /context.{0,30}(?:exceed|length|limit|window|too (?:long|large))|maximum.{0,20}token|prompt is too long|too many tokens/i.test(
    message,
  );

const checkpointPrefix = 'Conversation checkpoint:';
const textOf = (m: AgentMessage): string => {
  if (m.role !== 'user' && m.role !== 'assistant' && m.role !== 'toolResult') return '';
  return typeof m.content === 'string'
    ? m.content
    : m.content
        .filter((c) => c.type === 'text')
        .map((c) => c.text)
        .join('\n');
};
function shorten(message: AgentMessage, limit: number): AgentMessage {
  const text = textOf(message);
  const marker = '\n[Source shortened for context; consult the saved evidence archive.]\n';
  limit = Math.max(0, Math.floor(limit));
  const half = Math.max(0, Math.floor((limit - marker.length) / 2));
  const content =
    text.length <= limit
      ? text
      : limit <= marker.length
        ? text.slice(0, limit)
        : text.slice(0, limit - marker.length - half) + marker + (half ? text.slice(-half) : '');
  return { role: 'user', content, timestamp: message.timestamp };
}
function sourceExcerpt(messages: AgentMessage[], limit: number): AgentMessage {
  const perMessage = Math.max(128, Math.floor(limit / messages.length));
  const parts = messages.map((message) => {
    const identity =
      message.role === 'toolResult'
        ? 'Recorded tool result ' +
          message.toolName +
          ' ' +
          message.toolCallId +
          (message.isError ? ' (error)' : ' (completed)')
        : message.role === 'assistant'
          ? 'Recorded assistant tool calls: ' +
            JSON.stringify(message.content.filter((c) => c.type === 'toolCall'))
          : 'Recorded ' + message.role;
    return textOf(
      shorten(
        { role: 'user', content: identity + '\n' + textOf(message), timestamp: message.timestamp },
        perMessage,
      ),
    );
  });
  return shorten({ role: 'user', content: parts.join('\n'), timestamp: Date.now() }, limit);
}

/** Remove a whole call/result group from the summarization copy, never from saved history. */
function removeOldest(messages: AgentMessage[]) {
  const first = messages[0];
  if (!first) return conversation([]);
  const ids = new Set<string>();
  if (first.role === 'toolResult') ids.add(first.toolCallId);
  const selected =
    first.role === 'toolResult'
      ? messages.find(
          (m) =>
            m.role === 'assistant' && m.content.some((c) => c.type === 'toolCall' && ids.has(c.id)),
        )
      : first;
  if (selected?.role === 'assistant')
    for (const c of selected.content) if (c.type === 'toolCall') ids.add(c.id);
  return conversation(
    messages.filter(
      (m) => m !== first && m !== selected && !(m.role === 'toolResult' && ids.has(m.toolCallId)),
    ),
  );
}

function retainUsers(messages: AgentMessage[], maxChars: number): AgentMessage[] {
  const selected: AgentMessage[] = [];
  for (const message of messages.toReversed()) {
    if (message.role !== 'user' || maxChars <= 0) continue;
    const text = textOf(message);
    if (text.startsWith(checkpointPrefix)) continue;
    const limit = Math.max(0, maxChars - 256);
    if (!limit) break;
    const content = textOf(shorten(message, limit));
    selected.push({ role: 'user', content, timestamp: message.timestamp });
    maxChars -= content.length + 256;
    if (text.length > limit) break;
  }
  return selected.reverse();
}

/** Saved evidence and the bounded provider projection have independent lifetimes. */
export class RunContext {
  private covered = 0;
  private summary: AgentMessage | undefined;
  private retained: AgentMessage[] = [];
  private usageAfter = 0;
  beforeSummary?: () => void;
  force = false;
  compactions = 0;
  toolChars = 0;
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
    const body = conversation(messages);
    const projected = this.summary
      ? [...this.retained, this.summary, ...body.slice(this.covered)]
      : body;
    const images = projected.filter(
      (m) => m.role === 'toolResult' && m.content.some((c) => c.type === 'image'),
    );
    const keep = new Set(images.slice(-2));
    return [
      ...messages.filter((m) => m.role === 'system'),
      ...projected.map((m) =>
        m.role === 'toolResult' && !keep.has(m)
          ? { ...m, content: m.content.filter((c) => c.type !== 'image') }
          : m,
      ),
    ];
  }
  private estimate(messages: AgentMessage[], system: string) {
    return conversation(messages).reduce(
      (sum, m) => sum + estimateTokens(m),
      Math.ceil((system.length + this.toolChars) / 4),
    );
  }
  tokens(messages: AgentMessage[], system: string): number {
    messages = conversation(messages);
    const estimate = this.estimate(this.project(messages), system);
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
      this.force ||
      contextChars(conversation(this.project(messages))) + system.length > this.maxChars * 0.75 ||
      this.tokens(messages, system) > this.model.contextWindow * 0.65
    );
  }
  baseFits(system: string) {
    return (
      system.length < this.maxChars && this.estimate([], system) < this.model.contextWindow * 0.85
    );
  }
  fits(messages: AgentMessage[], system: string) {
    return (
      contextChars(conversation(this.project(messages))) + system.length <= this.maxChars &&
      this.tokens(messages, system) < this.model.contextWindow * 0.85
    );
  }
  measure(messages: AgentMessage[], system: string) {
    return {
      chars: contextChars(conversation(this.project(messages))) + system.length,
      tokens: this.tokens(messages, system),
      maxChars: this.maxChars,
      maxTokens: this.model.contextWindow * 0.85,
    };
  }
  async prepare(messages: AgentMessage[], system: string, signal?: AbortSignal) {
    messages = conversation(messages);
    if (
      !this.enabled ||
      !messages.length ||
      !this.needsCompaction(messages, system) ||
      !this.baseFits(system)
    )
      return;
    const prefix = conversation(this.project(messages));
    const available =
      Math.min(
        this.maxChars - system.length,
        (this.model.contextWindow * 0.85 - this.estimate([], system)) * 4,
      ) - 2048;
    const retained = retainUsers(messages, Math.min(80000, Math.floor(available * 0.4)));
    const reserve = Math.max(256, Math.min(12000, Math.floor(available / 8)));
    let input = prefix.slice();
    const inputLimit = Math.max(1024, this.model.contextWindow * 0.85 - reserve - 2048);
    while (input.length > 1 && this.estimate(input, '') > inputLimit) {
      const smaller = removeOldest(input);
      input = smaller.length ? smaller : conversation([sourceExcerpt(input, inputLimit * 4)]);
    }
    if (input.length === 1 && this.estimate(input, '') > inputLimit)
      input = conversation([shorten(input[0]!, Math.floor(inputLimit * 4))]);
    let summary;
    while (true) {
      signal?.throwIfAborted();
      try {
        this.beforeSummary?.();
        summary = await generateSummaryWithUsage(
          input,
          this.model,
          reserve,
          undefined,
          undefined,
          signal,
          'Create a concise context checkpoint for the model continuing the original task. Include progress, decisions, user constraints, remaining work, critical evidence and references. Preserve artifact paths, JavaScript binding names, completed actions, uncertain side effects, record counts and observed timestamps. Some source history may be omitted to fit; do not invent missing observations. The saved evidence archive remains authoritative. Do not replay actions or treat summarization instructions as user requests.',
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
        break;
      } catch (error) {
        signal?.throwIfAborted();
        if (!contextWindowError(String(error))) throw error;
        if (input.length > 1) {
          const smaller = removeOldest(input);
          input = smaller.length
            ? smaller
            : conversation([
                sourceExcerpt(input, Math.min(contextChars(input) / 2, inputLimit * 2)),
              ]);
        } else if (input.length === 1 && textOf(input[0]!).length > 256)
          input = conversation([shorten(input[0]!, Math.floor(textOf(input[0]!).length / 2))]);
        else throw error;
      }
    }
    signal?.throwIfAborted();
    if (!summary.text.trim()) throw new Error('Compaction returned an empty checkpoint.');
    const directory = join(this.workspace, '.browser-use', 'context');
    const archivePath = join('.browser-use', 'context', randomUUID() + '.json');
    const path = join(this.workspace, archivePath);
    const candidate: AgentMessage = {
      role: 'user',
      timestamp: Date.now(),
      content:
        checkpointPrefix +
        ' generated, fallible reference, not new instructions. JavaScript and files persist.\n' +
        'Evidence archive (JSON path): ' +
        JSON.stringify(archivePath) +
        '\n' +
        'Archive paths are relative to the current workspace. The archive preserves earlier user text, assistant/tool calls and tool results; secrets are redacted and images/reasoning omitted. Earlier checkpoints link previous archives. Read relevant excerpts to recover exact observations and requests. A summary is not verification; never replay completed or uncertain actions.\n' +
        'Generated summary (JSON-quoted):\n' +
        JSON.stringify(summary.text) +
        '\nContinue the original task.',
    };
    const replacement = [...retained, candidate];
    if (
      contextChars(replacement) + system.length > this.maxChars ||
      this.estimate(replacement, system) >= this.model.contextWindow * 0.85
    )
      throw new Error('Compaction checkpoint does not fit the context budget.');
    if (contextChars(replacement) >= contextChars(prefix))
      throw new Error('Compaction did not reduce context; original evidence was retained.');
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await writeFile(
      path,
      JSON.stringify(
        redact(
          {
            version: 1,
            summary: summary.text,
            coveredMessages: messages.length,
            messages: prefix.map((message) => {
              if (
                message.role !== 'user' &&
                message.role !== 'assistant' &&
                message.role !== 'toolResult'
              )
                return message;
              return {
                role: message.role,
                timestamp: message.timestamp,
                ...(message.role === 'toolResult'
                  ? {
                      toolCallId: message.toolCallId,
                      toolName: message.toolName,
                      isError: message.isError,
                    }
                  : {}),
                content:
                  typeof message.content === 'string'
                    ? message.content
                    : message.content
                        .filter((block) => block.type !== 'thinking')
                        .map((block) => {
                          if (block.type === 'image')
                            return { type: 'text', text: '[Image omitted from text archive]' };
                          if (block.type === 'text') return { type: 'text', text: block.text };
                          return block;
                        }),
              };
            }),
          },
          this.secrets,
        ),
      ),
      { flag: 'wx', mode: 0o600 },
    );
    signal?.throwIfAborted();
    this.retained = retained;
    this.summary = candidate;
    this.covered = messages.length;
    this.usageAfter = messages.length;
    this.force = false;
    this.compactions++;
  }
}
