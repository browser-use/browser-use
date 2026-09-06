# Turn a run into a demo

Record the real browser, then export a compact video without repeating its actions.

```ts
import { BrowserUse, exportRecording } from '@browser-use/next';

const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  recording: true,
});
try {
  const result = await agent.run('Complete the task.');
  if (result.recordingPath) {
    await exportRecording(result.recordingPath, {
      output: './demo.mp4',
      title: 'From brief to finished result',
    });
    await exportRecording(result.recordingPath, {
      output: './demo.gif',
      format: 'gif',
    });
  }
} finally {
  await agent.close();
}
```

## What gets captured

Recording is off by default. When enabled, a separate raw-CDP connection samples the current page. Mouse click/scroll, navigation and typing metadata trigger additional capture. Typed text is not recorded in action metadata. Screenshots can still show whatever the page displays.

Frames and `recording.json` live under `.browser-use/recordings/<run-id>/`. The manifest records capture warnings, status and whether the frame budget was exhausted. Default sampling is 750 ms with at most 400 sampled frames plus a final frame. Configure `recording: { intervalMs: 500, maxFrames: 600 }`; interval must be at least 100 ms and the frame cap at most 10,000.

This is a sampled trace, not a lossless screen recording. Rapid intermediate states can be missed. Navigation may invalidate a screenshot; the recorder queues a fresh action frame after an in-flight capture. Capture errors are retained in the manifest. Recording adds CDP work and can change timing, so record the setting in matched performance comparisons.

## The exported cut

The renderer uses a separate local headless Chrome to compose captured screenshots with a title, action caption, progress strip and animated recorded cursor. It never connects to the source browser or reenacts the task. An evenly spaced selection retains the start and final captured frames; the cut is explicitly labeled as edited highlights. The completion label is SDK delivery status, not an independent factual judgment.

MP4 uses H.264; GIF uses a palette pass. Export requires local Chrome and `ffmpeg`; override `executablePath` and `ffmpegPath` when needed. `maxFrames` defaults to 36 and accepts 2–120. `signal` cancels export. Existing output files are never overwritten.

```ts
await exportRecording(path, {
  output: './reviewed-demo.mp4',
  redact: [{ x: 0, y: 80, width: 500, height: 100 }],
});
```

Redaction rectangles use original screenshot pixels and apply to every exported frame. Raw source captures remain intact. Review footage before sharing; text redaction does not cover screenshots, and the exporter cannot infer which customer data is private.

## Try it without a paid model

```sh
npm run demo:session
```

This uses scripted model responses with real Chrome and a local fixture. It creates a workspace, performs a follow-up and exports MP4/GIF. The demo is integration evidence, not an accuracy benchmark.
