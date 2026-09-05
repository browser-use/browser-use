/** Real browser + real Pi tool loop. Model responses are deliberately scripted. */
import { resolve } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse, Type } from '@browser-use/next';
import { startFixture } from './fixture.mjs';

console.log('\nBrowser Use / next — local integration demo');
console.log('Scripted model · real browser · local data · no API charges\n');
const fixture = await startFixture();
const faux = fauxProvider({ tokensPerSecond: 1_000_000 });
const models = createModels();
models.setProvider(faux.provider);
const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });
faux.setResponses([
  call('javascript', {
    code: `await page.goto(${JSON.stringify(fixture.url)}); const products = await page.evaluate(() => Array.from(document.querySelectorAll('article'), el => ({name:el.querySelector('h2').textContent,price:Number(el.dataset.price)}))); await snapshot()`,
  }),
  call('javascript', {
    code: "await page.click({role:'button',name:'Save selection'}); const saved = await page.text({role:'status'}); await artifact('catalog.jpg', await page.screenshot({quality:80})); await artifact('products.json', JSON.stringify(products,null,2)); await screenshot(); console.log(JSON.stringify({products,saved}))",
  }),
  (context) => {
    const evidence = context.messages.findLast((m) => m.role === 'toolResult');
    if (evidence.isError) throw new Error(evidence.content[0].text);
    return call('finish', { result: JSON.parse(evidence.content[0].text) });
  },
]);
let agent;
try {
  agent = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    browser: process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
    workspace: resolve('artifacts', `demo-${Date.now()}`),
  });
  const result = await agent.run(
    'Read the catalog, save the selection once, and return product names and prices.',
    {
      schema: Type.Object({
        products: Type.Array(Type.Object({ name: Type.String(), price: Type.Number() })),
        saved: Type.String(),
      }),
      onEvent: (event) => {
        if (event.type === 'tool_execution_end')
          console.log(`${event.isError ? 'ERROR' : 'OK'}  ${event.toolName}`);
      },
    },
  );
  console.log(`\n${result.status} · ${result.steps} model turns · ${result.durationMs} ms`);
  console.log(JSON.stringify(result.status === 'completed' ? result.output : result, null, 2));
  console.log(`\nArtifacts: ${result.workspace}`);
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  await agent?.close();
  await fixture.close();
}
