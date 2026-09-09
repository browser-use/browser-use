import type { Protocol } from 'devtools-protocol';
import { setTimeout as delay } from 'node:timers/promises';
import { CDP } from './cdp.js';
import { positiveInteger } from './protocol.js';

export type AXNode = {
  id: number;
  role: string;
  name: string;
  value?: string;
  /** Present only when Chrome reports this state; absence does not mean false. */
  checked?: boolean | 'mixed';
  pressed?: boolean | 'mixed';
  selected?: boolean;
  expanded?: boolean;
  disabled?: boolean;
};

function controlState(node: Protocol.Accessibility.AXNode) {
  const state: Pick<AXNode, 'checked' | 'pressed' | 'selected' | 'expanded' | 'disabled'> = {};
  for (const { name, value } of node.properties ?? []) {
    const observed = value.value;
    if (name === 'checked' || name === 'pressed') {
      if (observed === 'mixed') state[name] = 'mixed';
      else if (observed === true || observed === 'true') state[name] = true;
      else if (observed === false || observed === 'false') state[name] = false;
    } else if (
      (name === 'selected' || name === 'expanded' || name === 'disabled') &&
      typeof observed === 'boolean'
    ) {
      state[name] = observed;
    }
  }
  return state;
}

/** A tab with explicit CDP, page evaluation and observation. No selector/action layer. */
export class Page {
  private constructor(
    readonly connection: CDP,
    public targetId: string,
    public sessionId: string,
  ) {}

  private initialize: (() => Promise<Page>) | undefined;
  private initializing: Promise<void> | undefined;
  static deferred(connection: CDP, initialize: () => Promise<Page>, targetId = '') {
    const page = new Page(connection, targetId, '');
    page.initialize = initialize;
    return page;
  }
  private async ready() {
    if (!this.initialize) return;
    this.initializing ??= this.initialize()
      .then((page) => {
        this.targetId = page.targetId;
        this.sessionId = page.sessionId;
        this.initialize = undefined;
      })
      .finally(() => {
        this.initializing = undefined;
      });
    await this.initializing;
  }
  static async attach(connection: CDP, targetId: string) {
    const { sessionId } = await connection.send('Target.attachToTarget', {
      targetId,
      flatten: true,
    });
    const page = new Page(connection, targetId, sessionId);
    try {
      await page.cdp('Page.enable');
      await page.cdp('Runtime.enable');
      return page;
    } catch (error) {
      // The caller never receives this page, so it cannot release the failed attachment.
      await connection.send('Target.detachFromTarget', { sessionId }).catch(() => {});
      throw error;
    }
  }
  async cdp<
    M extends keyof import('devtools-protocol/types/protocol-mapping.js').ProtocolMapping.Commands,
  >(
    method: M,
    params?: import('devtools-protocol/types/protocol-mapping.js').ProtocolMapping.Commands[M]['paramsType'][0],
  ) {
    await this.ready();
    return this.connection.send(method, params, this.sessionId);
  }
  async goto(url: string) {
    const result = await this.cdp('Page.navigate', { url });
    if (result.errorText) throw new Error(`Navigation failed: ${result.errorText}`);
    await this.waitFor(() => document.readyState !== 'loading');
    return this.info();
  }
  async info() {
    return this.evaluate(() => ({ url: location.href, title: document.title }));
  }
  async evaluate<T, A = undefined>(
    fn: ((argument: A) => T) | string,
    argument?: A,
  ): Promise<Awaited<T>> {
    const expression =
      typeof fn === 'string'
        ? fn
        : `(${fn.toString()})(${JSON.stringify(argument) ?? 'undefined'})`;
    const response = await this.cdp('Runtime.evaluate', {
      expression,
      // Bound synchronous execution in Chrome too; rejecting a CDP promise does not stop it.
      timeout: this.connection.timeoutMs,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (response.exceptionDetails)
      throw new Error(
        response.exceptionDetails.exception?.description ?? response.exceptionDetails.text,
      );
    return response.result.value as Awaited<T>;
  }
  async waitFor<A = undefined>(
    fn: (arg: A) => unknown,
    argument?: A,
    options: { timeoutMs?: number } = {},
  ) {
    const timeoutMs = positiveInteger('timeoutMs', options.timeoutMs ?? this.connection.timeoutMs);
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        if (await this.evaluate(fn, argument)) return;
      } catch (error) {
        if (
          !(error instanceof Error) ||
          !/Execution context was destroyed|Cannot find context|Cannot find default execution context/.test(
            error.message,
          )
        )
          throw error;
      }
      await delay(Math.min(100, Math.max(0, deadline - Date.now())));
    }
    throw new Error(`Page condition exceeded ${timeoutMs} ms.`);
  }
  async snapshot(): Promise<{ url: string; title: string; nodes: AXNode[] }> {
    const { nodes } = await this.cdp('Accessibility.getFullAXTree');
    return {
      ...(await this.info()),
      nodes: nodes
        .filter((n) => !n.ignored && n.backendDOMNodeId)
        .map((n) => ({
          id: n.backendDOMNodeId!,
          role: String(n.role?.value ?? ''),
          name: String(n.name?.value ?? '')
            .replace(/\s+/g, ' ')
            .trim(),
          ...(n.value ? { value: String(n.value.value) } : {}),
          ...controlState(n),
        })),
    };
  }
  async clickAt(x: number, y: number) {
    if (![x, y].every(Number.isFinite)) throw new Error('Coordinates must be finite.');
    await this.cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await this.cdp('Input.dispatchMouseEvent', {
      type: 'mousePressed',
      x,
      y,
      button: 'left',
      clickCount: 1,
    });
    await this.cdp('Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x,
      y,
      button: 'left',
      clickCount: 1,
    });
  }
  async screenshot(options: { quality?: number } = {}) {
    const { data } = await this.cdp('Page.captureScreenshot', {
      format: 'jpeg',
      quality: options.quality ?? 70,
    });
    return Buffer.from(data, 'base64');
  }
  async close() {
    await this.ready();
    await this.connection.send('Target.closeTarget', { targetId: this.targetId });
  }
}

/** Tab ownership stays explicit. Attached caller tabs are never included in cleanup. */
export class Tabs {
  constructor(
    readonly cdp: CDP,
    private own: (id: string) => void,
  ) {}
  async list() {
    return (await this.cdp.send('Target.getTargets')).targetInfos.filter((t) => t.type === 'page');
  }
  async open(url = 'about:blank') {
    const { targetId } = await this.cdp.send('Target.createTarget', { url: 'about:blank' });
    this.own(targetId);
    const page = await Page.attach(this.cdp, targetId);
    if (url !== 'about:blank') await page.goto(url);
    return page;
  }
  async get(id: string) {
    return Page.attach(this.cdp, id);
  }
}
