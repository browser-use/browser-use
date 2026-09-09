import { Browser, BrowserUse, Type, exportRecording } from '@browser_use/pi';
import { join } from 'node:path';

const url = process.env.START_URL;
if (!url) throw new Error('Set START_URL to your staging site.');
const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY ?? '' })
      : Browser.chromium(),
  workspace: process.env.WORKSPACE || './artifacts/qa',
  researchTools: true,
  recording: { intervalMs: 1000, maxFrames: 240 },
  highlightActions: true,
  log: 'pretty',
});
try {
  const result = await agent.run(
    `QA ${url}. Test navigation, search, empty/invalid inputs,
    keyboard access and layout at desktop and narrow widths. Inspect actual viewport dimensions;
    if resizing is unavailable, say so. Use synthetic data. Do not purchase or send messages.
    For every reproducible issue save a screenshot and report steps, expected vs actual behavior,
    severity and URL. Distinguish a product bug from an access failure. Keep a coverage ledger.
    Publish findings.json with checkpoint(..., {partial:true}) after each issue so a time limit
    still returns useful findings. Save a readable report.md.`,
    {
      schema: Type.Object({
        tested: Type.Array(Type.String()),
        bugs: Type.Array(
          Type.Object({
            title: Type.String(),
            severity: Type.Union([
              Type.Literal('low'),
              Type.Literal('medium'),
              Type.Literal('high'),
            ]),
            steps: Type.Array(Type.String()),
            expected: Type.String(),
            actual: Type.String(),
            url: Type.String(),
            screenshot: Type.String(),
          }),
        ),
        blocked: Type.Array(Type.String()),
      }),
      maxSteps: 30,
      timeoutMs: 180_000,
      maxCostUsd: 2,
    },
  );
  console.log(
    result.status,
    JSON.stringify(
      result.status === 'completed' ? result.output : (result.partial?.value ?? result.text),
      null,
      2,
    ),
  );
  if (result.recordingPath) {
    // Export the actual frames without repeating browser actions. Requires ffmpeg + local Chrome.
    console.log(
      await exportRecording(result.recordingPath, {
        output: join(agent.workspace, `qa-${result.runId}.gif`),
        format: 'gif',
        maxFrames: 24,
      }),
    );
  }
} finally {
  await agent.close();
}
