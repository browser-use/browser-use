import type { ProtocolMapping } from 'devtools-protocol/types/protocol-mapping.js';
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

/** Explicit commands and one-shot events over one flattened CDP WebSocket. No proxies. */
export class CDP {
  private nextId = 0;
  private pending = new Map<number, Pending>();
  private listeners = new Set<Listener>();
  private constructor(
    private socket: WebSocket,
    readonly timeoutMs: number,
  ) {
    socket.addEventListener('message', ({ data }) => {
      try {
        const message = JSON.parse(String(data));
        if (message.id !== undefined) {
          const request = this.pending.get(message.id);
          if (message.error)
            request?.reject(new Error(`CDP ${message.error.code}: ${message.error.message}`));
          else request?.resolve(message.result);
        } else {
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

  static async connect(endpoint: string, timeoutMs = 15_000): Promise<CDP> {
    positiveInteger('timeoutMs', timeoutMs);
    const url = new URL(endpoint);
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      url.pathname = `${url.pathname.replace(/\/$/, '')}/json/version`;
      const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
      if (!response.ok) throw new Error(`CDP discovery failed (${response.status}).`);
      endpoint = ((await response.json()) as { webSocketDebuggerUrl: string }).webSocketDebuggerUrl;
    } else if (!['ws:', 'wss:'].includes(url.protocol))
      throw new Error('Unsupported CDP endpoint protocol.');
    const socket = new WebSocket(endpoint);
    const connection = new CDP(socket, timeoutMs);
    await new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timer);
        socket.removeEventListener('open', open);
        socket.removeEventListener('error', failed);
        socket.removeEventListener('close', failed);
        if (error) {
          socket.close();
          reject(error);
        } else resolve();
      };
      const open = () => finish();
      const failed = () => finish(new Error('Could not connect to CDP endpoint.'));
      const timer = setTimeout(() => finish(new Error('CDP connection timed out.')), timeoutMs);
      socket.addEventListener('open', open, { once: true });
      socket.addEventListener('error', failed, { once: true });
      socket.addEventListener('close', failed, { once: true });
    });
    return connection;
  }

  send<M extends keyof Commands>(
    method: M,
    params: Commands[M]['paramsType'][0] = {} as Commands[M]['paramsType'][0],
    sessionId?: string,
  ): Promise<Commands[M]['returnType']> {
    if (this.socket.readyState !== WebSocket.OPEN)
      return Promise.reject(new Error('CDP connection is closed.'));
    if (this.pending.size >= 256)
      return Promise.reject(new Error('Too many pending CDP commands (256).'));
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
        this.socket.send(
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
      else if (this.socket.readyState !== WebSocket.OPEN)
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
    this.fail(new Error('CDP connection closed.'));
    this.socket.close();
  }
}
