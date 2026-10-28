"""Decision code never sees the truth: only msd.sim and msd.evals may read scenarios' truth."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "msd"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
        elif isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
    return out


@pytest.mark.parametrize("pkg", ["analysis", "assistant", "proposals", "web", "metrics", "tenancy"])
def test_no_truth_in_decision_code(pkg):
    for f in (SRC / pkg).rglob("*.py"):
        if "management" in f.parts:
            continue  # the demo seeder and the eval command are allowed to set up simulated accounts
        bad = {m for m in imports(f) if m.startswith(("msd.sim", "msd.evals"))}
        assert not bad, f"{f.relative_to(SRC)} imports {bad}"


def test_connectors_touch_the_simulator_only_for_simulated_accounts():
    src = (SRC / "connectors" / "sync.py").read_text()
    top = [n for n in ast.parse(src).body if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("msd.sim")]
    assert top == []  # imported inside the sim-mode branches only
