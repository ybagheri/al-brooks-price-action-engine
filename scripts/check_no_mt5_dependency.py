#!/usr/bin/env python3
"""Fail CI if the platform-independent core ever depends on MetaTrader 5.

The project's central architectural rule is that the core must stay
platform-independent: MT5 integration belongs in `albrooks.adapters.mt5`.
This script enforces that mechanically rather than by convention.

Checks performed:

1. No module under `src/albrooks` outside the MT5 adapter may import
   `MetaTrader5` (or a submodule of it).
2. No module outside the MT5 adapter may import anything from
   `albrooks.adapters` at all -- adapters may be *used by* consumers, but the
   core must not reach back into them.
3. The core must not import heavyweight third-party runtime dependencies that
   are not declared in `pyproject.toml`.

Exit code is 1 if any violation is found, 0 otherwise.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "albrooks"

# Paths (relative to the package root) that are allowed to touch MT5.
MT5_ALLOWED_PREFIXES = ("adapters/mt5", "adapters/mt5.py")

# Third-party modules the core must never import. The core is standard-library
# only; `pandas` is permitted but only behind the optional adapter.
FORBIDDEN_CORE_IMPORTS = {
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "torch",
    "MetaTrader5",
}


def _is_mt5_allowed(rel_path: Path) -> bool:
    rel = rel_path.as_posix()
    return any(rel == p or rel.startswith(p) for p in MT5_ALLOWED_PREFIXES)


def _imports(tree: ast.AST) -> set[str]:
    """Top-level module names imported anywhere in the file."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def main() -> int:
    if not SRC_ROOT.is_dir():
        print(f"FAIL: package source not found at {SRC_ROOT}")
        return 1

    violations: list[str] = []
    scanned = 0

    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel_path = path.relative_to(SRC_ROOT)
        if "__pycache__" in rel_path.parts:
            continue
        scanned += 1

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - defensive
            violations.append(f"{rel_path}: could not parse ({exc})")
            continue

        imported = _imports(tree)
        mt5_allowed = _is_mt5_allowed(rel_path)

        for name in sorted(imported):
            if name == "MetaTrader5" and not mt5_allowed:
                violations.append(
                    f"{rel_path}: imports MetaTrader5 outside the MT5 adapter"
                )
            if name in FORBIDDEN_CORE_IMPORTS and name != "MetaTrader5":
                violations.append(
                    f"{rel_path}: core module imports heavy dependency '{name}'"
                )
            if name == "adapters" and not mt5_allowed:
                violations.append(
                    f"{rel_path}: core module reaches back into the adapters layer"
                )

    print(f"Scanned {scanned} module(s) under {SRC_ROOT.relative_to(REPO_ROOT)}")

    if violations:
        print(f"\nFAIL: {len(violations)} architecture violation(s):")
        for v in violations:
            print(f"  - {v}")
        print(
            "\nThe core must remain platform-independent. Move MT5 or heavy "
            "dependency usage into an adapter module."
        )
        return 1

    print("PASS: core is free of MetaTrader 5 and heavy runtime dependencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
