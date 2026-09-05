# Browser Use / next

**A browser agent. A JavaScript import.**

A standalone TypeScript SDK built on Pi, a persistent V8 REPL, and raw CDP. Give it a task, get a validated result. Use the same browser directly whenever deterministic code is clearer.

**Prototype · v0.1.0 · Node.js 22.19+ · MIT · Not published to npm**

```ts
import { BrowserUse, Type } from '@browser-use/next';

const agent = await BrowserUse.create({ model: 'openai/gpt-5.5' });
try {
  const result = await agent.run('Compare three travel chargers under $100.', {
    schema: Type.Array(
      Type.Object({
        name: Type.String(),
        price: Type.Number(),
        source: Type.String(),
      }),
    ),
  });
  if (result.status === 'completed') console.table(result.output);
} finally {
  await agent.close();
}
```

## Try it

Clone the source branch and run the local demo:

```sh
git clone --branch codex/raw-cdp-k7m2 https://github.com/browser-use/bu-pi.git
cd bu-pi
npm ci
# Install Google Chrome, or attach an existing CDP endpoint.
npm run demo
```

The demo uses **scripted model responses and a real Chrome browser** against a local fixture. It exercises the complete Pi loop, persistent code, browser interactions, screenshots, artifacts, and typed output. It makes no paid provider request. The SDK, demo, and tests launch installed Google Chrome with a fresh temporary profile.

For an actual model run, configure the provider key (for example `OPENAI_API_KEY`), then:

```sh
node examples/research.mjs "Find the latest stable Node.js release on nodejs.org."
```

Optional environment variables: `MODEL`, `BROWSER_CDP_URL`, and `BROWSER_CHANNEL`. Real model runs incur provider charges. Browser provisioning is explicit; this SDK does not create paid cloud sessions.

## What is included

- **Pi models and tools.** Provider/model IDs, reasoning, native events, and custom typed tools.
- **Persistent JavaScript.** Real top-level bindings and `await`; native V8 REPL semantics.
- **Browser capability.** Accessibility discovery, coordinate clicks, frames, shadow DOM, screenshots, uploads, download events, page evaluation, and explicit CDP commands.
- **Typed delivery.** Return existing JavaScript values without rewriting them; schema-validated results; incomplete, cancelled, timed-out, and failed runs stay distinct.
- **Explicit control.** One active operation per session; step/time/context limits and a soft estimated-cost threshold.
- **Recovery.** One budgeted delivery repair for unfinished answers. Worker termination contains hangs. Reconnect to the primary tab without replaying failed actions.
- **Bounded context.** Output files for large results; native images; old screenshots omitted from later requests.

## Small architecture

```text
Your application → BrowserUse → Pi → model provider
                       └─ V8 child process → raw CDP → Chrome
```

[Design decisions](docs/architecture.md) · [API reference](docs/api.md) · [Migration scope](docs/migration.md) · [Verification](docs/verification.md)

**Internal Bench Hard: 91/106 passed (85.8%) vs 76/106 (71.7%) for the fresh frozen SDK baseline.** Same model, task set, judge configuration, and budgets; 19 gains, 4 regressions. Estimated candidate agent cost: **$123.63**. This full score belongs to `58ed778`; the later cleanup change passed a separate 2/2 smoke. [Results, failure analysis, and exact configuration](docs/benchmark.md).

## Documentation

```sh
npm run docs:dev
```

Open the printed localhost URL. The docs include quickstart, providers, typed extraction, browser recipes, tools/events, limits, recovery, architecture, migration, and verification. Search and model-specific copyable examples work locally.

## Develop and package

```sh
npm run check
npm test
npm run docs:build
npm pack
```

Install the resulting `browser-use-next-0.1.0.tgz` in a separate application. The package exports compiled ESM and TypeScript declarations and has no dependency on the surrounding eval platform.

## Execution boundary

The worker is **not a security sandbox**. Model-generated Node code can access the filesystem and network. Provider environment variables are not inherited by the worker, but this does not isolate host files. Run untrusted tasks in containers/VMs with restricted mounts and accounts. Custom application tools must honor cancellation. Artifacts remain after cleanup; your application owns their retention.

This prototype does not provide durable transcript restore, automatic compaction, cloud provisioning, stealth guarantees, or a hosted agent service. Existing Python Browser Use users and persisted sessions are unaffected.
