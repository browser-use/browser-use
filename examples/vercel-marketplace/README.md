# browser-use Vercel Marketplace Example

This folder contains guidance for creating a minimal Vercel Marketplace starter that demonstrates `browser-use` workflows.

## Recommended structure

- `package.json` – scripts for `build`/`start`/`dev`
- `next.config.js` – optional when using Next.js
- `pages/` or `app/` – a simple UI that triggers browser-use tasks via serverless functions or an API route
- `api/` – Vercel Serverless Functions (if required) that invoke the `browser-use` code
- `public/` – images for the Marketplace listing (banner, icon)

## Minimal pattern

1. Create a Next.js app that provides a simple UI to trigger a demo browser session.
2. Implement an API route that calls into `browser-use` to run the demo (careful with long-running tasks; consider using an external worker or a short-lived job runner).
3. Deploy to Vercel and use the deployed demo URL in the Marketplace listing.

## Deployment notes

- Vercel serverless functions are ideal for short-lived invocations. For longer tasks, run a background worker or external service and use the Vercel function only to enqueue jobs.
- Provide instructions for any required secrets or tokens in the listing.
