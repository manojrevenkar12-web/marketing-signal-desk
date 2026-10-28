# Writing a held-out scenario set

You are writing test scenarios for a tool that explains why an online shop's advertising CPA or
ROAS moved. You have not seen the tool and should not look for it. Write what really happens to
ad accounts, decide what a careful performance-marketing analyst would conclude, and record that as
the expected answer. The set is run once; its first result is recorded and never rewritten.

## The advertiser

A fictional skincare shop advertises on four platforms and measures purchases in GA4. Its normal
day (Monday factor 1.0; Friday to Sunday spend a little less):

| Channel | Campaign | Budget EUR/day | CPM EUR | CTR | CVR (purchases per click) | Clicks/day | GA4 purchases/day | CPA EUR |
|---|---|---|---|---|---|---|---|---|
| google_ads | Search - Brand | 300 | 25.0 | 8.0% | 9.0% | 960 | 79.5 | 3.8 |
| google_ads | Search - Generic | 900 | 18.0 | 3.5% | 3.2% | 1,750 | 51.5 | 17.5 |
| google_ads | PMax - Shopping | 1200 | 9.0 | 1.4% | 2.6% | 1,867 | 44.7 | 26.9 |
| meta | Prospecting - Advantage+ | 1500 | 8.0 | 1.1% | 1.8% | 2,062 | 34.2 | 43.9 |
| meta | Retargeting - DPA | 500 | 14.0 | 1.6% | 4.5% | 571 | 23.7 | 21.1 |
| microsoft_ads | Search - Generic | 350 | 14.0 | 3.0% | 3.0% | 750 | 20.7 | 16.9 |
| tiktok | Spark Ads - Creators | 600 | 6.0 | 0.9% | 0.9% | 900 | 7.5 | 80.5 |

In total about 5,350 EUR a day and about 262 GA4 purchases: a CPA of about 20.5 EUR. The average
order is about 68 EUR (ROAS about 3.3x on GA4 revenue). GA4 records about 92% of real purchases.
The platforms claim more than GA4 sees, as they do in real life: Google about 5% more than the real
number, Meta 25%, TikTok 30%, Microsoft about the same. Every number wobbles from day to day by a
few percent, plus counting noise (a channel with 7 purchases a day is noisy).

Data covers 3 August to 27 September 2026. The question is asked about the last week,
**21 to 27 September**, compared with the four weeks before it (24 August to 20 September).

## What can happen (events)

Each scenario lists events. An event starts on a date (put it on 21 September or later to affect
the question's week; up to 27 September) and lasts until the end unless it has `end`.

| type | fields | what it is |
|---|---|---|
| `cpm_spike` | channel, optional campaign, pct | auction prices up by pct% (competitors, seasonality) |
| `ctr_drop` | channel, optional campaign, pct | click-through down pct% (worn-out creatives) |
| `cvr_drop` | optional channel, optional campaign, pct | real purchases per click down pct% (slow page, broken checkout, worse offer). No channel = every channel |
| `tracking_loss` | optional channel, pct | GA4 records pct% fewer purchases; real purchases unchanged (broken tag, consent banner). No channel = every channel |
| `invalid_clicks` | channel, campaign, clicks_per_day | bots click: extra clicks and their cost, no purchases |
| `budget_shift` | channel (from), to_channel, eur_per_day | that much daily budget moved from one channel to another, split evenly across each channel's campaigns |
| `budget_change` | channel, optional campaign, pct | budget scaled by pct% (positive = more) |
| `overreport` | channel, pct | the platform claims pct% more purchases than before; GA4 and reality unchanged (attribution setting) |
| `aov_drop` | optional channel, pct | order value down pct% (a promotion) |
| `missing_days` | channel, dates (no start needed) | the platform's API returned nothing for those days |

## What the tool should conclude (expect)

CPA is measured in GA4 unless the question says otherwise. List the expected **causes**, most
important first, using these types:

- `auction_pressure` (channel): CPM up on one channel
- `creative_fatigue` (channel, campaign if one campaign): CTR down
- `conversion_drop` (channel, campaign if one campaign): real CVR down on one channel
- `site_conversion_drop`: CVR down on three or more channels at once (no channel)
- `tracking_loss` (channel, or no channel when three or more channels lose tracking): GA4 records fewer purchases while the platform's own numbers hold
- `invalid_traffic` (channel, campaign): bot clicks
- `budget_mix_shift` (channel = where the budget went): money moved towards a channel with worse CPA
- `order_value_drop`: order value down (for ROAS questions)
- `platform_overreporting` (channel): only when the question asks for the platforms' own numbers

And the expected data **signals**, which must be raised whether or not the KPI moved:
`tracking_gap` (channel, or none for several at once), `invalid_traffic` (channel), `overreporting`
(channel), `missing_days` (channel).

**Materiality.** Expect a cause only if it moves the total CPA (or ROAS) by at least about 5% on its
own. Estimate with the table, weighting by purchases, not spend: with budgets fixed, a 30% CPM rise
on Meta costs Meta 30% of its purchases (Meta has about 22% of all purchases), so total CPA rises
by roughly 1 / (1 - 0.22 × 0.23) - 1, about 5.4%: borderline, so use a clearly bigger or smaller
size. A 20% CTR drop on TikTok (7 purchases a
day of 262) moves total CPA by well under 5%: expect **no** cause. Events that only change what is
measured (overreporting, missing days) or small ones still expect their **signal**. When you are
not sure an effect reaches 5%, make it clearly bigger or clearly smaller; do not write borderline
cases.

## Format

One YAML file per scenario, in the folder you were given:

```yaml
id: short-kebab-case-id          # unique, same as the file name
title: One line in plain words
seed: 1234                        # any integer; different per scenario
question: "Why did our CPA go up last week?"   # optional; say "ROAS" for ROAS questions, "in the platforms" for platform numbers
events:
  - {type: cpm_spike, channel: meta, start: 2026-09-21, pct: 35}
expect:
  metric: cpa                     # or roas
  causes: [{type: auction_pressure, channel: meta}]
  signals: [{kind: tracking_gap, channel: google_ads}]   # data signals use the key "kind"
note: why this case exists
```

## What makes a good set

About 24 scenarios:

- a third with one clear cause, spread over the types;
- a quarter with no material change (noise only, small events, measurement-only events): `causes: []`;
- a quarter with two events at once (two causes, or a cause plus a data signal);
- the rest the hard ones: a tracking problem that looks like a performance drop, bots that look
  like better creatives, a budget move that looks like worse performance, an effect hidden by
  another moving the other way (both causes expected when each is at least 5% on its own).

Use realistic sizes (CPM +20 to +60%, CTR -25 to -60%, bots 200 to 1,500 clicks a day on one
campaign). Vary channels and campaigns. Do not try to guess how the tool works.

## Changes to this guide

- v2 (after set blind-1 was written): signals are written with the key `kind`; `missing_days`
  needs no `start`; the materiality example is weighted by purchases (v1 weighted by spend and said
  about 10%, which is wrong). blind-1 was written from v1; the loader accepts its `type` key for
  signals and derives `start` from `dates`, so its content is used exactly as written.
