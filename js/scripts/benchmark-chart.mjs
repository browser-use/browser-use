import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

// Offline rendering from retained numeric evidence. Never queries or selects a best run.
const root = new URL('../', import.meta.url);
const read = async (path) => JSON.parse(await readFile(new URL(path, root), 'utf8'));
const [vision, reliability, usage] = await Promise.all([
  read('evidence/vision.json'),
  read('evidence/reliability.json'),
  read('evidence/readme-usage.json'),
]);
const arms = [
  {
    run: vision.runs.find((r) => r.name === 'luna-vision'),
    label: 'bu-pi',
    detail: 'b430a91 · Sep 7, 2026',
    color: '#e65b37',
  },
  {
    run: reliability.runs.find((r) => r.name === 'browsercode-luna'),
    label: 'BrowserCode',
    detail: 'Historical · Aug 20, 2026',
    color: '#6b7280',
  },
];
const expectedIds = Array.from({ length: 60 }, (_, i) => `bub2-${String(i + 1).padStart(3, '0')}`);
for (const { run } of arms) {
  assert.ok(run, 'Missing frozen cohort');
  assert.equal(run.outcomes, 60);
  assert.deepEqual(run.tasks.map((t) => t.task_id).sort(), expectedIds);
  assert.ok(run.tasks.every((t) => Number.isFinite(t.score) && t.score >= 0 && t.score <= 1));
  assert.ok(
    Math.abs((run.tasks.reduce((n, t) => n + t.score, 0) / 60) * 100 - run.mean_percent) < 1e-8,
  );
  assert.ok(Math.abs(run.tasks.reduce((n, t) => n + t.cost, 0) - run.cost_usd) < 1e-8);
}
assert.equal(usage.evaluation_id, arms[0].run.evaluation_id);
assert.deepEqual(usage.tasks.map((t) => t.task_id).sort(), expectedIds);
const metered = usage.tasks.filter((t) => t.metrics !== null);
assert.equal(metered.length, 59);
const totals = Object.fromEntries(
  [
    'input_tokens',
    'output_tokens',
    'cached_input_tokens',
    'cache_write_tokens',
    'total_tokens',
    'total_cost',
  ].map((key) => [
    key,
    metered.reduce((sum, t) => {
      assert.ok(Number.isFinite(t.metrics[key]) && t.metrics[key] >= 0, `Invalid ${key}`);
      return sum + t.metrics[key];
    }, 0),
  ]),
);
assert.equal(
  totals.total_tokens,
  totals.input_tokens +
    totals.output_tokens +
    totals.cached_input_tokens +
    totals.cache_write_tokens,
);
assert.ok(Math.abs(totals.total_cost - arms[0].run.cost_usd) < 1e-8);

const ticks = [0, 25, 50, 75, 100]
  .map(
    (n) => `
  <line x1="${250 + n * 4.1}" x2="${250 + n * 4.1}" y1="162" y2="365" stroke="#e2e0da"/>
  <text x="${250 + n * 4.1}" y="389" text-anchor="middle" class="muted small">${n}</text>`,
  )
  .join('');
const rows = arms
  .map(({ run, label, detail, color }, index) => {
    const y = 212 + index * 113;
    return `
  <text x="38" y="${y - 3}" class="label">${label}</text>
  <text x="38" y="${y + 22}" class="muted small">${detail}</text>
  <rect x="250" y="${y - 27}" width="${run.mean_percent * 4.1}" height="44" rx="4" fill="${color}"/>
  <text x="${262 + run.mean_percent * 4.1}" y="${y + 3}" class="value">${run.mean_percent.toFixed(1)}</text>
  <text x="782" y="${y + 3}" text-anchor="middle" class="value">$${run.cost_usd.toFixed(2)}</text>
  <text x="782" y="${y + 27}" text-anchor="middle" class="muted small">60 assigned tasks</text>`;
  })
  .join('');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 516" role="img" aria-labelledby="title description">
<title id="title">Historical Luna xhigh results on BU_Bench_v2</title>
<desc id="description">bu-pi b430a91: 62.0 out of 100, recorded agent cost $17.86. BrowserCode: 41.2 out of 100, $21.49. Both retain 60 tasks. Different dates and runners. One bu-pi provisioning failure stays at zero. Costs are agent estimates only. This is not a controlled efficiency comparison.</desc>
<style>
text{font-family:Inter,Arial,sans-serif;fill:#20221f}
.muted{fill:#676b63}.small{font-size:13px}.label{font-size:22px;font-weight:700}.value{font-size:23px;font-weight:700}
</style>
<rect width="920" height="516" rx="14" fill="#faf9f6"/>
<text x="38" y="39" font-size="12" font-weight="700" letter-spacing="1.6" fill="#bc4328">BU-PI / HISTORICAL EVALUATION</text>
<text x="38" y="83" font-size="31" font-weight="700">Luna, on 60 real browser tasks.</text>
<text x="38" y="112" font-size="16" class="muted">BU_Bench_v2 · GPT-5.6-luna · xhigh reasoning</text>
<text x="250" y="148" font-size="13" font-weight="700">MEAN SCORE / 100 ↑</text>
<text x="782" y="148" text-anchor="middle" font-size="13" font-weight="700">RECORDED AGENT COST</text>
${ticks}${rows}
<line x1="38" x2="882" y1="415" y2="415" stroke="#deddd6"/>
<text x="38" y="442" class="muted small">Same task IDs. Different dates and runners. Not a controlled efficiency comparison.</text>
<text x="38" y="464" class="muted small">bu-pi: 59 judged + 1 provisioning zero. BrowserCode: 60 judged. Continuous scores, not pass rates.</text>
<text x="38" y="486" class="muted small">Costs exclude judge, browser, and runner. Exact run IDs and accounting: docs/benchmark-overview.md</text>
</svg>
`;
await mkdir(new URL('docs/public/benchmarks/', root), { recursive: true });
await writeFile(new URL('docs/public/benchmarks/luna.svg', root), svg);
console.log(
  JSON.stringify(
    { chart: 'docs/public/benchmarks/luna.svg', metered_tasks: metered.length, totals },
    null,
    2,
  ),
);
