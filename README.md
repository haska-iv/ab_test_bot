# A/B Test Design Bot

Slack bot that designs A/B experiments through a conversational interface powered by Claude.
Built at GoMining to standardise experiment setup across CRM and product teams.

## Problem

Analysts were calculating sample sizes ad-hoc, defining MDE after seeing results, and running experiments on the same audience simultaneously. This produced unreliable results and wasted traffic.

## What it does

Mention the bot in any Slack channel or thread. It asks for your experiment parameters, fetches real baseline data from the database, runs power analysis, and registers the design.

```
@ab-bot  I want to test a new onboarding email on users inactive for 15–30 days

→ ⏳ Иду в базу, считаю...
→ Segment: 4 200 users  |  Baseline purchase_rate: 4.3%
→ MDE table:
     uplift  | n/variant | weeks feasible
     0.5x (+0.2pp) |  18 400  |  18    ✗
     1.0x (+0.4pp) |   4 700  |   5    ✓
     1.5x (+0.6pp) |   2 100  |   3    ✓
→ Verdict: feasible at 1x uplift (5 weeks).  Save to registry? [yes / adjust]
```

## Architecture

```
Slack (Socket Mode)
      │  app_mention / thread message
      ▼
  bot.py
      │  one ABTestAgent per thread
      ▼
  agent.py  — Claude tool-use loop (up to 8 iterations)
  ├── db.py          ← PostgreSQL: metrics catalog, segment queries, registry
  └── sample_size.py ← power analysis (pure Python, no scipy)
```

## Agent tools

| Tool | What it does |
|---|---|
| `get_metrics_catalog` | Lists valid metrics, types, and typical baselines |
| `query_segment` | Counts users matching a SQL WHERE clause |
| `get_segment_baseline` | Fetches actual baseline from DB (falls back to catalog midpoint) |
| `run_power_analysis` | Returns MDE table + verdict (feasible / borderline / underpowered) |
| `save_experiment` | Writes the completed design to the registry |

The agent never uses a user-supplied baseline — it always fetches real data.

## Setup

```bash
pip install -r requirements.txt

# Init local DB
psql -c "CREATE DATABASE ab_tests"
psql ab_tests < schema.sql

export DATABASE_URL=postgresql://localhost/ab_tests
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export SLACK_SIGNING_SECRET=...

python bot.py
```

Slack app requires OAuth scopes: `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`.

## Key design choices

**No hardcoded forms.** A Slack modal forces analysts to know the right parameters upfront. The conversational agent asks clarifying questions and can handle ambiguous descriptions ("inactive users" → SQL WHERE clause).

**No scipy.** Power analysis uses a normal approximation (Abramowitz & Stegun) so the bot runs in minimal environments without a full scientific Python stack.

**Thread isolation.** Each Slack thread gets its own agent instance with independent history. Parallel conversations don't interfere.
