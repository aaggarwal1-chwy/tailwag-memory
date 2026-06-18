from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Protocol

from .models import EpisodeInput, EpisodeRecordResult, PersonInput, PlaceInput


class SlackConversationClient(Protocol):
    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict[str, Any]]:
        ...

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict[str, Any]]:
        ...

    def user_profile(self, user_id: str) -> "SlackUserProfile":
        ...


class EpisodeRecorder(Protocol):
    def record_episode(self, episode: EpisodeInput, *, extract_memory: bool = True) -> EpisodeRecordResult:
        ...


@dataclass(frozen=True)
class SlackUserProfile:
    display_name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class SlackPollResult:
    channel: str
    checked_threads: int
    ingested_threads: int
    latest_history_ts: str | None
    armed_without_backfill: bool = False
    memory_extraction_enabled: bool = True
    ingested_episode_ids: list[str] = field(default_factory=list)
    episode_records: list[EpisodeRecordResult] = field(default_factory=list)


class SlackWebApiClient:
    def __init__(self, token: str) -> None:
        try:
            from slack_sdk import WebClient
        except ImportError as exc:
            raise RuntimeError("Install the slack-sdk package to use Slack ingestion.") from exc

        self._client = WebClient(token=token)
        self._user_cache: dict[str, SlackUserProfile] = {}

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

    def user_profile(self, user_id: str) -> SlackUserProfile:
        if user_id not in self._user_cache:
            response = self._client.users_info(user=user_id)
            user = response.get("user") or {}
            profile = user.get("profile") or {}
            self._user_cache[user_id] = SlackUserProfile(
                display_name=(
                    profile.get("display_name")
                    or profile.get("real_name")
                    or user.get("real_name")
                    or user.get("name")
                ),
                email=_normalize_email(profile.get("email")),
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
        episode_recorder: EpisodeRecorder,
        state_path: Path,
        *,
        retention_class: str = "standard",
        active_thread_hours: float = 24.0,
    ) -> None:
        self.client = client
        self.episode_recorder = episode_recorder
        self.state_path = state_path
        self.retention_class = retention_class
        self.active_thread_hours = active_thread_hours

    def poll_once(
        self,
        channel: str,
        *,
        backfill_hours: float | None = None,
        force_backfill: bool = False,
        history_limit: int = 200,
        reply_limit: int = 200,
        extract_memory: bool = True,
    ) -> SlackPollResult:
        if force_backfill and backfill_hours is None:
            raise ValueError("force_backfill requires backfill_hours.")

        poll_started_ts = _now_slack_ts()
        state = SlackPollState(self.state_path)
        oldest = state.latest_history_ts(channel)

        if force_backfill:
            oldest = _datetime_to_slack_ts(datetime.now(timezone.utc) - timedelta(hours=backfill_hours or 0))
        elif oldest is None and backfill_hours is None:
            now_ts = _now_slack_ts()
            state.set_latest_history_ts(channel, now_ts)
            state.save()
            return SlackPollResult(
                channel=channel,
                checked_threads=0,
                ingested_threads=0,
                latest_history_ts=now_ts,
                armed_without_backfill=True,
                memory_extraction_enabled=extract_memory,
            )

        if oldest is None and backfill_hours is not None:
            oldest = _datetime_to_slack_ts(datetime.now(timezone.utc) - timedelta(hours=backfill_hours))

        history = self.client.history(channel=channel, oldest=oldest, limit=history_limit)
        history_messages: dict[str, list[dict[str, Any]]] = {}
        threaded_history: set[str] = set()
        for message in history:
            if not _is_memory_message(message):
                continue

            thread_ts = _thread_ts(message)
            if thread_ts is None:
                continue

            history_messages.setdefault(thread_ts, []).append(message)
            if _has_thread_replies(message):
                threaded_history.add(thread_ts)

        active_threads = state.active_threads(channel)
        threads_to_check = set(active_threads) | set(history_messages)
        episode_records: list[EpisodeRecordResult] = []
        thread_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.active_thread_hours)

        for thread_ts in sorted(threads_to_check, key=float):
            should_fetch_replies = thread_ts in active_threads or thread_ts in threaded_history
            if should_fetch_replies:
                replies = self.client.replies(channel=channel, thread_ts=thread_ts, limit=reply_limit)
                messages = [message for message in replies if _is_memory_message(message)]
            else:
                messages = [message for message in history_messages.get(thread_ts, []) if _is_memory_message(message)]

            if not messages:
                active_threads.pop(thread_ts, None)
                continue

            latest_thread_ts = _max_ts(messages)
            prior_thread_ts = active_threads.get(thread_ts, {}).get("latest_ts")
            if force_backfill or prior_thread_ts is None or _ts_greater(latest_thread_ts, prior_thread_ts):
                episode = build_episode_from_slack_thread(
                    channel=channel,
                    messages=messages,
                    client=self.client,
                    retention_class=self.retention_class,
                )
                episode_records.append(
                    self.episode_recorder.record_episode(
                        episode,
                        extract_memory=extract_memory,
                    )
                )

            latest_thread_time = _slack_ts_to_datetime(latest_thread_ts)
            if latest_thread_time >= thread_cutoff:
                active_threads[thread_ts] = {"latest_ts": latest_thread_ts}
            else:
                active_threads.pop(thread_ts, None)

        latest_history_ts = _max_ts(history) if history else poll_started_ts
        if latest_history_ts is not None:
            state.set_latest_history_ts(channel, latest_history_ts)
        state.save()

        return SlackPollResult(
            channel=channel,
            checked_threads=len(threads_to_check),
            ingested_threads=len(episode_records),
            latest_history_ts=latest_history_ts,
            memory_extraction_enabled=extract_memory,
            ingested_episode_ids=[record.episode_id for record in episode_records],
            episode_records=episode_records,
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
    user_profiles: dict[str, SlackUserProfile] = {}
    participants: list[PersonInput] = []
    seen_users: set[str] = set()
    transcript_lines: list[str] = []

    for message in ordered:
        user_id = str(message["user"])
        if user_id not in user_profiles:
            user_profiles[user_id] = client.user_profile(user_id)
        user_profile = user_profiles[user_id]
        display_name = user_profile.display_name or f"slack:{user_id}"

        if user_id not in seen_users:
            participants.append(
                PersonInput(
                    id=f"slack:{user_id}",
                    display_name=display_name,
                    email=_normalize_email(user_profile.email),
                    role="speaker",
                    source="slack",
                )
            )
            seen_users.add(user_id)

        message_time = _slack_ts_to_datetime(str(message["ts"])).isoformat()
        text = _format_slack_text(str(message.get("text") or ""), client=client, user_profiles=user_profiles)
        transcript_lines.append(f"[{message_time}] {display_name}: {text}")

    root_user_id = str(ordered[0]["user"])
    root_profile = user_profiles.get(root_user_id) or client.user_profile(root_user_id)
    user_profiles[root_user_id] = root_profile
    root_display_name = root_profile.display_name or f"slack:{root_user_id}"
    summary = _summarize(ordered[0], speaker_name=root_display_name, client=client, user_profiles=user_profiles)
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


def _has_thread_replies(message: dict[str, Any]) -> bool:
    return int(message.get("reply_count") or 0) > 0


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _format_slack_text(
    text: str,
    *,
    client: SlackConversationClient,
    user_profiles: dict[str, SlackUserProfile],
) -> str:
    return _clean_text(_replace_user_mentions(text, client=client, user_profiles=user_profiles))


def _replace_user_mentions(
    text: str,
    *,
    client: SlackConversationClient,
    user_profiles: dict[str, SlackUserProfile],
) -> str:
    def replace(match: re.Match[str]) -> str:
        user_id = match.group("user_id")
        label = match.group("label")
        if user_id not in user_profiles:
            user_profiles[user_id] = client.user_profile(user_id)
        display_name = user_profiles[user_id].display_name or label or f"slack:{user_id}"
        return f"@{display_name}"

    return re.sub(r"<@(?P<user_id>[A-Z0-9]+)(?:\|(?P<label>[^>]+))?>", replace, text)


def _normalize_email(email: Any) -> str | None:
    if not isinstance(email, str):
        return None
    normalized = email.strip().lower()
    return normalized or None


def _summarize(
    message: dict[str, Any],
    *,
    speaker_name: str,
    client: SlackConversationClient,
    user_profiles: dict[str, SlackUserProfile],
) -> str:
    text = _format_slack_text(
        str(message.get("text") or "Slack conversation"),
        client=client,
        user_profiles=user_profiles,
    )
    text = f"{speaker_name}: {text}"
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
