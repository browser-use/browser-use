import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

// Render the frozen concurrent pair. No live queries or best-run selection.
const root = new URL('../', import.meta.url);
const report = JSON.parse(
  await readFile(new URL('evidence/confirmation3-luna.json', root), 'utf8'),
);
const expectedIds = Array.from({ length: 60 }, (_, i) => `bub2-${String(i + 1).padStart(3, '0')}`);
const arms = [
  {
    name: 'candidate',
    label: 'bu-pi candidate',
    color: '#e65b37',
    sha: '29e2b5e49f6bcd8d9f1ecf1b737d143488abfb2b',
  },
  {
    name: 'reference',
    label: 'bu-pi reference',
    color: '#7b8078',
    sha: 'c3f7fac2d8a46a3801e06d89a3c3c9b1343db79e',
  },
].map((arm) => {
  const run = report.arms[arm.name];
  assert.equal(run.sdk_sha, arm.sha);
  assert.equal(run.complete, true);
  assert.equal(run.assigned, 60);
  assert.equal(run.actual_judgments, 60);
  assert.equal(run.inputs.model, 'gpt-5.6-luna');
  assert.equal(JSON.parse(run.inputs.options_json).reasoning_effort, 'xhigh');
  const tasks = Object.values(run.tasks);
  assert.deepEqual(tasks.map((task) => task.task_id).sort(), expectedIds);
  const sum = (key) =>
    tasks.reduce((total, task) => {
      assert.ok(Number.isFinite(task[key]) && task[key] >= 0, `Missing or invalid ${key}`);
      return total + task[key];
    }, 0);
  assert.ok(tasks.every((task) => task.actual_judgment && task.score <= 1));
  assert.ok(Math.abs((sum('score') / 60) * 100 - run.score_per_100) < 1e-8);
  assert.ok(Math.abs(sum('cost') - run.recorded_agent_cost_usd) < 1e-8);
  const tokens = sum('total_tokens');
  assert.equal(
    tokens,
    sum('input_tokens') +
      sum('output_tokens') +
      sum('cached_input_tokens') +
      sum('cache_write_tokens'),
  );
  return { ...arm, run, tokens };
});
const [candidate, reference] = arms;
for (const key of [
  'platform_ref',
  'dataset',
  'model',
  'judge',
  'judge_model',
  'max_steps',
  'max_parallel',
  'timeout_minutes',
]) {
  assert.equal(candidate.run.inputs[key], reference.run.inputs[key], `Unmatched ${key}`);
}
for (const key of ['options_json', 'judge_options_json']) {
  assert.deepEqual(
    JSON.parse(candidate.run.inputs[key]),
    JSON.parse(reference.run.inputs[key]),
    `Unmatched ${key}`,
  );
}
assert.equal(report.comparison.confirmation_eligible, true);
const paired = report.comparison.assigned_comparison;
assert.equal(paired.n, 60);
assert.ok(
  Math.abs(candidate.run.score_per_100 - reference.run.score_per_100 - paired.mean_delta_pp) < 1e-8,
);
const format = (n) => n.toFixed(2);
const tokenDelta = (candidate.tokens / reference.tokens - 1) * 100;
const costDelta =
  (candidate.run.recorded_agent_cost_usd / reference.run.recorded_agent_cost_usd - 1) * 100;
const ticks = [0, 25, 50, 75, 100]
  .map(
    (n) => `
  <line x1="${252 + n * 3.6}" x2="${252 + n * 3.6}" y1="163" y2="338" stroke="#e2e0da"/>
  <text x="${252 + n * 3.6}" y="360" text-anchor="middle" class="muted small">${n}</text>`,
  )
  .join('');
const rows = arms
  .map(({ run, label, color, tokens }, i) => {
    const y = 210 + i * 96;
    return `
  <text x="36" y="${y}" class="label">${label}</text>
  <text x="36" y="${y + 24}" class="muted small">${run.sdk_sha.slice(0, 7)} · 60/60 judged</text>
  <rect x="252" y="${y - 25}" width="${run.score_per_100 * 3.6}" height="43" rx="4" fill="${color}"/>
  <text x="${264 + run.score_per_100 * 3.6}" y="${y + 4}" class="value">${format(run.score_per_100)}</text>
  <text x="705" y="${y + 4}" text-anchor="middle" class="value">$${format(run.recorded_agent_cost_usd)}</text>
  <text x="854" y="${y + 4}" text-anchor="middle" class="value">${(tokens / 1e6).toFixed(1)}M</text>`;
  })
  .join('');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 556" role="img" aria-labelledby="title description">
<title id="title">Concurrent bu-pi comparison: Luna xhigh on BU_Bench_v2</title>
<desc id="description">Candidate ${format(candidate.run.score_per_100)}/100 versus reference ${format(reference.run.score_per_100)}/100, all 60 tasks judged per arm. Agent costs $${format(candidate.run.recorded_agent_cost_usd)} versus $${format(reference.run.recorded_agent_cost_usd)}. Total reported tokens ${candidate.tokens} versus ${reference.tokens}. Paired score difference +${format(paired.mean_delta_pp)} points, 95% interval +${format(paired.ci95_pp[0])} to +${format(paired.ci95_pp[1])}. More tokens and cost, not an efficiency win. Development benchmark, not held-out SOTA.</desc>
<style>
text{font-family:Inter,Arial,sans-serif;fill:#20221f}
.muted{fill:#676b63}.small{font-size:13px}.label{font-size:22px;font-weight:700}.value{font-size:23px;font-weight:700}
</style>
<rect width="960" height="556" rx="14" fill="#faf9f6"/>
<text x="36" y="36" font-size="12" font-weight="700" letter-spacing="1.6">BU-PI / CONCURRENT EVALUATION</text>
<text x="36" y="80" font-size="31" font-weight="700">Same model. Same 60 tasks.</text>
<text x="36" y="110" font-size="16" class="muted">BU_Bench_v2 · Luna xhigh · September 8, 2026 · matched budgets and judge</text>
<text x="252" y="149" font-size="12" font-weight="700">MEAN SCORE / 100 ↑</text>
<text x="705" y="149" text-anchor="middle" font-size="12" font-weight="700">AGENT COST</text>
<text x="854" y="149" text-anchor="middle" font-size="12" font-weight="700">TOTAL TOKENS</text>
${ticks}${rows}
<line x1="36" x2="924" y1="386" y2="386" stroke="#deddd6"/>
<text x="36" y="419" font-size="20" font-weight="700">+${format(paired.mean_delta_pp)} score points</text>
<text x="322" y="419" font-size="15" class="muted">Paired 95% interval: [+${format(paired.ci95_pp[0])}, +${format(paired.ci95_pp[1])}]</text>
<text x="36" y="451" font-size="15">${format(tokenDelta)}% more reported tokens · ${format(costDelta)}% more agent cost. No efficiency gain.</text>
<text x="36" y="485" class="muted small">Continuous scores, not pass rates. Tokens include repeated cached context and compaction.</text>
<text x="36" y="507" class="muted small">Costs exclude judge, browser, and runner. Previously inspected development tasks, not held-out SOTA.</text>
<text x="36" y="529" class="muted small">Candidate is the latest fully evaluated runtime, not current HEAD. Run IDs: docs/benchmark-overview.md</text>
</svg>
`;
await mkdir(new URL('docs/public/benchmarks/', root), { recursive: true });
await writeFile(new URL('docs/public/benchmarks/luna.svg', root), svg);
console.log(
  JSON.stringify(
    {
      chart: 'docs/public/benchmarks/luna.svg',
      arms: arms.map(({ name, run, tokens }) => ({
        name,
        evaluation_id: run.evaluation_id,
        score: run.score_per_100,
        cost: run.recorded_agent_cost_usd,
        tokens,
      })),
      tokenDelta,
      costDelta,
    },
    null,
    2,
  ),
);
