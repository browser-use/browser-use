// Run the actual TypeScript entrypoints with real CDP browsers and a scripted Pi model.
// Vendor CLIs are synthetic. This verifies wiring and side effects, not model quality/vendor auth.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = resolve(import.meta.dirname, '..');
const runFile = promisify(execFile);
const browser = process.env.EXAMPLE_BROWSER || 'local';
const cases = [
  'extract',
  'qa',
  'ehr',
  'form',
  'stripe-link',
  'onepassword',
  'apply-to-job',
  'research',
];
const html = (body) =>
  `<!doctype html><html><head><title>Browser Use JS test fixture</title></head><body>${body}</body></html>`;
const fixture = html(`
<h1>Browser Use JS sandbox</h1><p>Test checkout: Example Store, Demo book, final total USD 10.00. Tax and shipping included.</p>
<p>Patient TEST-1001: Avery Example, DOB 1990-01-02</p>
${Array.from({ length: 10 }, (_, i) => `<article><a href="?book=${i}">Book ${i + 1}</a><p>USD ${i + 1}.00, In stock</p></article>`).join('')}
<form id="pizza"><label>Customer <input name="customer"></label><label>Phone <input name="phone"></label><label>Email <input name="email" type="email"></label><label>Pizza size <select name="size"><option>small</option><option>medium</option><option>large</option></select></label><label><input type="checkbox" name="cheese">Cheese</label><label><input type="checkbox" name="mushroom">Mushroom</label><label>Delivery time <input name="time" type="time"></label><label>Comment <textarea name="comment"></textarea></label><button>Submit demo form</button></form>
<form id="login"><label>Username <input name="username" autocomplete="username"></label><label>Password <input type="password" name="password" autocomplete="current-password"></label><button>Log in</button></form>
<label>Visit note <textarea id="note"></textarea></label><button id="draft">Save unsigned draft</button><button id="sign">Sign note</button>
<form id="payment"><label>Card number <input name="cardNumber"></label><label>Expiry <input name="expiry"></label><label>CVC <input name="cvc" type="password"></label><button>Pay</button></form>
<label>Applicant name <input id="applicant"></label><label>Resume PDF <input id="resume" type="file" accept="application/pdf"></label><button id="apply">Submit application</button>
<label>Search <input id="search"></label><button id="searchButton">Search</button><p id="status" role="status"></p>
<script>
const status = document.querySelector('#status');
async function record(type,data){await fetch('/events',{method:'POST',body:JSON.stringify({type,data})});}
document.querySelector('#pizza').onsubmit=async e=>{e.preventDefault();await record('form',Object.fromEntries(new FormData(e.target)));status.textContent='Form submitted: '+JSON.stringify(Object.fromEntries(new FormData(e.target)));};
document.querySelector('#login').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);const ok=f.get('username')==='fixture-user-72'&&f.get('password')==='fixture-secret-83';await record('login',{ok});status.textContent=ok?'Signed in':'Invalid credentials';};
document.querySelector('#draft').onclick=async()=>{await record('draft',{note:document.querySelector('#note').value});status.textContent='Unsigned draft saved';};
document.querySelector('#sign').onclick=()=>record('signed',{});
document.querySelector('#payment').onsubmit=e=>{e.preventDefault();record('charged',{});};
document.querySelector('#payment').onchange=()=>record('card',{filled:document.querySelector('[name=cardNumber]').value==='4242424242424242'});
document.querySelector('#resume').onchange=async e=>{const f=e.target.files[0];await record('upload',{name:f.name,bytes:Array.from(new Uint8Array(await f.arrayBuffer()))});status.textContent='Attached '+f.name;};
document.querySelector('#apply').onclick=()=>record('applied',{});
document.querySelector('#searchButton').onclick=()=>{status.textContent='No results';};
</script>`);

// A valid minimal PDF, including byte offsets and cross-reference table.
function resumePDF() {
  let text = '%PDF-1.4\n';
  const offsets = [0];
  const stream = 'BT /F1 18 Tf 40 720 Td (Avery Example - synthetic resume) Tj ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  objects.forEach((o, i) => {
    offsets.push(Buffer.byteLength(text));
    text += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const start = Buffer.byteLength(text);
  text += `xref\n0 6\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((n) => String(n).padStart(10, '0') + ' 00000 n \n')
    .join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(text);
}

for (const name of [...cases, 'link-denied', 'op-failed'])
  test(
    `TypeScript example: ${name} (${browser})`,
    { timeout: process.env.EXAMPLE_LIVE_MODEL ? 480_000 : 120_000 },
    async () => {
      const dir = await mkdtemp(join(tmpdir(), 'bu-example-'));
      const events = [];
      const server = createServer(async (req, res) => {
        if (req.url === '/events') {
          let body = '';
          for await (const b of req) body += b;
          try {
            events.push(JSON.parse(body));
          } catch {
            res.writeHead(400);
            res.end('Expected a JSON event');
            return;
          }
          res.end('ok');
          return;
        }
        res.setHeader('content-type', 'text/html');
        res.end(fixture);
      });
      await new Promise((r) =>
        server.listen(Number(process.env.EXAMPLE_FIXTURE_PORT || 0), '127.0.0.1', r),
      );
      const url = process.env.EXAMPLE_FIXTURE_ORIGIN || `http://127.0.0.1:${server.address().port}`;
      const example =
        name === 'link-denied' ? 'stripe-link' : name === 'op-failed' ? 'onepassword' : name;
      await mkdir(join(dir, 'bin'));
      await mkdir(join(dir, 'work'));
      await writeFile(join(dir, 'resume.pdf'), resumePDF());
      await writeFile(
        join(dir, 'applicant.json'),
        JSON.stringify({ name: 'Avery Example', email: 'avery@example.com' }),
      );
      const cliLog = join(dir, 'cli.jsonl');
      await writeFile(
        join(dir, 'bin', 'op'),
        `#!/usr/bin/env node
if(process.env.EXAMPLE_CASE==='op-failed'){process.stderr.write('fixture-secret-83');process.exit(1);}
process.stdout.write(process.argv[3].endsWith('/username')?'fixture-user-72':'fixture-secret-83');`,
        { mode: 0o700 },
      );
      await writeFile(
        join(dir, 'bin', 'link-cli'),
        `#!/usr/bin/env node
const fs=require('node:fs');const args=process.argv.slice(2);fs.appendFileSync(${JSON.stringify(cliLog)},JSON.stringify(args)+'\\n');
const command=args[0]+' '+args[1];
let value=command==='auth status'?{authenticated:true,scope:'payment_methods.agentic'}:{id:'lsrq_fixture',status:process.env.EXAMPLE_CASE==='link-denied'?'denied':'approved'};
if(command==='spend-request create'&&!args.includes('--test'))process.exit(2);
if(args.includes('card')&&command==='spend-request retrieve')value.card={number:'4242424242424242',cvc:'123',exp_month:12,exp_year:2030};
process.stdout.write(JSON.stringify(value));`,
        { mode: 0o700 },
      );
      const outputs = {
        extract: {
          books: Array.from({ length: 10 }, (_, i) => ({
            title: `Book ${i + 1}`,
            price: i + 1,
            currency: 'USD',
            inStock: true,
            url: `${url}/?book=${i}`,
          })),
          csv: 'books.csv',
        },
        qa: {
          tested: ['Search'],
          bugs: [
            {
              title: 'Search returns no results for a visible book',
              severity: 'medium',
              steps: ['Search Book 1'],
              expected: 'Book 1',
              actual: 'No results',
              url,
              screenshot: 'search.png',
            },
          ],
          blocked: [],
        },
        ehr: {
          patientId: 'TEST-1001',
          draftSaved: true,
          evidence: 'Unsigned draft saved',
          needsReview: [],
        },
        form: { submitted: true, verifiedFields: { customer: 'Avery Example' }, mismatches: [] },
        onepassword: { loggedIn: true, evidence: 'Signed in', needsHuman: false },
        'apply-to-job': {
          resumeAttached: true,
          filled: ['name'],
          needsAnswers: [],
          reviewUrl: url,
          submitted: false,
        },
        research: 'Read the sandbox title',
      };
      const actions = {
        extract: `await fs.writeFile('books.csv','title,price\\n'+Array.from({length:10},(_,i)=>'Book '+(i+1)+','+(i+1)).join('\\n'));`,
        qa: `await page.evaluate(()=>{document.querySelector('#search').value='Book 1';document.querySelector('#searchButton').click()});await fs.writeFile('search.png',await page.screenshot());await fs.writeFile('report.md','Search for Book 1 returns no results.');`,
        ehr: `await page.evaluate(()=>{document.querySelector('#note').value='Demo visit: patient reports mild left ankle pain after a walk.';document.querySelector('#draft').click()});`,
        form: `await page.evaluate(()=>{document.querySelector('[name=customer]').value='Avery Example';document.querySelector('#pizza').requestSubmit()});`,
        onepassword: `var nodes=(await snapshot()).nodes;await fillSecret('username',nodes.find(n=>n.role==='textbox'&&n.name==='Username').id);await fillSecret('password',nodes.find(n=>n.role==='textbox'&&n.name==='Password').id);await page.evaluate(()=>document.querySelector('#login').requestSubmit());`,
        'apply-to-job': `var bytes=(await fs.readFile('resume.pdf')).toString('base64');await page.evaluate(b64=>{document.querySelector('#applicant').value='Avery Example';const dt=new DataTransfer();dt.items.add(new File([Uint8Array.from(atob(b64),c=>c.charCodeAt(0))],'resume.pdf',{type:'application/pdf'}));const input=document.querySelector('#resume');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));},bytes);await fs.writeFile('application-review.md','Attached resume.pdf. Not submitted.');`,
        research: `console.log(await page.evaluate(()=>document.title));`,
      };
      const preload = join(dir, 'preload.mjs');
      await writeFile(
        preload,
        `
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {BrowserUse} from ${JSON.stringify(pathToFileURL(join(root, 'dist/index.js')).href)};
import {createModels,fauxProvider,fauxAssistantMessage,fauxToolCall} from ${JSON.stringify(pathToFileURL(join(root, 'node_modules/@earendil-works/pi-ai/dist/index.js')).href)};
const original=BrowserUse.create.bind(BrowserUse);
BrowserUse.create=async options=>{
 const faux=fauxProvider({tokensPerSecond:1000000});const models=createModels();models.setProvider(faux.provider);
 const call=(name,args)=>fauxAssistantMessage(fauxToolCall(name,args),{stopReason:'toolUse'});
 let action=${JSON.stringify(actions[example] || '')};let output=${JSON.stringify(outputs[example] ?? null)};
 if(${JSON.stringify(example)}==='stripe-link'){
  if(options.sensitiveData){action="var nodes=(await snapshot()).nodes;await fillSecret('cardNumber',nodes.find(n=>n.role==='textbox'&&n.name==='Card number').id);await fillSecret('expiry',nodes.find(n=>n.role==='textbox'&&n.name==='Expiry').id);await fillSecret('cvc',nodes.find(n=>n.role==='textbox'&&n.name==='CVC').id);await page.evaluate(()=>document.querySelector('#payment').dispatchEvent(new Event('change')));";output={filled:true,submitted:false,needsHuman:[]};}
  else output={supported:true,merchant:'Example Store',amountCents:1000,currency:'usd',reason:'Test checkout'};
 }
 faux.setResponses([call('javascript',{code:'var fs=await import("node:fs/promises");await page.goto('+${JSON.stringify(JSON.stringify(url))}+');'+action+'await new Promise(r=>setTimeout(r,150));console.log("fixture action complete");'}),context=>{const tool=context.messages.findLast(m=>m.role==='toolResult');assert.equal(tool.isError,false,JSON.stringify(tool.content));return call('finish',{result:output});}]);
 const agent=await original(process.env.EXAMPLE_LIVE_MODEL ? {...options,telemetry:false} : {...options,model:faux.getModel().provider+'/'+faux.getModel().id,models,telemetry:false});
 const run=agent.run.bind(agent);agent.run=async(...args)=>{const result=await run(...args);await writeFile(${JSON.stringify(join(dir, 'result.json'))},JSON.stringify(result));if (process.env.EXAMPLE_LIVE_MODEL && 'qa'===${JSON.stringify(example)}) { assert.ok(result.status==='completed'||result.partial, result.text); } else assert.equal(result.status,'completed',result.text);return result;};return agent;
};
`,
      );
      try {
        const env = {
          ...process.env,
          PATH: join(dir, 'bin') + ':' + process.env.PATH,
          EXAMPLE_CASE: name,
          OPENROUTER_API_KEY: process.env.EXAMPLE_LIVE_MODEL ? process.env.OPENROUTER_API_KEY : '',
          DO_NOT_TRACK: '1',
          BROWSER: browser,
          WORKSPACE: join(dir, 'work'),
          START_URL: url,
          EHR_URL: url,
          LOGIN_URL: url,
          CHECKOUT_URL: url,
          PURCHASE: 'Demo book',
          JOB_URL: url,
          RESUME_PDF: join(dir, 'resume.pdf'),
          APPLICANT_JSON: join(dir, 'applicant.json'),
          OP_USERNAME_REF: 'op://Test/Login/username',
          OP_PASSWORD_REF: 'op://Test/Login/password',
        };
        let stdout = '',
          stderr = '',
          failed = false;
        try {
          ({ stdout, stderr } = await runFile(
            process.execPath,
            [
              '--import',
              preload,
              join(root, 'examples', example + '.ts'),
              ...(example === 'research' ? [`Read ${url}`] : []),
            ],
            {
              env,
              cwd: root,
              timeout: process.env.EXAMPLE_LIVE_MODEL ? 450_000 : 100_000,
              maxBuffer: 2 * 1024 * 1024,
            },
          ));
        } catch (e) {
          failed = true;
          stdout = e.stdout || '';
          stderr = e.stderr || '';
        }
        if (process.env.EXAMPLE_EVIDENCE) {
          const evidence = resolve(process.env.EXAMPLE_EVIDENCE, browser, name);
          await mkdir(evidence, { recursive: true });
          await writeFile(join(evidence, 'browser-events.json'), JSON.stringify(events));
          await writeFile(join(evidence, 'stdout.log'), stdout);
          await writeFile(join(evidence, 'stderr.log'), stderr);
          await import('node:fs/promises').then((fs) =>
            fs.cp(join(dir, 'work'), join(evidence, 'workspace'), { recursive: true }),
          );
          try {
            await writeFile(
              join(evidence, 'result.json'),
              await readFile(join(dir, 'result.json')),
            );
          } catch {}
        }
        assert.equal(failed, ['link-denied', 'op-failed'].includes(name), stderr);
        for (const secret of ['fixture-secret-83', '4242424242424242'])
          assert.ok(!(stdout + stderr).includes(secret));
        assert.ok(!events.some((e) => ['charged', 'signed', 'applied'].includes(e.type)));
        if (name === 'form')
          assert.equal(events.find((e) => e.type === 'form')?.data.customer, 'Avery Example');
        if (name === 'ehr')
          assert.match(events.find((e) => e.type === 'draft')?.data.note, /left ankle pain/);
        if (name === 'onepassword')
          assert.equal(events.find((e) => e.type === 'login')?.data.ok, true);
        if (name === 'apply-to-job')
          assert.deepEqual(
            Buffer.from(events.find((e) => e.type === 'upload')?.data.bytes || []),
            resumePDF(),
          );
        if (name === 'extract')
          assert.equal(
            (await readFile(join(dir, 'work/books.csv'), 'utf8')).trim().split('\n').length,
            11,
          );
        if (name === 'qa') {
          const result = JSON.parse(await readFile(join(dir, 'result.json'), 'utf8'));
          const gif = await readFile(join(dir, 'work', `qa-${result.runId}.gif`));
          assert.equal(gif.subarray(0, 3).toString(), 'GIF');
        }
        if (example === 'stripe-link') {
          const commands = (await readFile(cliLog, 'utf8'))
            .trim()
            .split('\n')
            .map((s) => JSON.parse(s));
          assert.ok(commands.some((a) => a[1] === 'cancel'));
          if (name === 'link-denied') {
            assert.ok(!commands.some((a) => a.includes('--include')));
            assert.ok(!events.some((e) => e.type === 'card'));
          } else assert.equal(events.find((e) => e.type === 'card')?.data.filled, true);
        }
      } finally {
        await new Promise((r) => server.close(r));
        await rm(dir, { recursive: true, force: true });
      }
    },
  );
