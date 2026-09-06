import { lstat, mkdir, open, readdir, readFile, rename, rm } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { AgentMessage } from '@earendil-works/pi-agent-core';
import type { Usage } from '@earendil-works/pi-ai';

export interface SessionHistory {
  version: 1;
  model: string;
  messages: AgentMessage[];
  usage: Usage;
  runs: number;
}
export interface WorkspaceFile {
  path: string;
  relativePath: string;
  size: number;
  modifiedAt: string;
}

/** JSON-safe observational copy. Non-JSON application metadata is labeled, never executed as code. */
export function redact<T>(value: T, secrets: readonly string[]): T {
  const ancestors: object[] = [];
  return JSON.parse(
    JSON.stringify(value, function (_key, item: unknown): unknown {
      if (typeof item === 'string')
        return secrets.reduce(
          (text, secret) => (secret ? text.split(secret).join('[REDACTED]') : text),
          item,
        );
      if (typeof item === 'bigint') return `${item}n`;
      if (typeof item === 'function' || typeof item === 'symbol') return '[Non-JSON metadata]';
      if (item && typeof item === 'object') {
        while (ancestors.length && ancestors.at(-1) !== this) ancestors.pop();
        if (ancestors.includes(item)) return '[Circular metadata]';
        ancestors.push(item);
      }
      return item;
    }),
  ) as T;
}

/** Same-directory atomic replacement; mode 0600. Does not serialize the V8 heap or browser. */
export async function saveHistory(
  path: string,
  history: SessionHistory,
  secrets: readonly string[] = [],
) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temp = `${path}.${randomUUID()}.tmp`;
  try {
    const file = await open(temp, 'wx', 0o600);
    try {
      await file.writeFile(JSON.stringify(redact(history, secrets)));
      await file.sync();
    } finally {
      await file.close();
    }
    await rename(temp, path);
  } finally {
    await rm(temp, { force: true });
  }
}

export async function loadHistory(path: string, model: string): Promise<SessionHistory> {
  const info = await lstat(path);
  if (!info.isFile() || info.size > 64_000_000)
    throw new Error('History must be a regular file no larger than 64 MB.');
  const data = JSON.parse(await readFile(path, 'utf8')) as SessionHistory;
  if (
    !data ||
    typeof data !== 'object' ||
    data.version !== 1 ||
    data.model !== model ||
    !Array.isArray(data.messages) ||
    !Number.isSafeInteger(data.runs) ||
    data.runs < 0
  )
    throw new Error('Unsupported history version, model mismatch, or invalid history.');
  for (const message of data.messages) {
    if (
      !message ||
      !['user', 'assistant', 'toolResult'].includes(message.role) ||
      !('content' in message) ||
      !(typeof message.content === 'string' || Array.isArray(message.content))
    )
      throw new Error('Invalid history message.');
    if (
      message.role === 'assistant' &&
      (!message.usage || !message.model || !message.provider || !message.api)
    )
      throw new Error('Invalid assistant history message.');
    if (message.role !== 'user' && !Array.isArray(message.content))
      throw new Error('Invalid non-user message content.');
    if (
      Array.isArray(message.content) &&
      message.content.some(
        (block) => !block || typeof block !== 'object' || typeof block.type !== 'string',
      )
    )
      throw new Error('Invalid message content block.');
    if (message.role === 'toolResult' && (!message.toolCallId || !message.toolName))
      throw new Error('Invalid tool history message.');
  }
  const validUsage = (value: Usage): boolean =>
    !!value &&
    ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'].every((k) => {
      const n = value[k as keyof Usage];
      return typeof n === 'number' && Number.isFinite(n) && n >= 0;
    }) &&
    !!value.cost &&
    ['input', 'output', 'cacheRead', 'cacheWrite', 'total'].every((k) => {
      const n = value.cost[k as keyof Usage['cost']];
      return typeof n === 'number' && Number.isFinite(n) && n >= 0;
    });
  if (
    !validUsage(data.usage) ||
    data.messages.some((m) => m.role === 'assistant' && !validUsage(m.usage))
  )
    throw new Error('Invalid history usage.');
  return data;
}

/** Bounded inventory. Symlinks are excluded; files stay ordinary files owned by the caller. */
export async function workspaceFiles(workspace: string): Promise<WorkspaceFile[]> {
  const result: WorkspaceFile[] = [];
  const visit = async (directory: string, depth: number) => {
    if (depth > 16) throw new Error('Workspace inventory exceeds 16 directory levels.');
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (
        entry.name === '.browser-use' ||
        entry.name === 'node_modules' ||
        entry.name === '.git' ||
        entry.isSymbolicLink()
      )
        continue;
      const path = join(directory, entry.name);
      if (entry.isDirectory()) await visit(path, depth + 1);
      else if (entry.isFile()) {
        const info = await lstat(path);
        if (!info.isFile()) continue;
        result.push({
          path,
          relativePath: relative(workspace, path),
          size: info.size,
          modifiedAt: info.mtime.toISOString(),
        });
        if (result.length > 10_000) throw new Error('Workspace inventory exceeds 10000 files.');
      }
    }
  };
  await visit(workspace, 0);
  return result.sort((a, b) => a.relativePath.localeCompare(b.relativePath));
}
