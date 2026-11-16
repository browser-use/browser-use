import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CDP } from '../dist/cdp.js';
import { Page } from '../dist/page.js';
import { AxHelpers } from '../dist/ax.js';

/** A tab over a fake socket: the page reports url, an AX tree of nodes and its visible text. No browser. */
function fakeTab({ url = 'https://example.com/', nodes, visible = '' }) {
  const socket = new EventTarget();
  socket.readyState = WebSocket.OPEN;
  socket.close = () => {};
  const value = (expression = '') =>
    expression.includes('__buObs')
      ? { idle: 1e6, ready: 'complete', url, title: 'T', n: 0, doc: 1 }
      : expression.includes('createTreeWalker')
        ? visible
        : undefined;
  const answer = ({ method, params }) => {
    if (method === 'Accessibility.getFullAXTree') return { nodes: params?.frameId ? [] : nodes };
    if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'main', url } } };
    if (method === 'Runtime.evaluate') {
      const v = value(params.expression);
      return { result: v === undefined ? { type: 'undefined' } : { type: typeof v, value: v } };
    }
    return {};
  };
  const emit = (message) =>
    socket.dispatchEvent(Object.assign(new Event('message'), { data: JSON.stringify(message) }));
  socket.send = (data) => {
    const message = JSON.parse(data);
    queueMicrotask(() => emit({ id: message.id, result: answer(message) }));
  };
  const cdp = new CDP(socket, 5000);
  const page = Page.deferred(cdp, async () => ({ targetId: 't1', sessionId: 's1' }));
  const logs = [];
  const ax = new AxHelpers(
    () => page,
    () => cdp,
    (line) => logs.push(line),
  );
  return { ax, emit, setUrl: (next) => (url = next), setNodes: (next) => (nodes = next) };
}
const node = (id, role, name, extra = {}) => ({
  nodeId: String(id),
  ignored: false,
  role: { type: 'role', value: role },
  name: { type: 'computedString', value: name },
  ...extra,
});
const props = (...pairs) => ({
  properties: pairs.map(([name, value]) => ({ name, value: { type: 'boolean', value } })),
});

test('bu.state keeps inner non-breaking spaces, drops nbsp spacers, prints disabled only for native disabled', async () => {
  const nodes = [
    node(1, 'RootWebArea', 'T', { childIds: ['2', '3', '4', '5'] }),
    node(2, 'StaticText', 'Price €5 at 10 am'),
    node(3, 'link', ' ', { backendDOMNodeId: 10, ...props(['focusable', true]) }),
    // aria-disabled: Chrome flags it disabled, but it stays focusable and accepts input.
    node(4, 'button', 'Search', {
      backendDOMNodeId: 11,
      ...props(['focusable', true], ['disabled', true]),
    }),
    node(5, 'button', 'Off', { backendDOMNodeId: 12, ...props(['disabled', true]) }),
  ];
  const { ax } = fakeTab({ nodes, visible: 'price €5 at 10 am search off' });
  const out = String(await ax.state());
  assert.match(out, /^Price €5 at 10 am$/m);
  assert.match(out, /^\[10\] link$/m);
  assert.match(out, /^\[11\] button "Search"$/m);
  assert.match(out, /^\[12\] button "Off" disabled$/m);
});

test("an empty tree says why; Chrome's error page names the failed load's net error", async () => {
  const { ax, emit, setUrl } = fakeTab({ nodes: [node(1, 'RootWebArea', '')] });
  assert.match(
    String(await ax.state()),
    /\(nothing in the accessibility tree: the page is blank, or a popup/,
  );
  emit({
    method: 'Network.requestWillBeSent',
    sessionId: 's1',
    params: { requestId: 'r1', type: 'Document' },
  });
  emit({
    method: 'Network.loadingFailed',
    sessionId: 's1',
    params: { requestId: 'r1', type: 'Document', errorText: 'net::ERR_INVALID_AUTH_CREDENTIALS' },
  });
  setUrl('chrome-error://chromewebdata/');
  assert.match(
    String(await ax.state()),
    /^\(the page did not load: net::ERR_INVALID_AUTH_CREDENTIALS\)$/m,
  );
  // A new document load clears it.
  emit({
    method: 'Network.requestWillBeSent',
    sessionId: 's1',
    params: { requestId: 'r2', type: 'Document' },
  });
  emit({ method: 'Network.loadingFinished', sessionId: 's1', params: { requestId: 'r2' } });
  assert.doesNotMatch(String(await ax.state()), /did not load/);
});
