# Custom tools

Give the agent functions from your application.

## Define a tool

```ts
import { BrowserUse, Type, type AgentTool } from '@browser-use/next';

const parameters = Type.Object({ sku: Type.String() });
const stock: AgentTool<typeof parameters> = {
  name: 'stock',
  label: 'Check stock',
  description: 'Look up the stock count for a product SKU.',
  parameters,
  async execute(_id, { sku }, signal) {
    signal?.throwIfAborted();
    const inventory: Record<string, number> = { 'charger-01': 12, 'charger-02': 0 };
    const count = inventory[sku] ?? 0;
    return {
      content: [{ type: 'text', text: String(count) }],
      details: { sku, count },
    };
  },
};

const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  tools: [stock],
});
try {
  await agent.run('How many charger-01 units are in stock?');
} finally {
  await agent.close();
}
```

Replace the example inventory with your database or API. `content` goes to the model; `details` carries application metadata.

## Control access

Use [`beforeToolCall`](/events#hooks) to block a tool and explain why. Tools run in your application process and should honor their abort signal.

::: details Tool names & execution boundaries
Custom tools execute in your application's process. They must honor their `AbortSignal`; the SDK cannot terminate arbitrary application callbacks. The names `javascript`, `finish`, and `finish_from_js` are reserved. Duplicate tool names fail before browser launch.

This hook can reject any tool call before it executes. Both `javascript` and `finish_from_js` execute generated code; a policy that restricts code execution must handle both names. The latter receives an `expression`, not a literal result. It is not a semantic security filter for arbitrary JavaScript: code can perform many actions inside one call. Put consequential operations behind explicit application tools and enforce access at the network/account boundary.
:::

::: details Native event callbacks

```js
const result = await agent.run('Compare three products.', {
  onEvent(event) {
    if (event.type === 'tool_execution_start') {
      console.log('Using', event.toolName);
    }
    if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
      process.stdout.write(event.assistantMessageEvent.delta);
    }
  },
});
```

Events are Pi's native lifecycle events. Async listeners are awaited, preserving order and applying backpressure. Awaited callbacks have a configurable `hookTimeoutMs` deadline. Keep them short and abort-aware; a timeout cannot undo external callback effects. Use the bounded `events()` iterator for independent streaming consumers. See [streaming and hooks](./events).

`onEvent` receives native Pi events. A run that needs the single missing-finish repair emits `agent_end` for the initial loop and again for the repair loop. Await `agent.run()` for the SDK's terminal result; do not treat the first `agent_end` as a delivered answer. `result.finishRepairs` records whether the extra turn was used, and its usage is included in the run totals.
:::
