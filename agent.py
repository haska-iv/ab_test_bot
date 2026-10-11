"""
Claude-based agent for A/B test design.
Runs a tool-use loop: gathers segment info → computes baseline → power analysis → saves result.
"""

import json
import logging
import os
import anthropic

from db import get_metrics_catalog, query_segment, get_segment_baseline, save_experiment
from sample_size import run_power_analysis

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
MAX_ITERATIONS = 8

SYSTEM_PROMPT = """You are an A/B test design assistant for a product analytics team.
Your job: help the user design a statistically sound experiment.

Workflow (always follow this order):
1. Call get_metrics_catalog to know valid metric IDs.
2. Ask the user for: experiment name, hypothesis, audience description, primary metric, expected uplift, number of variants, proposed duration.
3. Call query_segment with a SQL WHERE clause matching the described audience.
4. Call get_segment_baseline for the chosen metric over that segment.
5. Call run_power_analysis with the collected parameters.
6. Present results clearly: segment size, baseline, MDE table, verdict (feasible / borderline / underpowered).
7. Ask for confirmation, then call save_experiment to register the design.

Rules:
- Never use a user-supplied baseline — always fetch it from get_segment_baseline.
- Always present the MDE table before asking for confirmation.
- Be concise. Use Slack markdown (*bold*, `code`).
- Respond in the same language the user writes in."""

TOOLS = [
    {
        "name": "get_metrics_catalog",
        "description": "Return all available A/B test metrics with their types and typical baseline ranges.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_segment",
        "description": (
            "Count users matching a SQL WHERE clause against the `users` table. "
            "Returns segment size and estimated weekly_rate for dynamic segments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "where_clause": {
                    "type": "string",
                    "description": "SQL WHERE condition (without the WHERE keyword)",
                },
            },
            "required": ["where_clause"],
        },
    },
    {
        "name": "get_segment_baseline",
        "description": (
            "Compute the actual baseline value for a metric over a segment. "
            "Always call this — never trust a user-supplied baseline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string", "description": "Metric ID from the catalog"},
                "where_clause": {"type": "string", "description": "Same WHERE clause used in query_segment"},
                "lookback_days": {
                    "type": "integer",
                    "description": "Lookback window in days for conversion-rate metrics (default 30)",
                },
            },
            "required": ["metric_id", "where_clause"],
        },
    },
    {
        "name": "run_power_analysis",
        "description": (
            "Run statistical power analysis. Returns an MDE table across 5 uplift levels "
            "and a verdict (feasible / borderline / underpowered)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "baseline": {"type": "number", "description": "Baseline from get_segment_baseline"},
                "expected_uplift": {"type": "number", "description": "Expected absolute uplift"},
                "segment_size": {"type": "integer"},
                "n_variants": {"type": "integer", "description": "Total groups including control"},
                "stat_test": {
                    "type": "string",
                    "enum": ["z_test", "mann_whitney"],
                    "description": "z_test for binary metrics, mann_whitney for continuous",
                },
                "weekly_rate": {
                    "type": "integer",
                    "description": "New users/week for dynamic segments (from query_segment)",
                },
            },
            "required": ["metric_id", "baseline", "expected_uplift", "segment_size", "n_variants", "stat_test"],
        },
    },
    {
        "name": "save_experiment",
        "description": "Save the completed experiment design to the registry. Call last, after user confirms.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record": {
                    "type": "object",
                    "description": (
                        "Design record. Required keys: experiment_name, owner, hypothesis, "
                        "primary_metric, segment_description, segment_sql, segment_size, "
                        "baseline_value, expected_uplift, n_variants, stat_test, "
                        "required_n_per_variant, estimated_weeks, proposed_duration_weeks, verdict."
                    ),
                },
            },
            "required": ["record"],
        },
    },
]


def _run_tool(name: str, inputs: dict) -> dict:
    try:
        if name == "get_metrics_catalog":
            return {"metrics": get_metrics_catalog()}
        if name == "query_segment":
            return query_segment(inputs["where_clause"])
        if name == "get_segment_baseline":
            return get_segment_baseline(
                inputs["metric_id"],
                inputs["where_clause"],
                inputs.get("lookback_days", 30),
            )
        if name == "run_power_analysis":
            return run_power_analysis(
                metric_id=inputs["metric_id"],
                baseline=inputs["baseline"],
                expected_uplift=inputs["expected_uplift"],
                segment_size=inputs["segment_size"],
                n_variants=inputs["n_variants"],
                stat_test=inputs["stat_test"],
                weekly_rate=inputs.get("weekly_rate"),
            )
        if name == "save_experiment":
            exp_id = save_experiment(inputs["record"])
            return {"experiment_id": exp_id, "status": "saved"}
        return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        log.exception("tool error: %s", name)
        return {"error": str(e)}


class ABTestAgent:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._history: list[dict] = []

    def chat(self, user_message: str, on_first_tool: callable = None) -> str:
        """
        Add user message, run tool-use loop, return final text.
        on_first_tool: called once before the first tool execution (e.g. to post a "working..." message).
        """
        self._history.append({"role": "user", "content": user_message})

        notified = False

        for _ in range(MAX_ITERATIONS):
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self._history,
            )

            text_parts = [b.text for b in response.content if b.type == "text"]
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason == "end_turn":
                final = "\n".join(text_parts)
                self._history.append({"role": "assistant", "content": final})
                return final

            if response.stop_reason == "tool_use":
                if not notified and on_first_tool:
                    notified = True
                    on_first_tool()

                self._history.append({"role": "assistant", "content": response.content})

                results = []
                for block in tool_blocks:
                    log.info("tool: %s %s", block.name, json.dumps(block.input)[:200])
                    result = _run_tool(block.name, block.input)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

                self._history.append({"role": "user", "content": results})

        return "⚠️ Превышен лимит итераций."
