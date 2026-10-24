import type { ProtocolMapping } from 'devtools-protocol/types/protocol-mapping.js';
import {
  approveChromeConnection,
  cdpConnectionOptions,
  validCdpUrl,
  type CdpConnectionOptions,
} from './browser.js';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import WebSocket from 'ws';
import { positiveInteger } from './protocol.js';

type Commands = ProtocolMapping.Commands;
type Events = ProtocolMapping.Events;
type Pending = { resolve(value: unknown): void; reject(error: Error): void };
type Listener = {
  method: string;
  sessionId: string | undefined;
  accept(params: unknown): void;
  reject(error: Error): void;
};

async function discoverEndpoint(url: URL, timeoutMs: number, options: CdpConnectionOptions) {
  return new Promise<string>((resolve, reject) => {
    const request = (url.protocol === 'https:' ? httpsRequest : httpRequest)(
      url,
      {
        ...options.tls,
        headers: options.headers,
        rejectUnauthorized: true,
      },
      (response) => {
        if (response.statusCode !== 200) {
          response.resume();
          reject(new Error(`CDP discovery failed (${response.statusCode}).`));
          return;
        }
        let body = '';
        response.setEncoding('utf8');
        response.on('data', (chunk: string) => {
          body += chunk;
          if (body.length > 1_000_000)
            request.destroy(new Error('CDP discovery response exceeded 1 MB.'));
        });
        response.on('end', () => {
          try {
            const endpoint = JSON.parse(body).webSocketDebuggerUrl;
            if (typeof endpoint !== 'string') throw new Error();
            resolve(endpoint);
          } catch {
            reject(new Error('CDP discovery returned an invalid WebSocket endpoint.'));
          }
        });
        response.on('error', () => reject(new Error('CDP discovery response failed.')));
      },
    );
    const timer = setTimeout(
      () => request.destroy(new Error('CDP discovery timed out.')),
      timeoutMs,
    );
    request.on('close', () => clearTimeout(timer));
    request.on('error', () => reject(new Error('CDP discovery connection failed.')));
    request.end();
  });
}

/** Each connection carries explicit commands and one-shot events through one flattened CDP WebSocket. */
export class CDP {
  private nextId = 0;
  // Shared observation follows protocol sessions across lazy connections.
  private activity = {
    targets: new Map<string, string>(),
    parents: new Map<string, string>(),
    targetId: undefined as string | undefined,
  };
  get observationTargetId() {
    let targetId = this.activity.targetId;
    const visited = new Set<string>();
    while (targetId && this.activity.parents.has(targetId) && !visited.has(targetId)) {
      visited.add(targetId);
      targetId = this.activity.parents.get(targetId);
    }
    return targetId;
  }
  targetForSession(sessionId: string) {
    return this.activity.targets.get(sessionId);
  }
  /** Command observers receive metadata without controlling delivery. */
  observeCommand: ((method: string, params: unknown, sessionId?: string) => void) | undefined;
  /** Result observers can receive page data without controlling command delivery. */
  observeResponse:
    ((method: string, params: unknown, result: unknown, sessionId?: string) => void) | undefined;
  observeEvent: ((method: string, params: unknown, sessionId?: string) => void) | undefined;
  onConnected: (() => void) | undefined;
  private pending = new Map<number, Pending>();
  private listeners = new Set<Listener>();
  private eventObservers = new Set<NonNullable<CDP['observeEvent']>>();
  addEventObserver(observer: NonNullable<CDP['observeEvent']>) {
    this.eventObservers.add(observer);
    return () => this.eventObservers.delete(observer);
  }
  private notifyEvent(method: string, params: unknown, sessionId?: string) {
    for (const observer of [...this.eventObservers, this.observeEvent]) {
      try {
        observer?.(method, params, sessionId);
      } catch {}
    }
  }
  private constructor(
    private socket: WebSocket | undefined,
    readonly timeoutMs: number,
  ) {
    if (!socket) return;
    socket.addEventListener('message', ({ data }) => {
      try {
        const message = JSON.parse(String(data));
        if (message.id !== undefined) {
          const request = this.pending.get(message.id);
          if (message.error)
            request?.reject(new Error(`CDP ${message.error.code}: ${message.error.message}`));
          else request?.resolve(message.result);
        } else {
          this.notifyEvent(message.method, message.params, message.sessionId);
          if (message.method === 'Target.detachedFromTarget')
            this.activity.targets.delete(message.params.sessionId);
          for (const listener of [...this.listeners]) {
            if (listener.method === message.method && listener.sessionId === message.sessionId)
              listener.accept(message.params);
          }
        }
      } catch {
        this.fail(new Error('Malformed CDP message.'));
        socket.close();
      }
    });
    socket.addEventListener('close', () =>
      this.fail(new Error('CDP connection closed. Inspect state before retrying.')),
    );
    socket.addEventListener('error', () => this.fail(new Error('CDP connection failed.')));
  }

  private endpoint: string | undefined;
  private approveConnection = false;
  private connectionOptions: CdpConnectionOptions = {};
  private delegate: Promise<CDP> | undefined;
  private closed = false;

  /** Defer connection until the first browser operation without replaying commands. */
  static lazy(
    endpoint: string,
    timeoutMs = 15_000,
    approveConnection = false,
    options: CdpConnectionOptions = {},
  ) {
    const connection = new CDP(undefined, timeoutMs);
    connection.endpoint = endpoint;
    connection.approveConnection = approveConnection;
    connection.connectionOptions = cdpConnectionOptions(options);
    return connection;
  }
  private connected(): Promise<CDP> {
    if (this.closed) return Promise.reject(new Error('CDP connection is closed.'));
    this.delegate ??= CDP.connect(
      this.endpoint!,
      this.timeoutMs,
      this.approveConnection,
      this.connectionOptions,
    )
      .then((connection) => {
        if (this.closed) {
          connection.close();
          throw new Error('CDP connection is closed.');
        }
        connection.activity = this.activity;
        try {
          this.onConnected?.();
        } catch {}
        connection.observeEvent = (method, params, session) =>
          this.notifyEvent(method, params, session);
        connection.observeCommand = (method, params, sessionId) =>
          this.observeCommand?.(method, params, sessionId);
        return connection;
      })
      .catch((error) => {
        this.delegate = undefined;
        throw error;
      });
    return this.delegate;
  }

  static async connect(
    endpoint: string,
    timeoutMs = 15_000,
    approveConnection = false,
    options: CdpConnectionOptions = {},
  ): Promise<CDP> {
    if (approveConnection && process.platform !== 'darwin')
      throw new Error('Chrome approval is macOS only.');
    positiveInteger('timeoutMs', timeoutMs);
    // Allow browser startup to exceed a short command timeout.
    const connectMs = Math.max(timeoutMs, 15_000);
    const connectionOptions = cdpConnectionOptions(options);
    const url = new URL(validCdpUrl(endpoint));
    if (url.username || url.password)
      throw new Error('Use CDP headers for connection credentials.');
    if (connectionOptions.tls && !['https:', 'wss:'].includes(url.protocol))
      throw new Error('CDP TLS options require an HTTPS or WSS endpoint.');
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      url.pathname = `${url.pathname.replace(/\/$/, '')}/json/version`;
      endpoint = await discoverEndpoint(url, connectMs, connectionOptions);
    } else if (!['ws:', 'wss:'].includes(url.protocol))
      throw new Error('Unsupported CDP endpoint protocol.');
    let websocket: URL;
    try {
      websocket = new URL(endpoint);
    } catch {
      throw new Error('CDP discovery returned an invalid WebSocket endpoint.');
    }
    if (!['ws:', 'wss:'].includes(websocket.protocol) || websocket.username || websocket.password)
      throw new Error('CDP discovery returned an invalid WebSocket endpoint.');
    if (
      (connectionOptions.headers || connectionOptions.tls) &&
      (websocket.host !== url.host || (url.protocol === 'https:' && websocket.protocol !== 'wss:'))
    )
      throw new Error('Authenticated CDP discovery must retain the endpoint host and TLS.');
    const socket = new WebSocket(endpoint, {
      ...connectionOptions.tls,
      headers: connectionOptions.headers,
      rejectUnauthorized: true,
      followRedirects: false,
      handshakeTimeout: connectMs,
    });
    const connection = new CDP(socket, timeoutMs);
    await new Promise<void>((resolve, reject) => {
      const approval = new AbortController();
      const finish = (error?: Error) => {
        approval.abort();
        clearTimeout(timer);
        socket.removeEventListener('open', open);
        socket.removeEventListener('error', failed);
        socket.removeEventListener('close', failed);
        if (error) {
          socket.terminate();
          reject(error);
        } else resolve();
      };
      const open = () => finish();
      const failed = () => finish(new Error('Could not connect to CDP endpoint.'));
      const timer = setTimeout(() => finish(new Error('CDP connection timed out.')), connectMs);
      socket.addEventListener('open', open, { once: true });
      socket.addEventListener('error', failed, { once: true });
      socket.addEventListener('close', failed, { once: true });
      if (approveConnection) {
        void (async () => {
          while (!approval.signal.aborted) {
            await new Promise((resolve) => setTimeout(resolve, 300));
            if (approval.signal.aborted) return;
            if ((await approveChromeConnection(approval.signal)) === 'ready') return;
          }
        })().catch((error) => {
          if (!approval.signal.aborted) finish(error);
        });
      }
    });
    return connection;
  }

  async send<M extends keyof Commands>(
    method: M,
    params: Commands[M]['paramsType'][0] = {} as Commands[M]['paramsType'][0],
    sessionId?: string,
  ): Promise<Commands[M]['returnType']> {
    // Capture the observer at dispatch, so late responses cannot enter a later cell.
    const observe = this.observeResponse;
    const result = this.endpoint
      ? await (await this.connected()).send(method, params, sessionId)
      : await this.sendMessage(method, params, sessionId);
    if (method === 'Target.attachToTarget') {
      const attached = result as Commands['Target.attachToTarget']['returnType'];
      const target = (params as Commands['Target.attachToTarget']['paramsType'][0]).targetId;
      this.activity.targets.set(attached.sessionId, target);
      this.activity.targetId = target;
    } else if (method === 'Target.detachFromTarget') {
      const detached = params as Commands['Target.detachFromTarget']['paramsType'][0];
      if (detached?.sessionId) this.activity.targets.delete(detached.sessionId);
    } else if (method === 'Target.closeTarget' && (result as { success?: boolean }).success) {
      const target = (params as Commands['Target.closeTarget']['paramsType'][0]).targetId;
      if (this.observationTargetId === target || this.activity.targetId === target)
        this.activity.targetId = undefined;
      for (const [id, value] of this.activity.targets)
        if (value === target) this.activity.targets.delete(id);
      this.activity.parents.delete(target);
    }
    if (method === 'Target.getTargets' || method === 'Target.getTargetInfo') {
      const infos =
        method === 'Target.getTargets'
          ? (result as Commands['Target.getTargets']['returnType']).targetInfos
          : [(result as Commands['Target.getTargetInfo']['returnType']).targetInfo];
      for (const info of infos)
        if (info.type === 'iframe' && info.parentFrameId)
          this.activity.parents.set(info.targetId, info.parentFrameId);
    }
    if (method === 'Page.getFrameTree' && sessionId) {
      const targetId = this.targetForSession(sessionId);
      const visit = (tree: import('devtools-protocol').Protocol.Page.FrameTree) => {
        if (targetId && tree.frame.id !== targetId)
          this.activity.parents.set(tree.frame.id, targetId);
        tree.childFrames?.forEach(visit);
      };
      visit((result as Commands['Page.getFrameTree']['returnType']).frameTree);
    }
    try {
      observe?.(method, params, result, sessionId);
    } catch {}
    return result;
  }

  private sendMessage<M extends keyof Commands>(
    method: M,
    params: Commands[M]['paramsType'][0],
    sessionId?: string,
  ): Promise<Commands[M]['returnType']> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN)
      return Promise.reject(new Error('CDP connection is closed.'));
    if (this.pending.size >= 256)
      return Promise.reject(new Error('Too many pending CDP commands (256).'));
    if (sessionId) this.activity.targetId = this.targetForSession(sessionId);
    try {
      this.observeCommand?.(method, params, sessionId);
    } catch {}
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const finish = (error?: Error, value?: unknown) => {
        clearTimeout(timer);
        this.pending.delete(id);
        if (error) reject(error);
        else resolve(value as Commands[M]['returnType']);
      };
      const timer = setTimeout(
        () =>
          finish(
            new Error(`CDP ${method} exceeded ${this.timeoutMs} ms; the action may have happened.`),
          ),
        this.timeoutMs,
      );
      this.pending.set(id, {
        resolve: (value) => finish(undefined, value),
        reject: (error) => finish(error),
      });
      try {
        this.socket!.send(
          JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }),
        );
      } catch (error) {
        finish(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }

  waitFor<M extends keyof Events>(
    method: M,
    options: {
      sessionId?: string;
      timeoutMs?: number;
      signal?: AbortSignal;
      predicate?: (event: Events[M][0]) => boolean;
    } = {},
  ): Promise<Events[M][0]> {
    const timeoutMs = positiveInteger('timeoutMs', options.timeoutMs ?? this.timeoutMs);
    if (this.endpoint)
      return this.connected().then((connection) => connection.waitFor(method, options));
    const promise = new Promise<Events[M][0]>((resolve, reject) => {
      const finish = (error?: Error, value?: unknown) => {
        clearTimeout(timer);
        this.listeners.delete(listener);
        options.signal?.removeEventListener('abort', abort);
        if (error) reject(error);
        else resolve(value as Events[M][0]);
      };
      const listener: Listener = {
        method,
        sessionId: options.sessionId,
        accept: (value) => {
          try {
            if (!options.predicate || options.predicate(value as Events[M][0]))
              finish(undefined, value);
          } catch (e) {
            finish(e instanceof Error ? e : new Error(String(e)));
          }
        },
        reject: (error) => finish(error),
      };
      const abort = () => finish(new Error(`CDP ${method} wait cancelled.`));
      const timer = setTimeout(
        () => finish(new Error(`CDP event ${method} exceeded ${timeoutMs} ms.`)),
        timeoutMs,
      );
      this.listeners.add(listener);
      options.signal?.addEventListener('abort', abort, { once: true });
      if (options.signal?.aborted) abort();
      else if (this.socket?.readyState !== WebSocket.OPEN)
        finish(new Error('CDP connection is closed.'));
    });
    // A caller commonly registers a waiter before an action, then awaits it afterward.
    void promise.catch(() => {});
    return promise;
  }

  private fail(error: Error) {
    for (const request of [...this.pending.values()]) request.reject(error);
    for (const listener of [...this.listeners]) listener.reject(error);
  }
  close() {
    this.closed = true;
    this.eventObservers.clear();
    this.activity.targets.clear();
    this.activity.parents.clear();
    this.activity.targetId = undefined;
    void this.delegate?.then((connection) => connection.close()).catch(() => {});
    this.fail(new Error('CDP connection closed.'));
    this.socket?.close();
  }
}
