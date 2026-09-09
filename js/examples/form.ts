import { Browser, BrowserUse, Type } from '@browser_use/pi';

const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY ?? '' })
      : Browser.chromium(),
  workspace: process.env.WORKSPACE || './artifacts/form',
  highlightActions: true,
  log: 'pretty',
});
try {
  const result = await agent.run(
    `Open ${process.env.START_URL || 'https://httpbin.org/forms/post'}.
    Fill the test pizza form: customer Avery Example, phone 202-555-0142,
    email avery@example.com, medium pizza, cheese and mushroom toppings,
    delivery time 18:30, comment "Synthetic Browser Use Pi demo".
    Submit this demo form once. Inspect the response and verify the submitted fields.
    If the submission result is ambiguous, report that instead of submitting again.`,
    {
      schema: Type.Object({
        submitted: Type.Boolean(),
        verifiedFields: Type.Record(Type.String(), Type.String()),
        mismatches: Type.Array(Type.String()),
      }),
      maxSteps: 20,
      timeoutMs: 180_000,
      maxCostUsd: 1,
    },
  );
  console.log(result.status, result.status === 'completed' ? result.output : result.text);
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  await agent.close();
}
