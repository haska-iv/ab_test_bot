-- Minimal schema for local development

CREATE TABLE IF NOT EXISTS users (
    id          BIGINT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ,
    country     TEXT,
    -- add domain-specific columns here
    attributes  JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metrics_catalog (
    metric_id             TEXT PRIMARY KEY,
    display_name          TEXT NOT NULL,
    metric_type           TEXT NOT NULL CHECK (metric_type IN ('binary', 'continuous')),
    stat_test             TEXT NOT NULL CHECK (stat_test IN ('z_test', 'mann_whitney')),
    typical_baseline_low  NUMERIC NOT NULL,
    typical_baseline_high NUMERIC NOT NULL,
    baseline_sql          TEXT,   -- parameterised with {where_clause}; NULL = use catalog midpoint
    description           TEXT
);

CREATE TABLE IF NOT EXISTS experiment_registry (
    experiment_id          TEXT PRIMARY KEY,
    experiment_name        TEXT NOT NULL,
    owner                  TEXT,
    hypothesis             TEXT,
    primary_metric         TEXT REFERENCES metrics_catalog(metric_id),
    segment_description    TEXT,
    segment_sql            TEXT,
    segment_size           INTEGER,
    baseline_value         NUMERIC,
    expected_uplift        NUMERIC,
    n_variants             INTEGER,
    stat_test              TEXT,
    required_n_per_variant INTEGER,
    estimated_weeks        INTEGER,
    proposed_duration_weeks INTEGER,
    verdict                TEXT CHECK (verdict IN ('feasible', 'borderline', 'underpowered')),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sample metrics
INSERT INTO metrics_catalog VALUES
  ('purchase_rate', 'Purchase conversion', 'binary', 'z_test', 0.03, 0.08,
   'SELECT AVG((purchased)::int) AS baseline FROM events WHERE user_id IN (SELECT id FROM users WHERE {where_clause})',
   'Share of users who made at least one purchase'),
  ('click_rate', 'Email CTR', 'binary', 'z_test', 0.05, 0.15, NULL,
   'Click-through rate on email campaigns'),
  ('revenue_per_user', 'Revenue per user', 'continuous', 'mann_whitney', 5.0, 20.0, NULL,
   'Total revenue per user over the experiment window')
ON CONFLICT DO NOTHING;
