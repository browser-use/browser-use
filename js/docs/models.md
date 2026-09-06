# Models

Choose a provider and model. Use the same agent API.

```js
const agent = await BrowserUse.create({
  model: 'anthropic/claude-sonnet-4-6',
  reasoning: 'medium',
});
```

## API keys

Set your provider’s key in the environment:

| Provider  | Model example                 | Environment variable |
| --------- | ----------------------------- | -------------------- |
| OpenAI    | `openai/gpt-5.5`              | `OPENAI_API_KEY`     |
| Anthropic | `anthropic/claude-sonnet-4-6` | `ANTHROPIC_API_KEY`  |
| Google    | `google/gemini-2.5-pro`       | `GEMINI_API_KEY`     |

Model IDs use `provider/model-id`. Availability depends on your provider account. Pi supplies the model catalog; catalog support does not mean we have tested every model.

## Find a model

```js
import { builtinModels } from '@browser-use/next';

const models = builtinModels();
console.table(models.getModels('openai'));
```

An unknown model fails before Chrome launches.

::: details Custom providers
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
:::
