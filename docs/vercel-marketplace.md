# Vercel Marketplace for browser-use

This document explains how to prepare a browser-use integration for publishing on the Vercel Marketplace and includes a minimal example README.

## Overview

`browser-use` is a toolkit to drive browsers programmatically; publishing a Marketplace starter or integration lets users quickly deploy a demo that showcases automated browser workflows or assistant-driven demos.

## What to include

- A GitHub repository with the app source (prefer Next.js for easiest Vercel integration).
- `README.md` with clear deploy steps and any environment variables required.
- A demo URL hosted on Vercel so reviewers can see the integration in action.

## Minimal example

See `examples/vercel-marketplace/README.md` for a minimal example and deployment notes.

### Notes on serverless vs. client

If your integration requires persistent background processing (e.g., multi-tenant browser orchestration), prefer using external services or Vercel Serverless Functions to trigger runs; Vercel function timeouts may limit long-running browser sessions.

## Publishing to the Marketplace

1. Ensure your repo is public and well-documented.
2. Deploy the demo to Vercel and copy the demo URL.
3. Create the Marketplace listing on Vercel, include the repo URL, demo, images, and a short description.

## Example repository

See `examples/vercel-marketplace/README.md` in this project for a minimal guide.
