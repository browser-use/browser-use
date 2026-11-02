# Examples

These examples use the Browser Use gateway and a Cloud browser by default.
One `BROWSER_USE_API_KEY` covers both services.
Create a key in [Browser Use Cloud](https://cloud.browser-use.com/settings?tab=api-keys&new=1).

From this checkout:

```sh
npm ci
npm run build
cp .env.example .env
```

Add your key to `.env`, then run an example:

```sh
node --env-file=.env examples/extract.ts
```

Node 22.19 or later runs these TypeScript files directly.
Bun 1.3.14 or later also supports them, with Node available for the execution worker.
Python package wheels include their own Node runtime.

Set `BROWSER=local` for isolated local Chromium.
Local examples require an installed Chrome or Chromium browser.
Each script closes its browser in `finally`.
Set `WORKSPACE` to choose an output directory.

The research example also supports your real Chrome and existing browser connections:

```sh
BROWSER=chrome node --env-file=.env examples/research.ts "Read my dashboard"
BROWSER_CDP_URL=http://localhost:9222 node --env-file=.env examples/research.ts "Read my page"
```

Enable Chrome remote debugging before connecting your real Chrome.
Set `BROWSER_USE_MODEL=bu-smart` to select another Browser Use model.
An explicit `MODEL=provider/model` overrides that setting and uses the provider's credentials.
See [model configuration](../docs/models.md) for model choices and provider settings.

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
link-cli auth login --client-name "Browser Use Pi" --scope "userinfo:read payment_methods.agentic"
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

The extraction result contains `books` and `csvPath`, an absolute path to the saved CSV. It checks that the file exists and is non-empty before printing a completed result.

Each script limits steps, elapsed time, and estimated model cost.
Cost limits need known prices when you select a different provider.
Cost estimates do not include Cloud browser charges. A stopped run can return partial progress; inspect its status before treating the task as complete.

## Bring your own model key

The [Fireworks example](models/fireworks.py) uses a Fireworks key and a local browser.
Set `FIREWORKS_API_KEY` in `.env`, install local Chromium, and run:

```sh
uv run browser-use install
uv run --env-file .env examples/models/fireworks.py
```

The example selects its model explicitly and does not use the Browser Use model gateway.
