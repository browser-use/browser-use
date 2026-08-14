import WebSocket, { type RawData } from "ws";

type JsonObject = Record<string, unknown>;
type PendingCall = {
  resolve: (value: JsonObject) => void;
  reject: (error: Error) => void;
};
type CdpEvent = { method: string; params: JsonObject; sessionId?: string };
type CallListener = (method: string, params: JsonObject, result: JsonObject) => void;

const ROOT_DOMAINS = new Set(["Browser", "Target"]);
const INTERNAL_URL_PREFIXES = ["chrome://", "devtools://", "chrome-extension://"];

export interface CdpSessionOptions {
  cdpUrl: string;
  headers?: Record<string, string>;
}

/** Small flattened-session CDP client used by browser_execute. */
export class CdpSession {
  readonly cdpUrl: string;
  readonly headers: Record<string, string>;
  activeSessionId?: string;
  activeTargetId?: string;

  private socket: WebSocket | undefined;
  private nextId = 1;
  private readonly pending = new Map<number, PendingCall>();
  private readonly eventListeners = new Set<(event: CdpEvent) => void>();
  private readonly callListeners = new Set<CallListener>();

  constructor(options: CdpSessionOptions) {
    this.cdpUrl = options.cdpUrl;
    this.headers = options.headers ?? {};
  }

  async connect(): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) return;
    const wsUrl = await resolveWebSocketUrl(this.cdpUrl, this.headers);
    this.socket = await new Promise<WebSocket>((resolve, reject) => {
      const socket = new WebSocket(wsUrl, { headers: this.headers });
      const onError = (error: Error) => reject(error);
      socket.once("error", onError);
      socket.once("open", () => {
        socket.off("error", onError);
        resolve(socket);
      });
    });
    this.socket.on("message", (data) => this.consume(data));
    this.socket.on("close", () => this.failPending(new Error("CDP connection closed")));
    this.socket.on("error", (error) => this.failPending(error));
    await this.ensurePage();
  }

  async close(): Promise<void> {
    const socket = this.socket;
    this.socket = undefined;
    this.eventListeners.clear();
    if (!socket || socket.readyState === WebSocket.CLOSED) return;
    await new Promise<void>((resolve) => {
      socket.once("close", () => resolve());
      socket.close();
      setTimeout(resolve, 1_000).unref();
    });
  }

  async call(method: string, params: JsonObject = {}, session?: string | null): Promise<JsonObject> {
    if (this.socket?.readyState !== WebSocket.OPEN) await this.connect();
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error("CDP is not connected");
    const id = this.nextId++;
    const domain = method.split(".", 1)[0] ?? "";
    const routedSession = session === undefined
      ? (ROOT_DOMAINS.has(domain) ? undefined : this.activeSessionId)
      : (session ?? undefined);
    const payload: JsonObject = { id, method, params };
    if (routedSession) payload.sessionId = routedSession;
    const result = await new Promise<JsonObject>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      socket.send(JSON.stringify(payload), (error) => {
        if (!error) return;
        this.pending.delete(id);
        reject(error);
      });
    });
    for (const listener of this.callListeners) listener(method, params, result);
    return result;
  }

  async use(targetId: string): Promise<string> {
    if (targetId === this.activeTargetId && this.activeSessionId) return this.activeSessionId;
    const attached = await this.call("Target.attachToTarget", { targetId, flatten: true }, null);
    const sessionId = attached.sessionId;
    if (typeof sessionId !== "string" || !sessionId) throw new Error(`Could not attach to target ${targetId}`);
    this.activeTargetId = targetId;
    this.activeSessionId = sessionId;
    await Promise.all([
      this.call("Page.enable", {}, sessionId),
      this.call("Runtime.enable", {}, sessionId),
      this.call("DOM.enable", {}, sessionId),
    ]);
    return sessionId;
  }

  waitFor(method: string, timeoutMs = 30_000, sessionId = this.activeSessionId): Promise<JsonObject> {
    return handled(new Promise<JsonObject>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.eventListeners.delete(listener);
        reject(new Error(`Timed out waiting for ${method}`));
      }, timeoutMs);
      const listener = (event: CdpEvent) => {
        if (event.method !== method || (sessionId && event.sessionId !== sessionId)) return;
        clearTimeout(timeout);
        this.eventListeners.delete(listener);
        resolve(event.params);
      };
      this.eventListeners.add(listener);
    }));
  }

  onCallResult(listener: CallListener): () => void {
    this.callListeners.add(listener);
    return () => this.callListeners.delete(listener);
  }

  onEvent(method: string, listener: (params: JsonObject) => void, sessionId = this.activeSessionId): () => void {
    const wrapped = (event: CdpEvent) => {
      if (event.method !== method || (sessionId && event.sessionId !== sessionId)) return;
      try {
        listener(event.params);
      } catch {
        // CDP events arrive outside the snippet promise; a listener must not crash the agent process.
      }
    };
    this.eventListeners.add(wrapped);
    return () => this.eventListeners.delete(wrapped);
  }

  private async ensurePage(): Promise<void> {
    const response = await this.call("Target.getTargets", {}, null);
    const targets = Array.isArray(response.targetInfos) ? response.targetInfos : [];
    const pages = targets.filter((target): target is JsonObject => {
      if (!target || typeof target !== "object") return false;
      const value = target as JsonObject;
      return value.type === "page";
    });
    const preferred = pages.find((target) => {
      const url = typeof target.url === "string" ? target.url : "";
      return !INTERNAL_URL_PREFIXES.some((prefix) => url.startsWith(prefix));
    }) ?? pages[0];
    let targetId = preferred?.targetId;
    if (typeof targetId !== "string" || !targetId) {
      const created = await this.call("Target.createTarget", { url: "about:blank" }, null);
      targetId = created.targetId;
    }
    if (typeof targetId !== "string" || !targetId) throw new Error("CDP did not provide a page target");
    await this.use(targetId);
  }

  private consume(raw: RawData): void {
    let message: JsonObject;
    try {
      message = JSON.parse(raw.toString()) as JsonObject;
    } catch {
      return;
    }
    if (typeof message.id === "number") {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error && typeof message.error === "object") {
        const error = message.error as JsonObject;
        const detail = typeof error.message === "string" ? error.message : JSON.stringify(error);
        pending.reject(new Error(`${detail}${error.data ? `: ${String(error.data)}` : ""}`));
      } else {
        pending.resolve(message.result && typeof message.result === "object" ? message.result as JsonObject : {});
      }
      return;
    }
    if (typeof message.method !== "string") return;
    const event: CdpEvent = {
      method: message.method,
      params: message.params && typeof message.params === "object" ? message.params as JsonObject : {},
    };
    if (typeof message.sessionId === "string") event.sessionId = message.sessionId;
    for (const listener of this.eventListeners) listener(event);
  }

  private failPending(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error);
    this.pending.clear();
  }
}

export type BrowserSession = {
  connect: () => Promise<void>;
  close: () => Promise<void>;
  use: (targetId: string) => Promise<string>;
  waitFor: (method: string, timeoutMs?: number, sessionId?: string) => Promise<JsonObject>;
  cdp: (method: string, params?: JsonObject, session?: string | null) => Promise<JsonObject>;
  readonly activeTargetId?: string;
  readonly activeSessionId?: string;
  readonly domains: Record<string, unknown>;
  [domain: string]: unknown;
};

/** Build the small dynamic `session.Page.navigate(...)` surface shown to the model. */
export function createBrowserSession(client: CdpSession): BrowserSession {
  const domainCache = new Map<string, object>();
  const fixed: Record<string, unknown> = {
    connect: () => handled(client.connect()),
    close: () => handled(client.close()),
    use: (targetId: string) => handled(client.use(targetId)),
    waitFor: (method: string, timeoutMs?: number, sessionId?: string) => client.waitFor(method, timeoutMs, sessionId),
    cdp: (method: string, params: JsonObject = {}, session?: string | null) => handled(client.call(method, params, session)),
  };
  return new Proxy(fixed, {
    get(target, property, receiver) {
      if (property === "activeTargetId") return client.activeTargetId;
      if (property === "activeSessionId") return client.activeSessionId;
      if (property === "domains") return new Proxy({}, { get: (_unused, domain) => getDomain(String(domain)) });
      if (Reflect.has(target, property)) return Reflect.get(target, property, receiver);
      if (typeof property !== "string") return undefined;
      return getDomain(property);
    },
  }) as BrowserSession;

  function getDomain(domain: string): object {
    const existing = domainCache.get(domain);
    if (existing) return existing;
    const proxy = new Proxy({}, {
      get: (_target, method) => {
        if (typeof method !== "string") return undefined;
        if (method === "on") {
          return (event: string, listener: (params: JsonObject) => void) => client.onEvent(`${domain}.${event}`, listener);
        }
        return (paramsOrListener: JsonObject | ((params: JsonObject) => void) = {}) => {
          if (typeof paramsOrListener === "function") {
            return client.onEvent(`${domain}.${method}`, paramsOrListener);
          }
          return handled(client.call(`${domain}.${method}`, paramsOrListener));
        };
      },
    });
    domainCache.set(domain, proxy);
    return proxy;
  }
}

function handled<T>(promise: Promise<T>): Promise<T> {
  void promise.catch(() => {});
  return promise;
}

async function resolveWebSocketUrl(endpoint: string, headers: Record<string, string>): Promise<string> {
  if (endpoint.startsWith("ws://") || endpoint.startsWith("wss://")) return endpoint;
  const response = await fetch(`${endpoint.replace(/\/$/, "")}/json/version`, { headers });
  if (!response.ok) throw new Error(`CDP version endpoint returned HTTP ${response.status}`);
  const version = await response.json() as JsonObject;
  const wsUrl = version.webSocketDebuggerUrl;
  if (typeof wsUrl !== "string" || !wsUrl) throw new Error("CDP version response had no webSocketDebuggerUrl");
  return wsUrl;
}
