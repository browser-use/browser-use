import { CdpSession, createBrowserSession, type BrowserSession } from "./cdp.js";

export interface BrowserOptions {
  useCloud?: boolean;
  cdpUrl?: string;
  cdpHeaders?: Record<string, string>;
  apiKey?: string;
  profileId?: string;
  proxyCountryCode?: string | null;
  timeoutMinutes?: number;
  keepAlive?: boolean;
}

export interface BrowserInfo {
  id?: string;
  liveUrl?: string;
  cdpUrl: string;
  cloud: boolean;
}

/** Owns one persistent CDP session and, optionally, its Browser Use Cloud browser. */
export class Browser {
  readonly options: BrowserOptions;
  session: BrowserSession | undefined;
  info: BrowserInfo | undefined;

  private client: CdpSession | undefined;
  private ownsCloudBrowser = false;

  constructor(options: BrowserOptions = {}) {
    this.options = options;
  }

  async start(): Promise<BrowserInfo> {
    if (this.info && this.session) return this.info;
    const configuredUrl = this.options.cdpUrl
      ?? process.env.BU_CDP_WS
      ?? process.env.BROWSER_CDP_WS
      ?? process.env.BU_CDP_URL
      ?? process.env.BROWSER_USE_CDP_URL;
    const provisioned = configuredUrl ? undefined : await this.provisionCloudBrowser();
    const cdpUrl = configuredUrl ?? readString(provisioned, "cdpUrl", "cdp_url", "cdpWs", "cdp_ws");
    if (!cdpUrl) {
      throw new Error("No browser configured. Pass cdpUrl or set BROWSER_USE_API_KEY to provision Browser Use Cloud.");
    }
    this.client = new CdpSession({
      cdpUrl,
      ...(this.options.cdpHeaders ? { headers: this.options.cdpHeaders } : {}),
    });
    await this.client.connect();
    this.session = createBrowserSession(this.client);
    const id = readString(provisioned, "id");
    const liveUrl = readString(provisioned, "liveUrl", "live_url");
    const info: BrowserInfo = {
      cdpUrl,
      cloud: Boolean(provisioned),
      ...(id ? { id } : {}),
      ...(liveUrl ? { liveUrl } : {}),
    };
    this.info = info;
    return info;
  }

  async close(): Promise<void> {
    await this.client?.close();
    this.client = undefined;
    this.session = undefined;
    if (!this.ownsCloudBrowser || this.options.keepAlive || !this.info?.id) return;
    const apiKey = this.options.apiKey ?? process.env.BROWSER_USE_API_KEY;
    if (!apiKey) return;
    await fetch(`https://api.browser-use.com/api/v3/browsers/${this.info.id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Browser-Use-API-Key": apiKey,
      },
      body: JSON.stringify({ action: "stop" }),
    });
    this.ownsCloudBrowser = false;
  }

  onCallResult(listener: (method: string, params: Record<string, unknown>, result: Record<string, unknown>) => void): () => void {
    if (!this.client) throw new Error("Browser.start() must be called first");
    return this.client.onCallResult(listener);
  }

  private async provisionCloudBrowser(): Promise<Record<string, unknown>> {
    const apiKey = this.options.apiKey ?? process.env.BROWSER_USE_API_KEY;
    if (!apiKey) throw new Error("BROWSER_USE_API_KEY is required when no cdpUrl is supplied");
    const body: Record<string, unknown> = {};
    if (this.options.profileId) body.profileId = this.options.profileId;
    if (this.options.proxyCountryCode !== undefined) body.proxyCountryCode = this.options.proxyCountryCode;
    if (this.options.timeoutMinutes !== undefined) body.timeout = this.options.timeoutMinutes;
    const response = await fetch("https://api.browser-use.com/api/v3/browsers", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Browser-Use-API-Key": apiKey,
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Browser Use Cloud returned HTTP ${response.status}: ${await response.text()}`);
    this.ownsCloudBrowser = true;
    return await response.json() as Record<string, unknown>;
  }
}

function readString(value: unknown, ...keys: string[]): string | undefined {
  if (!value || typeof value !== "object") return undefined;
  const object = value as Record<string, unknown>;
  for (const key of keys) {
    const candidate = object[key];
    if (typeof candidate === "string" && candidate) return candidate;
  }
  return undefined;
}
