"""Real Python -> bundled Node -> Pi -> local SSE transport -> Python callable tests."""

import asyncio
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
            name, args = self.responses.pop(0)
            index = len(self.requests)
            item = {
                "id": f"fc_{index}",
                "type": "function_call",
                "call_id": f"call_{index}",
                "name": name,
                "arguments": json.dumps(args),
                "status": "completed",
            }
            events = [
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
                        "output_index": 0,
                        "item": {**item, "arguments": "", "status": "in_progress"},
                    },
                ),
                (
                    "response.function_call_arguments.delta",
                    {
                        "item_id": item["id"],
                        "output_index": 0,
                        "delta": item["arguments"],
                    },
                ),
                (
                    "response.function_call_arguments.done",
                    {
                        "item_id": item["id"],
                        "output_index": 0,
                        "arguments": item["arguments"],
                    },
                ),
                ("response.output_item.done", {"output_index": 0, "item": item}),
                (
                    "response.completed",
                    {
                        "response": {
                            "id": f"resp_{index}",
                            "status": "completed",
                            "output": [item],
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
            model="openai/gpt-5.5",
            workspace=self.directory.name,
            baseUrl=self.base_url,
            apiKey="local-fixture-key",
            **options,
        )
        return self.agent

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
            tools=[Tool("quote", "Price the quantity", Quantity, quote)]
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
