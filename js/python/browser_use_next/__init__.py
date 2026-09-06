"""Thin async Python client. One Pi engine; Python callables remain in Python."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel


class BrowserUseError(RuntimeError):
    """An explicit SDK, transport or lifecycle failure."""


def _schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline local Pydantic references before nesting a schema in tool parameters."""

    def visit(value: Any, refs: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [visit(item, refs) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/") or ref in refs:
                raise BrowserUseError(
                    "Only non-recursive local JSON Schema references are supported."
                )
            target: Any = schema
            try:
                for key in ref[2:].split("/"):
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError) as exc:
                raise BrowserUseError(f"Unresolved schema reference: {ref}") from exc
            # Pydantic uses plain reference nodes. Reject siblings rather than weakening constraints.
            if set(value) - {"$ref", "title", "description"}:
                raise BrowserUseError("Schema reference siblings are unsupported.")
            return visit(target, refs | {ref})
        return {
            key: visit(item, refs)
            for key, item in value.items()
            if key not in {"$defs", "definitions"}
        }

    return visit(schema)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: type[BaseModel]
    execute: Callable[[BaseModel], Any | Awaitable[Any]]


@dataclass(frozen=True)
class RunResult:
    status: str
    output: Any
    text: str
    metadata: dict[str, Any]

    @property
    def usage(self) -> dict[str, Any]:
        return self.metadata["usage"]


class BrowserUse:
    """An async session, backed by the packaged Node runtime. Use async context management."""

    def __init__(self) -> None:
        self.workspace = ""
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 0
        self._write_lock = asyncio.Lock()
        self._tools: dict[str, Tool] = {}
        self._tool_tasks: dict[str, asyncio.Task[None]] = {}
        self._queues: set[asyncio.Queue[Any]] = set()
        self._reader: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr = ""
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    @classmethod
    async def create(
        cls,
        *,
        model: str,
        tools: list[Tool] | None = None,
        node: str | None = None,
        server_path: str | Path | None = None,
        **options: Any,
    ) -> BrowserUse:
        self = cls()
        for tool in tools or []:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool: {tool.name}")
            self._tools[tool.name] = tool
        executable = node or shutil.which("node")
        if not executable:
            raise BrowserUseError(
                "Node.js 22.19+ is required. Install Node or pass node='/absolute/path/to/node'."
            )
        server = (
            Path(server_path)
            if server_path
            else Path(__file__).with_name("runtime") / "server.mjs"
        )
        if not server.is_file():
            raise BrowserUseError(
                "Packaged JS runtime is missing. Build with npm run build:python, or pass server_path."
            )
        # The agent process receives selected provider keys. Its JS worker receives no environment keys.
        allowed = {
            "PATH",
            "HOME",
            "TMPDIR",
            "TEMP",
            "SYSTEMROOT",
            "SSL_CERT_FILE",
            "NODE_EXTRA_CA_CERTS",
        }
        allowed.update(
            {
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "GOOGLE_API_KEY",
                "GEMINI_API_KEY",
                "OPENROUTER_API_KEY",
                "BROWSER_USE_API_KEY",
            }
        )
        env = {key: value for key, value in os.environ.items() if key in allowed}
        self._process = await asyncio.create_subprocess_exec(
            executable,
            str(server.resolve()),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=16_000_001,
        )
        self._reader = asyncio.create_task(self._read())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        try:
            ping = await asyncio.wait_for(self._call("ping"), 10)
            if ping.get("protocol") != 1:
                raise BrowserUseError("Unsupported runtime protocol.")
            version = tuple(int(part) for part in ping["node"].split(".")[:2])
            if version < (22, 19):
                raise BrowserUseError("Node.js 22.19+ is required.")
            specs = [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": _schema(t.parameters.model_json_schema()),
                }
                for t in self._tools.values()
            ]
            result = await asyncio.wait_for(
                self._call("create", {"model": model, **options, "tools": specs}), 30
            )
            self.workspace = result["workspace"]
            return self
        except BaseException:
            await self.close()
            raise

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._closed or not self._process or self._process.returncode is not None:
            raise BrowserUseError("Session is closed or runtime exited.")
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            message = (
                json.dumps(
                    {"id": request_id, "method": method, "params": params or {}},
                    allow_nan=False,
                ).encode()
                + b"\n"
            )
            if len(message) > 16_000_000:
                raise BrowserUseError(
                    "Bridge request exceeds 16 MB; use a workspace file."
                )
            async with self._write_lock:
                assert self._process.stdin
                self._process.stdin.write(message)
                await self._process.stdin.drain()
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def _read(self) -> None:
        assert self._process and self._process.stdout
        error: Exception = BrowserUseError(
            "Node runtime exited. JS state is lost; inspect browser state before retrying."
        )
        try:
            while line := await self._process.stdout.readline():
                message = json.loads(line)
                if "id" in message:
                    future = self._pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(
                                BrowserUseError(message["error"]["message"])
                            )
                        else:
                            future.set_result(message.get("result"))
                elif message.get("method") == "tool_call":
                    params = message["params"]
                    task = asyncio.create_task(self._execute_tool(params))
                    self._tool_tasks[params["id"]] = task
                    task.add_done_callback(
                        lambda _task, key=params["id"]: self._tool_tasks.pop(key, None)
                    )
                elif message.get("method") == "tool_cancel":
                    task = self._tool_tasks.get(message["params"]["id"])
                    if task:
                        task.cancel()
                elif message.get("method") in {"event", "stream_error"}:
                    self._broadcast(message["params"])
        except (
            ValueError,
            TypeError,
            KeyError,
            ConnectionError,
            asyncio.LimitOverrunError,
        ) as exc:
            error = BrowserUseError(f"Runtime protocol failure: {exc}")
        finally:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(error)
            for task in list(self._tool_tasks.values()):
                task.cancel()
            self._broadcast(error)

    def _broadcast(self, event: Any) -> None:
        for queue in list(self._queues):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(
                    BrowserUseError(
                        "Event consumer fell behind; read the persisted run log."
                    )
                )
                self._queues.discard(queue)
            else:
                queue.put_nowait(event)

    async def _read_stderr(self) -> None:
        assert self._process and self._process.stderr
        while chunk := await self._process.stderr.read(4096):
            self._stderr = (self._stderr + chunk.decode(errors="replace"))[-16000:]

    async def _execute_tool(self, params: dict[str, Any]) -> None:
        try:
            tool = self._tools[params["name"]]
            args = tool.parameters.model_validate(params["args"])
            # Synchronous application tools run off the event loop; cancellation is cooperative.
            result = (
                await tool.execute(args)
                if inspect.iscoroutinefunction(tool.execute)
                else await asyncio.to_thread(tool.execute, args)
            )
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, BaseModel):
                result = result.model_dump(mode="json")
            await self._call("tool_result", {"id": params["id"], "result": result})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- application tool exceptions become model-visible error results
            try:
                await self._call("tool_result", {"id": params["id"], "error": str(exc)})
            except BrowserUseError:
                pass

    async def _run(
        self,
        method: str,
        task: str,
        schema: type[BaseModel] | dict[str, Any] | None,
        options: dict[str, Any],
    ) -> RunResult:
        if schema is not None:
            options["schema"] = (
                _schema(schema.model_json_schema())
                if inspect.isclass(schema) and issubclass(schema, BaseModel)
                else _schema(schema)
            )
        try:
            result = await self._call(method, {"task": task, "options": options})
        except asyncio.CancelledError:
            await asyncio.shield(self.cancel())
            raise
        output = result.get("output")
        if (
            result["status"] == "completed"
            and inspect.isclass(schema)
            and issubclass(schema, BaseModel)
        ):
            output = schema.model_validate(output)
        return RunResult(result["status"], output, result["text"], result)

    async def run(
        self,
        task: str,
        *,
        schema: type[BaseModel] | dict[str, Any] | None = None,
        **options: Any,
    ) -> RunResult:
        return await self._run("run", task, schema, options)

    async def follow_up(
        self,
        task: str,
        *,
        schema: type[BaseModel] | dict[str, Any] | None = None,
        **options: Any,
    ) -> RunResult:
        return await self._run("followUp", task, schema, options)

    async def execute(self, code: str, **options: Any) -> dict[str, Any]:
        return await self._call("execute", {"code": code, "options": options})

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._queues.add(queue)
        try:
            while not self._closed:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                if item is None:
                    return
                yield item
        finally:
            self._queues.discard(queue)

    async def pause(self) -> bool:
        return (await self._call("pause"))["paused"]

    async def resume(self) -> None:
        await self._call("resume")

    async def steer(self, text: str) -> None:
        await self._call("steer", {"text": text})

    async def cancel(self) -> None:
        await self._call("cancel")

    async def files(self) -> list[dict[str, Any]]:
        return await self._call("files")

    async def history(self) -> dict[str, Any]:
        return await self._call("history")

    async def save_history(self, path: str | None = None) -> str:
        return await self._call("saveHistory", {"path": path} if path else {})

    async def export_recording(self, path: str, **options: Any) -> str:
        return await self._call("exportRecording", {"path": path, "options": options})

    async def close(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        await asyncio.shield(self._closing)

    async def _close(self) -> None:
        if self._closed:
            return
        try:
            if self._process and self._process.returncode is None:
                try:
                    await asyncio.wait_for(self._call("close"), 10)
                except (BrowserUseError, ConnectionError, asyncio.TimeoutError) as exc:
                    self._stderr = (self._stderr + f"\nGraceful close failed: {exc}")[
                        -16000:
                    ]
                if self._process.stdin:
                    self._process.stdin.close()
                try:
                    await asyncio.wait_for(self._process.wait(), 5)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
        finally:
            self._closed = True
            self._broadcast(None)
            tasks = [
                task
                for task in [
                    self._reader,
                    self._stderr_task,
                    *self._tool_tasks.values(),
                ]
                if task
            ]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()
