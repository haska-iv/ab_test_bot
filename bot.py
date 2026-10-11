"""
Slack bot entry point.
One agent instance per Slack thread — threads are isolated conversations.
"""

import logging
import os
import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from agent import ABTestAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"], signing_secret=os.environ["SLACK_SIGNING_SECRET"])

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_agents: dict[str, ABTestAgent] = {}  # thread_ts → agent


def _get_agent(thread_ts: str) -> ABTestAgent:
    if thread_ts not in _agents:
        _agents[thread_ts] = ABTestAgent()
    return _agents[thread_ts]


def _reply(client, channel: str, thread_ts: str, text: str) -> None:
    client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text, mrkdwn=True)


@app.event("app_mention")
def on_mention(event: dict, client) -> None:
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    user_text = _MENTION_RE.sub("", event.get("text", "")).strip() or "Хочу спроектировать AB-тест."

    agent = _get_agent(thread_ts)

    def working():
        _reply(client, channel, thread_ts, "⏳ Иду в базу, считаю...")

    try:
        answer = agent.chat(user_text, on_first_tool=working)
    except Exception:
        log.exception("agent error thread=%s", thread_ts)
        answer = "⚠️ Что-то пошло не так — смотри логи."

    _reply(client, channel, thread_ts, answer)


@app.event("message")
def on_thread_message(event: dict, client) -> None:
    # Only respond to thread replies in active agent threads
    if event.get("bot_id") or not event.get("thread_ts"):
        return
    thread_ts = event["thread_ts"]
    if thread_ts not in _agents or _MENTION_RE.search(event.get("text", "")):
        return

    channel = event["channel"]
    user_text = event.get("text", "").strip()
    if not user_text:
        return

    agent = _get_agent(thread_ts)

    def working():
        _reply(client, channel, thread_ts, "⏳ Считаю...")

    try:
        answer = agent.chat(user_text, on_first_tool=working)
    except Exception:
        log.exception("agent error thread=%s", thread_ts)
        answer = "⚠️ Что-то пошло не так — смотри логи."

    _reply(client, channel, thread_ts, answer)


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
