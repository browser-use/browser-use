import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse, exportRecording } from '../dist/index.js';
const exec = promisify(execFile);
const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });

test('captures actual raw-CDP actions and exports playable MP4/GIF without replay', async () => {
  await exec('ffmpeg', ['-version']); // Explicit integration prerequisite, not a silent skip.
  const workspace = await mkdtemp(join(tmpdir(), 'bu-recording-'));
  const faux = fauxProvider({ tokensPerSecond: 1000000 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    call('javascript', {
      code: `await page.goto(${JSON.stringify('data:text/html,' + encodeURIComponent(`<body style="font:32px system-ui;padding:80px;background:#eff6ff"><h1>Session demo</h1><p id="count">0</p><button onclick="document.getElementById('count').textContent=Number(document.getElementById('count').textContent)+1">Collect record</button></body>`))}); await new Promise(r=>setTimeout(r,160)); await page.click({role:'button',name:'Collect record'}); await new Promise(r=>setTimeout(r,200));`,
    }),
    call('finish', { result: 'Collected one record.' }),
  ]);
  const agent = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    workspace,
    recording: { intervalMs: 150, maxFrames: 60 },
  });
  try {
    const result = await agent.run('Collect one record');
    assert.equal(result.status, 'completed');
    assert.deepEqual(
      agent.history.messages.filter((m) => m.role === 'toolResult' && m.isError),
      [],
    );
    const recording = JSON.parse(await readFile(result.recordingPath, 'utf8'));
    assert.ok(recording.frames.length >= 2);
    assert.ok(
      recording.frames.some((f) => f.label === 'Click' && f.cursor?.click),
      JSON.stringify(recording),
    );
    assert.equal(recording.frames.at(-1).label, 'completed');
    const output = join(workspace, 'demo.mp4');
    await exportRecording(result.recordingPath, {
      output,
      maxFrames: 4,
      redact: [{ x: 0, y: 0, width: 20, height: 20 }],
    });
    assert.ok((await stat(output)).size > 1000);
    const { stdout } = await exec('ffprobe', [
      '-v',
      'error',
      '-select_streams',
      'v:0',
      '-show_entries',
      'stream=codec_name,width,height',
      '-of',
      'json',
      output,
    ]);
    const stream = JSON.parse(stdout).streams[0];
    assert.equal(stream.codec_name, 'h264');
    assert.equal(stream.width, 1440);
    assert.equal(stream.height, 1060);
    const gif = join(workspace, 'demo.gif');
    await exportRecording(result.recordingPath, { output: gif, format: 'gif', maxFrames: 3 });
    assert.equal((await readFile(gif)).subarray(0, 6).toString(), 'GIF89a');
    await assert.rejects(exportRecording(result.recordingPath, { output, maxFrames: 2 }), /EEXIST/);
    assert.equal((await agent.execute("await page.text({css:'#count'})")).text, "'1'");
  } finally {
    await agent.close();
    await rm(workspace, { recursive: true, force: true });
  }
});
