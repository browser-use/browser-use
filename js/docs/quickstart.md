# Pi, with a browser

A TypeScript SDK. The agent writes JavaScript, sees Chrome’s accessibility tree, and uses raw CDP. Pi supplies the model loop. bu-pi adds the browser and a persistent session.

## Install

You need Node **22.19+** and Chrome. npm and pnpm install packages; Node executes the SDK and its worker. Bun and Windows are not verified runtime targets.

```sh
git clone --branch codex/raw-cdp-k7m2 https://github.com/browser-use/bu-pi.git
cd bu-pi
npm ci
npm run build
export OPENROUTER_API_KEY=...
```

This prototype is not published to npm. Run examples from the checkout, or use `npm pack` and install the resulting tarball into your project.

## Run

Save as `agent.mjs` inside the checkout:

```js
import { BrowserUse } from '@browser-use/next';

const agent = await BrowserUse.create({
  model: 'openrouter/openai/gpt-5.6-luna',
  workspace: './work',
  log: 'pretty',
});
try {
  const result = await agent.run('Find the top story on Hacker News.');
  console.log(result.status, result.text);
  await agent.followUp('Summarize the comments.');
} finally {
  await agent.close();
}
```

```sh
node agent.mjs
```

`completed` means the agent delivered a schema-valid answer. Verify business outcomes in your application. Other statuses describe the stop reason; always check them.

Use [models](./models.md) for credentials, [sessions](./sessions.md) for login and persistence, and [API](./api.md) for output, events and hooks.
