from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Protocol

from . import slack_episode_conversion as _conversion
from .models import EpisodeInput, EpisodeRecordResult
from .slack_episode_conversion import (
    PersonIdResolver,
    SlackProfileClient,
    build_episode_from_slack_thread,
)


class SlackConversationClient(SlackProfileClient, Protocol):
    """Describe the Slack conversation methods used by polling."""

    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict[str, Any]]:
        """Return channel history newer than the optional Slack timestamp."""
        ...

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict[str, Any]]:
        """Return replies for a Slack thread."""
        ...

class EpisodeRecorder(Protocol):
    """Describe the episode recording behavior needed by Slack polling."""

    def record_episode(
        self,
        episode: EpisodeInput,
        *,
        extract_memory: bool = True,
        enqueue_memory_extraction: bool = True,
    ) -> EpisodeRecordResult:
        """Record one episode and optionally extract memory."""
        ...


@dataclass(frozen=True)
class SlackUserProfile:
    """Hold Slack user display metadata."""

    display_name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class SlackPollResult:
    """Summarize one Slack polling pass."""

    channel: str
    checked_threads: int
    ingested_threads: int
    latest_history_ts: str | None
    armed_without_backfill: bool = False
    memory_extraction_enabled: bool = True
    ingested_episode_ids: list[str] = field(default_factory=list)
    episode_records: list[EpisodeRecordResult] = field(default_factory=list)


@dataclass
class SlackChannelState:
    """Hold one Slack channel's polling checkpoint."""

    latest_history_ts: str | None = None
    active_threads: dict[str, dict[str, str]] = field(default_factory=dict)
    version: object | None = None


class SlackPollStateConflict(RuntimeError):
    """Raised when a state save observes a stale channel version."""


class SlackPollStateStore(Protocol):
    """Describe storage for per-channel Slack polling state."""

    def load_channel(self, channel: str) -> SlackChannelState:
        """Return one channel's polling state and opaque store version."""
        ...

    def save_channel(self, channel: str, state: SlackChannelState, expected_version: object | None) -> None:
        """Save one channel if its current version still matches expected_version."""
        ...


class SlackWebApiClient:
    """Fetch Slack conversations through the Slack Web API."""

    def __init__(self, token: str, *, include_email: bool = False) -> None:
        """Create a Slack API client with optional email capture."""
        try:
            from slack_sdk import WebClient
        except ImportError as exc:
            raise RuntimeError("Install the slack-sdk package to use Slack ingestion.") from exc

        self._client = WebClient(token=token)
        self._user_cache: dict[str, SlackUserProfile] = {}
        self.include_email = include_email

    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict[str, Any]]:
        """Return paginated channel history from Slack."""
        params: dict[str, Any] = {"channel": channel, "inclusive": False}
        if oldest is not None:
            params["oldest"] = oldest
        return self._paginated_messages(self._client.conversations_history, params, limit)

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict[str, Any]]:
        """Return paginated replies for a Slack thread."""
        return self._paginated_messages(
            self._client.conversations_replies,
            {"channel": channel, "ts": thread_ts},
            limit,
        )

    def _paginated_messages(
        self,
        method: Callable[..., dict[str, Any]],
        base_params: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return all Slack message pages for an endpoint."""
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        page_size = min(200, max(1, int(limit or 200)))
        while True:
            params = {**base_params, "limit": page_size}
            if cursor is not None:
                params["cursor"] = cursor

            response = method(**params)
            messages.extend(response.get("messages", []))
            cursor = (response.get("response_metadata") or {}).get("next_cursor")
            if not response.get("has_more") or not cursor:
                break
        return messages

    def user_profile(self, user_id: str) -> SlackUserProfile:
        """Return cached Slack profile metadata for a user."""
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
                email=(
                    _conversion.normalize_email(profile.get("email"))
                    if self.include_email
                    else None
                ),
            )
        return self._user_cache[user_id]


class SlackFilePollStateStore:
    """Persist per-channel Slack polling cursors in a local JSON file."""

    def __init__(self, path: Path) -> None:
        """Create a file-backed Slack poll state store."""
        self.path = path

    def load_channel(self, channel: str) -> SlackChannelState:
        """Load one channel's polling state from disk."""
        data = self._load()
        channels = data.get("channels", {})
        return self._channel_state(channels.get(channel), channel=channel)

    def save_channel(self, channel: str, state: SlackChannelState, expected_version: object | None) -> None:
        """Atomically save one channel's polling state to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self._load()
        channels = data.setdefault("channels", {})
        current_channel = channels.get(channel)
        current_version = self._channel_version(current_channel, channel=channel)
        if current_version != expected_version:
            raise SlackPollStateConflict(f"Slack poll state changed for channel {channel}.")

        channels[channel] = self._serialize_channel_state(state)
        serialized = json.dumps(data, indent=2, sort_keys=True) + "\n"
        with NamedTemporaryFile("w", dir=self.path.parent, delete=False) as temp_file:
            temp_file.write(serialized)
            temp_path = Path(temp_file.name)
        temp_path.replace(self.path)

    def _load(self) -> dict[str, Any]:
        """Load and validate poll state JSON."""
        if not self.path.exists():
            return {"channels": {}}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Slack poll state file is not valid JSON: {self.path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Slack poll state file must contain a JSON object: {self.path}")
        channels = data.setdefault("channels", {})
        if not isinstance(channels, dict):
            raise ValueError(f"Slack poll state file channels must be a JSON object: {self.path}")
        return data

    def _channel_state(self, raw_channel: object, *, channel: str) -> SlackChannelState:
        """Return a validated SlackChannelState for a raw channel object."""
        if raw_channel is None:
            return SlackChannelState(version=None)
        latest_history_ts, active_threads = self._validated_channel_values(
            raw_channel,
            channel=channel,
        )
        return SlackChannelState(
            latest_history_ts=latest_history_ts,
            active_threads=active_threads,
            version=self._channel_version(raw_channel, channel=channel),
        )

    def _channel_version(self, raw_channel: object, *, channel: str) -> str | None:
        """Return an opaque version derived from the stored channel JSON."""
        if raw_channel is None:
            return None
        channel_state = self._serialize_channel_state(
            self._channel_state_without_version(raw_channel, channel=channel)
        )
        return json.dumps(channel_state, sort_keys=True, separators=(",", ":"))

    def _channel_state_without_version(self, raw_channel: object, *, channel: str) -> SlackChannelState:
        """Validate raw channel state without recursively deriving a version."""
        if raw_channel is None:
            return SlackChannelState()
        latest_history_ts, active_threads = self._validated_channel_values(
            raw_channel,
            channel=channel,
        )
        return SlackChannelState(
            latest_history_ts=latest_history_ts,
            active_threads=active_threads,
        )

    def _serialize_channel_state(self, state: SlackChannelState) -> dict[str, Any]:
        """Return the JSON-compatible channel state without the opaque version."""
        serialized: dict[str, Any] = {}
        if state.latest_history_ts is not None:
            serialized["latest_history_ts"] = state.latest_history_ts
        serialized["active_threads"] = state.active_threads if state.active_threads else {}
        return serialized

    def _validated_channel_values(
        self,
        raw_channel: object,
        *,
        channel: str,
    ) -> tuple[str | None, dict[str, dict[str, str]]]:
        """Validate and normalize the persisted values for one channel."""
        if not isinstance(raw_channel, dict):
            raise ValueError(
                f"Slack poll state channel {channel} must be a JSON object: {self.path}"
            )

        latest_history_ts = raw_channel.get("latest_history_ts")
        if latest_history_ts is not None and not isinstance(latest_history_ts, str):
            raise ValueError(
                f"Slack poll state latest_history_ts for {channel} must be a string: {self.path}"
            )

        active_threads = raw_channel.get("active_threads", {})
        if not isinstance(active_threads, dict):
            raise ValueError(
                f"Slack poll state active_threads for {channel} must be a JSON object: {self.path}"
            )

        normalized_threads: dict[str, dict[str, str]] = {}
        for thread_ts, thread_state in active_threads.items():
            if not isinstance(thread_ts, str) or not isinstance(thread_state, dict):
                raise ValueError(
                    f"Slack poll state active_threads for {channel} must map strings to objects: {self.path}"
                )
            latest_ts = thread_state.get("latest_ts")
            if latest_ts is not None and not isinstance(latest_ts, str):
                raise ValueError(
                    f"Slack poll state active thread latest_ts for {channel} must be a string: {self.path}"
                )
            normalized_threads[thread_ts] = dict(thread_state)
        return latest_history_ts, normalized_threads


class SlackMemoryPoller:
    """Poll Slack root messages and threads and record them as Tailwag episodes."""

    def __init__(
        self,
        client: SlackConversationClient,
        episode_recorder: EpisodeRecorder,
        state_store: SlackPollStateStore,
        *,
        retention_class: str = "standard",
        active_thread_hours: float = 24.0,
        person_id_resolver: PersonIdResolver | None = None,
    ) -> None:
        """Create a poller for a Slack client and episode recorder."""
        self.client = client
        self.episode_recorder = episode_recorder
        self.state_store = state_store
        self.retention_class = retention_class
        self.active_thread_hours = active_thread_hours
        recorder_resolver = getattr(
            episode_recorder,
            "canonical_person_id_by_email",
            None,
        )
        self.person_id_resolver = person_id_resolver or (
            recorder_resolver if callable(recorder_resolver) else None
        )

    def poll_once(
        self,
        channel: str,
        *,
        backfill_hours: float | None = None,
        force_backfill: bool = False,
        history_limit: int = 200,
        reply_limit: int = 200,
        extract_memory: bool = True,
        enqueue_memory_extraction: bool = True,
    ) -> SlackPollResult:
        """Run one Slack channel polling pass."""
        if force_backfill and backfill_hours is None:
            raise ValueError("force_backfill requires backfill_hours.")

        poll_started_ts = _now_slack_ts()
        state = self.state_store.load_channel(channel)
        expected_version = state.version
        oldest = state.latest_history_ts

        if force_backfill:
            oldest = _datetime_to_slack_ts(
                datetime.now(timezone.utc) - timedelta(hours=backfill_hours or 0)
            )
        elif oldest is None and backfill_hours is None:
            now_ts = _now_slack_ts()
            state.latest_history_ts = now_ts
            self.state_store.save_channel(channel, state, expected_version)
            return SlackPollResult(
                channel=channel,
                checked_threads=0,
                ingested_threads=0,
                latest_history_ts=now_ts,
                armed_without_backfill=True,
                memory_extraction_enabled=extract_memory,
            )

        if oldest is None and backfill_hours is not None:
            oldest = _datetime_to_slack_ts(
                datetime.now(timezone.utc) - timedelta(hours=backfill_hours)
            )

        history = self.client.history(channel=channel, oldest=oldest, limit=history_limit)
        history_messages: dict[str, list[dict[str, Any]]] = {}
        threaded_history: set[str] = set()
        for message in history:
            if not _conversion.is_memory_message(message):
                continue

            thread_ts = _conversion.thread_ts(message)
            if thread_ts is None:
                continue

            history_messages.setdefault(thread_ts, []).append(message)
            if int(message.get("reply_count") or 0) > 0:
                threaded_history.add(thread_ts)

        active_threads = state.active_threads
        threads_to_check = set(active_threads) | set(history_messages)
        episode_records: list[EpisodeRecordResult] = []
        thread_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.active_thread_hours)

        for thread_ts in sorted(threads_to_check, key=float):
            should_fetch_replies = thread_ts in active_threads or thread_ts in threaded_history
            if should_fetch_replies:
                replies = self.client.replies(channel=channel, thread_ts=thread_ts, limit=reply_limit)
                messages = [
                    message for message in replies if _conversion.is_memory_message(message)
                ]
            else:
                messages = [
                    message
                    for message in history_messages.get(thread_ts, [])
                    if _conversion.is_memory_message(message)
                ]

            if not messages:
                active_threads.pop(thread_ts, None)
                continue

            latest_thread_ts = _conversion.max_ts(messages)
            prior_thread_ts = active_threads.get(thread_ts, {}).get("latest_ts")
            if (
                force_backfill
                or prior_thread_ts is None
                or float(latest_thread_ts) > float(prior_thread_ts)
            ):
                episode = build_episode_from_slack_thread(
                    channel=channel,
                    messages=messages,
                    client=self.client,
                    retention_class=self.retention_class,
                    person_id_resolver=self.person_id_resolver,
                )
                episode_records.append(
                    self.episode_recorder.record_episode(
                        episode,
                        extract_memory=extract_memory,
                        **(
                            {"enqueue_memory_extraction": False}
                            if not enqueue_memory_extraction
                            else {}
                        ),
                    )
                )

            latest_thread_time = _conversion.slack_ts_to_datetime(latest_thread_ts)
            if latest_thread_time >= thread_cutoff:
                active_threads[thread_ts] = {"latest_ts": latest_thread_ts}
            else:
                active_threads.pop(thread_ts, None)

        latest_history_ts = _conversion.max_ts(history) if history else poll_started_ts
        if latest_history_ts is not None:
            state.latest_history_ts = latest_history_ts
        self.state_store.save_channel(channel, state, expected_version)

        return SlackPollResult(
            channel=channel,
            checked_threads=len(threads_to_check),
            ingested_threads=len(episode_records),
            latest_history_ts=latest_history_ts,
            memory_extraction_enabled=extract_memory,
            ingested_episode_ids=[record.episode_id for record in episode_records],
            episode_records=episode_records,
        )


def _datetime_to_slack_ts(value: datetime) -> str:
    """Convert a datetime to Slack timestamp text."""
    return f"{value.timestamp():.6f}"


def _now_slack_ts() -> str:
    """Return the current time as a Slack timestamp."""
    return _datetime_to_slack_ts(datetime.now(timezone.utc))
