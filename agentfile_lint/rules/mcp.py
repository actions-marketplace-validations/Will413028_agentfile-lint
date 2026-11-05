"""M1 to M4: a project's `.mcp.json` (docs/rules.md "M1 to M4 .mcp.json").

Only what makes Claude Code skip the file or a server: the file is JSON, servers sit under an
`mcpServers` object, each entry is an object with a known `type`, and each has the field its type
needs (`command` for stdio, the type of an entry without one; `url` for the remote types). The MCP
docs state the `mcpServers` key, the types and the `url`-without-`type` failure; each consequence and
the required fields were measured with `claude mcp list` on Claude Code 2.1.318. Optional fields are
not checked. Positions are JSON paths (`mcpServers.<name>`); the line is the file (0) except for a
JSON syntax error.
"""
from __future__ import annotations

from typing import Any

from ..errors import levels_only
from ..finding import Finding
from ._json import blank, kind, load

FAMILY = "mcp"

CHECKS = (
    ("M1", "mcp-json", ".mcp.json is valid JSON and an object"),
    ("M2", "mcp-servers", "servers sit under an mcpServers object"),
    ("M3", "mcp-type", "every server entry is an object with a documented type"),
    ("M4", "mcp-required", "every server has the field its type needs: command for stdio, url otherwise"),
)
WHOLE_FILE = tuple(rule_id for rule_id, _, _ in CHECKS)   # JSON has no comments; no directive applies

STDIO = "stdio"
# MCP docs: stdio, http (alias streamable-http), sse and ws; "sdk" only an SDK host can register.
REMOTE = ("http", "streamable-http", "sse", "ws")
TYPES = (STDIO, *REMOTE)
SKIPPED = "Claude Code skips this server"


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    return {}, levels_only(tables)


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    if blank(text):
        return []
    data, problem = load(text)
    if problem is not None:
        if not problem.invalid:
            return [Finding(path, 0, "M1", problem.why)]
        return [Finding(path, problem.line, "M1", f"not valid JSON: {problem.why}; Claude Code loads no server "
                        "from this file")]
    if not isinstance(data, dict):
        return [Finding(path, 0, "M1", f"the file is a JSON {kind(data)}, not an object; Claude Code loads no "
                        "server from it")]
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        if "mcpServers" in data:
            got = f"mcpServers is a JSON {kind(servers)}, not an object of servers by name"
        elif "servers" in data:
            got = 'servers sit under "servers" (another client\'s format); Claude Code reads only "mcpServers"'
        else:
            got = "no mcpServers object"
        return [Finding(path, 0, "M2", f"{got}; Claude Code loads no server from this file")]
    found: list[Finding] = []
    for name, entry in servers.items():
        found += _server(path, f"mcpServers.{name}", entry)
    return found


def _server(path: str, where: str, entry: Any) -> list[Finding]:
    if not isinstance(entry, dict):
        return [Finding(path, 0, "M3", f"{where} is a JSON {kind(entry)}, not an object; {SKIPPED}")]
    if "type" in entry:
        server_type = entry["type"]
        if server_type == "sdk":
            return [Finding(path, 0, "M3", f'{where}.type is "sdk", which only an SDK host application can '
                            f"register; {SKIPPED}")]
        if not isinstance(server_type, str) or server_type not in TYPES:
            shown = repr(server_type) if isinstance(server_type, str) else f"a JSON {kind(server_type)}"
            return [Finding(path, 0, "M3", f"{where}.type is {shown}, not one of {', '.join(TYPES)}; {SKIPPED}")]
    else:
        server_type = STDIO
    field = "command" if server_type == STDIO else "url"
    value = entry.get(field)
    if isinstance(value, str) and (value or field == "url"):   # an empty url loads; an empty command is refused
        return []
    if field == "command" and "type" not in entry and "url" in entry:
        return [Finding(path, 0, "M4", f'{where} has a url but no type, so it is read as a stdio server; add '
                        f'"type": "http" (or "sse" / "ws"); {SKIPPED}')]
    got = "missing" if field not in entry else ("empty" if value == "" else f"a JSON {kind(value)}")
    return [Finding(path, 0, "M4", f"{where}.{field} is {got}; a {server_type} server requires it as a "
                    f"{'non-empty ' if field == 'command' else ''}string; {SKIPPED}")]
