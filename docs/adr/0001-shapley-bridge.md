# 0001: Explain a KPI move with an exact Shapley decomposition

## Context

CPA is spend over conversions, summed across channels. When it moves, the drivers (each channel's
CPM, CTR and CVR, and the spend mix between channels) interact, so changing them one at a time
gives an answer that depends on the order. Marketers need parts that add up to the move they see.

## Decision

Write the KPI as a function of the drivers and compute exact Shapley values over them (`msd.analysis
.shapley`, at most 18 players). Shares add up to the change to floating-point precision; the evals
record the largest gap (below 1e-14). A driver is a cause only when it is material (share of the
change, effect on the KPI) and outside its normal movement (z-score against weekly history blocks,
with a counting-noise floor). Related drivers fold into one cause (site-wide conversion rate, mix
within a channel, mix caused by invalid traffic).

## Consequences

- The bridge chart is the decomposition itself, so the chart and the text cannot disagree.
- Cost grows as 2^n; channels × drivers stays far below the 18-player cap for an agency client.
- Thresholds live in `config/analysis.yaml` and are judged by the held-out set, not tuned to it.
