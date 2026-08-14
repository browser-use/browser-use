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
  const evaluation = requests.find((request) => request.method === "Runtime.evaluate");
  assert.equal(evaluation.sessionId, "session-1");
  assert.equal(requests.find((request) => request.method === "Target.getTargets").sessionId, undefined);
  await client.close();
  await new Promise((resolve) => server.close(resolve));
});
