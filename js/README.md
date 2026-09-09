<img src="https://raw.githubusercontent.com/browser-use/browser-use-js/main/docs/public/banner.webp" alt="A white arch above the clouds" width="100%" />

# Browser Use JS

**Pi, with a browser.** A small TypeScript SDK for agents that write JavaScript and control Chrome through raw CDP.

The agent gets a persistent JS session, an accessibility tree, screenshots, and a workspace. It writes the rest. No Playwright. No selector engine. No fork of Pi.

## Start

Runs in **Node 22.19+** or **Bun 1.3.14+**. Bun also needs Node installed for the execution worker. Use local Chrome or a [cloud browser](https://github.com/browser-use/browser-use-js/blob/main/docs/sessions.md). Install with npm, pnpm or Bun:

```sh
npm install @browser_use/js
export OPENROUTER_API_KEY=...
```

```ts
import { BrowserUse } from '@browser_use/js';

const agent = await BrowserUse.create({
  model: 'openrouter/openai/gpt-5.6-luna',
  workspace: './work',
});

try {
  const result = await agent.run('Find the top story on Hacker News.');
  console.log(result.status, result.text);
  await agent.followUp('Summarize the comments.');
} finally {
  await agent.close();
}
```

Save as `agent.ts`. Run with `node agent.ts` or `bun agent.ts`.

## How it works

```text
Your task → upstream Pi → persistent JavaScript → raw CDP → Chrome
                  ↑          AX tree / screenshots          │
                  └─────────────────────────────────────────┘
```

AX first. Screenshots when useful. Real mouse and keyboard input. Small primitives, agent-written helpers.

Follow-ups, saved logins, typed results, streaming, hooks, compaction, and GIF/video exports are included. JavaScript runs in a killable worker so a bad cell cannot hang your application. It has filesystem and network access; use an isolated machine for untrusted tasks.

[Quickstart](https://github.com/browser-use/browser-use-js/blob/main/docs/quickstart.md) · [API](https://github.com/browser-use/browser-use-js/blob/main/docs/api.md) · [Browser primitives](https://github.com/browser-use/browser-use-js/blob/main/docs/browser.md) · [Sessions](https://github.com/browser-use/browser-use-js/blob/main/docs/sessions.md) · [Models](https://github.com/browser-use/browser-use-js/blob/main/docs/models.md) · [Python](https://github.com/browser-use/browser-use-js/blob/main/docs/python.md) · [Historical benchmarks](https://github.com/browser-use/browser-use-js/blob/main/docs/benchmarks.md)

[Eight TypeScript examples](examples/README.md): extraction, QA + GIF, EHR, forms, Link, 1Password, job applications and research.

## Develop

```sh
npm test
npm run check
npm run docs:build
npm run test:python
```

Anonymous run counters are enabled. Disable with `telemetry: false` or `DO_NOT_TRACK=1`. [Payload](https://github.com/browser-use/browser-use-js/blob/main/docs/api.md#telemetry).

The [eval adapter](https://github.com/browser-use/browser-use-js/blob/main/eval/README.md) keeps benchmark configuration explicit. Historical scores do not establish this simplified version’s performance.
