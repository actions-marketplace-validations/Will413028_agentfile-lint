""".mcp.json (M1 to M4; docs/rules.md "M1 to M4 .mcp.json").

Each case's consequence was measured with `claude mcp list` on Claude Code 2.1.318 (2026-11-06).
"""
import json
import unittest

from helpers import make_repo, run_new

MCP = ".mcp.json"


def lint(files: dict[str, str | bytes], config: str | None = None):
    files = dict(files)
    files.setdefault("AGENTS.md", "ok\n")
    if config is not None:
        files[".agentfile-lint.toml"] = config
    root = make_repo(files)
    r = run_new(root, "--format", "json", "--today", "2026-11-06")
    if r.returncode == 2:
        raise AssertionError(r.stderr)
    doc = json.loads(r.stdout)
    return [(f["file"], f["line"], f["rule"]) for f in doc["findings"]], doc


def servers(**entries) -> str:
    return json.dumps({"mcpServers": entries})


def rules_of(text: str | bytes, path: str = MCP) -> list[str]:
    return sorted({rule for _, _, rule in lint({path: text})[0]})


def messages(text: str | bytes) -> list[str]:
    return [f["message"] for f in lint({MCP: text})[1]["findings"]]


class ValidTest(unittest.TestCase):
    def test_documented_examples_report_nothing(self):
        text = servers(
            shared={"type": "http", "url": "https://example.com/mcp"},
            local={"type": "stdio", "command": "/path/to/weather-cli", "args": ["--api-key", "abc123"], "env": {"CACHE_DIR": "/tmp"}},
            implicit={"command": "npx", "args": ["-y", "@example/mcp-server"]},
            streamable={"type": "streamable-http", "url": "https://example.com/mcp"},
            events={"type": "ws", "url": "wss://mcp.example.com/socket"},
            legacy={"type": "sse", "url": "https://mcp.asana.com/sse"},
        )
        self.assertEqual(rules_of(text), [])

    def test_empty_file_bom_and_no_servers_report_nothing(self):
        self.assertEqual(rules_of(""), [])
        self.assertEqual(rules_of('{"mcpServers": {}}'), [])
        self.assertEqual(rules_of(b"\xef\xbb\xbf" + servers(a={"command": "x"}).encode()), [])

    def test_only_the_root_file_is_checked(self):
        # Project MCP configuration is the repository root's .mcp.json; a plugin's has another format.
        self.assertEqual(lint({"plugins/p/.mcp.json": '{"a": {"command": "x"}}', ".claude/.mcp.json": "{"})[0], [])


class FileTest(unittest.TestCase):
    def test_invalid_json(self):
        found, doc = lint({MCP: '{\n  "mcpServers": {\n'})
        self.assertEqual([r for _, _, r in found], ["M1"])
        self.assertEqual(doc["findings"][0]["level"], "warning")

    def test_top_level_not_an_object(self):
        self.assertEqual(rules_of("[]"), ["M1"])

    def test_servers_must_sit_under_mcp_servers(self):
        self.assertEqual(rules_of('{"servers": {"a": {"command": "x"}}}'), ["M2"])
        self.assertIn('"servers"', messages('{"servers": {"a": {"command": "x"}}}')[0])
        for text in ("{}", '{"mcpServers": []}', '{"mcpServers": null}'):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), ["M2"])


class EntryTest(unittest.TestCase):
    def test_entry_must_be_an_object_with_a_known_type(self):
        cases = ["x", None, {"type": "tcp", "url": "u"}, {"type": "STDIO", "command": "x"},
                 {"type": 1, "command": "x"}, {"type": None, "command": "x"}, {"type": "sdk"}]
        for entry in cases:
            with self.subTest(entry=entry):
                self.assertEqual(rules_of(servers(a=entry)), ["M3"])

    def test_sdk_type_says_why(self):
        self.assertIn("SDK host", messages(servers(a={"type": "sdk"}))[0])

    def test_required_field_per_type(self):
        cases = [{"type": "stdio"}, {}, {"command": ""}, {"command": ["npx"]},
                 {"type": "http"}, {"type": "sse", "url": 5}, {"type": "ws"}, {"url": "https://example.com/mcp"}]
        for entry in cases:
            with self.subTest(entry=entry):
                self.assertEqual(rules_of(servers(a=entry)), ["M4"])

    def test_url_without_type_says_to_add_one(self):
        self.assertIn('"type"', messages(servers(a={"url": "https://example.com/mcp"}))[0])

    def test_message_names_the_server(self):
        self.assertIn("mcpServers.my-db", messages(servers(**{"my-db": {"type": "http"}}))[0])

    def test_what_claude_code_accepts_is_not_reported(self):
        # A blank command only warns about whitespace, an empty url loads; optional field types are not checked.
        for entry in ({"command": "  "}, {"type": "http", "url": ""}, {"command": "x", "args": "y"}):
            with self.subTest(entry=entry):
                self.assertEqual(rules_of(servers(a=entry)), [])


class FamilyTest(unittest.TestCase):
    def test_mcp_globs_replace_and_extend(self):
        files = {MCP: "{", "plugins/p/.mcp.json": "{"}
        self.assertEqual({p for p, _, _ in lint(files, '[discover]\nmcp_globs = ["plugins/p/.mcp.json"]\n')[0]},
                         {"plugins/p/.mcp.json"})
        self.assertEqual({p for p, _, _ in lint(files, '[discover]\nextend_mcp_globs = ["plugins/*/.mcp.json"]\n')[0]},
                         {MCP, "plugins/p/.mcp.json"})
        self.assertEqual(lint(files, "[discover]\nmcp_globs = []\n")[0], [])

    def test_effective_config_shows_the_keys(self):
        root = make_repo({"AGENTS.md": "ok\n"})
        doc = json.loads(run_new(root, "config", "--format", "json").stdout)
        self.assertEqual(doc["discover"]["mcp_globs"], [".mcp.json"])
        self.assertEqual(doc["discover"]["extend_mcp_globs"], [])
        self.assertEqual([doc["rules"][f"M{i}"] for i in range(1, 5)], [{"level": "warn"}] * 4)

    def test_a_file_named_on_the_command_line_triggers_the_run(self):
        root = make_repo({"AGENTS.md": "ok\n", MCP: "{"})
        r = run_new(root, "--format", "json", MCP)
        self.assertEqual([f["rule"] for f in json.loads(r.stdout)["findings"]], ["M1"])


if __name__ == "__main__":
    unittest.main()
