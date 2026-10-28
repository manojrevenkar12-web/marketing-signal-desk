"""The blind set and its first run are pinned: changing either fails here (see AGENTS.md)."""

import hashlib
import json

from tests.conftest import ROOT

SET_SHA256 = "0d75d3936d59"  # prefix of the set digest recorded in the first run
FIRST_RUN_SHA256 = "06ca45ca43a4b198d60edb1a59380f83f904fc1a4c31fd3e4000230b19b01344"


def test_first_run_is_never_rewritten():
    p = ROOT / "reports" / "heldout" / "blind-1" / "first_run.json"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == FIRST_RUN_SHA256


def test_the_set_is_unchanged():
    h = hashlib.sha256()
    for p in sorted((ROOT / "heldout" / "blind-1").glob("*.yaml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    rec = json.loads((ROOT / "reports" / "heldout" / "blind-1" / "first_run.json").read_text())
    assert h.hexdigest() == rec["set_sha256"] and rec["set_sha256"].startswith(SET_SHA256)
