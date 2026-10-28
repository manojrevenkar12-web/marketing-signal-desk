"""python manage.py evals [dev|robustness|heldout <set>|all]

dev and heldout run end to end in a throwaway test database (created and dropped by this command).
The held-out set's first run is written once to reports/heldout/<set>/first_run.json and never
rewritten; later runs go to latest.json, and a changed set is refused."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.test.utils import setup_databases, teardown_databases

from msd.conf import ROOT


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + "\n")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


class Command(BaseCommand):
    help = "Run the evaluation suites"

    def add_arguments(self, parser):
        parser.add_argument("suite", choices=["dev", "robustness", "heldout", "all"])
        parser.add_argument("set", nargs="?", default="")
        parser.add_argument("--seeds", type=int, default=10)

    def handle(self, *args: Any, **o: Any) -> None:
        suite = o["suite"]
        if suite in ("robustness", "all"):
            from msd.evals.robustness import run

            rep = run(ROOT / "scenarios" / "dev", o["seeds"])
            _write(ROOT / "reports" / "evals" / "robustness.json", rep)
            self.stdout.write(f"robustness: {rep['summary']['fully_right']}/{rep['summary']['runs']} fully right ({rep['summary']['rate']:.1%})")
        if suite in ("dev", "all"):
            rep = self._e2e(ROOT / "scenarios" / "dev")
            _write(ROOT / "reports" / "evals" / "dev.json", rep)
            self._print("dev", rep["summary"])
        if suite == "heldout":
            if not o["set"]:
                raise CommandError("name the held-out set, e.g. evals heldout blind-1")
            self._heldout(o["set"])

    def _e2e(self, directory: Path) -> dict[str, Any]:
        from django.db import connections

        from msd.evals.run import run_suite

        connections["default"].settings_dict["TEST"]["NAME"] = "msd_eval"  # never the test suite's database
        old = setup_databases(verbosity=0, interactive=False)
        try:
            return run_suite(directory)
        finally:
            teardown_databases(old, verbosity=0)

    def _print(self, name: str, s: dict[str, Any]) -> None:
        self.stdout.write(
            f"{name}: top cause right {s['top_cause_right']}/{s['scenarios']}, recall {s['cause_recall']}, false causes {s['false_causes']}, "
            f"signals {s['signals_found']}/{s['signals_expected']} (false {s['false_signals']}), untraced numbers shipped {s['untraced_numbers_shipped']}, "
            f"wrong cuts/day {s['wrong_budget_cuts_per_day']} vs naive {s['naive_rule_wrong_cuts_per_day']}"
        )
        if s["failed"]:
            self.stdout.write("  failed: " + ", ".join(s["failed"]))

    def _heldout(self, name: str) -> None:
        from msd.evals.run import file_sha256

        d = ROOT / "heldout" / name
        cases = list(d.glob("*.yaml"))
        if not cases:
            raise CommandError(f"no scenarios in {d}")
        digest = hashlib_dir(d)
        out = ROOT / "reports" / "heldout" / name
        first = out / "first_run.json"
        if first.exists():
            pinned = json.loads(first.read_text())["set_sha256"]
            if pinned != digest:
                raise CommandError(f"heldout/{name} changed since its first run; a changed set needs a new name")
            target = out / "latest.json"
            self.stdout.write("first run already recorded; writing latest.json (the first run is never rewritten)")
        else:
            target = first
        rep = self._e2e(d)
        rep.update(
            set_sha256=digest,
            status=(d / "STATUS").read_text().strip() if (d / "STATUS").exists() else "heldout",
            code_commit=_commit(),
            recorded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            files={p.name: file_sha256(p) for p in sorted(cases)},
        )
        _write(target, rep)
        self._print(f"heldout/{name}", rep["summary"])


def hashlib_dir(d: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in sorted(d.glob("*.yaml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()
