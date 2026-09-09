import { Browser, BrowserUse, Type } from '@browser_use/js';
import { copyFile, mkdir, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const url = process.env.JOB_URL;
const resume = process.env.RESUME_PDF;
const details = process.env.APPLICANT_JSON;
if (!url || !resume || !details)
  throw new Error('Set JOB_URL, RESUME_PDF and APPLICANT_JSON (path to your application details).');
const pdf = await readFile(resume);
if (pdf.subarray(0, 5).toString() !== '%PDF-') throw new Error('RESUME_PDF must be a PDF file.');
const applicant: unknown = JSON.parse(await readFile(details, 'utf8'));
const workspace = resolve(process.env.WORKSPACE || './artifacts/apply-to-job');
await mkdir(workspace, { recursive: true });
if (resolve(resume) !== join(workspace, 'resume.pdf'))
  await copyFile(resume, join(workspace, 'resume.pdf'));
const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY ?? '' })
      : Browser.chromium(),
  workspace,
  researchTools: true,
  telemetry: false,
  log: false,
});
try {
  const result = await agent.run(
    `Prepare the application at ${url} using ONLY these facts:
    ${JSON.stringify(applicant)}
    The real PDF is resume.pdf in the workspace. Attach it and verify the filename in the form.
    For uploads that work with local AND remote Chrome: read the PDF in Node, send its base64
    to page.evaluate, construct a File with type application/pdf from the decoded bytes,
    assign it through DataTransfer to the observed file input, then dispatch input/change events.
    DOM.setFileInputFiles with a local path cannot upload a host file to a remote browser.
    Leave unknown fields blank and report required ones. Do not guess eligibility or protected
    characteristics. Stop at final review, BEFORE submitting or accepting legal declarations.
    Save application-review.md listing filled fields, missing answers and the attached file.`,
    {
      schema: Type.Object({
        resumeAttached: Type.Boolean(),
        filled: Type.Array(Type.String()),
        needsAnswers: Type.Array(Type.String()),
        reviewUrl: Type.String(),
        submitted: Type.Literal(false),
      }),
      maxSteps: 40,
      timeoutMs: 300_000,
      maxCostUsd: 2,
    },
  );
  console.log(result.status, result.status === 'completed' ? result.output : result.text);
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  await agent.close();
}
