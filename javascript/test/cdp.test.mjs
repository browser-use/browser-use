import assert from "node:assert/strict";
import test from "node:test";
import { WebSocketServer } from "ws";
import { CdpSession, createBrowserSession } from "../dist/cdp.js";

test("CDP session attaches once and routes page calls through the active session", async () => {
  const requests = [];
  const server = new WebSocketServer({ port: 0 });
  await new Promise((resolve) => server.once("listening", resolve));
  server.on("connection", (socket) => {
    socket.on("message", (raw) => {
      const request = JSON.parse(raw.toString());
      requests.push(request);
      if (request.method === "Runtime.throwForTest") {
        socket.send(JSON.stringify({ id: request.id, error: { message: "test CDP error" } }));
        return;
      }
      const result = request.method === "Target.getTargets"
        ? { targetInfos: [{ type: "page", targetId: "page-1", url: "about:blank" }] }
        : request.method === "Target.attachToTarget"
          ? { sessionId: "session-1" }
          : request.method === "Runtime.evaluate"
            ? { result: { value: "Example" } }
            : {};
      socket.send(JSON.stringify({ id: request.id, result }));
    });
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const client = new CdpSession({ cdpUrl: `ws://127.0.0.1:${address.port}` });
  await client.connect();
  const session = createBrowserSession(client);
  const result = await session.Runtime.evaluate({ expression: "document.title", returnByValue: true });
  assert.equal(result.result.value, "Example");
  let observedUrl = "";
  const unsubscribe = session.Network.requestWillBeSent((event) => {
    observedUrl = event.request.url;
  });
  const socket = [...server.clients][0];
  socket.send(JSON.stringify({
    method: "Network.requestWillBeSent",
    sessionId: "session-1",
    params: { request: { url: "https://example.com/product" } },
  }));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(observedUrl, "https://example.com/product");
  assert.equal(typeof unsubscribe, "function");
  unsubscribe();
  assert.equal(requests.some((request) => request.method === "Network.requestWillBeSent"), false);
  const abandonedWait = session.waitFor("Page.eventThatNeverArrives", 5);
  const abandonedCommand = session.Runtime.throwForTest({});
  await new Promise((resolve) => setTimeout(resolve, 10));
  await assert.rejects(abandonedWait, /Timed out waiting/);
  await assert.rejects(abandonedCommand, /test CDP error/);
  const evaluation = requests.find((request) => request.method === "Runtime.evaluate");
  assert.equal(evaluation.sessionId, "session-1");
  assert.equal(requests.find((request) => request.method === "Target.getTargets").sessionId, undefined);
  await client.close();
  await new Promise((resolve) => server.close(resolve));
});
