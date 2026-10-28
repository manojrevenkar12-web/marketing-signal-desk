"""Shape analysis results for the templates: the KPI bridge, answer text with its checked numbers,
and labels. No styling decisions here beyond which token a bar uses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from msd.conf import channel_label as _label

DRIVER_LABEL = {"cpm": "CPM", "ctr": "CTR", "cvr": "CVR", "aov": "order value", "mix": "Spend mix"}
MEASUREMENT = {"tracking_loss", "platform_overreporting"}
CHART_W = 640
ROW_H = 40  # px; the template's label rows use h-10 (2.5rem), keep the two equal
BAR_H = 16
BAR_Y = (ROW_H - BAR_H) / 2
MAX_ROWS = 7


def channel_label(ch: str | None) -> str:
    return _label(ch) if ch else "All channels"


def cause_cards(result: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in result.get("causes", []):
        label = _label(c.get("channel"))
        where = f"{c['campaign']} on {label}" if c.get("campaign") else (label if c.get("channel") else "Every channel")
        out.append({**c, "where": where, "measurement": c["type"] in MEASUREMENT})
    return out


@dataclass
class Bar:
    label: str
    note: str
    value: float
    x: float
    width: float
    y: float
    tone: str  # start, end, worse, better, measure
    negative: bool
    step: int


def _fmt(v: float, metric: str, signed: bool = False) -> str:
    if metric == "roas":
        return f"{v:+.2f}x" if signed else f"{v:.2f}x"
    return f"{v:+,.2f}" if signed else f"{v:,.2f}"


def bridge(result: dict[str, Any]) -> dict[str, Any] | None:
    dec = result.get("decomposition")
    if not dec:
        return None
    metric = result["metric"]
    shares: dict[str, float] = dec["shares"]
    # which players belong to a measurement cause, and the cause behind each player
    owner: dict[str, str] = {}
    for c in result.get("causes", []):
        chans = [c["channel"]] if c.get("channel") else list(dec["units"])
        for ch in chans:
            for d in c["drivers"]:
                owner["mix" if d == "mix" else f"{ch}|{d}"] = c["type"]
    ranked = sorted(shares, key=lambda p: -abs(shares[p]))
    top = ranked[:MAX_ROWS]
    rest = sum(shares[p] for p in ranked[MAX_ROWS:])
    rows: list[tuple[str, str, float, str | None]] = []
    for p in top:
        if p == "mix":
            label = "Spend mix"
        else:
            ch, d = p.split("|")
            label = f"{channel_label(ch)} {DRIVER_LABEL[d]}"
        rows.append((label, owner.get(p, ""), shares[p], owner.get(p)))
    if abs(rest) > 1e-9:
        rows.append(("Everything else", "", rest, None))
    base, cur = dec["baseline"], dec["current"]
    cum = base
    points = [base]
    for _, _, v, _ in rows:
        cum += v
        points.append(cum)
    # bars start at zero, as a bridge's first and last bars do, so the totals read as lengths
    lo, hi = min(0.0, *points), max(points) * 1.04 or 1.0
    pad = 0.0

    def sx(v: float) -> float:
        return (v - lo) / (hi - lo) * CHART_W

    worse_sign = 1 if metric == "cpa" else -1
    bars = [Bar("Before", _period(result, "baseline"), base, sx(min(lo + pad, base)), sx(base) - sx(min(lo + pad, base)), BAR_Y, "start", False, 0)]
    cum = base
    for i, (label, kind, v, own) in enumerate(rows, 1):
        a, b = cum, cum + v
        tone = "measure" if own in MEASUREMENT else ("worse" if v * worse_sign > 0 else "better")
        bars.append(Bar(label, kind.replace("_", " ") if kind else "", v, sx(min(a, b)), max(1.5, abs(sx(b) - sx(a))), i * ROW_H + BAR_Y, tone, v < 0, min(i, 8)))
        cum = b
    n = len(bars)
    bars.append(Bar("Now", _period(result, "current"), cur, sx(min(lo + pad, cur)), sx(cur) - sx(min(lo + pad, cur)), n * ROW_H + BAR_Y, "end", False, min(n, 8)))
    return {
        "metric": metric.upper(),
        "bars": bars,
        "width": CHART_W,
        "height": (n + 1) * ROW_H,
        "row_h": ROW_H,
        "bar_h": BAR_H,
        "labels": [{"label": b.label, "note": b.note, "value": _fmt(b.value, metric, signed=b.tone not in ("start", "end")), "tone": b.tone} for b in bars],
    }


def _period(result: dict[str, Any], key: str) -> str:
    p = result["periods"][key]
    from datetime import date

    s, e = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    return f"{s:%-d %b} to {e:%-d %b}"


def answer_segments(text: str, numbers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split an answer into text and checked numbers, by the offsets the grounding check recorded."""
    out: list[dict[str, Any]] = []
    pos = 0
    for n in sorted((n for n in numbers if n.get("checked", True)), key=lambda n: n["start"]):
        s, e = n["start"], n["end"]
        # the recorded span may include a leading space or currency sign: trim to the visible number
        while s < e and text[s].isspace():
            s += 1
        if s < pos:
            continue
        if s > pos:
            out.append({"text": text[pos:s], "number": False})
        out.append({"text": text[s:e].rstrip(), "number": True, "traced": n["traced"]})
        pos = s + len(text[s:e].rstrip())
    if pos < len(text):
        out.append({"text": text[pos:], "number": False})
    return out
