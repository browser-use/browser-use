import { stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { Browser, BrowserUse, Type } from '@browser_use/pi';

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
  const csvPath = resolve(agent.workspace, 'books.csv');
  const result = await agent.run(
    `Visit ${process.env.START_URL || 'https://books.toscrape.com/'}.
    Collect the first 10 books in displayed order. Open their detail pages to verify title,
    price, currency and stock status. Keep missing values null; do not guess.
    Save books.csv in the workspace and publish a checkpoint after each verified book.
    Return the records and csvPath: the absolute path to that file, not CSV contents.`,
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
        csvPath: Type.Literal(csvPath, {
          description: 'Absolute path to the saved books.csv file.',
        }),
      }),
      maxSteps: 40,
      timeoutMs: 300_000,
      maxCostUsd: 2,
    },
  );
  if (result.status === 'completed') {
    const file = await stat(csvPath);
    if (!file.isFile() || file.size === 0)
      throw new Error(`CSV file is empty or not a file: ${csvPath}`);
  }
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
