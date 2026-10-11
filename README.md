# A/B Test Design Bot

Slack bot for experiment design automation. Built at GoMining to standardise A/B test setup across CRM, product, and marketing teams.

## Problem

Before this tool, experiment parameters were calculated ad-hoc — sample sizes guessed, MDE not defined upfront, no check for audience overlap between concurrent tests. This led to underpowered tests and conflicting experiments running on the same segment simultaneously.

## What it does

**`/abtest design`** — opens a modal where you fill in:
- Primary metric + baseline value
- MDE (minimum lift you care about, in %)
- Daily eligible users and max duration

The bot returns:
- Required sample size per variant
- Full MDE table (how many days needed for each MDE threshold)
- Overlap check against active experiments in the same segment
- Registers the experiment in BigQuery with a unique ID

**`/abtest status`** — lists all currently running and planned experiments with owner and date range.

**`/abtest check`** — standalone overlap check: pick a segment and date range, returns any conflicting experiments.

## Architecture

```
Slack (Socket Mode)
      │
      ▼
  bot.py  (slack-bolt)
  ├── sample_size.py          ← power analysis, MDE table
  └── experiment_registry.py  ← BigQuery-backed registry
                                  analytics.ab_experiments.registry
```

`sample_size.py` has no external dependencies — uses a normal approximation (Abramowitz & Stegun) instead of scipy so it can run in lightweight Lambda / Cloud Function environments.

## Sample size logic

For proportion metrics (conversion rate):
- Cohen's h effect size between baseline and baseline × (1 + MDE)
- Two-sided z-test at α = 0.05, power = 0.80 by default
- Returns n per variant; multiply by variant count for total

## MDE table example

```
  MDE |  n/variant |   Days |  Weeks
------+------------+--------+-------
  3%  |     22 101 |     45 |    6.4
  5%  |      8 012 |     17 |    2.4
  7%  |      4 120 |      9 |    1.3
 10%  |      2 038 |      5 |    0.7
 15%  |        916 |      2 |    0.3
```

## Overlap detection

Experiments are stored in BigQuery with `segment`, `start_date`, `end_date`, `status`. Before registering a new experiment the bot queries for any active experiment with the same segment that overlaps the proposed time window.

This prevents the most common source of SRM and inflated effects: two tests running on the same audience simultaneously.

## Setup

```bash
pip install -r requirements.txt

export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export GCP_PROJECT=your-project-id

python bot.py
```

Slack app requires scopes: `commands`, `chat:write`, `chat:write.public`.
BigQuery table schema: `experiment_id`, `name`, `owner`, `metric_primary`, `segment`, `variant_count`, `split`, `start_date`, `end_date`, `mde_relative`, `baseline`, `daily_users`, `status`, `metrics_guardrail`, `notes`, `created_at`.
