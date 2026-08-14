# Browser Use JS

A deliberately small TypeScript browser agent: Pi's published agent runtime, one JavaScript CDP tool, and Browser Use
Cloud.

```bash
npm install @browser-use/browser-use
```

```ts
import { Agent } from '@browser-use/browser-use'

const result = await new Agent({
  task: 'Find the number one post on Show HN',
}).run()

console.log(result.output)
```

Set `OPENAI_API_KEY` for the default model. Set `BROWSER_USE_API_KEY` to provision an isolated Browser Use Cloud
browser automatically, or pass an existing `cdpUrl`.

```ts
const result = await new Agent({
  task: 'Find the cheapest direct flight',
  browser: {
    useCloud: true,
    profileId: 'my-profile',
    proxyCountryCode: 'us',
  },
}).run()
```

The browser agent receives exactly one browser tool. Its JavaScript snippets execute against a persistent raw CDP
session, and `Page.captureScreenshot` results are returned to the model as native images.
