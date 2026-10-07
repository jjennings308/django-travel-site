#!/usr/bin/env python
"""
Check that local apps only import down the dependency layers in CLAUDE.md.

Usage:
    python scripts/check_layers.py

Apps live under apps/ and are imported as apps.<name>; LAYERS is keyed by
the bare name (= the app label). Exits 1 and lists each violation if any app
imports from a higher layer, from a same-layer app the table does not allow,
imports the concrete apps.accounts.models.User outside accounts, imports a
local app without the apps. prefix, or if a Django app directory (one with
apps.py) sits at the repo root other than config and theme, or under apps/
without a LAYERS entry. Keep LAYERS and SAME_LAYER_ALLOWED in step with the
"Dependency layers" table in CLAUDE.md.
"""
import ast
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APPS_PACKAGE = "apps"
ROOT_APPS_ALLOWED = {"config", "theme"}

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
    """Return the violation messages for one import (empty if it is allowed).

    ``module`` is the absolute dotted path as written; local apps are expected
    as ``apps.<name>``.
    """
    parts = module.split(".")
    if parts[0] in LAYERS:
        return [f"imports local app as '{module}'; use 'apps.{module}'"]
    if parts[0] != APPS_PACKAGE or len(parts) < 2:
        return []
    target = parts[1]
    if target == app:
        return []

    messages = []
    if module == "apps.accounts.models" and "User" in names:
        messages.append("imports concrete apps.accounts.models.User; use settings.AUTH_USER_MODEL or get_user_model()")

    if target in LAYERS:
        src, dst = LAYERS[app], LAYERS[target]
        if dst > src:
            messages.append(f"layer {src} imports {target} (layer {dst})")
        elif dst == src and src != TOP_LAYER and (app, target) not in SAME_LAYER_ALLOWED:
            messages.append(f"same-layer import {app} -> {target} is not in the allowed list")
    return messages


def check_layout(base_dir):
    """App directories must live under apps/ and be listed in LAYERS."""
    problems = []
    for apps_py in sorted(base_dir.glob("*/apps.py")):
        name = apps_py.parent.name
        if name not in ROOT_APPS_ALLOWED:
            problems.append(f"{name}/: Django app at the repo root; move it under {APPS_PACKAGE}/")
    for apps_py in sorted((base_dir / APPS_PACKAGE).glob("*/apps.py")):
        name = apps_py.parent.name
        if name not in LAYERS:
            problems.append(f"{APPS_PACKAGE}/{name}/: app has no entry in LAYERS")
    return problems


def find_violations(base_dir=BASE_DIR):
    violations = check_layout(base_dir)
    for app in LAYERS:
        app_dir = base_dir / APPS_PACKAGE / app
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
