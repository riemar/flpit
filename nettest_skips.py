import ast
from pathlib import Path
from collections import Counter, defaultdict

skips = defaultdict(Counter)

for path in Path("./tests/nettests").rglob("*.py"):
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        continue

    for node in ast.walk(tree):
        if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "skip"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pytest"
        ):
            if node.args:
                try:
                    reason = ast.literal_eval(node.args[0])
                except (ValueError, TypeError):
                    reason = "<dynamic reason>"
            else:
                reason = "<no reason>"

            skips[str(path)][reason] += 1

for path in sorted(skips):
    print(path)
    for reason, count in skips[path].most_common():
        print(f"  {count:4}  {reason}")