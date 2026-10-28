# 0002: Check the data before explaining performance

## Context

Many "CPA went up" alarms are not performance at all: a broken GA4 tag, a consent banner, a
platform changing attribution, bot clicks, or a day missing from an export. Cutting budget on those
loses money that was never at risk.

## Decision

Run data checks (`msd.analysis.signals`) before the decomposition: tracking gap (GA4 conversions fall
while the platform's do not), over-reporting (the reverse), invalid traffic (extra clicks that do not
convert) and missing days. A cause backed by a measurement problem is shown as "data problem", and
its proposal is to hold, not to cut.

## Consequences

- The proposal engine never cuts budget for a tracking problem. The evals compare it with a naive
  rule (cut 25% when a channel's CPA rises 20%): 0 wrong cuts against 3,901 EUR/day on the dev set
  and 3,751 EUR/day on the blind set.
- The checks compare GA4 and platform numbers, so a workspace needs both connected.
