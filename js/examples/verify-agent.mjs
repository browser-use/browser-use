/** Autonomous model smoke against a local fixture; model-provider charges apply. */
import { resolve } from 'node:path';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { BrowserUse, Type } from '@browser-use/next';
import { startFixture } from './fixture.mjs';

const model = process.env.MODEL;
if (!model)
  throw new Error('Set MODEL=provider/model explicitly. This example makes paid model requests.');
const fixture = await startFixture();
const workspace = resolve('artifacts', `autonomous-${Date.now()}`);
const task = `Open ${fixture.url}. Find the charger priced below $40. Search for that product, choose Express shipping, and click Save selection exactly once. Return the product name, numeric price, and the resulting saved status. Verify the page state before finishing.`;
const events = [];
let agent;
console.log(
  `Autonomous fixture smoke — ${model}\nReal model decisions; synthetic local browser data. Provider charges apply.\n`,
);
try {
  agent = await BrowserUse.create({
    model,
    workspace,
    reasoning: 'off',
  });
  const result = await agent.run(task, {
    schema: Type.Object({ product: Type.String(), price: Type.Number(), status: Type.String() }),
    maxSteps: 12,
    timeoutMs: 180_000,
    onEvent(event) {
      if (['message_end', 'tool_execution_end', 'turn_end'].includes(event.type))
        events.push(structuredClone(event));
      if (event.type === 'tool_execution_start') console.log(`→ ${event.toolName}`);
      if (event.type === 'tool_execution_end')
        console.log(
          `${event.isError ? 'ERROR' : 'OK'} ${event.toolName}: ${JSON.stringify(event.result.content).slice(0, 1400)}`,
        );
      if (event.type === 'message_end' && event.message.role === 'assistant')
        console.log(
          event.message.content
            .filter((c) => c.type === 'text')
            .map((c) => c.text)
            .join(''),
        );
    },
  });
  console.log('Run status:', result.status, result.error ?? '', result.text);
  let pageState = {};
  try {
    const observed = await agent.execute(
      "console.log(JSON.stringify({status:await page.text({role:'status'}),shipping:await page.evaluate(() => document.querySelector('#shipping').value),visible:await page.evaluate(() => Array.from(document.querySelectorAll('article:not([hidden]) h2'), el => el.textContent))}))",
    );
    pageState = JSON.parse(observed.text);
  } catch (error) {
    pageState = { verificationError: error.message };
  }
  const checks = {
    completed: result.status === 'completed',
    product: result.output?.product === 'Atlas',
    price: result.output?.price === 29,
    status: result.output?.status === 'Saved 1 time(s)',
    savedOnce: pageState.status === 'Saved 1 time(s)',
    express: pageState.shipping === 'Express',
    filtered: JSON.stringify(pageState.visible) === '["Atlas"]',
  };
  await agent.execute("await artifact('final-page.jpg',await page.screenshot({quality:85}))");
  const fixtureHash = createHash('sha256')
    .update(await readFile(new URL('./fixture.mjs', import.meta.url)))
    .digest('hex');
  const report = {
    kind: 'autonomous-local-smoke',
    task,
    fixtureHash,
    model,
    node: process.version,
    configuration: { maxSteps: 12, timeoutMs: 180000, reasoning: 'off', contextWindow: 32768 },
    result,
    pageState,
    checks,
    passed: Object.values(checks).every(Boolean),
  };
  await writeFile(resolve(workspace, 'report.json'), JSON.stringify(report, null, 2));
  await writeFile(resolve(workspace, 'events.json'), JSON.stringify(events, null, 2));
  console.log(JSON.stringify(report, null, 2));
  console.log(`Evidence: ${workspace}`);
  if (!report.passed) process.exitCode = 1;
} finally {
  await agent?.close();
  await fixture.close();
}
