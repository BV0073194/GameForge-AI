"""Validated, project-scoped MCP configuration shared by Codex and ACP.

Only environment variable *names* are persisted in gameforge.json. Secrets
remain in the user's process environment; never serialize them into state or logs.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
HEADER = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
MAX_SERVERS = 24


def validate_mcp_servers(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_SERVERS:
        raise ValueError("MCP servers must be a list of at most 24 entries")
    names: set[str] = set()
    result: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Each MCP server must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not NAME.fullmatch(name) or name.lower() in names:
            raise ValueError("MCP server names must be unique and use letters, digits, _ or -")
        names.add(name.lower())
        kind = entry.get("type", "http")
        if kind not in {"http", "stdio"}:
            raise ValueError(f"{name}: type must be http or stdio")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{name}: enabled must be true or false")
        cleaned: dict[str, Any] = {"name": name, "type": kind, "enabled": enabled}
        if kind == "http":
            url = entry.get("url")
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError(f"{name}: missing or invalid MCP URL")
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError(f"{name}: MCP URL must be http(s) with no credentials or fragment")
            cleaned["url"] = url
            bearer = entry.get("bearer_token_env_var", "")
            if bearer:
                if not isinstance(bearer, str) or not ENV.fullmatch(bearer):
                    raise ValueError(f"{name}: invalid bearer token environment variable")
                cleaned["bearer_token_env_var"] = bearer
            headers = entry.get("env_http_headers", {})
            if not isinstance(headers, dict) or len(headers) > 16:
                raise ValueError(f"{name}: env_http_headers must be an object with at most 16 entries")
            for header, variable in headers.items():
                if not isinstance(header, str) or not HEADER.fullmatch(header) or not isinstance(variable, str) or not ENV.fullmatch(variable):
                    raise ValueError(f"{name}: invalid HTTP header or environment variable")
            if headers:
                cleaned["env_http_headers"] = dict(headers)
        else:
            command = entry.get("command")
            args = entry.get("args", [])
            env_vars = entry.get("env_vars", [])
            if not isinstance(command, str) or not command.strip() or len(command) > 2048:
                raise ValueError(f"{name}: missing stdio executable")
            if not isinstance(args, list) or len(args) > 64 or any(not isinstance(a, str) or len(a) > 4096 for a in args):
                raise ValueError(f"{name}: invalid stdio args")
            if not isinstance(env_vars, list) or len(env_vars) > 32 or any(not isinstance(v, str) or not ENV.fullmatch(v) for v in env_vars):
                raise ValueError(f"{name}: invalid stdio env_vars")
            cleaned.update({"command": command, "args": list(args), "env_vars": list(env_vars)})
        result.append(cleaned)
    return result


def codex_mcp_config(servers: Any) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for server in validate_mcp_servers(servers):
        if not server["enabled"]:
            continue
        if server["type"] == "http":
            values: dict[str, Any] = {"url": server["url"], "enabled": True}
            for key in ("bearer_token_env_var", "env_http_headers"):
                if key in server:
                    values[key] = server[key]
        else:
            values = {"command": server["command"], "args": server["args"], "enabled": True}
            if server["env_vars"]:
                values["env_vars"] = server["env_vars"]
        config[server["name"]] = values
    return {"mcp_servers": config} if config else {}


def acp_mcp_servers(servers: Any, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    environment = os.environ if env is None else env
    result = []
    for server in validate_mcp_servers(servers):
        if not server["enabled"]:
            continue
        if server["type"] == "http":
            headers = [
                {"name": header, "value": environment[variable]}
                for header, variable in server.get("env_http_headers", {}).items()
                if environment.get(variable)
            ]
            bearer = server.get("bearer_token_env_var")
            if bearer and environment.get(bearer):
                if not any(h["name"].lower() == "authorization" for h in headers):
                    headers.append({"name": "Authorization", "value": "Bearer " + environment[bearer]})
            result.append({"type": "http", "name": server["name"], "url": server["url"], "headers": headers})
        else:
            variables = [
                {"name": key, "value": environment[key]}
                for key in server["env_vars"] if key in environment
            ]
            result.append({"type": "stdio", "name": server["name"], "command": server["command"], "args": server["args"], "env": variables})
    return result


def public_mcp_servers(servers: Any) -> list[dict[str, Any]]:
    """Never return expanded credentials to the dashboard."""
    return validate_mcp_servers(servers)
