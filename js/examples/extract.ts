import { Browser, BrowserUse, Type } from '@browser_use/js';

// A website becomes a typed dataset and a CSV, with source URLs for every row.
const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY ?? '' })
      : Browser.chromium(),
  workspace: process.env.WORKSPACE || './artifacts/extract',
  researchTools: true,
  log: 'pretty',
  highlightActions: true,
});
try {
  const result = await agent.run(
    `Visit ${process.env.START_URL || 'https://books.toscrape.com/'}.
    Collect the first 10 books in displayed order. Open their detail pages to verify title,
    price, currency and stock status. Keep missing values null; do not guess.
    Save books.csv in the workspace and publish a checkpoint after each verified book.
    Return the records and the CSV path.`,
    {
      schema: Type.Object({
        books: Type.Array(
          Type.Object({
            title: Type.String(),
            price: Type.Union([Type.Number(), Type.Null()]),
            currency: Type.Union([Type.String(), Type.Null()]),
            inStock: Type.Union([Type.Boolean(), Type.Null()]),
            url: Type.String(),
          }),
        ),
        csv: Type.String(),
      }),
      maxSteps: 40,
      timeoutMs: 300_000,
      maxCostUsd: 2,
    },
  );
  console.log(
    JSON.stringify(
      result.status === 'completed' ? result.output : (result.partial?.value ?? result.text),
      null,
      2,
    ),
  );
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  await agent.close();
}
