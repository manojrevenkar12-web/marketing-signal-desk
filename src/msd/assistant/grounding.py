"""Every number in a written answer must come from the facts.

A number counts as traced when some fact equals it at the precision it is written ("12.5%" matches
12.46; "1,234" matches 1234.2). Sign words are allowed ("down 3%" for -3). Dates, years and numbers
the user wrote in the question are not checked. An untraced number sends the answer back to the
model once; if it is still there, the answer is replaced by the template, which is traced by
construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUM = re.compile(r"(?<![\w.])([-+−]?)(?:€\s?)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?(?:%|x|€|EUR|pts|pp|points|days?|h|clicks|conversions)?)", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?\b|\b(?:19|20)\d{2}\b", re.I)


@dataclass
class Stated:
    text: str
    value: float
    decimals: int
    start: int
    end: int
    unit: str = ""


@dataclass
class Report:
    stated: list[Stated] = field(default_factory=list)
    untraced: list[Stated] = field(default_factory=list)
    exempt: list[Stated] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.untraced

    def as_list(self) -> list[dict]:
        bad = {(u.start, u.end) for u in self.untraced}
        free = {(u.start, u.end) for u in self.exempt}
        return [{"text": s.text, "value": s.value, "start": s.start, "end": s.end, "traced": (s.start, s.end) not in bad, "checked": (s.start, s.end) not in free} for s in self.stated]


def extract(text: str) -> list[Stated]:
    masked = _DATE.sub(lambda m: " " * len(m.group()), text)
    out = []
    for m in _NUM.finditer(masked):
        sign, whole, frac, unit = m.groups()
        v = float(whole.replace(",", "") + (frac or ""))
        if sign in ("-", "−"):
            v = -v
        euro = "€" in m.group()
        out.append(Stated(m.group().strip(), v, len(frac) - 1 if frac else 0, m.start(), m.end(), (unit or "").strip() or ("€" if euro else "")))
    return out


def _close(s: Stated, fact: float) -> bool:
    tol = 0.5 * 10 ** (-s.decimals) + 1e-9
    for cand in (fact, abs(fact)):
        if abs(abs(s.value) - abs(cand)) <= tol:
            return True
        # "about 3,400" stated for 3,412: allow rounding to the stated significant digits
        if s.decimals == 0 and abs(s.value) >= 100:
            digits = len(str(int(abs(s.value)))) - len(str(int(abs(s.value))).rstrip("0"))
            if digits and round(abs(cand), -digits) == abs(s.value):
                return True
    return False


def verify(text: str, facts: list[float], exempt: list[str] | None = None) -> Report:
    free = {abs(x.value) for e in exempt or [] for x in extract(e)}
    rep = Report()
    for s in extract(text):
        rep.stated.append(s)
        if abs(s.value) in free or (s.decimals == 0 and abs(s.value) <= 10 and not s.unit):
            rep.exempt.append(s)  # small bare counts ("3 channels", "top 2 causes") and the user's own numbers
            continue
        if not any(_close(s, f) for f in facts):
            rep.untraced.append(s)
    return rep
