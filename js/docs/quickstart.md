# Pi, with a browser

A TypeScript SDK. The agent writes JavaScript, sees Chrome’s accessibility tree, and uses raw CDP. Pi supplies the model loop. Browser Use JS adds the browser and a persistent session.

## Install

Run your app with **Node 22.19+** or **Bun 1.3.14+**. Bun also requires Node on `PATH`: the persistent JavaScript worker uses Node’s V8 inspector. Set `BROWSER_USE_NODE=/absolute/path/to/node` to choose that executable. The worker does not inherit host preload flags or API keys.

Use local Chrome or [Browser Use Cloud](./sessions.md). Runtime checks cover macOS; Windows has not been verified.

```sh
git clone --branch codex/raw-cdp-k7m2 https://github.com/browser-use/bu-pi.git browser-use-js
cd browser-use-js
npm ci
npm run build
export OPENROUTER_API_KEY=...
```

The package is named `@browser_use/js` and is not published yet. Run examples from the checkout, or create a tarball with `npm pack`. In another project, use any one of:

```sh
npm install /path/to/browser_use-js-0.1.0.tgz
pnpm add /path/to/browser_use-js-0.1.0.tgz
bun add /path/to/browser_use-js-0.1.0.tgz
```

## Run

Save as `agent.mjs` inside the checkout:

```js
import { BrowserUse } from '@browser_use/js';

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
# or
bun agent.mjs
```

`completed` means the agent delivered a schema-valid answer. Verify business outcomes in your application. Other statuses describe the stop reason; always check them.

Use [models](./models.md) for credentials, [sessions](./sessions.md) for login and persistence, and [API](./api.md) for output, events and hooks.

## Publish to npm (maintainers)

The public package is `@browser_use/js`. Use an npm account with publish permission in the `browser_use` organization and complete npm's required 2FA setup.

```sh
npm login
npm whoami
npm run check && npm test && npm run test:bun
npm pack
npm publish ./browser_use-js-0.1.0.tgz --access public --dry-run
# After verifying that exact tarball:
npm publish ./browser_use-js-0.1.0.tgz --access public
```

`npm test` runs the full Node suite. `npm run test:bun` runs browser, agent, session, policy, recording and recovery tests in Bun; Node-specific test mocks stay in the Node suite. Install and smoke-test the tarball in a clean project before publishing. npm versions cannot be overwritten; bump the version for each later release. For automated releases, configure [npm trusted publishing](https://docs.npmjs.com/trusted-publishers) for the final GitHub repository name. No npm token needs to live in this repository.
