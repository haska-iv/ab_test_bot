"""
Experiment registry backed by BigQuery.
Stores experiment metadata, checks for audience overlaps.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from google.cloud import bigquery


REGISTRY_TABLE = "analytics.ab_experiments.registry"


@dataclass
class Experiment:
    name: str
    owner: str
    metric_primary: str
    segment: str           # e.g. "all_users", "active_30d", "no_device"
    variant_count: int
    split: float           # fraction per variant
    start_date: date
    end_date: date
    mde_relative: float
    baseline: float
    daily_users: int
    status: str = "planned"  # planned | running | paused | completed
    metrics_guardrail: list[str] = field(default_factory=list)
    notes: str = ""
    experiment_id: Optional[str] = None

    def to_bq_row(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "owner": self.owner,
            "metric_primary": self.metric_primary,
            "segment": self.segment,
            "variant_count": self.variant_count,
            "split": self.split,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "mde_relative": self.mde_relative,
            "baseline": self.baseline,
            "daily_users": self.daily_users,
            "status": self.status,
            "metrics_guardrail": ",".join(self.metrics_guardrail),
            "notes": self.notes,
            "created_at": datetime.utcnow().isoformat(),
        }


class ExperimentRegistry:
    def __init__(self, project: str):
        self.client = bigquery.Client(project=project)

    def register(self, exp: Experiment) -> str:
        """Insert experiment into registry, return experiment_id."""
        import uuid
        exp.experiment_id = str(uuid.uuid4())[:8].upper()
        errors = self.client.insert_rows_json(REGISTRY_TABLE, [exp.to_bq_row()])
        if errors:
            raise RuntimeError(f"BQ insert error: {errors}")
        return exp.experiment_id

    def get_active(self, as_of: Optional[date] = None) -> list[dict]:
        """Return all experiments active on a given date."""
        as_of = as_of or date.today()
        query = f"""
            SELECT *
            FROM `{REGISTRY_TABLE}`
            WHERE status IN ('planned', 'running')
              AND start_date <= '{as_of}'
              AND end_date   >= '{as_of}'
        """
        return [dict(row) for row in self.client.query(query).result()]

    def check_overlap(self, segment: str, start: date, end: date) -> list[dict]:
        """
        Return active experiments that overlap in segment and time window.
        Same segment = risk of audience overlap affecting results.
        """
        query = f"""
            SELECT experiment_id, name, owner, segment, start_date, end_date
            FROM `{REGISTRY_TABLE}`
            WHERE status IN ('planned', 'running')
              AND segment = '{segment}'
              AND start_date <= '{end}'
              AND end_date   >= '{start}'
        """
        return [dict(row) for row in self.client.query(query).result()]

    def update_status(self, experiment_id: str, status: str) -> None:
        query = f"""
            UPDATE `{REGISTRY_TABLE}`
            SET status = '{status}', updated_at = CURRENT_TIMESTAMP()
            WHERE experiment_id = '{experiment_id}'
        """
        self.client.query(query).result()
