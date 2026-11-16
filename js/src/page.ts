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

const contextLost =
  /Execution context was destroyed|Cannot find context|Cannot find default execution context/;

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

/** key -> [windowsVirtualKeyCode, code, text], as browser-harness press_key sends them. */
const NAMED_KEYS: Record<string, [number, string, string]> = {
  Enter: [13, 'Enter', '\r'],
  Tab: [9, 'Tab', '\t'],
  Backspace: [8, 'Backspace', ''],
  Escape: [27, 'Escape', ''],
  Delete: [46, 'Delete', ''],
  ' ': [32, 'Space', ' '],
  ArrowLeft: [37, 'ArrowLeft', ''],
  ArrowUp: [38, 'ArrowUp', ''],
  ArrowRight: [39, 'ArrowRight', ''],
  ArrowDown: [40, 'ArrowDown', ''],
  Home: [36, 'Home', ''],
  End: [35, 'End', ''],
  PageUp: [33, 'PageUp', ''],
  PageDown: [34, 'PageDown', ''],
};
const PUNCTUATION_KEYS: Record<string, [string, number]> = {
  '`': ['Backquote', 192],
  '-': ['Minus', 189],
  '=': ['Equal', 187],
  '[': ['BracketLeft', 219],
  ']': ['BracketRight', 221],
  '\\': ['Backslash', 220],
  ';': ['Semicolon', 186],
  "'": ['Quote', 222],
  ',': ['Comma', 188],
  '.': ['Period', 190],
  '/': ['Slash', 191],
};
const SHIFTED: Record<string, string> = Object.fromEntries(
  [...'~!@#$%^&*()_+{}|:"<>?'].map((c, i) => [c, "`1234567890-=[]\\;',./"[i]!]),
);
/** [code, virtual key, needs Shift] for one printable ASCII character on a US layout; undefined otherwise. */
function printableKey(char: string): [string, number, boolean] | undefined {
  const base = SHIFTED[char] ?? char;
  const shift = char in SHIFTED || (char !== char.toLowerCase() && char === char.toUpperCase());
  if (/^[a-z]$/i.test(base))
    return [`Key${base.toUpperCase()}`, base.toUpperCase().charCodeAt(0), shift];
  if (/^[0-9]$/.test(base)) return [`Digit${base}`, base.charCodeAt(0), shift];
  const punctuation = PUNCTUATION_KEYS[base];
  return punctuation && [punctuation[0], punctuation[1], shift];
}

const ENABLE_WAIT_MS = 4000;
/** Waits for a command up to ms; its result or failure is ignored either way. */
async function bounded(command: Promise<unknown>, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  await Promise.race([
    command.catch(() => {}),
    new Promise((resolve) => (timer = setTimeout(resolve, ms))),
  ]);
  clearTimeout(timer);
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
    // Python 1.0.5 (browser-harness daemon _enable_default_domains): the enables run in parallel, each awaited at most
    // 4 s, and a slow or failed one never fails the attach; a late one still takes effect. Waiting 20 s for each in turn
    // and throwing failed 32 BU Bench cells with "Page.enable exceeded 20000 ms", mostly tabs.get on a background tab.
    await Promise.all([
      bounded(page.cdp('Page.enable'), ENABLE_WAIT_MS),
      bounded(page.cdp('Runtime.enable'), ENABLE_WAIT_MS),
    ]);
    return page;
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
    // A document still parsing after the wait is returned, not thrown: Python 1.0.5's goto_url/new_tab return once
    // the navigation commits and its wait_for_load() returns False. Throwing ended 31 BU Bench cells mid-batch
    // ("Page condition exceeded 20000 ms" from goto/tabs.open), including loops and Promise.all over URLs.
    await this.waitFor(() => document.readyState !== 'loading').catch((error: unknown) => {
      if (!(error instanceof Error) || !error.message.startsWith('Page condition exceeded'))
        throw error;
    });
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
        if (!(error instanceof Error) || !contextLost.test(error.message)) throw error;
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
  /** Inserts text into the focused element (Python type_text). */
  async typeText(text: string) {
    await this.cdp('Input.insertText', { text: String(text) });
  }
  /** One key press with US-layout key, code and key code (Python press_key). Modifiers: 1 Alt, 2 Ctrl, 4 Meta, 8 Shift. */
  async pressKey(key: string, modifiers = 0) {
    let [vk, code, text] = NAMED_KEYS[key] ?? [0, key, ''];
    if (!NAMED_KEYS[key] && [...key].length === 1) {
      text = key;
      const resolved = printableKey(key);
      [code, vk] = resolved ? [resolved[0], resolved[1]] : ['', 0];
      if (resolved?.[2] && !(modifiers & 7)) modifiers |= 8;
    }
    // No nativeVirtualKeyCode: macOS Chrome reads browser-harness's Windows code as a Mac one, so a printable key on
    // a visible tab also opened chrome://settings/help. Python 1.0.5's worker drops it from every CDP call.
    const base = { key, code, modifiers, windowsVirtualKeyCode: vk };
    const printable = [...key].length === 1 && !!text && !(modifiers & 7);
    await this.cdp('Input.dispatchKeyEvent', {
      type: 'keyDown',
      ...base,
      ...(!printable && text ? { text } : {}),
    });
    if (printable) await this.cdp('Input.dispatchKeyEvent', { type: 'char', text, ...base });
    await this.cdp('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
  }
  /** Mouse-wheel scroll at viewport x,y; positive dy scrolls down (Python scroll). */
  async scroll(x: number, y: number, dy = 600, dx = 0) {
    if (![x, y, dx, dy].every(Number.isFinite)) throw new Error('Scroll values must be finite.');
    await this.cdp('Input.dispatchMouseEvent', {
      type: 'mouseWheel',
      x,
      y,
      deltaX: dx,
      deltaY: dy,
    });
  }
  async screenshot(options: { quality?: number } = {}) {
    // The page's own devicePixelRatio (emulation changes it) makes image pixels page.clickAt coordinates.
    // Raw evaluate: page.evaluate's userGesture would grant the page a user activation per capture.
    const clip = await this.cdp('Runtime.evaluate', {
      expression:
        '({ x: visualViewport.pageLeft, y: visualViewport.pageTop, width: visualViewport.width, height: visualViewport.height, scale: 1 / devicePixelRatio })',
      returnByValue: true,
    }).then(
      ({ result }) => result.value,
      (error) => {
        // Mid-navigation there is no context to ask; capture unclipped. Anything else (an open dialog) fails as before.
        if (!(error instanceof Error) || !contextLost.test(error.message)) throw error;
      },
    );
    const { data } = await this.cdp('Page.captureScreenshot', {
      format: 'jpeg',
      quality: options.quality ?? 70,
      ...(clip && { clip }),
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
