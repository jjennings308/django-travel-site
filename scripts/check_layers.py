#!/usr/bin/env python
"""
Check that local apps only import down the dependency layers in CLAUDE.md.

Usage:
    python scripts/check_layers.py

Exits 1 and lists each violation if any app imports from a higher layer, from
a same-layer app the table does not allow, or imports the concrete
accounts.models.User outside accounts. Keep LAYERS and SAME_LAYER_ALLOWED in
step with the "Dependency layers" table in CLAUDE.md.
"""
import ast
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LAYERS = {
    "core": 0,
    "accounts": 1,
    "notifications": 2, "media_app": 2, "approval_system": 2, "rewards": 2,
    "locations": 3, "activities": 3, "vendors": 3, "events": 3,
    "bucketlists": 4, "trips": 4, "reviews": 4, "recommendations": 4,
    "pages": 5, "admin_tools": 5,
}

# Same-layer imports the table allows (importer -> imported). Layer 5 may import anything.
SAME_LAYER_ALLOWED = {
    ("approval_system", "notifications"),
    ("vendors", "locations"),
    ("events", "locations"),
    ("events", "activities"),
    ("reviews", "trips"),
    ("recommendations", "trips"),
}

TOP_LAYER = max(LAYERS.values())
SKIP_DIRS = {"migrations", "__pycache__"}


def iter_imports(path):
    """Yield (lineno, module, names) for each absolute import in a file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, []
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module, [alias.name for alias in node.names]


def check_import(app, module, names):
    """Return the violation messages for one import (empty if it is allowed)."""
    target = module.split(".")[0]
    if target == app:
        return []

    messages = []
    if module == "accounts.models" and "User" in names:
        messages.append("imports concrete accounts.models.User; use settings.AUTH_USER_MODEL or get_user_model()")

    if target in LAYERS:
        src, dst = LAYERS[app], LAYERS[target]
        if dst > src:
            messages.append(f"layer {src} imports {target} (layer {dst})")
        elif dst == src and src != TOP_LAYER and (app, target) not in SAME_LAYER_ALLOWED:
            messages.append(f"same-layer import {app} -> {target} is not in the allowed list")
    return messages


def find_violations(base_dir=BASE_DIR):
    violations = []
    for app in LAYERS:
        app_dir = base_dir / app
        if not app_dir.is_dir():
            continue
        for path in sorted(app_dir.rglob("*.py")):
            if SKIP_DIRS.intersection(path.relative_to(app_dir).parts):
                continue
            for lineno, module, names in iter_imports(path):
                for message in check_import(app, module, names):
                    violations.append(f"{path.relative_to(base_dir)}:{lineno}: {message}")
    return violations


def main():
    violations = find_violations()
    for line in violations:
        print(line)
    if violations:
        print(f"\n{len(violations)} layer violation(s). See 'Dependency layers' in CLAUDE.md.")
        return 1
    print("No layer violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
