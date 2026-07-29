"""The mcp 1.x / 2.x seam: handler binding, request-context lookup, renamed model fields.

These run against whichever SDK is installed — CI runs the suite on both majors, which is the
only thing that actually proves the compat layer works.
"""
import asyncio

import pytest
from mcp import types as t
from mcp.server.lowlevel import Server

from cli_bridge import mcp_compat, server

IS_V1 = hasattr(Server, "list_tools")


def test_register_binds_all_six_handlers():
    # server.py calls register() at import time; the six MCP methods must be served either way.
    if IS_V1:
        for req in (t.ListToolsRequest, t.CallToolRequest, t.ListPromptsRequest,
                    t.GetPromptRequest, t.ListResourcesRequest, t.ReadResourceRequest):
            assert req in server.server.request_handlers
    else:
        for method in ("tools/list", "tools/call", "prompts/list", "prompts/get",
                       "resources/list", "resources/read"):
            assert server.server.get_request_handler(method) is not None


def test_capabilities_still_advertise_tools_prompts_resources():
    # Binding via add_request_handler (2.x) must advertise the same capabilities the decorators
    # did — a server that serves tools but doesn't declare them is invisible to the host.
    caps = server.server.create_initialization_options().capabilities
    assert caps.tools is not None and caps.prompts is not None and caps.resources is not None


def test_request_ctx_is_none_outside_a_request():
    # 1.x's server.request_context is a property that RAISES LookupError when no request is in
    # flight, so getattr(..., None) would NOT shield this. Async jobs, the human CLI and tests
    # all land here.
    assert mcp_compat.request_ctx(server.server) is None


def test_request_ctx_reads_the_contextvar():
    sentinel = object()
    token = mcp_compat._CTX.set(sentinel)
    try:
        assert mcp_compat.request_ctx(server.server) is sentinel
    finally:
        mcp_compat._CTX.reset(token)


def test_attr_reads_either_spelling():
    tool = t.Tool(name="x", description="d", inputSchema={"type": "object"})
    assert mcp_compat.attr(tool, "inputSchema") == {"type": "object"}
    assert mcp_compat.attr(tool, "nothingLikeThis", "fallback") == "fallback"
    # A falsy value must come back as itself, not be swallowed by the default.
    ann = t.ToolAnnotations(readOnlyHint=False)
    assert mcp_compat.attr(ann, "readOnlyHint", "default") is False


def test_progress_token_handles_both_meta_shapes():
    assert mcp_compat.progress_token(None) is None
    assert mcp_compat.progress_token({"progress_token": 7}) == 7   # 2.x: _meta is a plain dict
    assert mcp_compat.progress_token({}) is None
    assert mcp_compat.progress_token(t.RequestParams.Meta(progressToken=7) if IS_V1
                                     else {"progress_token": 7}) == 7


@pytest.mark.skipif(IS_V1, reason="2.x adapters only exist when mcp 2.x is installed")
def test_call_tool_adapter_wraps_content():
    res = asyncio.run(mcp_compat._on_call_tool(
        None, t.CallToolRequestParams(name="doctor", arguments={})))
    assert isinstance(res, t.CallToolResult)
    assert mcp_compat.attr(res, "isError") is False
    assert res.content and res.content[0].text


@pytest.mark.skipif(IS_V1, reason="2.x adapters only exist when mcp 2.x is installed")
def test_call_tool_adapter_turns_an_exception_into_an_error_result(monkeypatch):
    # 1.x's @call_tool() decorator swallowed exceptions into isError; 2.x would let them become
    # a JSON-RPC protocol error instead. The adapter has to reproduce the old envelope.
    async def boom(name, args):
        raise RuntimeError("lane exploded")

    monkeypatch.setitem(mcp_compat._H, "call_tool", boom)
    res = asyncio.run(mcp_compat._on_call_tool(
        None, t.CallToolRequestParams(name="doctor", arguments={})))
    assert mcp_compat.attr(res, "isError") is True
    assert "lane exploded" in res.content[0].text


@pytest.mark.skipif(IS_V1, reason="2.x adapters only exist when mcp 2.x is installed")
def test_call_tool_adapter_validates_input_against_the_schema():
    # `task` is required on every ask_* tool; 1.x rejected a call missing it before our code ran.
    tools = asyncio.run(server.list_tools())
    ask = next((x for x in tools if x.name.startswith("ask_")), None)
    if ask is None:
        pytest.skip("no lane installed on this machine")
    res = asyncio.run(mcp_compat._on_call_tool(None, t.CallToolRequestParams(name=ask.name,
                                                                            arguments={})))
    assert mcp_compat.attr(res, "isError") is True
    assert "Input validation error" in res.content[0].text


@pytest.mark.skipif(IS_V1, reason="2.x adapters only exist when mcp 2.x is installed")
def test_read_resource_adapter_wraps_text():
    res = asyncio.run(mcp_compat._on_read_resource(
        None, t.ReadResourceRequestParams(uri="cli-bridge://config")))
    assert res.contents[0].text.startswith("{")
    # 1.x wrapped a str return as text/plain — same bytes on the wire on both majors.
    assert mcp_compat.attr(res.contents[0], "mimeType") == "text/plain"
