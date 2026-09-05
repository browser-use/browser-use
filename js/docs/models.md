# Models & providers

Choose the model explicitly. Pi handles provider protocols, authentication, reasoning, tool calls, and images.

```js
const agent = await BrowserUse.create({
  model: 'anthropic/claude-sonnet-4-6',
  reasoning: 'medium',
});
```

## One identifier, many providers

The format is `provider/model-id`. Everything after the first slash belongs to the model ID, so OpenRouter IDs with slashes work.

| Provider  | Example                       | Environment variable |
| --------- | ----------------------------- | -------------------- |
| OpenAI    | `openai/gpt-5.5`              | `OPENAI_API_KEY`     |
| Anthropic | `anthropic/claude-sonnet-4-6` | `ANTHROPIC_API_KEY`  |
| Google    | `google/gemini-2.5-pro`       | `GEMINI_API_KEY`     |

These are explicit examples, not moving “latest” aliases. Availability depends on the provider and your account. A model present in Pi's catalog is not a claim that it has been tested with this SDK.

## Discover the installed catalog

```js
import { builtinModels } from '@browser-use/next';

const models = builtinModels();
console.table(
  models.getModels('openai').map((m) => ({
    id: m.id,
    vision: m.input.includes('image'),
    context: m.contextWindow,
  })),
);
```

An unknown model fails during `create()`, before launching a browser. No model substitution occurs.

## Bring your own provider

The SDK accepts Pi's native `Models` collection. Register a provider using Pi's factories, including compatible endpoints or your own model definitions, then pass the collection:

```js
import { createModels } from '@earendil-works/pi-ai';
import { openaiProvider } from '@earendil-works/pi-ai/providers/openai';
import { BrowserUse } from '@browser-use/next';

const models = createModels();
models.setProvider(openaiProvider());

const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  models,
});
```

This keeps new model support in Pi instead of maintaining another provider registry here. The lockfile pins Pi for reproducible installs. Upgrade it deliberately, run compatibility tests, and compare matched evaluations before changing your application's default.

## Model choice is part of the experiment

For quality comparisons, freeze the model ID, reasoning level, task IDs, browser environment, step/time limits, retries, and judge. Report price and completion separately. A newer model or different judge makes a different experiment.
