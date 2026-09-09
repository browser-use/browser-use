# Examples

Plain TypeScript. `.mjs` is JavaScript explicitly marked as an ES module; the examples use `.ts` so your editor checks the SDK calls.

From this checkout:

```sh
npm ci && npm run build
cp .env.example .env # fill the two API keys
node --env-file=.env examples/extract.ts
# or: bun --env-file=.env examples/extract.ts
```

Node 22.19+ runs these files directly. Bun 1.3.14+ also needs Node for the execution worker. npm and pnpm are package managers, not runtimes.

Set `BROWSER=cloud` for Browser Use Cloud, or `BROWSER=local` for isolated local Chrome. Local Chrome must be installed. Each script closes its browser in `finally`. Use `WORKSPACE` to choose where files go.

| Example                            | What you get                                       | Extra environment variables                                   |
| ---------------------------------- | -------------------------------------------------- | ------------------------------------------------------------- |
| [extract.ts](extract.ts)           | Ten verified books, typed records, CSV             | Optional `START_URL`                                          |
| [qa.ts](qa.ts)                     | Bug report, screenshots, partial findings, GIF     | `START_URL` (staging); ffmpeg + local Chrome for GIF export   |
| [ehr.ts](ehr.ts)                   | An unsigned note for a synthetic patient           | `EHR_URL`; optional cloud `BROWSER_PROFILE_ID`                |
| [form.ts](form.ts)                 | A submitted demo pizza form, verified response     | Optional `START_URL`                                          |
| [stripe-link.ts](stripe-link.ts)   | Link-approved test card prefilling                 | `CHECKOUT_URL`, `PURCHASE`; Link CLI login                    |
| [onepassword.ts](onepassword.ts)   | Login using two selected vault secrets             | `LOGIN_URL`, `OP_USERNAME_REF`, `OP_PASSWORD_REF`; `op` login |
| [apply-to-job.ts](apply-to-job.ts) | Filled application, attached PDF, review checklist | `JOB_URL`, `RESUME_PDF`, `APPLICANT_JSON`                     |
| [research.ts](research.ts)         | A streamed answer to your own task                 | Task as command-line argument                                 |

## Credentials and payments

**1Password:** install the [official CLI](https://developer.1password.com/docs/cli/), sign in, and select references such as `op://Test/Login/username` and `op://Test/Login/password`. The host reads those two fields. The model receives names and uses `fillSecret`; it gets no vault-reading tool. MFA stops for a human.

**Link:** install `@stripe/link-cli@0.18.0` and put its `link-cli` executable on PATH. Check `link-cli auth status --format json`. For a new session:

```sh
link-cli auth login --client-name "Browser Use JS" --scope "userinfo:read payment_methods.agentic"
```

For an existing session missing payment access, use `auth upgrade` with the same scope. The example inspects a test checkout, creates a `--test` card request, prints its approval URL, waits up to eight minutes, then prefills and cancels the unused request. It never clicks Pay. It supports ordinary card forms, not Link Pay Tokens or HTTP 402 flows. Keep the checkout directly revisitable: preflight and filling use separate browsers.

Credentials stay out of normal logs and recordings are disabled in these examples. Screenshots are **not pixel-redacted**, and agent-written code has filesystem/network access. Domain rules are navigation controls, not a sandbox. Use test accounts in an isolated environment.

## EHR and job applications

The EHR example requires a sandbox containing patient `TEST-1001`, Avery Example, born `1990-01-02`. It checks both identifiers and saves only an unsigned draft. Local login persists in `artifacts/ehr-profile`; cloud login needs your profile ID.

The job example reads facts from your JSON file and attaches a real PDF by transferring bytes into the browser, so uploads also work remotely. It leaves unknown answers blank and stops before submission. For example:

```json
{
  "name": "Avery Example",
  "email": "avery@example.com",
  "phone": "202-555-0142",
  "experience": "Two years building TypeScript applications"
}
```

Each script caps steps, time and cost. A stopped run can return partial progress; inspect its status before treating the task as complete.
