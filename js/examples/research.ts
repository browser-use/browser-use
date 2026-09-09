import { Browser, BrowserUse } from '@browser_use/js';

const task = process.argv.slice(2).join(' ');
if (!task) throw new Error('Usage: node examples/research.ts "Your browser task"');
const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY ?? '' })
      : process.env.BROWSER_CDP_URL
        ? { cdpUrl: process.env.BROWSER_CDP_URL }
        : Browser.chromium(),
  workspace: process.env.WORKSPACE || './artifacts/research',
});
const controller = new AbortController();
const cancel = () => controller.abort();
process.once('SIGINT', cancel);
try {
  const result = await agent.run(task, {
    signal: controller.signal,
    maxSteps: 30,
    timeoutMs: 300_000,
    maxCostUsd: 2,
    onEvent(event) {
      if (event.type === 'tool_execution_start') process.stderr.write(`→ ${event.toolName}\n`);
      if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta')
        process.stderr.write(event.assistantMessageEvent.delta);
    },
  });
  console.log(JSON.stringify(result, null, 2));
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  process.removeListener('SIGINT', cancel);
  await agent.close();
}
