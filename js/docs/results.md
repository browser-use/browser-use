# Typed results

Define the shape your application needs. The model delivers it through `finish` or `finish_from_js`; both validate against your schema. Invalid arguments are returned to the model as a repairable error.

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

`completed` means a delivery tool accepted a value matching your schema. It does **not** mean an independent judge verified every factual claim. Use source fields, application checks, and an outcome evaluator for consequential workflows.

If the model stops without delivery, the SDK gives it one delivery-only repair turn within the original budgets. If that fails, the run is `incomplete`. A budget limit, timeout, cancellation, or model error does not become a successful result.

| Status          | Meaning                                                   |
| --------------- | --------------------------------------------------------- |
| `completed`     | A schema-valid result was delivered                       |
| `incomplete`    | Model stopped without validated delivery                  |
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

The model can call `finish_from_js({ expression: 'rows' })` to return an existing array directly. The SDK evaluates the expression once in the persistent REPL, transfers its JSON value to the host, validates your schema, and returns it as `result.output`. No rows pass through the model's generated answer or the truncated observation channel.

```ts
const result = await agent.run('Extract every listing with its source URL.', {
  schema: Type.Array(Type.Object({ title: Type.String(), source: Type.String() })),
});
```

For the default string schema, the model uses `finish_from_js({ expression: 'JSON.stringify(rows)' })`. For a structured schema, it returns the matching value directly. Invalid schema values, cycles, and unsupported JSON values produce a repairable tool error. Delivery is limited to 16 MB of serialized JSON; use an artifact path for larger files. Dates and custom `toJSON` methods follow normal JSON serialization semantics.

This removes a demonstrated delivery failure: the baseline extracted 125 jobs, then regenerated 126. It does not prove source coverage or factual correctness. Check record counts, filters, required fields, and source URLs before delivery. The SDK never automatically replays an expression after a timeout; expressions are executable JavaScript and may have side effects.
