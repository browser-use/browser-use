# Your first web agent

One session, one model, one task. The browser and JavaScript variables stay alive until you close the session.

::: info Source preview
`@browser-use/next` is a working prototype, not a published npm release. Clone the source branch below. Node.js **22.19 or newer** is required.
:::

## Install and verify locally

```sh
git clone --branch codex/raw-cdp-k7m2 https://github.com/browser-use/bu-pi.git
cd bu-pi
npm ci
# Install Google Chrome, or attach an existing CDP endpoint.
npm run demo
```

The demo uses Pi's **scripted test provider** against a local product catalog in a real Chromium browser. It exercises the complete tool loop and typed delivery without an API key or model charges. It is a plumbing demonstration, not an autonomous-agent benchmark.

Install Google Chrome locally, specify `browser.executablePath`, or attach to a cloud browser using `browser.cdpUrl`. No browser automation runtime or browser download is bundled.

## Use a real model

Set your provider's API key through your normal environment or secret manager. For OpenAI, that is `OPENAI_API_KEY`. Then run:

```sh
node examples/research.mjs "Find the latest stable Node.js release on nodejs.org."
```

This example makes real provider requests and incurs the provider's normal charges. It reads `MODEL` if set; otherwise it uses `openai/gpt-5.5`.

```js
import { BrowserUse } from '@browser-use/next';

const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
});

try {
  const result = await agent.run('Find the latest stable Node.js release on nodejs.org.', {
    maxSteps: 20,
    timeoutMs: 120_000,
  });

  if (result.status === 'completed') {
    console.log(result.output);
  } else {
    console.log(result.status, result.text, result.error);
  }
} finally {
  await agent.close();
}
```

## Install into another project

From the package directory:

```sh
npm run check
npm test
npm pack
```

Then, in your application:

```sh
npm install /path/to/browser-use-next-0.1.0.tgz
# Install Google Chrome, or attach an existing CDP endpoint.
```

The tarball contains compiled ESM, TypeScript declarations, source maps, examples, and the license. It has no dependency on the evaluation platform and runs without its credentials.

## Make cleanup automatic

TypeScript projects targeting explicit resource management can use:

```ts
await using agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
});
const result = await agent.run('Read the current Node.js release notes.');
```

For portable JavaScript, use `try/finally`. `close()` is idempotent. Output files remain available in `agent.workspace` after closing.
