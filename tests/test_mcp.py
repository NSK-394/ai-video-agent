"""
Smoke tests for the MCP module.

MCP tools are not yet fully implemented — these tests verify the module
imports cleanly and the scaffolding is in place.
"""
import pytest


def test_mcp_server_imports():
    from mcp.server import start_mcp_server
    assert callable(start_mcp_server)


def test_mcp_server_does_not_raise_on_call():
    from mcp.server import start_mcp_server
    # The current stub logs "Starting MCP Server..." and returns None
    result = start_mcp_server()
    assert result is None
