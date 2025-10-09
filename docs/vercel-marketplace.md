# Deploying `browser-use` on Vercel Marketplace

This guide explains how to integrate and deploy **browser-use** as a Vercel Marketplace app.  
It includes setup instructions, configuration steps, and an example deployment to help developers get started quickly.

---

## 📘 Overview

The Vercel Marketplace allows developers to publish integrations and apps that enhance workflows for Vercel users.  
By following this guide, you can make `browser-use` deployable via Vercel and optionally submit it as a Marketplace integration.

**Example Reference:**  
[Vercel Marketplace – X.AI Integration](https://vercel.com/marketplace/xai)

---

## ⚙️ Prerequisites

Before starting, ensure the following:

- You have a **Vercel account** ([sign up here](https://vercel.com/signup)).
- You have **Node.js ≥ 18** and **npm ≥ 9** installed locally.
- You have forked and cloned the [`browser-use`](https://github.com/browser-use/browser-use) repository.
- You are familiar with basic GitHub and Vercel workflows.

---
### Configure Marketplace Environment Variables

The Vercel integration handler needs credentials to communicate with the Marketplace API.

1.  **Retrieve Credentials:** Get your **Integration Client ID** and **Client Secret** from the Vercel Integration Console.
2.  **Set Environment Variables:** Add these to your Vercel project's environment variables (for all environments: Development, Preview, Production).

    ```bash
    # Set the Client ID
    vercel env add INTEGRATION_CLIENT_ID 

    # Set the Client Secret
    vercel env add INTEGRATION_CLIENT_SECRET
    # ---INSERT THE CLOSING FENCE HERE ---
3. **Deploy:** Deploy the integration handler project to Vercel.
    ```bash
    vercel --prod
    ```    ```
###  Configure Marketplace Settings

1.  **Update Marketplace Settings:** Go back to your integration's page in the Vercel Integration Console.
2.  **Set URLs:** Update the **Base URL** and **Redirect URL** to point to your newly deployed Vercel project URL.
    * **Base URL:** `https://your-integration-name.vercel.app`
    * **Redirect Login URL:** `https://your-integration-name.vercel.app/callback`

###  Installation Flow

1.  **Go to Vercel Marketplace:** Open the public URL for your integration.
2.  **Install:** Click the "Install" button. This triggers the OAuth flow, which hits your deployed Vercel integration project (handled by your `browser-use` code).
3.  **Project Linking:** During installation, the integration logic (within your Python/JS code) should handle the provision of resources (if any) and use the **Vercel API** to automatically set a private environment variable (`BROWSER_USE_API_KEY`) on the connected Vercel project(s).

---
