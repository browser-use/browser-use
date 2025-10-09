/**
 * Example Vercel Marketplace integration for browser-use
 * ------------------------------------------------------
 * This file exports a simple API handler that runs on Vercel.
 * When deployed, visiting the URL will return a JSON response.
 *
 * File location: pages/api/browser-use.js
 * Access at: https://browser-use.vercel.app/api/browser-use
 */

// Uncomment this if browser-use is installed as a dependency
// import { Browser } from 'browser-use';

export default async function handler(req, res) {
  // Only allow GET requests
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    // Example placeholder logic (replace with browser-use demo if needed)
    const data = {
      project: "browser-use",
      deployment: "Vercel Marketplace Example",
      timestamp: new Date().toISOString(),
      message: "✅ browser-use successfully deployed on Vercel!",
    };

    // Optional: demonstrate a mock browser-use call
    /*
    const browser = new Browser();
    await browser.start();
    const page = await browser.newPage();
    await page.goto('https://example.com');
    const title = await page.title();
    await browser.close();
    data.browserUseExample = `Visited example.com → ${title}`;
    */

    return res.status(200).json(data);
  } catch (error) {
    return res.status(500).json({
      error: "Something went wrong while processing the request.",
      details: error.message,
    });
  }
}
