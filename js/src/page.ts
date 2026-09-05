import type { Protocol } from 'devtools-protocol';
import { setTimeout as delay } from 'node:timers/promises';
import { CDP } from './cdp.js';
import { positiveInteger } from './protocol.js';

export type Target = number | { role: string; name?: string } | { css: string };
export type AXNode = { id: number; role: string; name: string; value?: string };

/** A tab or an explicit frame execution context. DOM ids expire across navigation. */
export class Page {
  private constructor(
    readonly connection: CDP,
    readonly targetId: string,
    readonly sessionId: string,
    private contextId?: number,
    private frameId?: string,
  ) {}

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
  cdp<
    M extends keyof import('devtools-protocol/types/protocol-mapping.js').ProtocolMapping.Commands,
  >(
    method: M,
    params?: import('devtools-protocol/types/protocol-mapping.js').ProtocolMapping.Commands[M]['paramsType'][0],
  ) {
    return this.connection.send(method, params, this.sessionId);
  }
  async goto(url: string) {
    const result = await this.cdp('Page.navigate', {
      url,
      ...(this.frameId ? { frameId: this.frameId } : {}),
    });
    if (result.errorText) throw new Error(`Navigation failed: ${result.errorText}`);
    if (this.frameId)
      this.contextId = (
        await this.cdp('Page.createIsolatedWorld', {
          frameId: this.frameId,
          worldName: 'browser-use-frame',
        })
      ).executionContextId;
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
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
      ...(this.contextId ? { contextId: this.contextId } : {}),
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
          this.contextId ||
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
    const { nodes } = await this.cdp(
      'Accessibility.getFullAXTree',
      this.frameId ? { frameId: this.frameId } : {},
    );
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
        })),
    };
  }
  async find(target: Target): Promise<number> {
    if (typeof target === 'number') {
      if (!Number.isInteger(target) || target <= 0)
        throw new Error('Expected a positive backend DOM node id.');
      return target;
    }
    const deadline = Date.now() + this.connection.timeoutMs;
    do {
      let ids: number[];
      if ('css' in target) {
        const result = await this.cdp('Runtime.evaluate', {
          expression: `(() => { const nodes=document.querySelectorAll(${JSON.stringify(target.css)}); if(nodes.length>1)throw new Error('Ambiguous CSS target: '+nodes.length+' matches'); return nodes[0]; })()`,
          ...(this.contextId ? { contextId: this.contextId } : {}),
        });
        if (result.exceptionDetails)
          throw new Error(
            result.exceptionDetails.exception?.description ?? result.exceptionDetails.text,
          );
        ids = [];
        if (result.result.objectId) {
          try {
            ids.push(
              (await this.cdp('DOM.describeNode', { objectId: result.result.objectId })).node
                .backendNodeId,
            );
          } finally {
            await this.cdp('Runtime.releaseObject', { objectId: result.result.objectId });
          }
        }
      } else {
        ids = (await this.snapshot()).nodes
          .filter(
            (n) => n.role === target.role && (target.name === undefined || n.name === target.name),
          )
          .map((n) => n.id);
      }
      if (ids.length > 1)
        throw new Error(
          `Ambiguous target: ${ids.length} matches. Inspect and use an exact node id.`,
        );
      if (ids[0]) return ids[0];
      await delay(100);
    } while (Date.now() < deadline);
    throw new Error(
      `Element not found within ${this.connection.timeoutMs} ms: ${JSON.stringify(target)}`,
    );
  }
  private async withNode<T>(
    id: number,
    fn: (this: HTMLElement, arg: unknown) => T,
    arg?: unknown,
  ): Promise<T> {
    const { object } = await this.cdp('DOM.resolveNode', {
      backendNodeId: id,
      ...(this.contextId ? { executionContextId: this.contextId } : {}),
    });
    if (!object.objectId) throw new Error('Element is stale; inspect the page again.');
    try {
      const result = await this.cdp('Runtime.callFunctionOn', {
        objectId: object.objectId,
        functionDeclaration: fn.toString(),
        arguments: [{ value: arg }],
        returnByValue: true,
      });
      if (result.exceptionDetails)
        throw new Error(
          result.exceptionDetails.exception?.description ?? result.exceptionDetails.text,
        );
      return result.result.value as T;
    } finally {
      await this.cdp('Runtime.releaseObject', { objectId: object.objectId });
    }
  }
  async click(target: Target) {
    const id = await this.find(target);
    await this.cdp('DOM.scrollIntoViewIfNeeded', { backendNodeId: id });
    const { model } = await this.cdp('DOM.getBoxModel', { backendNodeId: id });
    const q = model.content;
    const x = (q[0]! + q[2]! + q[4]! + q[6]!) / 4;
    const y = (q[1]! + q[3]! + q[5]! + q[7]!) / 4;
    const enabled = await this.withNode(id, function () {
      return !this.matches(':disabled,[aria-disabled="true"]') && this.getClientRects().length > 0;
    });
    if (!enabled) throw new Error('Element is disabled or hidden.');
    // Do not send a click through an overlay. Hit testing is in the element's document.
    const clear = await this.withNode(id, function () {
      const r = this.getBoundingClientRect();
      let hit = this.ownerDocument.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      while (hit?.shadowRoot) {
        const inner = hit.shadowRoot.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        if (!inner || inner === hit) break;
        hit = inner;
      }
      return hit === this || (hit !== null && this.contains(hit));
    });
    if (!clear) throw new Error('Element is covered. Inspect the page before clicking.');
    await this.clickAt(x, y);
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
  async fill(target: Target, text: string) {
    const id = await this.find(target);
    const editable = await this.withNode(id, function () {
      return (
        !this.matches(':disabled,[readonly]') &&
        (this.isContentEditable ||
          this.matches('input:not([type=file]):not([type=checkbox]):not([type=radio]),textarea'))
      );
    });
    if (!editable) throw new Error('Element is not editable.');
    await this.cdp('DOM.focus', { backendNodeId: id });
    await this.cdp('Input.dispatchKeyEvent', {
      type: 'rawKeyDown',
      key: 'a',
      code: 'KeyA',
      modifiers: 2,
      commands: ['selectAll'],
    });
    await this.cdp('Input.dispatchKeyEvent', {
      type: 'keyUp',
      key: 'a',
      code: 'KeyA',
      modifiers: 2,
    });
    if (text) await this.cdp('Input.insertText', { text });
    else await this.press('Backspace');
  }
  async press(key: string) {
    const codes: Record<string, number> = {
      Enter: 13,
      Tab: 9,
      Escape: 27,
      Backspace: 8,
      ArrowDown: 40,
      ArrowUp: 38,
      ArrowLeft: 37,
      ArrowRight: 39,
      Delete: 46,
    };
    if (!(key in codes))
      throw new Error(
        'Use Enter, Tab, Escape, Backspace, Delete or Arrow keys; raw CDP handles other chords.',
      );
    await this.cdp('Input.dispatchKeyEvent', {
      type: 'keyDown',
      key,
      code: key,
      windowsVirtualKeyCode: codes[key]!,
      ...(key === 'Enter' ? { text: '\r' } : {}),
    });
    await this.cdp('Input.dispatchKeyEvent', {
      type: 'keyUp',
      key,
      code: key,
      windowsVirtualKeyCode: codes[key]!,
    });
  }
  async text(target: Target) {
    return this.withNode(await this.find(target), function () {
      return this.textContent ?? '';
    });
  }
  async select(target: Target, label: string) {
    return this.withNode(
      await this.find(target),
      function (label) {
        if (!(this instanceof HTMLSelectElement) || this.disabled)
          throw new Error('Expected an enabled select.');
        const options = Array.from(this.options).filter((o) => o.label === label);
        if (options.length !== 1 || options[0]!.disabled)
          throw new Error('Select label is missing, ambiguous, or disabled.');
        this.value = options[0]!.value;
        this.dispatchEvent(new Event('input', { bubbles: true }));
        this.dispatchEvent(new Event('change', { bubbles: true }));
        return this.value;
      },
      label,
    );
  }
  async upload(target: Target, files: string[]) {
    await this.cdp('DOM.setFileInputFiles', { backendNodeId: await this.find(target), files });
  }
  async screenshot(options: { quality?: number } = {}) {
    const { data } = await this.cdp('Page.captureScreenshot', {
      format: 'jpeg',
      quality: options.quality ?? 70,
    });
    return Buffer.from(data, 'base64');
  }
  async frames() {
    const { frameTree } = await this.cdp('Page.getFrameTree');
    const frames: Protocol.Page.Frame[] = [];
    const visit = (tree: Protocol.Page.FrameTree) => {
      frames.push(tree.frame);
      tree.childFrames?.forEach(visit);
    };
    visit(frameTree);
    const { targetInfos } = await this.connection.send('Target.getTargets');
    // Chrome omits out-of-process children from their parent's frame tree.
    const remaining = targetInfos.filter((t) => t.type === 'iframe');
    let changed = true;
    while (changed) {
      changed = false;
      for (let i = remaining.length - 1; i >= 0; i--) {
        const target = remaining[i]!;
        if (!frames.some((f) => f.id === target.parentFrameId)) continue;
        remaining.splice(i, 1);
        const { sessionId } = await this.connection.send('Target.attachToTarget', {
          targetId: target.targetId,
          flatten: true,
        });
        try {
          visit((await this.connection.send('Page.getFrameTree', undefined, sessionId)).frameTree);
        } finally {
          await this.connection.send('Target.detachFromTarget', { sessionId });
        }
        changed = true;
      }
    }
    return frames;
  }

  async frame(id: string) {
    // OOPIFs have their own target/session; in-process frames use an isolated world.
    const { targetInfos } = await this.connection.send('Target.getTargets');
    if (targetInfos.some((t) => t.targetId === id && t.type === 'iframe'))
      return Page.attach(this.connection, id);
    const { executionContextId } = await this.cdp('Page.createIsolatedWorld', {
      frameId: id,
      worldName: 'browser-use-frame',
    });
    return new Page(this.connection, this.targetId, this.sessionId, executionContextId, id);
  }
  async close() {
    await this.connection.send('Target.closeTarget', { targetId: this.targetId });
  }
}
