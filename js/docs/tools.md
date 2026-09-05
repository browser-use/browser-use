# Custom tools & events

Use Pi's existing tool contract. There is no second registry or decorator system.

## Add an application tool

```ts
import { BrowserUse, Type, type AgentTool } from '@browser-use/next';

const parameters = Type.Object({ sku: Type.String() });
const stock: AgentTool<typeof parameters> = {
  name: 'stock',
  label: 'Check stock',
  description: 'Read current stock for a product SKU.',
  parameters,
  async execute(_id, { sku }, signal) {
    const response = await fetch(
      `https://your-inventory.example/items/${encodeURIComponent(sku)}`,
      { signal },
    );
    if (!response.ok) throw new Error(`Inventory returned ${response.status}`);
    const item = await response.json();
    return {
      content: [{ type: 'text', text: JSON.stringify(item) }],
      details: { sku },
    };
  },
};

const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  tools: [stock],
});
```

Custom tools execute in your application's process. They must honor their `AbortSignal`; the SDK cannot terminate arbitrary application callbacks. The names `javascript` and `finish` are reserved. Duplicate tool names fail before browser launch.

## Stream progress

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

Events are Pi's native lifecycle events. Async listeners are awaited, preserving order and applying backpressure. A listener that never settles can prevent the run from settling; keep callbacks short, bounded, and abort-aware.

## Gate application actions

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  tools: [stock],
  async beforeToolCall({ toolCall }) {
    if (toolCall.name === 'stock' && !inventoryAccessAllowed) {
      return { block: true, reason: 'Inventory access is disabled.' };
    }
  },
});
```

This hook can reject any tool call before it executes. It is not a semantic security filter for arbitrary JavaScript: code can perform many actions inside one call. Put consequential operations behind explicit application tools and enforce access at the network/account boundary.
