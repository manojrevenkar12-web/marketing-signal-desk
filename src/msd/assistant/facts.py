"""The facts a written answer may use: the diagnosis, rounded the way it will be stated.

Campaign and account names come from the ad platforms, and anyone who can create a campaign can
put text in them. They reach the model only inside the facts, as data, with anything that reads
like an instruction cut out.
"""

from __future__ import annotations

import re
from typing import Any

from msd.conf import channel_label

_INSTRUCTION = re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions?|rules|above|previous)\b|\b(you are now|system prompt|assistant:)", re.I)


def clean_name(name: str | None) -> str | None:
    if name is None:
        return None
    name = re.sub(r"[\x00-\x1f<>{}`]", " ", name)[:120]
    return "[name withheld: contains instructions]" if _INSTRUCTION.search(name) else name.strip()


def _r(v: Any, nd: int = 2) -> Any:
    return round(v, nd) if isinstance(v, float) else v


def build(result: dict[str, Any], proposals: list[dict[str, Any]], currency: str = "EUR") -> dict[str, Any]:
    k = result.get("kpi", {})
    metric = result.get("metric", "cpa")
    unit = currency if metric == "cpa" else "x"
    f: dict[str, Any] = {
        "metric": metric.upper(),
        "unit": unit,
        "source": "GA4" if result.get("source") == "ga4" else "the ad platforms",
        "current_period": result["periods"]["current"],
        "baseline_period": result["periods"]["baseline"],
        "kpi_before": _r(k.get("baseline")),
        "kpi_now": _r(k.get("current")),
        "kpi_change": _r(k.get("change")),
        "kpi_change_pct": k.get("change_pct"),
        "material": result.get("material", False),
        "offsetting": result.get("offsetting", False),
        "causes": [],
        "data_problems": [],
        "proposals": [],
    }
    for i, c in enumerate(result.get("causes", []), 1):
        f["causes"].append(
            {
                "rank": i,
                "type": c["type"],
                "what": c["text"],
                "channel": channel_label(c.get("channel")) if c.get("channel") else None,
                "campaign": clean_name(c.get("campaign")),
                "effect_on_kpi": _r(c["share"]),
                "share_of_change_pct": c.get("share_of_change_pct"),
                "evidence": {key: (clean_name(v) if isinstance(v, str) else _r(v)) for key, v in c.get("evidence", {}).items()},
            }
        )
    for s in result.get("signals", []):
        f["data_problems"].append(
            {
                "kind": s["kind"],
                "channel": channel_label(s.get("channel")) if s.get("channel") else None,
                "campaign": clean_name(s.get("campaign")),
                "since": s.get("since"),
                "summary": s["summary"],
                "evidence": s.get("evidence", {}),
            }
        )
    for p in proposals:
        f["proposals"].append({"title": p["title"], "budget_change_per_day": p.get("budget_change_per_day"), "action": p["action"]})
    return f


def numbers(obj: Any) -> list[float]:
    """Every number in the facts, including those written inside text (summaries, actions)."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, str):
        for m in re.finditer(r"[-+]?\d[\d,]*(?:\.\d+)?", obj):
            try:
                out.append(float(m.group().replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(numbers(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(numbers(v))
    return out
