# Quickstart

Give an agent a task. Get the result.

You need **Node.js 22.19+**, **Google Chrome** and a model API key. Works with JavaScript and TypeScript.

## 1. Install

The package is in preview. Install from source for now:

```sh
git clone --branch codex/raw-cdp-k7m2 https://github.com/browser-use/bu-pi.git
cd bu-pi
npm ci
npm run build
```

## 2. Add your API key

```sh
export OPENAI_API_KEY="your-key"
```

Using Anthropic or Google? See [models](/models).

## 3. Run an agent

Save this as `agent.mjs` in the `bu-pi` directory:

```js
import { BrowserUse } from '@browser-use/next';

const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  browser: { headless: false },
});

try {
  const result = await agent.run('Find the top story on Hacker News.');
  console.log(result.status, result.text);
} finally {
  await agent.close();
}
```

```sh
node agent.mjs
```

Chrome opens, the agent works, and the answer prints in your terminal. Model requests use your provider account.

## Keep going

Before closing the agent, ask a follow-up:

```js
await agent.followUp('Summarize the comments on that story.');
```

[Save your login](/sessions) · [Get structured output](/results) · [Record a GIF](/recording)

::: details Try it without an API key
Run `npm run demo` from the checkout. It uses scripted model responses and real Chrome against a local fixture. It tests the setup without paid model requests.
:::

::: details Install in your own project
Run `npm pack` in the checkout, then install the tarball in your application:

```sh
npm install /path/to/browser-use-next-0.1.0.tgz
```

Use the same import from an ESM JavaScript or TypeScript file. The package includes compiled JavaScript and TypeScript definitions. It is not published to npm yet.

Node 22.19 and npm installs are tested on macOS. pnpm/Yarn installs and Linux/Windows have not been verified. Bun runtime execution is not currently supported. [Test coverage](/session-verification).
:::

::: details Running tasks for other users
The agent executes Node code with filesystem and network access. Use an isolated container or VM for untrusted tasks. [Execution boundaries](/recovery#execution-boundaries).
:::
