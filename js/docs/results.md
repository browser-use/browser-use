# Typed results

Define the shape your application needs. The model delivers it through a validated `finish` tool. Invalid arguments are returned to the model as a repairable error.

```ts
import { BrowserUse, Type } from '@browser-use/next';

const schema = Type.Object({
  products: Type.Array(
    Type.Object({
      name: Type.String(),
      price: Type.Number({ minimum: 0 }),
      source: Type.String(),
    }),
  ),
  missing: Type.Array(Type.String()),
});

const agent = await BrowserUse.create({ model: 'openai/gpt-5.5' });
try {
  const result = await agent.run('Compare three travel chargers. Include price and source URL.', {
    schema,
  });
  if (result.status === 'completed') {
    // Inferred: { products: { name: string; price: number; source: string }[]; missing: string[] }
    console.table(result.output.products);
  }
} finally {
  await agent.close();
}
```

## Completion is an explicit event

`completed` means the `finish` tool accepted a value matching your schema. It does **not** mean an independent judge verified every factual claim. Use source fields, application checks, and an outcome evaluator for consequential workflows.

If the model merely writes “I will do that” and stops, the run is `incomplete`. A budget limit, timeout, cancellation, or model error does not become a successful result.

| Status          | Meaning                                                   |
| --------------- | --------------------------------------------------------- |
| `completed`     | A schema-valid result was delivered                       |
| `incomplete`    | Model stopped without calling `finish`                    |
| `max_steps`     | Maximum model turns reached                               |
| `timeout`       | Run time limit reached                                    |
| `cancelled`     | Caller cancelled or closed the session                    |
| `cost_limit`    | Estimated cost crossed the threshold                      |
| `context_limit` | Projected context exceeded the configured character limit |
| `error`         | Model, callback, or runtime failure prevented completion  |

Only `completed` has an `output` property in the TypeScript union. Other statuses preserve available assistant text and may include an error.

## Files are first-class outputs

The browser tool has `artifact(name, data)`. Large tool outputs are captured into files automatically and returned as bounded text plus the file path. Local downloads use `Browser.setDownloadBehavior`; remote files require the browser provider’s download API or a fetch of an observed URL.

Use a schema containing artifact paths when the deliverable is a file. The helper refuses overwriting an existing filename. Artifacts remain after `close()`; your application owns retention and deletion.

## Deliver large tables without regenerating them

Save the extracted JavaScript value directly, then return its path. Asking the model to rewrite hundreds of records into `finish` introduces another opportunity to omit or invent a row. In the hard benchmark, one task extracted 125 jobs, then delivered 126 after regenerating the JSON.

```ts
const result = await agent.run(
  'Extract the listings into a JavaScript array. Save that exact array with artifact() as JSON. Return the artifact path and record count; do not rewrite the rows in your answer.',
  {
    schema: Type.Object({
      path: Type.String(),
      count: Type.Integer({ minimum: 0 }),
    }),
  },
);
```

The browser tool can write `await artifact('listings.json', JSON.stringify(rows, null, 2))`. Your application should read the file from its trusted workspace, validate each record, and compare the count against the source. This preserves the extracted bytes; it does not independently prove that extraction covered every listing. This recipe has not been evaluated as a separate benchmark arm.
