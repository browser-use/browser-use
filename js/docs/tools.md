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

Custom tools execute in your application's process. They must honor their `AbortSignal`; the SDK cannot terminate arbitrary application callbacks. The names `javascript`, `finish`, and `finish_from_js` are reserved. Duplicate tool names fail before browser launch.

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

This hook can reject any tool call before it executes. Both `javascript` and `finish_from_js` execute generated code; a policy that restricts code execution must handle both names. The latter receives an `expression`, not a literal result. It is not a semantic security filter for arbitrary JavaScript: code can perform many actions inside one call. Put consequential operations behind explicit application tools and enforce access at the network/account boundary.

## Loop endings and delivery repair

`onEvent` receives native Pi events. A run that needs the single missing-finish repair emits `agent_end` for the initial loop and again for the repair loop. Await `agent.run()` for the SDK's terminal result; do not treat the first `agent_end` as a delivered answer. `result.finishRepairs` records whether the extra turn was used, and its usage is included in the run totals.
