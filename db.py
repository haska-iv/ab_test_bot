"""
PostgreSQL helpers — metrics catalog, segment queries, experiment registry.
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DSN = os.environ.get("DATABASE_URL", "postgresql://localhost/ab_tests")


@contextmanager
def conn():
    c = psycopg2.connect(DSN)
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ── Metrics catalog ────────────────────────────────────────────────────────────

def get_metrics_catalog() -> list[dict]:
    """Return all available metrics with their types and typical baseline ranges."""
    with conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT metric_id, display_name, metric_type,
                       typical_baseline_low, typical_baseline_high,
                       stat_test, description
                FROM metrics_catalog
                ORDER BY metric_id
            """)
            return [dict(r) for r in cur.fetchall()]


# ── Segments ───────────────────────────────────────────────────────────────────

def query_segment(where_clause: str) -> dict:
    """
    Count users matching a WHERE clause against the users table.
    Returns segment size and weekly_rate (new users/week over last 4 weeks).
    """
    with conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    COUNT(*)                                        AS size,
                    COUNT(*) FILTER (
                        WHERE created_at >= NOW() - INTERVAL '28 days'
                    ) / 4.0                                        AS weekly_rate
                FROM users
                WHERE {where_clause}
            """)
            row = dict(cur.fetchone())
            return {"size": int(row["size"]), "weekly_rate": round(float(row["weekly_rate"] or 0))}


def get_segment_baseline(metric_id: str, where_clause: str, lookback_days: int = 30) -> dict:
    """
    Compute actual baseline for a metric over the given segment.
    Falls back to catalog midpoint if no data.
    """
    with conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Catalog lookup
            cur.execute(
                "SELECT metric_type, typical_baseline_low, typical_baseline_high,"
                "       baseline_sql FROM metrics_catalog WHERE metric_id = %s",
                (metric_id,),
            )
            catalog = cur.fetchone()
            if not catalog:
                return {"error": f"Unknown metric: {metric_id}"}

            # Try baseline_sql if defined
            if catalog["baseline_sql"]:
                try:
                    sql = catalog["baseline_sql"].replace("{where_clause}", where_clause)
                    cur.execute(sql)
                    row = cur.fetchone()
                    if row and row.get("baseline") is not None:
                        return {"baseline": float(row["baseline"]), "source": "sql"}
                except Exception:
                    pass  # fall through to catalog midpoint

            # Fallback: catalog midpoint
            midpoint = (catalog["typical_baseline_low"] + catalog["typical_baseline_high"]) / 2
            return {"baseline": midpoint, "source": "catalog_midpoint"}


# ── Registry ───────────────────────────────────────────────────────────────────

def save_experiment(record: dict) -> str:
    """Insert a completed experiment design into the registry. Returns experiment_id."""
    import uuid
    record["experiment_id"] = str(uuid.uuid4())[:8].upper()

    cols = ", ".join(record.keys())
    vals = ", ".join(f"%({k})s" for k in record.keys())

    with conn() as c:
        with c.cursor() as cur:
            cur.execute(f"INSERT INTO experiment_registry ({cols}) VALUES ({vals})", record)

    return record["experiment_id"]
