import { createCodingTools } from '@earendil-works/pi-coding-agent';
import type { AgentTool } from '@earendil-works/pi-agent-core';

/** Pi's file and shell tools work independently of the browser/REPL process. */
export function researchTools(workspace: string, timeoutMs: number): AgentTool[] {
  return createCodingTools(workspace, {
    bash: {
      exposeSessionEnvironment: false,
      spawnHook: (context) => ({
        ...context,
        env: {
          PATH: process.env.PATH ?? '/usr/bin:/bin',
          LANG: 'en_US.UTF-8',
          HOME: workspace,
          TMPDIR: workspace,
        },
      }),
    },
  }).map((tool) => ({
    ...tool,
    executionMode: 'sequential',
    replay: 'never',
    execute: (id, args, signal, update) => {
      const input = args as { command: string; timeout?: number };
      return tool.execute(
        id,
        tool.name === 'bash'
          ? { ...input, timeout: Math.min(input.timeout ?? timeoutMs / 1000, timeoutMs / 1000) }
          : args,
        signal,
        update,
      );
    },
  }));
}
