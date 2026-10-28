# Held-out set blind-1

25 scenarios written by a separate writer who read only `heldout/WRITING_SCENARIOS.md` (v1), in an
empty folder, without seeing the code, the development scenarios or the thresholds. The files are
used exactly as written; the loader accepts two forms the v1 guide left open (see the guide's
change log). Its first run is recorded once in `reports/heldout/blind-1/first_run.json`; the set and
the first run are pinned by sha256 in `tests/test_heldout.py`.

The writer flagged one error in the v1 guide: its materiality example weighted by spend instead
of purchases. The writer sized every scenario with the purchase-weighted method and avoided
borderline effects.
