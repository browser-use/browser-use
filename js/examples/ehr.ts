import { Browser, BrowserUse, Type } from '@browser_use/js';

const url = process.env.EHR_URL;
if (!url) throw new Error('Set EHR_URL to an EHR sandbox containing synthetic patient TEST-1001.');
const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({
          apiKey: process.env.BROWSER_USE_API_KEY ?? '',
          ...(process.env.BROWSER_PROFILE_ID ? { profileId: process.env.BROWSER_PROFILE_ID } : {}),
        })
      : Browser.chromium({ profileDir: `${process.env.WORKSPACE || './artifacts/ehr'}-profile` }),
  workspace: process.env.WORKSPACE || './artifacts/ehr',
  telemetry: false,
  log: false,
});
try {
  // Synthetic source note. Reuse a sandbox login through the browser profile.
  const note = {
    patientId: 'TEST-1001',
    patientName: 'Avery Example',
    dateOfBirth: '1990-01-02',
    subjective: 'Demo visit: patient reports mild left ankle pain after a walk.',
    objective: 'Demo measurements: pulse 72 bpm; blood pressure 118/76 mmHg.',
    assessment: 'Assessment pending clinician review.',
    plan: 'Plan pending clinician review.',
  };
  const result = await agent.run(
    `Open the EHR sandbox at ${url}.
    Find exactly this synthetic patient and verify BOTH identifier and date of birth.
    If either does not match, stop. Create an UNSIGNED DRAFT visit note from this source:
    ${JSON.stringify(note)}
    Preserve the source wording. Do not infer diagnoses, add orders, change medications,
    sign/finalize notes or contact anyone. Save the draft and verify it appears as unsigned.
    If login is needed, stop and report it.`,
    {
      schema: Type.Object({
        patientId: Type.String(),
        draftSaved: Type.Boolean(),
        evidence: Type.String(),
        needsReview: Type.Array(Type.String()),
      }),
      maxSteps: 30,
      timeoutMs: 300_000,
      maxCostUsd: 2,
    },
  );
  console.log(result.status, result.status === 'completed' ? result.output : result.text);
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  await agent.close();
}
