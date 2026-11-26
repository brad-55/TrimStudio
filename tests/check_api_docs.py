"""The API contract must stay documented (docs/API.md).

Routes are extracted from app/main.py with AST (decorators only, which is how every route is
registered today).  A route count below/above EXPECTED_ROUTE_COUNT fails on purpose: adding
a route is an intentional change and the reviewer must update API.md and this constant.
"""
import ast
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "app" / "main.py"
DOC = ROOT / "docs" / "API.md"
EXPECTED_ROUTE_COUNT = 39  # intentional change gate: update together with docs/API.md
METHODS = ("get", "post", "delete", "put", "patch")

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


def norm(path):
    """One wildcard per path parameter, segment positions preserved."""
    out = []
    for seg in path.strip("/").split("/"):
        out.append("{param}" if seg.startswith("{") else seg)
    return "/" + "/".join(out)


def routes():
    tree = ast.parse(io.open(MAIN, encoding="utf-8").read())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in METHODS:
                continue
            if not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "app":
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                found.append((dec.func.attr.upper(), norm(dec.args[0].value)))
    return found


found = routes()
check("api docs: the route extraction found the expected number",
      len(found) == EXPECTED_ROUTE_COUNT,
      "extracted=%d expected=%d (update EXPECTED_ROUTE_COUNT and docs/API.md together)"
      % (len(found), EXPECTED_ROUTE_COUNT))

doc = io.open(DOC, encoding="utf-8").read()
documented = set()
for m in re.finditer(r"\b(GET|POST|DELETE|PUT|PATCH)\s+(\/[^\s,);|?<]*)", doc):
    documented.add((m.group(1), norm(m.group(2))))

missing = [r for r in found if r not in documented]
check("api docs: every route is documented", not missing,
      "missing=%s documented_count=%d" % (missing[:10], len(documented)))

# no stale entries: a documented METHOD+path that no longer exists
stale = sorted(documented - set(found))
check("api docs: no stale routes are documented", not stale, "stale=%s" % (stale[:10],))

print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
sys.exit(1 if fails else 0)
