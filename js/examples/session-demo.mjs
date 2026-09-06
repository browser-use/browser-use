import { mkdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse, Type, exportRecording } from '../dist/index.js';
import { startFixture } from './fixture.mjs';

const fixture = await startFixture();
const workspace = resolve(process.argv[2] ?? `artifacts/session-demo-${Date.now()}`);
await mkdir(workspace, { recursive: true });
const models = createModels();
const faux = fauxProvider({ tokensPerSecond: 1000000 });
models.setProvider(faux.provider);
const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });
faux.setResponses([
  call('javascript', {
    code: `await page.goto(${JSON.stringify(fixture.url)}); await new Promise(r=>setTimeout(r,500)); const products = await page.evaluate(()=>Array.from(document.querySelectorAll('article'),el=>({name:el.querySelector('h2').textContent,price:Number(el.dataset.price)}))); await screenshot();`,
  }),
  call('finish_from_js', { expression: 'products' }),
  call('javascript', {
    code: `await page.fill({role:'searchbox',name:'Search products'},'Atlas'); await page.click({role:'button',name:'Search'}); await new Promise(r=>setTimeout(r,400)); await page.click({role:'button',name:'Save selection'}); await new Promise(r=>setTimeout(r,400)); const csvPath=await artifact('products.csv','name,price\\n'+products.map(p=>p.name+','+p.price).join('\\n')+'\\n'); await screenshot();`,
  }),
  call('finish_from_js', { expression: 'csvPath' }),
]);
const agent = await BrowserUse.create({
  model: `${faux.getModel().provider}/${faux.getModel().id}`,
  models,
  workspace,
  log: 'pretty',
  recording: { intervalMs: 300 },
});
try {
  console.log('Scripted model responses · real Chrome · local fixture · no provider charges');
  const first = await agent.run('Read the product catalog.', {
    schema: Type.Array(Type.Object({ name: Type.String(), price: Type.Number() })),
  });
  if (first.status !== 'completed') throw new Error(JSON.stringify(first));
  const second = await agent.followUp('Select Atlas and export the original catalog as CSV.');
  if (second.status !== 'completed') throw new Error(JSON.stringify(second));
  await agent.saveHistory();
  console.table(await agent.files());
  await exportRecording(second.recordingPath, {
    output: join(workspace, 'demo.mp4'),
    title: 'Browser Use · follow up, act, deliver',
  });
  await exportRecording(second.recordingPath, {
    output: join(workspace, 'demo.gif'),
    format: 'gif',
    maxFrames: 16,
    title: 'Browser Use · follow up, act, deliver',
  });
  console.log(
    JSON.stringify({ workspace, output: second.output, recording: second.recordingPath }, null, 2),
  );
} finally {
  await agent.close();
  await fixture.close();
}
