"""
A/B Test Design Bot — Slack interface.

Slash commands:
  /abtest design   — interactive design form (opens modal)
  /abtest status   — list active experiments
  /abtest check    — check segment overlap for a date range
"""

import os
from datetime import date, timedelta
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from sample_size import build_mde_table, format_mde_table, calculate_sample_size_proportion
from experiment_registry import Experiment, ExperimentRegistry

app = App(token=os.environ["SLACK_BOT_TOKEN"])
registry = ExperimentRegistry(project=os.environ["GCP_PROJECT"])

SEGMENTS = ["all_users", "active_30d", "inactive_15_30d", "inactive_60_120d", "no_device", "no_simple_earn"]
METRICS   = ["purchase_rate", "revenue_per_user", "d7_retention", "activation_rate", "click_rate"]


# ── /abtest ────────────────────────────────────────────────────────────────────

@app.command("/abtest")
def handle_abtest(ack, body, client):
    ack()
    subcommand = (body.get("text") or "").strip().split()[0] if body.get("text") else ""

    if subcommand == "design":
        open_design_modal(client, body["trigger_id"])
    elif subcommand == "status":
        show_active_experiments(body["channel_id"], client)
    elif subcommand == "check":
        open_overlap_check_modal(client, body["trigger_id"])
    else:
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text=(
                "*A/B Test Bot* — available commands:\n"
                "• `/abtest design` — create a new experiment\n"
                "• `/abtest status` — list running experiments\n"
                "• `/abtest check` — check segment overlap"
            ),
        )


# ── Design modal ───────────────────────────────────────────────────────────────

def open_design_modal(client, trigger_id: str):
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "ab_design_submit",
            "title": {"type": "plain_text", "text": "New A/B Experiment"},
            "submit": {"type": "plain_text", "text": "Calculate & Register"},
            "blocks": [
                _input("exp_name",       "Experiment name",          "e.g. reactivation_email_v3"),
                _input("metric",         "Primary metric",           "e.g. purchase_rate",         hint="Conversion rate metric (0–1)"),
                _input("baseline",       "Baseline value",           "e.g. 0.05",                  hint="Current metric value as decimal"),
                _input("mde",            "MDE (relative, %)",        "e.g. 10",                    hint="Minimum lift you care about, in percent"),
                _input("daily_users",    "Daily eligible users",     "e.g. 5000"),
                _input("duration_days",  "Max test duration (days)", "e.g. 28"),
                _select("segment",       "Audience segment",         SEGMENTS),
                _input("guardrails",     "Guardrail metrics",        "e.g. unsubscribe_rate, d7_retention", hint="Comma-separated, optional"),
                _input("notes",          "Notes",                    "Context, links, hypothesis", hint="Optional"),
            ],
        },
    )


@app.view("ab_design_submit")
def handle_design_submit(ack, body, view, client):
    ack()
    v = view["state"]["values"]

    def val(key):
        block = v.get(key, {})
        action = next(iter(block.values()))
        if action["type"] == "static_select":
            return action["selected_option"]["value"]
        return (action.get("value") or "").strip()

    try:
        baseline    = float(val("baseline"))
        mde         = float(val("mde")) / 100
        daily_users = int(val("daily_users"))
        duration    = int(val("duration_days"))
        segment     = val("segment")
        user_id     = body["user"]["id"]

        # Sample size
        n = calculate_sample_size_proportion(baseline, mde)
        days_needed = n / (daily_users * 0.5)

        # MDE table
        table_rows = build_mde_table(baseline, daily_users)
        table_text = format_mde_table(table_rows)

        # Overlap check
        start = date.today()
        end   = start + timedelta(days=duration)
        overlaps = registry.check_overlap(segment, start, end)

        # Register
        exp = Experiment(
            name=val("exp_name"),
            owner=user_id,
            metric_primary=val("metric"),
            segment=segment,
            variant_count=2,
            split=0.5,
            start_date=start,
            end_date=end,
            mde_relative=mde,
            baseline=baseline,
            daily_users=daily_users,
            metrics_guardrail=[m.strip() for m in val("guardrails").split(",") if m.strip()],
            notes=val("notes"),
        )
        exp_id = registry.register(exp)

        # Build response
        overlap_text = ""
        if overlaps:
            names = ", ".join(o["name"] for o in overlaps)
            overlap_text = f"\n⚠️ *Segment overlap* with active experiments: {names}\nConsider staggering or using a different segment."

        msg = (
            f"*Experiment registered:* `{exp_id}` — {val('exp_name')}\n\n"
            f"*Segment:* {segment}   *Baseline:* {baseline:.1%}   *MDE:* {mde:.0%}\n"
            f"*Required n/variant:* {n:,}   *Days needed:* {round(days_needed)} / {duration} available\n"
            f"{overlap_text}\n"
            f"```\n{table_text}\n```"
        )
        client.chat_postMessage(channel=f"@{user_id}", text=msg)

    except Exception as e:
        client.chat_postMessage(
            channel=f"@{body['user']['id']}",
            text=f"❌ Error processing experiment design: {e}",
        )


# ── Active experiments ─────────────────────────────────────────────────────────

def show_active_experiments(channel: str, client):
    experiments = registry.get_active()
    if not experiments:
        client.chat_postMessage(channel=channel, text="No active experiments right now.")
        return

    lines = ["*Active experiments:*\n"]
    for e in experiments:
        lines.append(
            f"• `{e['experiment_id']}` *{e['name']}* — {e['segment']} | "
            f"{e['start_date']} → {e['end_date']} | owner: <@{e['owner']}>"
        )
    client.chat_postMessage(channel=channel, text="\n".join(lines))


# ── Overlap check modal ────────────────────────────────────────────────────────

def open_overlap_check_modal(client, trigger_id: str):
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "overlap_check_submit",
            "title": {"type": "plain_text", "text": "Check Segment Overlap"},
            "submit": {"type": "plain_text", "text": "Check"},
            "blocks": [
                _select("oc_segment", "Segment",    SEGMENTS),
                _input("oc_start",   "Start date", "YYYY-MM-DD"),
                _input("oc_end",     "End date",   "YYYY-MM-DD"),
            ],
        },
    )


@app.view("overlap_check_submit")
def handle_overlap_check(ack, body, view, client):
    ack()
    v = view["state"]["values"]

    def val(key):
        block = v.get(key, {})
        action = next(iter(block.values()))
        if action["type"] == "static_select":
            return action["selected_option"]["value"]
        return (action.get("value") or "").strip()

    segment = val("oc_segment")
    start   = date.fromisoformat(val("oc_start"))
    end     = date.fromisoformat(val("oc_end"))

    overlaps = registry.check_overlap(segment, start, end)
    user_id  = body["user"]["id"]

    if not overlaps:
        msg = f"✅ No overlapping experiments for segment *{segment}* between {start} and {end}."
    else:
        lines = [f"⚠️ Experiments overlapping with *{segment}* ({start} → {end}):\n"]
        for o in overlaps:
            lines.append(f"• `{o['experiment_id']}` {o['name']} — {o['start_date']} → {o['end_date']}")
        msg = "\n".join(lines)

    client.chat_postMessage(channel=f"@{user_id}", text=msg)


# ── Block kit helpers ──────────────────────────────────────────────────────────

def _input(block_id: str, label: str, placeholder: str, hint: str = "") -> dict:
    block = {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "plain_text_input",
            "action_id": block_id,
            "placeholder": {"type": "plain_text", "text": placeholder},
        },
        "optional": hint != "" and label.lower().endswith(("notes", "guardrail")),
    }
    if hint:
        block["hint"] = {"type": "plain_text", "text": hint}
    return block


def _select(block_id: str, label: str, options: list[str]) -> dict:
    return {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "static_select",
            "action_id": block_id,
            "options": [
                {"text": {"type": "plain_text", "text": o}, "value": o}
                for o in options
            ],
        },
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
