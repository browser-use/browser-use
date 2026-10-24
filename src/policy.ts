import type { CDP } from './cdp.js';
import type { Protocol } from 'devtools-protocol';

export interface DomainOptions {
  /** Wildcard patterns include the root host under an HTTP(S)-only navigation policy. */
  allowedDomains?: string[];
  /** Denials win over allowances. */
  prohibitedDomains?: string[];
}
export interface BrowserPolicyOptions extends DomainOptions {
  initScripts?: string[];
}
export type SensitiveData = Record<string, { value: string; domains: string[] }>;

export function domainMatcher(pattern: string): (host: string) => boolean {
  if (typeof pattern !== 'string' || !pattern || /[\s/@:#?]/.test(pattern))
    throw new Error('Domain patterns must be hostnames, optionally prefixed with *.');
  const wildcard = pattern.startsWith('*.');
  const name = pattern.slice(wildcard ? 2 : 0);
  if (!name || name.includes('*'))
    throw new Error('Only a leading *. domain wildcard is supported.');
  const domain = new URL(`https://${name}`).hostname.replace(/\.$/, '');
  return (host) => host === domain || (wildcard && host.endsWith(`.${domain}`));
}
export function navigationPolicy(options: DomainOptions) {
  for (const list of [options.allowedDomains, options.prohibitedDomains])
    if (list !== undefined && !Array.isArray(list)) throw new Error('Domain rules must be arrays.');
  const allow = options.allowedDomains?.map(domainMatcher);
  const deny = options.prohibitedDomains?.map(domainMatcher) ?? [];
  return (url: string) => {
    if (url === 'about:blank') return true;
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password)
        return false;
      const host = parsed.hostname.replace(/\.$/, '');
      return (
        !deny.some((match) => match(host)) &&
        (allow === undefined || allow.some((match) => match(host)))
      );
    } catch {
      return false;
    }
  };
}
export function validateSensitiveData(data: SensitiveData = {}) {
  for (const [name, secret] of Object.entries(data)) {
    if (
      !/^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(name) ||
      !secret ||
      typeof secret.value !== 'string' ||
      !secret.value ||
      !Array.isArray(secret.domains) ||
      !secret.domains.length
    )
      throw new Error('Each sensitiveData entry needs a plain name, a nonempty value and domains.');
    secret.domains.forEach(domainMatcher);
  }
}

/** Guard document navigation on this connection without restricting host execution. */
export function installDomainPolicy(
  browser: CDP,
  options: BrowserPolicyOptions,
  onPopup?: (targetId: string) => void,
  onFeature?: (name: 'domain_checks' | 'domain_denials') => void,
) {
  const restricted =
    options.allowedDomains !== undefined || options.prohibitedDomains !== undefined;
  const scripts = options.initScripts ?? [];
  if (
    !Array.isArray(scripts) ||
    scripts.some((script) => typeof script !== 'string' || !script.trim())
  )
    throw new Error('initScripts must contain nonempty JavaScript strings.');
  if (!restricted && !scripts.length) return;
  const policy = navigationPolicy(options);
  const allowed = (url: string) => {
    const result = !restricted || policy(url);
    if (restricted) {
      onFeature?.('domain_checks');
      if (!result) onFeature?.('domain_denials');
    }
    return result;
  };
  const send = browser.send.bind(browser);
  const armed = new Set<string>();
  const related = new Set<string>();
  let watching = false;
  const pending = new Map<string, Promise<void>>();
  const check = (url: string) => {
    if (!allowed(url)) throw new Error('Navigation blocked by domain policy.');
  };
  const arm = (session: string) => {
    let setup = pending.get(session);
    if (!setup) {
      armed.add(session);
      setup = (async () => {
        if (restricted)
          await send(
            'Fetch.enable',
            { patterns: [{ resourceType: 'Document', requestStage: 'Request' }] },
            session,
          );
        for (const source of scripts)
          await send(
            'Page.addScriptToEvaluateOnNewDocument',
            { source, runImmediately: true },
            session,
          );
      })();
      pending.set(session, setup);
    }
    return setup;
  };
  browser.addEventObserver((method, raw, session) => {
    if (!restricted) return;
    if (method === 'Target.detachedFromTarget') {
      const event = raw as Protocol.Target.DetachedFromTargetEvent;
      armed.delete(event.sessionId);
      pending.delete(event.sessionId);
    }
    if (method === 'Fetch.requestPaused' && session && armed.has(session)) {
      const event = raw as Protocol.Fetch.RequestPausedEvent;
      void (
        allowed(event.request.url)
          ? send('Fetch.continueRequest', { requestId: event.requestId }, session)
          : send(
              'Fetch.failRequest',
              { requestId: event.requestId, errorReason: 'BlockedByClient' },
              session,
            )
      ).catch((error) => {
        // Chrome discards interception identifiers when navigation replaces or cancels their requests.
        if (error instanceof Error && /^CDP -32602: Invalid InterceptionId\.?$/.test(error.message))
          return;
        if (armed.has(session)) browser.close();
      });
    }
    if (method === 'Target.attachedToTarget') {
      const event = raw as Protocol.Target.AttachedToTargetEvent;
      if (!['page', 'iframe'].includes(event.targetInfo.type)) return;
      const info = event.targetInfo;
      if (
        !related.has(info.targetId) &&
        !related.has(info.openerId ?? '') &&
        !related.has(info.parentFrameId ?? '')
      ) {
        // Auto-attach pauses popup requests and resumes unrelated targets without interception.
        void send('Runtime.runIfWaitingForDebugger', undefined, event.sessionId).catch(() => {});
        return;
      }
      if (!related.has(info.targetId)) {
        related.add(info.targetId);
        if (info.type === 'page') onPopup?.(info.targetId);
      }
      void arm(event.sessionId)
        .then(async () => {
          if (!allowed(event.targetInfo.url || 'about:blank')) {
            await send('Target.closeTarget', { targetId: event.targetInfo.targetId });
          } else await send('Runtime.runIfWaitingForDebugger', undefined, event.sessionId);
        })
        .catch(() => {
          if (armed.has(event.sessionId)) browser.close();
        });
    }
  });
  browser.send = async (method, params = {} as never, session) => {
    const raw = params as { url?: string; targetId?: string };
    if (restricted && ['Page.navigate', 'Target.createTarget'].includes(method))
      check(raw.url ?? 'about:blank');
    if (
      restricted &&
      [
        'Fetch.disable',
        'Fetch.enable',
        'Fetch.continueRequest',
        'Fetch.fulfillRequest',
        'Target.setAutoAttach',
        'Target.autoAttachRelated',
        'Target.sendMessageToTarget',
      ].includes(method)
    )
      throw new Error('This CDP command is managed by the domain policy.');
    if (restricted && method === 'Target.attachToTarget' && raw.targetId) {
      const { targetInfo } = await send('Target.getTargetInfo', { targetId: raw.targetId });
      check(targetInfo.url || 'about:blank');
      related.add(raw.targetId);
    }
    const result = await send(method, params, session);
    if (method === 'Target.attachToTarget') {
      const id = (result as Protocol.Target.AttachToTargetResponse).sessionId;
      await arm(id);
      if (restricted && !watching) {
        watching = true;
        await send('Target.setAutoAttach', {
          autoAttach: true,
          flatten: true,
          waitForDebuggerOnStart: true,
          filter: [{ type: 'page' }, { type: 'iframe' }, { exclude: true }],
        });
      }
    }
    return result;
  };
}

/** Verify the input document before inserting a named secret. */
export async function fillSecret(
  browser: CDP,
  session: string,
  name: string,
  nodeId: number,
  data: SensitiveData,
) {
  const secret = Object.hasOwn(data, name) ? data[name] : undefined;
  if (!secret) throw new Error('Unknown secret name.');
  if (!Number.isSafeInteger(nodeId) || nodeId <= 0)
    throw new Error('Expected an AX backend node id.');
  const allowsSecret = navigationPolicy({ allowedDomains: secret.domains });
  const { frameTree } = await browser.send('Page.getFrameTree', undefined, session);
  if (frameTree.frame.url === 'about:blank' || !allowsSecret(frameTree.frame.url))
    throw new Error('Secret insertion blocked: input document is outside its allowed domains.');
  // An isolated world protects origin checks and native setters from page script changes.
  const { executionContextId } = await browser.send(
    'Page.createIsolatedWorld',
    {
      frameId: frameTree.frame.id,
      worldName: 'bu-pi-secrets',
    },
    session,
  );
  const { object } = await browser.send(
    'DOM.resolveNode',
    {
      backendNodeId: nodeId,
      executionContextId,
    },
    session,
  );
  if (!object.objectId) throw new Error('Secret target is no longer available.');
  try {
    const { result } = await browser.send(
      'Runtime.callFunctionOn',
      {
        objectId: object.objectId,
        functionDeclaration: `function() { return { url: this.ownerDocument.location.href, input: this instanceof this.ownerDocument.defaultView.HTMLInputElement || this instanceof this.ownerDocument.defaultView.HTMLTextAreaElement }; }`,
        returnByValue: true,
      },
      session,
    );
    const target = result.value as { url?: string; input?: boolean } | undefined;
    if (!target?.input || !target.url || !allowsSecret(target.url) || target.url === 'about:blank')
      throw new Error('Secret insertion blocked: input document is outside its allowed domains.');
    // Check origin and insert through the same DOM object within one renderer task.
    const filled = await browser.send(
      'Runtime.callFunctionOn',
      {
        objectId: object.objectId,
        functionDeclaration: `function(value, url) {
        if (!this.isConnected || this.ownerDocument.location.href !== url) throw new Error('Secret target changed');
        const win = this.ownerDocument.defaultView;
        const proto = this instanceof win.HTMLInputElement ? win.HTMLInputElement.prototype : win.HTMLTextAreaElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(this, value);
        this.dispatchEvent(new win.Event('input', {bubbles:true}));
        this.dispatchEvent(new win.Event('change', {bubbles:true}));
      }`,
        arguments: [{ value: secret.value }, { value: target.url }],
      },
      session,
    );
    if (filled.exceptionDetails) throw new Error('Secret target changed or rejected insertion.');
  } finally {
    await browser
      .send('Runtime.releaseObject', { objectId: object.objectId }, session)
      .catch(() => {});
  }
  return 'Secret inserted.';
}
