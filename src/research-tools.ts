import {
  createCodingTools,
  createWriteTool,
  type WriteToolInput,
} from '@earendil-works/pi-coding-agent';
import type { AgentTool } from '@earendil-works/pi-agent-core';
import { mkdir, realpath, writeFile } from 'node:fs/promises';
import { isAbsolute, relative, sep } from 'node:path';
async function writeWithLocation(
  workspace: string,
  id: string,
  args: WriteToolInput,
  signal?: AbortSignal,
) {
  let writtenPath: string | undefined;
  const writer = createWriteTool(workspace, {
    operations: {
      mkdir: async (path) => {
        await mkdir(path, { recursive: true });
      },
      writeFile: async (path, content) => {
        await writeFile(path, content, 'utf8');
        writtenPath = path;
      },
    },
  });
  const result = await writer.execute(id, args, signal);
  try {
    const [root, file] = await Promise.all([realpath(workspace), realpath(writtenPath!)]);
    const path = relative(root, file);
    if (path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path)) return result;
    result.content.push({
      type: 'text',
      text: `Delivery warning: the write succeeded outside workspace ${JSON.stringify(workspace)} at ${JSON.stringify(file)}. BrowserUse.files() does not include this path. If this is a deliverable, save a copy inside workspace and reference that copy. The existing file has not been moved or rewritten.`,
    });
  } catch {
    result.content.push({
      type: 'text',
      text: 'Delivery warning: the write succeeded, but its location could not be verified. Check the saved file and workspace before claiming delivery.',
    });
  }
  return result;
}
export function researchTools(
  workspace: string,
  timeoutMs: number,
  shellEnv: Record<string, string> = {},
  defaultTimeoutMs = timeoutMs,
): AgentTool[] {
  return createCodingTools(workspace, {
    bash: {
      exposeSessionEnvironment: false,
      spawnHook: (context) => ({
        ...context,
        env: {
          PATH: process.env.PATH ?? '/usr/bin:/bin',
          LANG: 'en_US.UTF-8',
          ...Object.fromEntries(
            Object.entries(process.env).filter(
              ([name, value]) =>
                value !== undefined &&
                [
                  'ProgramFiles',
                  'ProgramFiles(x86)',
                  'PROGRAMFILES',
                  'PROGRAMFILES(X86)',
                  'SYSTEMROOT',
                  'SystemRoot',
                ].includes(name),
            ),
          ),
          HOME: workspace,
          TMPDIR: workspace,
          ...shellEnv,
        },
      }),
    },
  }).map((tool) => ({
    ...tool,
    executionMode: 'sequential',
    replay: 'never',
    execute: (id, args, signal, update) => {
      if (tool.name === 'write')
        return writeWithLocation(workspace, id, args as WriteToolInput, signal);
      const input = args as {
        command: string;
        timeout?: number;
      };
      return tool.execute(
        id,
        tool.name === 'bash'
          ? {
              ...input,
              timeout: Math.min(input.timeout ?? defaultTimeoutMs / 1000, timeoutMs / 1000),
            }
          : args,
        signal,
        update,
      );
    },
  }));
}
