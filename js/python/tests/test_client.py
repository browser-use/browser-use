"""Real Python -> bundled Node -> Pi -> local SSE transport -> Python callable tests."""

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path

from browser_use_next import BrowserUse, BrowserUseError, Tool
from pydantic import BaseModel


class Quantity(BaseModel):
    quantity: int


class Quote(BaseModel):
    total: int


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="bu-python-")
        self.agent = None
        self.responses = []
        self.requests = []
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.base_url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/v1"

    async def asyncTearDown(self):
        if self.agent:
            await self.agent.close()
        self.server.close()
        await self.server.wait_closed()
        self.directory.cleanup()

    async def handle(self, reader, writer):
        try:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode()
            length = next(
                int(line.split(":", 1)[1])
                for line in headers.splitlines()
                if line.lower().startswith("content-length:")
            )
            request = json.loads(await reader.readexactly(length))
            self.requests.append(request)
            if "contents" in request:
                # Gemini, with the URL-safe signature a re-serializing gateway returns.
                name, args = self.responses.pop(0)[:2]
                part = {"functionCall": {"name": name, "args": args}, "thoughtSignature": "-_-_Pj8="}
                chunk = {
                    "candidates": [
                        {"index": 0, "finishReason": "STOP", "content": {"role": "model", "parts": [part]}}
                    ],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                }
                payload = f"data: {json.dumps(chunk)}\n\n".encode()
                writer.write(
                    f"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                    + payload
                )
                await writer.drain()
                return
            if "max_tokens" in request and "messages" in request:
                # Anthropic, answering under the gateway's upstream name for the model.
                name, args = self.responses.pop(0)[:2]
                events = [
                    ("message_start", {"message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-4-7", "content": [], "stop_reason": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
                    ("content_block_start", {"index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
                    ("content_block_delta", {"index": 0, "delta": {"type": "thinking_delta", "thinking": "plan"}}),
                    ("content_block_delta", {"index": 0, "delta": {"type": "signature_delta", "signature": "sig-1"}}),
                    ("content_block_stop", {"index": 0}),
                    ("content_block_start", {"index": 1, "content_block": {"type": "tool_use", "id": f"toolu_{len(self.requests)}", "name": name, "input": {}}}),
                    ("content_block_delta", {"index": 1, "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}}),
                    ("content_block_stop", {"index": 1}),
                    ("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}}),
                    ("message_stop", {}),
                ]
                payload = "".join(
                    f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n" for kind, body in events
                ).encode()
                writer.write(
                    f"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                    + payload
                )
                await writer.drain()
                return
            name, args, *reasoning = self.responses.pop(0)
            index = len(self.requests)
            item = {
                "id": f"fc_{index}",
                "type": "function_call",
                "call_id": f"call_{index}",
                "name": name,
                "arguments": json.dumps(args),
                "status": "completed",
            }
            before = [
                ("response.output_item.done", {"output_index": 0, "item": item})
                for item in reasoning
            ]
            offset = len(reasoning)
            events = [
                *before,
                (
                    "response.created",
                    {
                        "response": {
                            "id": f"resp_{index}",
                            "status": "in_progress",
                            "output": [],
                        }
                    },
                ),
                (
                    "response.output_item.added",
                    {
                        "output_index": offset,
                        "item": {**item, "arguments": "", "status": "in_progress"},
                    },
                ),
                (
                    "response.function_call_arguments.delta",
                    {
                        "item_id": item["id"],
                        "output_index": offset,
                        "delta": item["arguments"],
                    },
                ),
                (
                    "response.function_call_arguments.done",
                    {
                        "item_id": item["id"],
                        "output_index": offset,
                        "arguments": item["arguments"],
                    },
                ),
                ("response.output_item.done", {"output_index": offset, "item": item}),
                (
                    "response.completed",
                    {
                        "response": {
                            "id": f"resp_{index}",
                            "status": "completed",
                            "output": [*reasoning, item],
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "total_tokens": 15,
                                "input_tokens_details": {"cached_tokens": 0},
                            },
                        }
                    },
                ),
            ]
            payload = "".join(
                f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n"
                for kind, body in events
            ).encode()
            writer.write(
                f"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def create(self, **options):
        self.agent = await BrowserUse.create(
            workspace=self.directory.name,
            baseUrl=self.base_url,
            apiKey="local-fixture-key",
            telemetry=False,
            **{"model": "openai/gpt-5.5", **options},
        )
        return self.agent

    async def test_browser_policy_and_secrets_cross_the_python_bridge(self):
        agent = await self.create(
            browser={"kind": "chromium"},
            allowedDomains=[],
            sensitiveData={"password": {"value": "fixture-private-password", "domains": ["example.com"]}},
        )
        with self.assertRaisesRegex(BrowserUseError, "domain policy"):
            await agent.execute("await page.goto('https://example.com')")
        self.responses = [("finish", {"result": "Policy configured"})]
        result = await agent.run("Report readiness.")
        self.assertEqual(result.status, "completed")
        self.assertNotIn("fixture-private-password", json.dumps(self.requests))

    async def test_partial_findings_survive_step_limit_without_final_schema_validation(self):
        self.responses = [("javascript", {"code": "await checkpoint('findings.json', [{issue:'Broken search'}], {partial:true})"})]
        agent = await self.create(highlightActions=True)
        result = await agent.run("Audit", schema=Quote, maxSteps=1)
        self.assertEqual(result.status, "max_steps")
        self.assertIsNone(result.output)
        self.assertEqual(result.partial["value"], [{"issue": "Broken search"}])
        self.assertTrue(Path(result.partial["path"]).is_file())
        self.assertEqual(len(self.requests), 1)

    async def test_typed_python_tool_round_trip_and_live_events(self):
        called = []

        async def quote(args):
            called.append(args.quantity)
            return Quote(total=args.quantity * 7)

        self.responses = [
            ("quote", {"quantity": 3}),
            ("finish", {"result": {"total": 21}}),
        ]
        agent = await self.create(
            tools=[Tool("quote", "Price the quantity", Quantity, quote)],
            modelTimeoutMs=5000,
            compactionTimeoutMs=2000,
        )
        stream = agent.events()
        first = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        running = asyncio.create_task(agent.run("Calculate quote", schema=Quote))
        self.assertEqual((await asyncio.wait_for(first, 5))["type"], "run_start")
        result = await asyncio.wait_for(running, 15)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, Quote(total=21))
        self.assertEqual(called, [3])
        self.assertIn("21", json.dumps(self.requests[1]))
        self.assertEqual(result.usage["totalTokens"], 30)
        await stream.aclose()

    async def test_workspace_and_followup(self):
        self.responses = [
            ("finish", {"result": "first"}),
            ("finish", {"result": "second"}),
        ]
        agent = await self.create()
        await agent.execute(
            "const x = 9; await require('node:fs/promises').writeFile('output.txt', 'hello')"
        )
        self.assertEqual((await agent.execute("x + 1"))["text"], "10")
        self.assertEqual((await agent.files())[0]["relativePath"], "output.txt")
        await agent.run("remember the first task")
        self.assertEqual((await agent.follow_up("continue")).output, "second")
        self.assertIn("remember the first task", json.dumps(self.requests[1]))
        path = await agent.save_history()
        self.assertEqual(json.loads(Path(path).read_text())["version"], 1)

    async def test_bundled_oversized_screenshot_preserves_original_and_reaches_provider(self):
        agent = await self.create()
        capture = await agent.execute(
            "await page.goto('data:text/html,<body>Image fixture</body>'); "
            "await page.cdp('Page.captureScreenshot', {format:'png',captureBeyondViewport:true,"
            "clip:{x:0,y:0,width:1440,height:22000,scale:1}})"
            ".then(r=>artifact('original.png',Buffer.from(r.data,'base64')))"
        )
        self.assertEqual(len(capture["images"]), 1, capture["text"])
        self.assertIn("model preview", capture["text"])
        original = (Path(self.directory.name) / "original.png").read_bytes()
        self.assertEqual(int.from_bytes(original[20:24], "big"), 22000)
        preview = base64.b64decode(capture["images"][0]["data"])
        self.assertNotEqual(original, preview)
        # Run the screenshot through the real bundled Pi loop and inspect the local provider request.
        self.responses = [
            ("javascript", {"code": "await page.cdp('Page.captureScreenshot', {format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:1440,height:22000,scale:1}}); void 0"}),
            ("finish", {"result": "preview received"}),
        ]
        result = await agent.run("Capture and inspect the full page")
        self.assertEqual(result.output, "preview received")
        serialized = json.dumps(self.requests[-1])
        self.assertIn("input_image", serialized)
        self.assertIn("model preview", serialized)
        self.assertNotIn(base64.b64encode(original).decode(), serialized)

    async def test_cancel_propagates_to_python_tool(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def slow(_args):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        self.responses = [("slow", {"quantity": 1})]
        agent = await self.create(tools=[Tool("slow", "Wait", Quantity, slow)])
        task = asyncio.create_task(agent.run("wait"))
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 5)

    async def test_model_id_renames_only_the_upstream_model(self):
        self.responses = [("finish", {"result": "done"})]
        agent = await self.create(modelId="gpt-6-luna")
        self.assertEqual((await agent.run("say done")).output, "done")
        self.assertEqual(self.requests[0]["model"], "gpt-6-luna")

    async def test_model_info_serves_a_model_newer_than_the_catalog(self):
        self.responses = [("finish", {"result": "done"})]
        info = {"template": "openai/gpt-5.5", "contextWindow": 250_000, "maxTokens": 32_000}
        agent = await self.create(model="openai/gpt-7-fixture", modelInfo=info)
        self.assertEqual((await agent.run("say done")).output, "done")
        self.assertEqual(self.requests[0]["model"], "gpt-7-fixture")
        self.assertEqual(self.requests[0]["max_output_tokens"], 32_000)
        path = Path(self.directory.name) / "history.json"
        await agent.save_history(str(path))
        self.assertEqual(json.loads(path.read_text())["model"], "openai/gpt-7-fixture")

    async def test_gemini_signatures_are_replayed_as_standard_base64(self):
        self.responses = [("javascript", {"code": "1 + 1"}), ("finish", {"result": "done"})]
        agent = await self.create(model="google/gemini-3.6-flash")
        self.assertEqual((await agent.run("add")).output, "done")
        replayed = [
            part
            for content in self.requests[1]["contents"]
            if content["role"] == "model"
            for part in content["parts"]
        ]
        self.assertEqual(replayed[0]["thoughtSignature"], "+/+/Pj8=")

    async def test_thinking_survives_a_gateway_answering_under_another_model_name(self):
        self.responses = [("javascript", {"code": "1 + 1"}), ("finish", {"result": "done"})]
        agent = await self.create(model="anthropic/claude-opus-4-7", modelId="claude-opus-4.7")
        self.assertEqual((await agent.run("add")).output, "done")
        replayed = [
            block
            for message in self.requests[1]["messages"]
            if message["role"] == "assistant"
            for block in message["content"]
        ]
        self.assertIn({"type": "thinking", "thinking": "plan", "signature": "sig-1"}, replayed)

    async def test_model_info_thinking_levels_override_the_catalog(self):
        self.responses = [("finish", {"result": "done"})]
        info = {"thinkingLevelMap": {"off": "disabled"}, "compat": {"supportsMidConvoEffort": False}}
        agent = await self.create(model="anthropic/claude-opus-5", modelInfo=info, reasoning="off")
        await agent.run("say done")
        self.assertEqual(self.requests[0]["thinking"], {"type": "disabled"})

    async def test_model_info_can_turn_thinking_off_entirely(self):
        self.responses = [("finish", {"result": "done"})]
        agent = await self.create(model="anthropic/claude-opus-5", modelInfo={"reasoning": False, "compat": {"supportsMidConvoEffort": False}})
        try:
            await agent.run("say done")
        except BrowserUseError:
            pass  # the fixture cannot answer in Anthropic's format; only the request matters
        self.assertNotIn("thinking", self.requests[0])
        self.assertNotIn("output_config", self.requests[0])

    async def test_shell_env_reaches_the_bash_tool(self):
        self.responses = [("bash", {"command": "echo token=$CLOUD_TOKEN"}), ("finish", {"result": "done"})]
        agent = await self.create(researchTools=True, shellEnv={"CLOUD_TOKEN": "fixture-run-token"})
        self.assertEqual((await agent.run("check")).output, "done")
        self.assertIn("token=fixture-run-token", json.dumps(self.requests[1]["input"]))

    async def test_shell_timeout_outlasts_the_cell_timeout(self):
        # Installs and deploys outlast a browser cell; the host sets the shell's own limit.
        self.responses = [("bash", {"command": "sleep 3 && echo slept"}), ("finish", {"result": "done"})]
        agent = await self.create(researchTools=True, cellTimeoutMs=2000, shellTimeoutMs=10000)
        self.assertEqual((await agent.run("wait")).output, "done")
        outputs = [i for i in self.requests[1]["input"] if i.get("type") == "function_call_output"]
        self.assertTrue(any("slept" in json.dumps(i["output"]) for i in outputs), outputs)

    async def test_moving_to_another_browser_needs_the_host_option(self):
        agent = await self.create(browser={"kind": "chromium"})
        with self.assertRaisesRegex(BrowserUseError, "not enabled"):
            await agent.execute("await reconnect('ws://127.0.0.1:9/devtools/browser/x')")

    async def test_model_info_compat_overrides_the_catalog(self):
        # A gateway that does not forward Anthropic betas needs the beta-only effort
        # messages off; the fixture cannot answer in Anthropic's format, so only the
        # request matters.
        for info in (None, {"compat": {"supportsMidConvoEffort": False}}):
            self.responses = [("finish", {"result": "done"})]
            await self.create(model="anthropic/claude-opus-5", **({"modelInfo": info} if info else {}))
            try:
                await self.agent.run("say done")
            except BrowserUseError:
                pass
            await self.agent.close()
        beta_messages = [
            [m for m in request["messages"] if "output_config" in m] for request in self.requests
        ]
        self.assertTrue(beta_messages[0])
        self.assertEqual(beta_messages[-1], [])

    async def test_unknown_model_without_a_template_is_refused(self):
        with self.assertRaisesRegex(BrowserUseError, "Unknown model"):
            await self.create(model="openai/gpt-7-fixture", modelInfo={"maxTokens": 32_000})

    async def test_gateway_null_fields_are_not_replayed_on_reasoning_items(self):
        # Gateways that re-serialize Responses events add nulls such as "status": null,
        # which OpenAI rejects when the item comes back as input on the next turn.
        reasoning = {
            "id": "rs_1",
            "type": "reasoning",
            "summary": [],
            "encrypted_content": "gAAAA-opaque",
            "status": None,
        }
        self.responses = [
            ("javascript", {"code": "1 + 1"}, reasoning),
            ("finish", {"result": "done"}),
        ]
        agent = await self.create()
        self.assertEqual((await agent.run("add")).output, "done")
        replayed = [i for i in self.requests[1]["input"] if i.get("type") == "reasoning"]
        self.assertEqual(replayed, [{k: v for k, v in reasoning.items() if v is not None}])

    async def test_stream_deltas_false_keeps_only_settled_events(self):
        self.responses = [("finish", {"result": "done"})]
        agent = await self.create(streamDeltas=False)
        seen = []

        async def collect():
            async for event in agent.events():
                if event.get("type") == "agent_event":
                    seen.append(event["event"]["type"])

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await agent.run("finish")
        await asyncio.sleep(0.2)
        task.cancel()
        self.assertNotIn("message_update", seen)
        self.assertIn("message_end", seen)

    async def test_unknown_options_and_missing_runtime_fail_explicitly(self):
        with self.assertRaisesRegex(BrowserUseError, "Unsupported create option"):
            await BrowserUse.create(model="openai/gpt-5.5", imaginaryOption=True)
        with self.assertRaisesRegex(BrowserUseError, "runtime is missing"):
            await BrowserUse.create(
                model="openai/gpt-5.5", server_path="/nonexistent/server.mjs"
            )

    async def test_nested_pydantic_schema_round_trip(self):
        class Invoice(BaseModel):
            quote: Quote

        self.responses = [("finish", {"result": {"quote": {"total": 21}}})]
        agent = await self.create()
        result = await agent.run("Nested schema", schema=Invoice)
        self.assertEqual(result.output.quote.total, 21)
        self.assertNotIn('"$ref"', json.dumps(self.requests[0]["tools"]))

    async def test_tool_failure_is_returned_to_agent_for_recovery(self):
        async def broken(_args):
            raise ValueError("fixture business error")

        self.responses = [
            ("broken", {"quantity": 1}),
            ("finish", {"result": "reported failure"}),
        ]
        agent = await self.create(tools=[Tool("broken", "Fail", Quantity, broken)])
        result = await agent.run("report errors")
        self.assertEqual(result.output, "reported failure")
        self.assertIn("fixture business error", json.dumps(self.requests[1]))


if __name__ == "__main__":
    unittest.main()
