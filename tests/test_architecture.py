import ast
import unittest

import helpers

PACKAGE = "agentfile_lint"
# What a rule module may import from the package: the core it runs on, never the command layer.
RULE_ALLOWED = {"context", "discover", "errors", "finding", "frontmatter", "rules", "rules._json", "rules._text"}
# Vendored third-party code (PyYAML): its own imports are not checked; only frontmatter.py may use it.
VENDORED = f"{PACKAGE}._yaml"
VENDORED_USERS = {f"{PACKAGE}.frontmatter"}


def import_graph(root):
    """Module name -> set of package modules it imports (relative and absolute imports)."""
    pkg_dir = root / PACKAGE
    modules = {}
    for path in pkg_dir.rglob("*.py"):
        parts = path.relative_to(root).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        modules[name] = path
    graph = {}
    for name, path in modules.items():
        base_pkg = name if path.name == "__init__.py" else name.rpartition(".")[0]
        targets = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    anchor = base_pkg.split(".")[: len(base_pkg.split(".")) - (node.level - 1)]
                    base = ".".join(anchor + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                for alias in node.names:
                    full = f"{base}.{alias.name}"
                    if full in modules:
                        targets.add(full)
                    elif base in modules:
                        targets.add(base)
            elif isinstance(node, ast.Import):
                targets.update(a.name for a in node.names if a.name in modules)
        targets.discard(name)
        graph[name] = targets
    return graph


def is_vendored(name):
    return name == VENDORED or name.startswith(VENDORED + ".")


def own_modules(graph):
    """The graph without the vendored modules' own import edges."""
    return {name: targets for name, targets in graph.items() if not is_vendored(name)}


def vendored_users(graph):
    """Package modules outside the vendored code that import it."""
    return {name for name, targets in own_modules(graph).items() if any(is_vendored(t) for t in targets)}


def find_cycle(graph):
    state = {}

    def visit(node, stack):
        state[node] = 1
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt, stack + [nxt])
                if found:
                    return found
        state[node] = 2
        return None

    for node in sorted(graph):
        if node not in state:
            found = visit(node, [node])
            if found:
                return found
    return None


def rule_violations(graph):
    bad = []
    for name, targets in sorted(graph.items()):
        if not name.startswith(f"{PACKAGE}.rules."):
            continue
        for target in sorted(targets):
            short = target.removeprefix(f"{PACKAGE}.")
            if short not in RULE_ALLOWED and not short.startswith("rules."):
                bad.append(f"{name} -> {target}")
    return bad


class ArchitectureTest(unittest.TestCase):
    def test_package_has_no_import_cycle(self):
        self.assertIsNone(find_cycle(own_modules(import_graph(helpers.REPO))))

    def test_only_frontmatter_uses_the_vendored_yaml(self):
        self.assertEqual(vendored_users(import_graph(helpers.REPO)), VENDORED_USERS)

    def test_rules_import_only_the_core(self):
        self.assertEqual(rule_violations(import_graph(helpers.REPO)), [])

    def test_checks_catch_a_cycle_and_a_reverse_import(self):
        graph = {"p.a": {"p.b"}, "p.b": {"p.a"}}
        self.assertEqual(find_cycle(graph), ["p.a", "p.b", "p.a"])
        graph = {f"{PACKAGE}.rules.size": {f"{PACKAGE}.cli", f"{PACKAGE}.finding"}}
        self.assertEqual(rule_violations(graph), [f"{PACKAGE}.rules.size -> {PACKAGE}.cli"])
        graph = {f"{PACKAGE}.rules.skill": {f"{VENDORED}.loader"}, f"{VENDORED}.loader": {f"{VENDORED}.reader"}}
        self.assertEqual(vendored_users(graph), {f"{PACKAGE}.rules.skill"})


if __name__ == "__main__":
    unittest.main()
