"""The one place that knows which `mcp` SDK is installed.

mcp 2.0.0 removed the six low-level decorators this server was built on and changed how a
handler receives its request context. Rather than fork `server.py`, the six handlers there keep
their original name/signature/body and get *bound* here — so the version branch lives in a
single file, and dropping 1.x support later is one deleted branch.

What each SDK gives us, and what we therefore have to reproduce:

  1.x  @server.call_tool()  validates the arguments against the tool's inputSchema and turns a
       raised exception into an `isError` tool result. `read_resource` returning a `str` is
       wrapped as `text/plain`. The other four decorators do NOT catch exceptions.
  2.x  `add_request_handler(method, params_type, handler)` does none of that — a handler is
       (ctx, params) -> *Result and an exception becomes a JSON-RPC protocol error.

So the 2.x adapters below re-implement exactly the 1.x envelope, no more: the wire payload must
not depend on which SDK happens to be resolved. `jsonschema` is a hard dependency of `mcp`
itself on both majors, so using it adds nothing to our own footprint (stdlib + `mcp` only).
"""
from __future__ import annotations

import contextvars
import re
from collections.abc import Awaitable, Callable
from typing import Any

import jsonschema
from mcp import types as t

_MISSING = object()
_SNAKE = re.compile(r"(?<!^)([A-Z])")

# 1.x publishes the live request context on the server; 2.x hands it to the handler instead.
# The adapters below stash it here so `request_ctx()` answers the same question either way.
# Same propagation semantics as the SDK's own (a ContextVar, inherited by child tasks).
_CTX: contextvars.ContextVar[Any] = contextvars.ContextVar("cli_bridge_mcp_ctx", default=None)

# The six handlers, filled by register() on the 2.x path (the 1.x path hands them to the SDK).
_H: dict[str, Callable[..., Awaitable[Any]]] = {}

# Mirrors the 1.x server's own tool cache: fill on a miss, keep otherwise. Only used to find an
# inputSchema for validation, so a lane installed mid-session is picked up on the next miss.
_TOOL_CACHE: dict[str, Any] = {}


def register(
    server: Any,
    *,
    list_tools: Callable[[], Awaitable[Any]],
    call_tool: Callable[[str, dict], Awaitable[Any]],
    list_prompts: Callable[[], Awaitable[Any]],
    get_prompt: Callable[[str, dict | None], Awaitable[Any]],
    list_resources: Callable[[], Awaitable[Any]],
    read_resource: Callable[[Any], Awaitable[str]],
) -> None:
    """Bind the six MCP handlers to whichever SDK major is installed."""
    if hasattr(server, "list_tools"):
        # mcp 1.x. The decorators return the function unchanged, so calling them for their side
        # effect and discarding the result is exactly what `@server.list_tools()` did — just
        # explicit, and in one place.
        server.list_tools()(list_tools)
        server.call_tool()(call_tool)
        server.list_prompts()(list_prompts)
        server.get_prompt()(get_prompt)
        server.list_resources()(list_resources)
        server.read_resource()(read_resource)
        return
    # mcp 2.x. Capabilities are derived from the registered method names, so add_request_handler
    # advertises tools/prompts/resources exactly as the decorators used to.
    _H.update(list_tools=list_tools, call_tool=call_tool, list_prompts=list_prompts,
              get_prompt=get_prompt, list_resources=list_resources, read_resource=read_resource)
    for method, params_type, handler in (
        ("tools/list",     t.PaginatedRequestParams,    _on_list_tools),
        ("tools/call",     t.CallToolRequestParams,     _on_call_tool),
        ("prompts/list",   t.PaginatedRequestParams,    _on_list_prompts),
        ("prompts/get",    t.GetPromptRequestParams,    _on_get_prompt),
        ("resources/list", t.PaginatedRequestParams,    _on_list_resources),
        ("resources/read", t.ReadResourceRequestParams, _on_read_resource),
    ):
        server.add_request_handler(method, params_type, handler)


def attr(obj: Any, camel: str, default: Any = None) -> Any:
    """Read a field off an SDK model whatever this major calls it.

    2.0 renamed every model attribute to snake_case and kept camelCase only as the pydantic
    *alias* — so it still validates and still goes on the wire camelCased, but `tool.inputSchema`
    and `params.clientInfo` now raise AttributeError. Construction with camelCase keeps working
    (populate_by_name), which is why only reads need this.
    """
    for name in (camel, _SNAKE.sub(r"_\1", camel).lower()):
        found = getattr(obj, name, _MISSING)
        if found is not _MISSING:
            return found
    return default


def progress_token(meta: Any) -> Any:
    """`_meta.progressToken` off a request context's meta, or None if the caller wants no
    progress. 1.x parses `_meta` into a model; 2.x leaves a plain dict keyed `progress_token`
    (it re-aliases to `progressToken` on the way back out)."""
    if meta is None:
        return None
    if isinstance(meta, dict):
        return meta.get("progress_token")
    return getattr(meta, "progressToken", None)


def request_ctx(server: Any) -> Any:
    """The live MCP request context, or None outside a request.

    1.x exposes it as a server property that RAISES LookupError when there is no request in
    flight — which is why this is a try/except and not `getattr(server, ..., None)`, whose
    default only covers AttributeError. 2.x has no such property at all (AttributeError), and
    the adapters above put the context in _CTX instead.
    """
    try:
        return server.request_context
    except (AttributeError, LookupError):
        return _CTX.get()


# ─────────────────────────────── mcp 2.x adapters ───────────────────────────────

async def _on_list_tools(ctx: Any, params: Any) -> Any:
    _CTX.set(ctx)
    return t.ListToolsResult(tools=await _H["list_tools"]())


async def _on_list_prompts(ctx: Any, params: Any) -> Any:
    _CTX.set(ctx)
    return t.ListPromptsResult(prompts=await _H["list_prompts"]())


async def _on_get_prompt(ctx: Any, params: Any) -> Any:
    _CTX.set(ctx)
    return await _H["get_prompt"](params.name, params.arguments)


async def _on_list_resources(ctx: Any, params: Any) -> Any:
    _CTX.set(ctx)
    return t.ListResourcesResult(resources=await _H["list_resources"]())


async def _on_read_resource(ctx: Any, params: Any) -> Any:
    _CTX.set(ctx)
    text = await _H["read_resource"](params.uri)
    # 1.x wraps a str return as text/plain; keep that, so a host sees the same bytes on both.
    return t.ReadResourceResult(contents=[
        t.TextResourceContents(uri=params.uri, mimeType="text/plain", text=text)])


async def _on_call_tool(ctx: Any, params: Any) -> Any:
    _CTX.set(ctx)
    args = params.arguments or {}
    try:
        tool = await _tool_def(params.name)
        if tool is not None:
            try:
                jsonschema.validate(instance=args, schema=attr(tool, "inputSchema"))
            except jsonschema.ValidationError as e:
                return _error_result(f"Input validation error: {e.message}")
        return t.CallToolResult(content=list(await _H["call_tool"](params.name, args)),
                                isError=False)
    except Exception as e:                     # noqa: BLE001 — a tool error, not a protocol error
        return _error_result(str(e))


async def _tool_def(name: str) -> Any:
    if name not in _TOOL_CACHE:
        for tool in await _H["list_tools"]():
            _TOOL_CACHE[tool.name] = tool
    return _TOOL_CACHE.get(name)


def _error_result(message: str) -> Any:
    return t.CallToolResult(content=[t.TextContent(type="text", text=message)], isError=True)
