"""Tests for MCP transport selection."""

import pytest
from mcp.server.fastmcp import FastMCP

import main
from mcp_config import resolve_host, resolve_port, resolve_transport


class TestResolveTransport:
    """Tests for resolve_transport()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "stdio"),
            ("", "stdio"),
            ("   ", "stdio"),
            ("\t\n", "stdio"),
            ("  STDIO ", "stdio"),
            ("http", "streamable-http"),
            ("Http", "streamable-http"),
            ("streamable-http", "streamable-http"),
            ("streamable_http", "streamable-http"),
            ("sse", "sse"),
        ],
    )
    def test_valid_values(self, value, expected):
        assert resolve_transport(value) == expected

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_TRANSPORT"):
            resolve_transport("websocket")


class TestResolveHost:
    """Tests for resolve_host()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "127.0.0.1"),
            ("", "127.0.0.1"),
            ("   ", "127.0.0.1"),
            ("\t\n", "127.0.0.1"),
            (" 127.0.0.1 ", "127.0.0.1"),
            ("0.0.0.0", "0.0.0.0"),
        ],
    )
    def test_values(self, value, expected):
        assert resolve_host(value) == expected


class TestResolvePort:
    """Tests for resolve_port()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, 8000),
            ("", 8000),
            ("   ", 8000),
            ("\t\n", 8000),
            ("9000", 9000),
            (" 9000 ", 9000),
            ("1", 1),
            ("65535", 65535),
        ],
    )
    def test_valid_values(self, value, expected):
        assert resolve_port(value) == expected

    def test_non_integer_raises(self):
        with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_PORT"):
            resolve_port("not-a-number")

    def test_out_of_range_raises(self):
        for value in ("0", "-1", "65536"):
            with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_PORT"):
                resolve_port(value)


class TestApplyHostSettings:
    """Tests for apply_host_settings()."""

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
    def test_loopback_host_keeps_transport_security(self, host):
        server = FastMCP("whatsapp")
        main.apply_host_settings(server, host, 8000)
        assert server.settings.host == host
        assert server.settings.port == 8000
        assert server.settings.transport_security is not None
        assert server.settings.transport_security.enable_dns_rebinding_protection is True

    @pytest.mark.parametrize("host", ["0.0.0.0", "999.888.777.666", "internal-proxy.example"])
    def test_non_loopback_host_clears_transport_security(self, host):
        server = FastMCP("whatsapp")
        main.apply_host_settings(server, host, 9000)
        assert server.settings.host == host
        assert server.settings.port == 9000
        assert server.settings.transport_security is None
