import type { CDP } from './cdp.js';

/** Browser Use's orange corner animation. Cosmetic, aria-hidden and pointer-transparent. */
export function actionHighlighter(browser: CDP) {
  let generation = 0;

  return async (method: string, raw: unknown, sessionId?: string) => {
    const params = raw as {
      type?: string;
      x?: number;
      y?: number;
      backendNodeId?: number;
      nodeId?: number;
      objectId?: string;
    };
    if (
      !sessionId ||
      !(
        (method === 'Input.dispatchMouseEvent' && params.type === 'mouseReleased') ||
        method === 'DOM.focus' ||
        method === 'Input.insertText'
      )
    )
      return;
    const current = ++generation;
    try {
      let node: { backendNodeId?: number; nodeId?: number; objectId?: string };
      if (method === 'Input.dispatchMouseEvent') {
        const hit = await browser.send(
          'DOM.getNodeForLocation',
          {
            x: Math.round(params.x!),
            y: Math.round(params.y!),
          },
          sessionId,
        );
        node = { backendNodeId: hit.backendNodeId };
      } else if (method === 'DOM.focus') {
        node =
          params.backendNodeId !== undefined
            ? { backendNodeId: params.backendNodeId }
            : params.nodeId !== undefined
              ? { nodeId: params.nodeId }
              : params.objectId
                ? { objectId: params.objectId }
                : {};
      } else {
        const { result } = await browser.send(
          'Runtime.evaluate',
          {
            expression: 'document.activeElement',
            objectGroup: `bu-pi-highlight-${current}`,
          },
          sessionId,
        );
        if (!result.objectId) return;
        node = { objectId: result.objectId };
      }
      if (current !== generation) return;
      const objectId =
        node.objectId ?? (await browser.send('DOM.resolveNode', node, sessionId)).object.objectId;
      if (!objectId) return;
      try {
        if (current !== generation) return;
        await browser.send(
          'Runtime.callFunctionOn',
          {
            objectId,
            functionDeclaration: drawCorners.toString(),
          },
          sessionId,
        );
      } finally {
        if (!node.objectId)
          await browser.send('Runtime.releaseObject', { objectId }, sessionId).catch(() => {});
      }
    } catch {
      // Detached nodes, navigation and unsupported targets must not fail the action.
    } finally {
      if (method === 'Input.insertText')
        await browser
          .send(
            'Runtime.releaseObjectGroup',
            { objectGroup: `bu-pi-highlight-${current}` },
            sessionId,
          )
          .catch(() => {});
    }
  };
}

// Geometry, color and timing follow browser_use/browser/session.py highlight_interaction_element.
function drawCorners(this: Element) {
  const doc = this.ownerDocument;
  const rect = this.getBoundingClientRect();
  if (!this.isConnected || !rect.width || !rect.height) return;
  doc.querySelector('[data-browser-use-interaction-highlight]')?.remove();
  const host = doc.createElement('div');
  host.setAttribute('data-browser-use-interaction-highlight', 'true');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = `all:initial;position:absolute;left:${rect.left + doc.defaultView!.scrollX}px;top:${rect.top + doc.defaultView!.scrollY}px;width:${rect.width}px;height:${rect.height}px;pointer-events:none;z-index:2147483647;opacity:1;transition:opacity .3s;`;
  const root = host.attachShadow({ mode: 'closed' });
  const size = Math.max(8, Math.min(20, Math.min(rect.width, rect.height) * 0.35));
  for (const [vertical, horizontal] of [
    ['top', 'left'],
    ['top', 'right'],
    ['bottom', 'left'],
    ['bottom', 'right'],
  ]) {
    const corner = doc.createElement('div');
    corner.style.cssText = `position:absolute;width:${size}px;height:${size}px;${vertical}:-10px;${horizontal}:-10px;border-${vertical}:3px solid rgb(255,127,39);border-${horizontal}:3px solid rgb(255,127,39);pointer-events:none;transition:all .15s ease-out;`;
    root.append(corner);
    setTimeout(() => {
      corner.style.setProperty(vertical!, '-3px');
      corner.style.setProperty(horizontal!, '-3px');
    }, 10);
  }
  doc.documentElement.append(host);
  setTimeout(() => {
    host.style.opacity = '0';
    setTimeout(() => host.remove(), 300);
  }, 1000);
}
