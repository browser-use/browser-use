<img src="https://raw.githubusercontent.com/browser-use/browser-use-pi/main/docs/public/banner.webp" alt="A white arch above the clouds" width="100%" />

# Browser Use Pi

**Browser Use, built on Pi Mono. In TypeScript.**

Pi Mono + a persistent V8 REPL + raw CDP. The agent writes JavaScript, controls Chrome, and builds the helpers it needs as it goes.

```text
Your task → Pi Mono → persistent V8 REPL → raw CDP → Chrome
                ↑                                    │
                └──────── AX tree + screenshots ──────┘
```

The programmability of Browser Harness, with sessions, saved logins, streaming and typed results. One SDK you can put in your app.

## Start

```sh
npm install @browser_use/pi
# or: pnpm add @browser_use/pi
# or: bun add @browser_use/pi
export OPENROUTER_API_KEY=...
export BROWSER_USE_API_KEY=...
```

```ts
import { Browser, BrowserUse } from '@browser_use/pi';

const agent = await BrowserUse.create({
  model: 'openrouter/openai/gpt-5.6-luna',
  reasoning: 'xhigh',
  browser: Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY! }),
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

Save as `agent.ts`. Run with `node agent.ts` or `bun agent.ts`. Uses [Browser Use Cloud](docs/sessions.md); no local Chrome installation needed.

**Node 22.19+ · Bun 1.3.14+**. Bun also needs Node for the V8 worker.

## Keep building

- **Models:** upstream Pi's model catalog and transports, with custom providers supported. Model capabilities and provider access vary. [Models](docs/models.md)
- **Sessions:** follow-ups, saved logins, persistent workspaces, cloud browsers or your own Chrome. [Sessions](docs/sessions.md)
- **Control:** streaming, hooks, typed results and compaction. Cap steps, time or cost and keep partial work. [API](docs/api.md)
- **Show the work:** interaction highlights, recordings and GIF exports. [Examples](examples/README.md)

[Quickstart](docs/quickstart.md) · [Browser primitives](docs/browser.md) · [Python](docs/python.md) · [Historical benchmarks](docs/benchmarks.md)

JavaScript runs in a killable worker with filesystem and network access. Use an isolated machine for untrusted tasks. Anonymous run counters are enabled; disable with `telemetry: false` or `DO_NOT_TRACK=1`. [Telemetry](docs/api.md#telemetry)

## Develop

```sh
npm test
npm run check
npm run docs:build
npm run test:python
```
