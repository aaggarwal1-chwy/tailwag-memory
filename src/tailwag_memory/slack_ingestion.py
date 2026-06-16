from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Protocol

from .ingestion import EpisodeIngestionService
from .models import EpisodeInput, PersonInput, PlaceInput


class SlackConversationClient(Protocol):
    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict[str, Any]]:
        ...

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict[str, Any]]:
        ...

    def user_display_name(self, user_id: str) -> str | None:
        ...


@dataclass(frozen=True)
class SlackPollResult:
    channel: str
    checked_threads: int
    ingested_threads: int
    latest_history_ts: str | None
    armed_without_backfill: bool = False


class SlackWebApiClient:
    def __init__(self, token: str) -> None:
        try:
            from slack_sdk import WebClient
        except ImportError as exc:
            raise RuntimeError("Install the slack-sdk package to use Slack ingestion.") from exc

        self._client = WebClient(token=token)
        self._user_cache: dict[str, str | None] = {}

    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(messages) < limit:
            page_size = min(200, limit - len(messages))
            params: dict[str, Any] = {
                "channel": channel,
                "limit": page_size,
                "inclusive": False,
            }
            if oldest is not None:
                params["oldest"] = oldest
            if cursor is not None:
                params["cursor"] = cursor

            response = self._client.conversations_history(**params)
            messages.extend(response.get("messages", []))
            cursor = (response.get("response_metadata") or {}).get("next_cursor")
            if not response.get("has_more") or not cursor:
                break
        return messages

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(messages) < limit:
            page_size = min(200, limit - len(messages))
            params: dict[str, Any] = {
                "channel": channel,
                "ts": thread_ts,
                "limit": page_size,
            }
            if cursor is not None:
                params["cursor"] = cursor

            response = self._client.conversations_replies(**params)
            messages.extend(response.get("messages", []))
            cursor = (response.get("response_metadata") or {}).get("next_cursor")
            if not response.get("has_more") or not cursor:
                break
        return messages

    def user_display_name(self, user_id: str) -> str | None:
        if user_id not in self._user_cache:
            response = self._client.users_info(user=user_id)
            user = response.get("user") or {}
            profile = user.get("profile") or {}
            self._user_cache[user_id] = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("real_name")
                or user.get("name")
            )
        return self._user_cache[user_id]


class SlackPollState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def latest_history_ts(self, channel: str) -> str | None:
        return self._channel(channel).get("latest_history_ts")

    def set_latest_history_ts(self, channel: str, ts: str) -> None:
        self._channel(channel)["latest_history_ts"] = ts

    def active_threads(self, channel: str) -> dict[str, dict[str, str]]:
        return self._channel(channel).setdefault("active_threads", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    def _channel(self, channel: str) -> dict[str, Any]:
        channels = self.data.setdefault("channels", {})
        return channels.setdefault(channel, {})

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"channels": {}}
        return json.loads(self.path.read_text())


class SlackMemoryPoller:
    def __init__(
        self,
        client: SlackConversationClient,
        episode_service: EpisodeIngestionService,
        state_path: Path,
        *,
        retention_class: str = "standard",
        active_thread_hours: float = 24.0,
    ) -> None:
        self.client = client
        self.episode_service = episode_service
        self.state_path = state_path
        self.retention_class = retention_class
        self.active_thread_hours = active_thread_hours

    def poll_once(
        self,
        channel: str,
        *,
        backfill_hours: float | None = None,
        history_limit: int = 200,
        reply_limit: int = 200,
    ) -> SlackPollResult:
        state = SlackPollState(self.state_path)
        oldest = state.latest_history_ts(channel)

        if oldest is None and backfill_hours is None:
            now_ts = _now_slack_ts()
            state.set_latest_history_ts(channel, now_ts)
            state.save()
            return SlackPollResult(
                channel=channel,
                checked_threads=0,
                ingested_threads=0,
                latest_history_ts=now_ts,
                armed_without_backfill=True,
            )

        if oldest is None and backfill_hours is not None:
            oldest = _datetime_to_slack_ts(datetime.now(timezone.utc) - timedelta(hours=backfill_hours))

        history = self.client.history(channel=channel, oldest=oldest, limit=history_limit)
        history_threads = {_thread_ts(message) for message in history if _is_memory_message(message)}
        history_threads.discard(None)

        active_threads = state.active_threads(channel)
        threads_to_check = set(active_threads) | {str(thread_ts) for thread_ts in history_threads}
        ingested_threads = 0
        thread_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.active_thread_hours)

        for thread_ts in sorted(threads_to_check, key=float):
            replies = self.client.replies(channel=channel, thread_ts=thread_ts, limit=reply_limit)
            messages = [message for message in replies if _is_memory_message(message)]
            if not messages:
                active_threads.pop(thread_ts, None)
                continue

            latest_thread_ts = _max_ts(messages)
            prior_thread_ts = active_threads.get(thread_ts, {}).get("latest_ts")
            if prior_thread_ts is None or _ts_greater(latest_thread_ts, prior_thread_ts):
                episode = build_episode_from_slack_thread(
                    channel=channel,
                    messages=messages,
                    client=self.client,
                    retention_class=self.retention_class,
                )
                self.episode_service.ingest(episode)
                ingested_threads += 1

            latest_thread_time = _slack_ts_to_datetime(latest_thread_ts)
            if latest_thread_time >= thread_cutoff:
                active_threads[thread_ts] = {"latest_ts": latest_thread_ts}
            else:
                active_threads.pop(thread_ts, None)

        latest_history_ts = _max_ts(history) if history else oldest
        if latest_history_ts is not None:
            state.set_latest_history_ts(channel, latest_history_ts)
        state.save()

        return SlackPollResult(
            channel=channel,
            checked_threads=len(threads_to_check),
            ingested_threads=ingested_threads,
            latest_history_ts=latest_history_ts,
        )


def build_episode_from_slack_thread(
    *,
    channel: str,
    messages: list[dict[str, Any]],
    client: SlackConversationClient,
    retention_class: str = "standard",
) -> EpisodeInput:
    ordered = sorted([message for message in messages if _is_memory_message(message)], key=lambda item: float(item["ts"]))
    if not ordered:
        raise ValueError("Cannot build an episode from an empty Slack thread.")

    thread_ts = _thread_ts(ordered[0])
    user_names: dict[str, str | None] = {}
    participants: list[PersonInput] = []
    seen_users: set[str] = set()
    transcript_lines: list[str] = []

    for message in ordered:
        user_id = str(message["user"])
        if user_id not in user_names:
            user_names[user_id] = client.user_display_name(user_id)
        display_name = user_names[user_id] or f"slack:{user_id}"

        if user_id not in seen_users:
            participants.append(
                PersonInput(
                    id=f"slack:{user_id}",
                    display_name=display_name,
                    role="speaker",
                    source="slack",
                )
            )
            seen_users.add(user_id)

        transcript_lines.append(f"{display_name}: {_clean_text(str(message.get('text') or ''))}")

    summary = _summarize(ordered[0])
    return EpisodeInput(
        id=f"slack:{channel}:{thread_ts}",
        episode_type="conversation",
        start_time=_slack_ts_to_datetime(str(ordered[0]["ts"])).isoformat(),
        end_time=_slack_ts_to_datetime(_max_ts(ordered)).isoformat(),
        summary=summary,
        transcript="\n".join(transcript_lines),
        retention_class=retention_class,
        place=PlaceInput(building_code="SLACK", room_id=channel),
        participants=participants,
    )


def _is_memory_message(message: dict[str, Any]) -> bool:
    subtype = message.get("subtype")
    if subtype in {"message_deleted", "channel_join", "channel_leave"}:
        return False
    return bool(message.get("user")) and bool(_clean_text(str(message.get("text") or ""))) and bool(message.get("ts"))


def _thread_ts(message: dict[str, Any]) -> str | None:
    ts = message.get("thread_ts") or message.get("ts")
    return str(ts) if ts is not None else None


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _summarize(message: dict[str, Any]) -> str:
    text = _clean_text(str(message.get("text") or "Slack conversation"))
    if len(text) <= 160:
        return text
    return text[:157].rstrip() + "..."


def _max_ts(messages: list[dict[str, Any]]) -> str:
    return max((str(message["ts"]) for message in messages if message.get("ts") is not None), key=float)


def _ts_greater(left: str, right: str) -> bool:
    return float(left) > float(right)


def _slack_ts_to_datetime(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def _datetime_to_slack_ts(value: datetime) -> str:
    return f"{value.timestamp():.6f}"


def _now_slack_ts() -> str:
    return _datetime_to_slack_ts(datetime.now(timezone.utc))
