import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse, Type } from '../dist/index.js';
import { startFixture } from '../examples/fixture.mjs';
import { SYSTEM_PROMPT } from '../dist/prompt.js';
import { imageDimensions } from '../dist/images.js';

let fixture;
before(async () => {
  fixture = await startFixture();
});
after(async () => {
  await fixture?.close();
});

async function session(responses, config = {}) {
  const faux = fauxProvider({ tokensPerSecond: 1_000_000 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses(responses);
  const workspace = await mkdtemp(join(tmpdir(), 'bu-agent-test-'));
  const agent = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    browser: process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
    workspace,
    ...config,
  });
  return {
    agent,
    faux,
    close: async () => {
      await agent.close();
      await rm(workspace, { recursive: true, force: true });
    },
  };
}
const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });

test('Pi loop reads a real browser and returns schema-validated data with events', async () => {
  const s = await session([
    call('javascript', {
      code: `await page.goto(${JSON.stringify(fixture.url)}); console.log(JSON.stringify(await page.evaluate(() => Array.from(document.querySelectorAll('article h2'), el => el.textContent))))`,
    }),
    (context) => {
      assert.ok(
        context.systemPrompt.includes(
          `Workspace directory (JSON string): ${JSON.stringify(s.agent.workspace)}`,
        ),
      );
      const result = context.messages.findLast((m) => m.role === 'toolResult');
      assert.equal(result.isError, false);
      return call('finish', { result: { products: JSON.parse(result.content[0].text) } });
    },
  ]);
  try {
    const events = [];
    const result = await s.agent.run('List the products.', {
      schema: Type.Object({ products: Type.Array(Type.String()) }),
      onEvent: (e) => {
        events.push(e.type);
      },
    });
    assert.equal(result.status, 'completed');
    assert.deepEqual(result.output, { products: ['Atlas', 'Orbit'] });
    assert.equal(result.steps, 2);
    assert.ok(events.includes('tool_execution_end'));
    assert.ok(events.includes('agent_end'));
    assert.equal(s.faux.state.callCount, 2);
  } finally {
    await s.close();
  }
});
test('invalid structured output is rejected, then the model can repair it', async () => {
  const s = await session([
    call('finish', { result: { count: 'wrong' } }),
    (context) => {
      assert.equal(context.messages.at(-1).isError, true);
      return call('finish', { result: { count: 2 } });
    },
  ]);
  try {
    const result = await s.agent.run('Count products', {
      schema: Type.Object({ count: Type.Number() }),
    });
    assert.equal(result.status, 'completed');
    assert.equal(result.output.count, 2);
  } finally {
    await s.close();
  }
});
test('a completed result blocks later browser mutations in the same model batch', async () => {
  const s = await session([
    fauxAssistantMessage(
      [
        fauxToolCall('finish', { result: 'done' }),
        fauxToolCall('javascript', { code: "throw new Error('must not run')" }),
      ],
      { stopReason: 'toolUse' },
    ),
  ]);
  try {
    const result = await s.agent.run('Finish');
    assert.equal(result.status, 'completed');
    assert.equal(result.output, 'done');
  } finally {
    await s.close();
  }
});
test('step limits stop the loop without inventing a completed result', async () => {
  const s = await session([
    call('javascript', { code: '42' }),
    call('finish', { result: 'unreachable' }),
  ]);
  try {
    const result = await s.agent.run('Loop', { maxSteps: 1 });
    assert.equal(result.status, 'max_steps');
    assert.equal(result.output, undefined);
    assert.equal(s.faux.state.callCount, 1);
  } finally {
    await s.close();
  }
});
test('model failures and plain unfinished answers are distinct from completion', async () => {
  const s = await session([
    fauxAssistantMessage('partial', { stopReason: 'error', errorMessage: 'provider unavailable' }),
    fauxAssistantMessage('I will start'),
    fauxAssistantMessage('Still unfinished'),
  ]);
  try {
    const failure = await s.agent.run('Research');
    assert.equal(failure.status, 'error');
    assert.match(failure.error, /provider unavailable/);
    assert.equal((await s.agent.run('Research')).status, 'incomplete');
  } finally {
    await s.close();
  }
});
test('pre-cancelled runs make no model request', async () => {
  const s = await session([call('finish', { result: 'not called' })]);
  try {
    const result = await s.agent.run('Stop', { signal: AbortSignal.abort() });
    assert.equal(result.status, 'cancelled');
    assert.equal(s.faux.state.callCount, 0);
  } finally {
    await s.close();
  }
});
test('wall-clock timeout cancels an active cell and the session recovers', async () => {
  const s = await session([call('javascript', { code: 'await new Promise(() => {})' })]);
  try {
    await s.agent.execute('42');
    const result = await s.agent.run('Wait', { timeoutMs: 200 });
    assert.equal(result.status, 'timeout');
    assert.equal((await s.agent.execute('42')).text, '42');
  } finally {
    await s.close();
  }
});
test('custom typed tools and preflight rejection use the same Pi contract', async () => {
  let executed = 0;
  const s = await session(
    [
      call('lookup', { id: 'A' }),
      (context) => {
        assert.match(context.messages.at(-1).content[0].text, /blocked by application/);
        return call('finish', { result: 'denied' });
      },
    ],
    {
      tools: [
        {
          name: 'lookup',
          label: 'Lookup',
          description: 'Look up a record',
          parameters: Type.Object({ id: Type.String() }),
          execute: async () => {
            executed++;
            return { content: [{ type: 'text', text: 'secret' }], details: {} };
          },
        },
      ],
      beforeToolCall: async ({ toolCall }) =>
        toolCall.name === 'lookup' ? { block: true, reason: 'blocked by application' } : undefined,
    },
  );
  try {
    assert.equal((await s.agent.run('Lookup A')).output, 'denied');
    assert.equal(executed, 0);
  } finally {
    await s.close();
  }
});
test('invalid budgets and model IDs fail explicitly', async () => {
  await assert.rejects(BrowserUse.create({ model: 'openai/not-a-model' }), /Unknown model/);
  const s = await session([]);
  try {
    await assert.rejects(s.agent.run('task', { maxSteps: 0 }), /positive integer/);
    await assert.rejects(s.agent.run('task', { maxCostUsd: NaN }), /finite positive/);
  } finally {
    await s.close();
  }
});

test('cost and context limits preserve partial state without claiming completion', async () => {
  const expensive = call('javascript', { code: '42' });

  const cost = await session([expensive]);
  const costEvents = (event) => {
    if (event.type === 'message_end' && event.message.role === 'assistant') {
      event.message.usage.cost.total = 1;
    }
  };
  try {
    const result = await cost.agent.run('Work', { maxCostUsd: 0.01, onEvent: costEvents });
    assert.equal(result.status, 'cost_limit');
    assert.ok(result.usage.cost.total >= 0.01);
  } finally {
    await cost.close();
  }
  const context = await session([call('javascript', { code: '42' })]);
  try {
    assert.equal(
      (await context.agent.run('Work', { maxContextChars: 10 })).status,
      'context_limit',
    );
  } finally {
    await context.close();
  }
});

test('native screenshot bytes do not consume the text-context budget', async () => {
  const s = await session([
    call('javascript', {
      code: `await page.goto(${JSON.stringify(fixture.url)}); await screenshot()`,
    }),
    call('finish', { result: 'saw the page' }),
  ]);
  try {
    const result = await s.agent.run('Inspect the page', {
      maxContextChars: SYSTEM_PROMPT.length + 2000,
    });
    assert.equal(result.status, 'completed');
  } finally {
    await s.close();
  }
});

test('delivers a large existing value exactly, independent of observation truncation', async () => {
  const rows = Array.from({ length: 455 }, (_, id) => ({
    id,
    text: 'record-' + id + '-'.repeat(200),
  }));
  const s = await session(
    [
      call('javascript', {
        code: `const rows = ${JSON.stringify(rows)}; console.log(JSON.stringify(rows))`,
      }),
      (context) => {
        assert.match(context.messages.at(-1).content[0].text, /Truncated/);
        return call('finish_from_js', { expression: 'rows' });
      },
    ],
    { maxOutputChars: 100 },
  );
  try {
    const result = await s.agent.run('Deliver every row', {
      schema: Type.Array(Type.Object({ id: Type.Number(), text: Type.String() })),
    });
    assert.equal(result.status, 'completed');
    assert.deepEqual(result.output, rows);
    assert.equal(result.text, JSON.stringify(rows));
    assert.equal(result.finishRepairs, 0);
  } finally {
    await s.close();
  }
});

test('runtime delivery rejects invalid and lossy values, then repairs without losing state', async () => {
  const bad = [
    '({count:"wrong"})',
    '({count:NaN})',
    '({count:undefined})',
    '({count:1n})',
    '(()=>{const a={};a.a=a;return a})()',
  ];
  const s = await session([
    call('javascript', { code: 'const verified = {count:200}' }),
    ...bad.map((expression, i) => (context) => {
      if (i) assert.equal(context.messages.at(-1).isError, true);
      return call('finish_from_js', { expression });
    }),
    (context) => {
      assert.equal(context.messages.at(-1).isError, true);
      return call('finish_from_js', { expression: 'verified' });
    },
    call('finish', { result: 'next run' }),
  ]);
  try {
    const result = await s.agent.run('Count', { schema: Type.Object({ count: Type.Number() }) });
    assert.equal(result.status, 'completed');
    assert.deepEqual(result.output, { count: 200 });
    assert.equal((await s.agent.run('New task')).output, 'next run');
  } finally {
    await s.close();
  }
});

test('runtime completion blocks later actions in the same model batch', async () => {
  const s = await session([
    call('javascript', { code: 'let mutations = 0; const answerText = "verified"' }),
    fauxAssistantMessage(
      [
        fauxToolCall('finish_from_js', { expression: 'answerText' }),
        fauxToolCall('javascript', { code: 'mutations++' }),
      ],
      { stopReason: 'toolUse' },
    ),
  ]);
  try {
    assert.equal((await s.agent.run('Deliver')).output, 'verified');
    assert.equal((await s.agent.execute('mutations')).text, '0');
  } finally {
    await s.close();
  }
});

test('one empty-ending repair delivers existing records with the same transcript and budgets', async () => {
  const s = await session([
    call('javascript', {
      code: 'const records = Array.from({length:200}, (_,id)=>({id})); let mutations = 1',
    }),
    fauxAssistantMessage(''),
    (context) => {
      assert.match(context.messages.at(-1).content[0].text, /single delivery repair/);
      assert.deepEqual(
        context.tools.map((t) => t.name),
        ['finish', 'finish_from_js'],
      );
      return call('finish_from_js', { expression: 'JSON.stringify(records)' });
    },
  ]);
  try {
    const result = await s.agent.run('Deliver all', { maxSteps: 3 });
    assert.equal(result.status, 'completed');
    assert.equal(JSON.parse(result.output).length, 200);
    assert.equal(result.steps, 3);
    assert.equal(result.finishRepairs, 1);
    assert.equal((await s.agent.execute('mutations')).text, '1');
  } finally {
    await s.close();
  }
});

test('missing-finish repair never resets exhausted step, cost, context or cancellation budgets', async () => {
  for (const [options, expected] of [
    [{ maxSteps: 1 }, 'max_steps'],
    [
      {
        maxCostUsd: 0.01,
        onEvent: (e) => {
          if (e.type === 'message_end' && e.message.role === 'assistant')
            e.message.usage.cost.total = 1;
        },
      },
      'cost_limit',
    ],
    [{ maxContextChars: 100 }, 'context_limit'],
  ]) {
    const s = await session([fauxAssistantMessage(''), call('finish', { result: 'unreachable' })]);
    try {
      const result = await s.agent.run('Deliver', options);
      assert.equal(result.status, expected);
      assert.equal(result.finishRepairs, 0);
      // Oversized input now stops before the first provider request.
      assert.equal(s.faux.state.callCount, expected === 'context_limit' ? 0 : 1);
    } finally {
      await s.close();
    }
  }
  const controller = new AbortController();
  const s = await session([fauxAssistantMessage('')]);
  try {
    const result = await s.agent.run('Deliver', {
      signal: controller.signal,
      onEvent: (e) => {
        if (e.type === 'agent_end') controller.abort();
      },
    });
    assert.equal(result.status, 'cancelled');
    assert.equal(result.finishRepairs, 0);
    assert.equal(s.faux.state.callCount, 1);
  } finally {
    await s.close();
  }
});

test('repair is one turn even when it calls an invalid finish', async () => {
  const s = await session([
    fauxAssistantMessage('partial evidence'),
    call('finish_from_js', { expression: 'undefined' }),
    call('finish', { result: 'unreachable' }),
  ]);
  try {
    const result = await s.agent.run('Deliver');
    assert.equal(result.status, 'incomplete');
    assert.equal(result.finishRepairs, 1);
    assert.equal(result.text, 'partial evidence');
    assert.equal(result.steps, 2);
    assert.equal(s.faux.state.callCount, 2);
  } finally {
    await s.close();
  }
});

test('repair remains under the original deadline', async () => {
  const s = await session([
    fauxAssistantMessage(''),
    call('finish_from_js', { expression: 'await new Promise(()=>{})' }),
  ]);
  try {
    await s.agent.execute('42');
    const result = await s.agent.run('Deliver', { timeoutMs: 200 });
    assert.equal(result.status, 'timeout');
    assert.equal(result.finishRepairs, 1);
    assert.equal((await s.agent.execute('42')).text, '42');
  } finally {
    await s.close();
  }
});

test('automatic Pi compaction resumes the same run, preserves constraints and accounts for summary calls', async () => {
  let work = 0,
    summaries = 0;
  const response = (context) => {
    if (!context.tools?.length) {
      summaries++;
      return fauxAssistantMessage(
        'Task: inspect only; never purchase. Progress in memory and notes.json. Continue remaining observations.',
      );
    }
    assert.match(JSON.stringify(context.messages), /never purchase/);
    if (++work > 8) return call('finish', { result: 'done' });
    return call('javascript', { code: "console.log('evidence '.repeat(800))" });
  };
  const s = await session(
    Array.from({ length: 20 }, () => response),
    { maxOutputChars: 8000 },
  );
  try {
    const result = await s.agent.run('Inspect only; never purchase.', {
      maxSteps: 20,
      maxContextChars: 35000,
    });
    assert.equal(result.status, 'completed');
    assert(summaries > 0);
    assert.equal(result.compactions, summaries);
    assert.equal(result.steps, 9);
    assert.equal(s.faux.state.callCount, 9 + summaries);
    assert.match(JSON.stringify(s.agent.history.messages), /never purchase/);
  } finally {
    await s.close();
  }
});

test('agent retrieves an observation omitted by compaction without repeating its source action', async () => {
  let work = 0;
  let retrieving = false;
  let sourceActions = 0;
  const sourceCode = "console.log('inventory_units=73')";
  const response = (context) => {
    if (!context.tools?.length)
      return fauxAssistantMessage('Continue the task; the exact count was omitted.');
    if (retrieving) return call('finish_from_js', { expression: 'String(recoveredUnits)' });
    const checkpoint = context.messages.find(
      (m) =>
        m.role === 'user' &&
        typeof m.content === 'string' &&
        m.content.includes('Evidence archive (JSON path):'),
    );
    if (checkpoint) {
      assert.doesNotMatch(JSON.stringify(context.messages), /inventory_units=73/);
      const path = JSON.parse(
        checkpoint.content.match(/^Evidence archive \(JSON path\): (.+)$/m)[1],
      );
      retrieving = true;
      return call('javascript', {
        code: `const evidence = JSON.parse(require('node:fs').readFileSync(${JSON.stringify(path)}, 'utf8')); const observation = evidence.messages.filter(m => m.role === 'toolResult').flatMap(m => m.content).find(c => c.type === 'text' && c.text.includes('inventory_units=')); const recoveredUnits = Number(observation.text.match(/inventory_units=(\\d+)/)[1]);`,
      });
    }
    return call('javascript', {
      code: work++ === 0 ? sourceCode : "console.log('unrelated evidence '.repeat(400))",
    });
  };
  const s = await session(
    Array.from({ length: 20 }, () => response),
    { maxOutputChars: 10000 },
  );
  try {
    const result = await s.agent.run('Return the observed inventory count.', {
      maxSteps: 20,
      maxContextChars: 35000,
      onEvent: (e) => {
        if (e.type === 'tool_execution_start' && e.args.code === sourceCode) sourceActions++;
      },
    });
    assert.equal(result.status, 'completed');
    assert.equal(result.output, '73');
    assert(result.compactions >= 1);
    assert.equal(sourceActions, 1);
  } finally {
    await s.close();
  }
});

test('transient failed inference retries once without executing the failed response tools', async () => {
  const failed = fauxAssistantMessage(
    fauxToolCall('javascript', { code: "throw new Error('must not execute')" }),
    {
      stopReason: 'error',
      errorMessage: 'OpenAI Responses stream ended before a terminal response event',
    },
  );
  const s = await session([failed, call('finish', { result: 'recovered' })]);
  try {
    const events = [];
    const result = await s.agent.run('Inspect', { onEvent: (e) => events.push(e.type) });
    assert.equal(result.status, 'completed');
    assert.equal(result.providerRetries, 1);
    assert.equal(s.faux.state.callCount, 2);
    assert.equal(events.filter((x) => x === 'tool_execution_start').length, 1);
  } finally {
    await s.close();
  }
});

test('the agent can recover a prior observation window from its live redacted journal', async () => {
  let journalPath;
  const s = await session(
    [
      call('javascript', {
        code: `await page.goto(${JSON.stringify(fixture.url)}); console.log(JSON.stringify(await page.evaluate(() => { globalThis.journalReads = (globalThis.journalReads ?? 0) + 1; return {value:'journal-sample', separator:'line\u2028separator', secret:'journal-secret', observedAt:Date.now()}; })));`,
      }),
      (context) => {
        const match = context.systemPrompt.match(/^Run journal \(JSON path\): (.+)$/m);
        assert.ok(match, 'The live journal must be discoverable before delivery.');
        journalPath = JSON.parse(match[1]);
        return call('javascript', {
          code: `var journalText = require('node:fs').readFileSync(${JSON.stringify(journalPath)}, 'utf8');
var journalEvents = journalText.split('\\n').filter(Boolean).map(JSON.parse);
var observedEnd = journalEvents.find(e => e.event?.type === 'tool_execution_end' && e.event.result?.content?.some(c => c.type === 'text' && c.text.includes('journal-sample')));
var observedStart = journalEvents.find(e => e.event?.type === 'tool_execution_start' && e.event.toolCallId === observedEnd.event.toolCallId);
var journalRecovered = {observation:JSON.parse(observedEnd.event.result.content.find(c=>c.type==='text').text), startedAt:observedStart.timestamp, endedAt:observedEnd.timestamp, recoveredAt:Date.now(), redacted:!journalText.includes('journal-' + 'secret')};`,
        });
      },
      call('finish_from_js', {
        expression:
          'JSON.stringify({...journalRecovered, readCount:await page.evaluate(()=>globalThis.journalReads)})',
      }),
    ],
    { redact: ['journal-secret'] },
  );
  try {
    const result = await s.agent.run('Recover the original observation and its execution window.');
    assert.equal(result.status, 'completed', result.error);
    assert.equal(result.eventsPath, journalPath);
    const recovered = JSON.parse(result.output);
    assert.deepEqual(recovered.observation, {
      value: 'journal-sample',
      separator: 'line\u2028separator',
      secret: '[REDACTED]',
      observedAt: recovered.observation.observedAt,
    });
    assert.ok(recovered.startedAt <= recovered.observation.observedAt);
    assert.ok(recovered.observation.observedAt <= recovered.endedAt);
    assert.ok(recovered.endedAt <= recovered.recoveredAt);
    assert.equal(recovered.redacted, true);
    assert.equal(recovered.readCount, 1);
    let followUpPath;
    s.faux.setResponses([
      (context) => {
        followUpPath = JSON.parse(
          context.systemPrompt.match(/^Run journal \(JSON path\): (.+)$/m)[1],
        );
        return call('finish', { result: 'continued' });
      },
    ]);
    const next = await s.agent.followUp('Continue with a new run journal.');
    assert.equal(next.status, 'completed');
    assert.equal(next.eventsPath, followUpPath);
    assert.notEqual(followUpPath, journalPath);
  } finally {
    await s.close();
  }
});

for (const errorMessage of [
  'Sorry, something went wrong.',
  'server_error: Sorry, something went wrong.',
  'Unable to verify model access right now. Please retry.',
  'An error occurred while processing your request. You can retry your request, or contact us through our help center at help.openai.com if the error persists. Please include the request ID req_fixture in your message.',
]) {
  test(`explicit temporary provider failure preserves prior work: ${errorMessage.split('.')[0]}`, async () => {
    const s = await session([
      call('javascript', { code: 'let deliveredRows = [{value:42}]; let mutations = 1;' }),
      fauxAssistantMessage(
        fauxToolCall('javascript', { code: 'mutations++; deliveredRows = [];' }),
        {
          stopReason: 'error',
          errorMessage,
        },
      ),
      call('finish_from_js', { expression: 'JSON.stringify({rows:deliveredRows,mutations})' }),
    ]);
    try {
      const result = await s.agent.run('Return the collected rows.');
      assert.equal(result.status, 'completed');
      assert.deepEqual(JSON.parse(result.output), { rows: [{ value: 42 }], mutations: 1 });
      assert.equal(result.providerRetries, 1);
      assert.equal(s.faux.state.callCount, 3);
    } finally {
      await s.close();
    }
  });
}

test('provider recovery keeps original budgets and never becomes a repeated retry loop', async () => {
  for (const scenario of [
    'steps',
    'cost',
    'cancel',
    'permanent',
    'repeated',
    'temporary-repeated',
    'processing-repeated',
    'generic-repeated',
    'access-denied',
    'generic-with-denial',
  ]) {
    const retryAllowed = [
      'repeated',
      'temporary-repeated',
      'processing-repeated',
      'generic-repeated',
    ].includes(scenario);
    const controller = new AbortController();
    const failure = () =>
      fauxAssistantMessage(
        fauxToolCall('javascript', { code: "throw new Error('not executed')" }),
        {
          stopReason: 'error',
          errorMessage:
            {
              permanent: 'Invalid API key',
              'temporary-repeated': 'Unable to verify model access right now. Please retry.',
              'processing-repeated':
                'An error occurred while processing your request. You can retry your request, or contact support.',
              'access-denied': 'You do not have access to this model.',
              'generic-repeated': 'Sorry, something went wrong.',
              'generic-with-denial':
                'Sorry, something went wrong. You do not have access to this model.',
            }[scenario] ?? 'socket hang up',
        },
      );
    const s = await session([failure(), failure(), call('finish', { result: 'must not run' })]);
    let tools = 0;
    try {
      const result = await s.agent.run('Inspect without repeating actions', {
        maxSteps: scenario === 'steps' ? 1 : 10,
        maxCostUsd: scenario === 'cost' ? 0.01 : undefined,
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === 'tool_execution_start') tools++;
          if (event.type === 'message_end' && event.message.role === 'assistant') {
            if (scenario === 'cost') event.message.usage.cost.total = 0.02;
            if (scenario === 'cancel') controller.abort();
          }
        },
      });
      assert.equal(
        result.status,
        {
          steps: 'max_steps',
          cost: 'cost_limit',
          cancel: 'cancelled',
          permanent: 'error',
          repeated: 'error',
          'temporary-repeated': 'error',
          'processing-repeated': 'error',
          'generic-repeated': 'error',
          'access-denied': 'error',
          'generic-with-denial': 'error',
        }[scenario],
        scenario,
      );
      assert.equal(result.providerRetries, retryAllowed ? 1 : 0, scenario);
      assert.equal(s.faux.state.callCount, retryAllowed ? 2 : 1, scenario);
      assert.equal(tools, 0, scenario);
      assert.equal(result.finishRepairs, 0, scenario);
      if (scenario === 'cost') assert.equal(result.usage.cost.total, 0.02);
    } finally {
      await s.close();
    }
  }
});

test('saving an explicit page screenshot also supplies the image to the next model turn', async () => {
  const s = await session([
    call('javascript', {
      code: `await page.goto(${JSON.stringify(fixture.url)}); await page.screenshot({quality:70}).then(bytes => artifact('visual-check.jpg', bytes))`,
    }),
    (context) => {
      const result = context.messages.findLast((m) => m.role === 'toolResult');
      const images = result.content.filter((part) => part.type === 'image');
      assert.equal(images.length, 1);
      assert.equal(images[0].mimeType, 'image/jpeg');
      assert.equal(Buffer.from(images[0].data, 'base64')[0], 0xff);
      return call('finish', { result: 'Image received' });
    },
  ]);
  try {
    const result = await s.agent.run('Inspect the mobile rendering');
    assert.equal(result.status, 'completed');
    assert.equal(result.output, 'Image received');
  } finally {
    await s.close();
  }
});

test('a full-page image exceeding provider patch limits reaches the next model turn as a bounded preview', async () => {
  const s = await session([
    call('javascript', {
      code: `await page.goto(${JSON.stringify(fixture.url)}); await page.evaluate(() => { document.body.style.height='22000px'; }); await page.cdp('Page.captureScreenshot', {format:'jpeg',quality:60,captureBeyondViewport:true,clip:{x:0,y:0,width:1440,height:22000,scale:1}}).then(r => artifact('original.jpg', Buffer.from(r.data,'base64')));`,
    }),
    (context) => {
      const result = context.messages.findLast((m) => m.role === 'toolResult');
      const images = result.content.filter((part) => part.type === 'image');
      assert.equal(images.length, 1);
      const size = imageDimensions(Buffer.from(images[0].data, 'base64'));
      assert.ok(size.width <= 2000 && size.height <= 2000);
      assert.match(
        result.content.find((part) => part.type === 'text').text,
        /model preview.*unreadable text/,
      );
      return call('finish', { result: 'Preview received; original retained' });
    },
  ]);
  try {
    const result = await s.agent.run('Capture the full page');
    assert.equal(result.status, 'completed');
    assert.equal(result.output, 'Preview received; original retained');
  } finally {
    await s.close();
  }
});

test('a failed JavaScript cell retains native images and target metadata through Pi and hooks', async () => {
  let hookSawEvidence = false;
  const s = await session(
    [
      call('javascript', {
        code: `await page.goto(${JSON.stringify(fixture.url)}); await page.click({role:'button',name:'Save selection'}); await screenshot(); throw new Error('failure after capture')`,
      }),
      (context) => {
        const result = context.messages.at(-1);
        assert.equal(result.isError, true);
        assert.match(result.content[0].text, /failure after capture/);
        assert.match(result.content[0].text, /State reset: false/);
        assert.equal(result.content.filter((part) => part.type === 'image').length, 1);
        return call('javascript', { code: "await page.text({role:'status'})" });
      },
      (context) => {
        const result = context.messages.at(-1);
        assert.equal(result.isError, false);
        assert.match(result.content[0].text, /Saved 1 time/);
        assert.equal(result.content.filter((part) => part.type === 'image').length, 0);
        return call('finish', { result: 'retained without replay' });
      },
    ],
    {
      afterToolCall(call) {
        if (!call.isError) return;
        assert.equal(call.result.content.filter((part) => part.type === 'image').length, 1);
        assert.ok(call.result.details.targetId);
        assert.ok(call.result.details.observationTargetId);
        assert.ok(call.result.details.outputFile);
        hookSawEvidence = true;
      },
    },
  );
  const events = [];
  try {
    const result = await s.agent.run('Retain evidence through a failed cell.', {
      onEvent: (event) => {
        if (event.type === 'tool_execution_end') events.push(event);
      },
    });
    assert.equal(result.status, 'completed');
    assert.equal(hookSawEvidence, true);
    const failed = events.find((event) => event.toolName === 'javascript' && event.isError);
    assert.ok(failed?.result.details.targetId);
    assert.equal(failed.result.details.observationTargetId, failed.result.details.targetId);
    assert.equal(failed.result.content.filter((part) => part.type === 'image').length, 1);
  } finally {
    await s.close();
  }
});
