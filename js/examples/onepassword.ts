import { Browser, BrowserUse, Type } from '@browser_use/js';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const url = process.env.LOGIN_URL;
const usernameRef = process.env.OP_USERNAME_REF;
const passwordRef = process.env.OP_PASSWORD_REF;
if (!url || !usernameRef?.startsWith('op://') || !passwordRef?.startsWith('op://'))
  throw new Error(
    'Set LOGIN_URL, OP_USERNAME_REF and OP_PASSWORD_REF. Sign in with the 1Password CLI first.',
  );
const domain = new URL(url).hostname;
if (!['https:', 'http:'].includes(new URL(url).protocol))
  throw new Error('LOGIN_URL must be HTTP(S).');

// Read only the two references chosen by the human. Never expose a vault-reading tool to the model.
async function secret(reference: string) {
  try {
    const { stdout } = await promisify(execFile)('op', ['read', reference, '--no-newline'], {
      timeout: 30_000,
    });
    if (!stdout) throw new Error('Empty secret');
    return stdout;
  } catch {
    // execFile errors may contain stdout. Do not log the original error.
    throw new Error('1Password could not resolve a reference. Check op signin and vault access.');
  }
}
const [username, password] = await Promise.all([secret(usernameRef), secret(passwordRef)]);
const agent = await BrowserUse.create({
  model: process.env.MODEL || 'openrouter/openai/gpt-5.6-luna',
  browser:
    process.env.BROWSER === 'cloud'
      ? Browser.cloud({ apiKey: process.env.BROWSER_USE_API_KEY ?? '' })
      : Browser.chromium(),
  workspace: process.env.WORKSPACE || './artifacts/onepassword',
  allowedDomains: [domain],
  sensitiveData: {
    username: { value: username, domains: [domain] },
    password: { value: password, domains: [domain] },
  },
  telemetry: false,
  log: false,
});
try {
  const result = await agent.run(
    `Log in at ${url} using the named secrets username and password
    with fillSecret. Never read back or print their values. Verify a signed-in page is visible.
    Stop if MFA, a different login domain or a permission request needs the human.
    Do not change account settings or perform any other action.`,
    {
      schema: Type.Object({
        loggedIn: Type.Boolean(),
        evidence: Type.String(),
        needsHuman: Type.Boolean(),
      }),
      maxSteps: 20,
      timeoutMs: 180_000,
      maxCostUsd: 1,
    },
  );
  console.log(result.status, result.status === 'completed' ? result.output : result.text);
  if (result.status !== 'completed') process.exitCode = 1;
} finally {
  await agent.close();
}
