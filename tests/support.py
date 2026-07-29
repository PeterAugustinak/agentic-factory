"""Shared test helpers.

PAF's deterministic scripts live at paths that are not importable names —
`hooks/PreToolUse-agent-guard.py` and `skills/paf-shared/paf-report-cost.py` both
contain hyphens, and neither directory is a package. They are loaded by file path
instead, which is also the honest thing to test: the tests exercise the exact file
the installer ships.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_GUARD = REPO_ROOT / "hooks" / "PreToolUse-agent-guard.py"
REPORT_COST = REPO_ROOT / "skills" / "paf-shared" / "paf-report-cost.py"


def load_module(path, name):
    """Import a Python file by path under an arbitrary module name.

    Both targets guard their entry point with `if __name__ == "__main__"`, so
    importing them runs only module-level definitions — no side effects.
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
