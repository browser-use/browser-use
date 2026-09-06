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
    const result = await s.agent.run('Inspect the page', { maxContextChars: 8000 });
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
