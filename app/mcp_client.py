

import asyncio
import json
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self):
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._thread: threading.Thread | None = None
        self._thread_loop: asyncio.AbstractEventLoop | None = None
        self._thread_ready = threading.Event()

    def _needs_dedicated_loop(self) -> bool:
        return sys.platform == "win32" and isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)

    async def _run_in_dedicated_loop(self, coroutine):
        if self._thread is None:
            self._thread = threading.Thread(target=self._start_thread_loop, daemon=True)
            self._thread.start()
            await asyncio.to_thread(self._thread_ready.wait)

        future = asyncio.run_coroutine_threadsafe(coroutine, self._thread_loop)
        return await asyncio.wrap_future(future)

    def _start_thread_loop(self):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        self._thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._thread_loop)
        self._thread_ready.set()
        self._thread_loop.run_forever()

    async def _list_tools(self) -> list[dict]:
        await self._ensure_connected()
        result = await self._session.list_tools()
        return [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in result.tools
        ]

    async def _call_tool(self, name: str, arguments: dict) -> dict | list | str:
        await self._ensure_connected()
        result = await self._session.call_tool(name, arguments)

        if result.isError:
            error_text = result.content[0].text if result.content else "unknown MCP tool error"
            raise RuntimeError(f"MCP tool '{name}' failed: {error_text}")

        text = result.content[0].text if result.content else "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def _ensure_connected(self):
        if self._session is not None:
            return
        async with self._lock:
            if self._session is not None: 
                return
            self._stack = AsyncExitStack()
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "mcp_server.server"],
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session

    async def list_tools(self) -> list[dict]:
        if self._needs_dedicated_loop():
            return await self._run_in_dedicated_loop(self._list_tools())
        return await self._list_tools()

    async def call_tool(self, name: str, arguments: dict) -> dict | list | str:
        if self._needs_dedicated_loop():
            return await self._run_in_dedicated_loop(self._call_tool(name, arguments))
        return await self._call_tool(name, arguments)

    async def close(self):
        if self._thread_loop is not None:
            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(
                        asyncio.run_coroutine_threadsafe(self._close(), self._thread_loop)
                    ),
                    timeout=2.0
                )
            except (RuntimeError, asyncio.TimeoutError, asyncio.CancelledError, Exception):
                # Ignore all errors during shutdown with dedicated thread loop
                # This can happen during uvicorn reload/shutdown
                pass
            finally:
                try:
                    self._thread_loop.call_soon_threadsafe(self._thread_loop.stop)
                except (RuntimeError, Exception):
                    pass
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=1)
                self._thread = None
                self._thread_loop = None
                self._thread_ready.clear()
            return
        
        try:
            await self._close()
        except (RuntimeError, asyncio.CancelledError, Exception):
            pass

    async def _close(self):
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except (RuntimeError, asyncio.CancelledError, Exception):
                # Ignore all errors during cleanup
                pass
            finally:
                self._session = None
                self._stack = None


mcp_client = MCPClient()
