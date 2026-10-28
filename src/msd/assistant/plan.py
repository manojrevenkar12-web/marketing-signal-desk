"""What a question asks for, as a typed plan the rest of the system can check."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QuestionPlan(BaseModel):
    """The analysis a question asks for. Dates are inclusive."""

    supported: bool = Field(description="False when the question is not about why CPA or ROAS changed for this workspace")
    reason: str = Field(default="", description="When unsupported: what the assistant can answer instead")
    metric: Literal["cpa", "roas"] = Field(default="cpa", description="cpa = cost per acquisition/conversion; roas = return on ad spend")
    source: Literal["ga4", "platform"] = Field(default="ga4", description="ga4 unless the question asks for the platforms' own numbers")
    current_start: date | None = Field(default=None, description="First day of the period the question is about")
    current_end: date | None = Field(default=None, description="Last day of that period")
    baseline_start: date | None = Field(default=None, description="First day of the comparison period, if the question names one")
    baseline_end: date | None = None

    @model_validator(mode="after")
    def _order(self) -> QuestionPlan:
        if self.current_start and self.current_end and self.current_start > self.current_end:
            raise ValueError("current_start is after current_end")
        if self.baseline_start and self.baseline_end and self.baseline_start > self.baseline_end:
            raise ValueError("baseline_start is after baseline_end")
        if (self.baseline_start is None) != (self.baseline_end is None):
            raise ValueError("give both baseline dates or neither")
        return self


class PlanProblem(ValueError):
    pass


def check(plan: QuestionPlan, first_day: date, last_day: date) -> QuestionPlan:
    """Fill defaults and refuse periods the data does not cover."""
    if not plan.supported:
        return plan
    if plan.current_end is None:
        plan.current_end = last_day
    if plan.current_start is None:
        plan.current_start = plan.current_end - timedelta(days=6)
    if plan.current_end > last_day or plan.current_start < first_day:
        raise PlanProblem(f"the data covers {first_day:%d %b} to {last_day:%d %b %Y}; ask about a period inside it")
    if plan.baseline_start and (plan.baseline_start < first_day or plan.baseline_end > last_day):  # type: ignore[operator]
        raise PlanProblem(f"the comparison period must lie between {first_day:%d %b} and {last_day:%d %b %Y}")
    return plan
