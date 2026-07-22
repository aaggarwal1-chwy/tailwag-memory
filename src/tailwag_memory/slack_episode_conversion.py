from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from typing import Any, Callable, Protocol

from .models import EpisodeInput, EpisodeMentionInput, PersonInput, PlaceInput


PersonIdResolver = Callable[[str], str | None]


class SlackProfile(Protocol):
    """Describe Slack profile fields used during episode conversion."""

    display_name: str | None
    email: str | None


class SlackProfileClient(Protocol):
    """Describe the profile lookup needed during episode conversion."""

    def user_profile(self, user_id: str) -> SlackProfile:
        """Return profile data for a Slack user."""
        ...


def build_episode_from_slack_thread(
    *,
    channel: str,
    messages: list[dict[str, Any]],
    client: SlackProfileClient,
    retention_class: str = "standard",
    person_id_resolver: PersonIdResolver | None = None,
) -> EpisodeInput:
    """Convert Slack root-message or thread messages into an episode input."""
    ordered = sorted(
        [message for message in messages if is_memory_message(message)],
        key=lambda item: float(item["ts"]),
    )
    if not ordered:
        raise ValueError("Cannot build an episode from empty Slack messages.")

    thread_timestamp = thread_ts(ordered[0])
    user_profiles: dict[str, SlackProfile] = {}
    participants: list[PersonInput] = []
    seen_users: set[str] = set()
    mentioned_user_ids: list[str] = []
    transcript_lines: list[str] = []

    for message in ordered:
        user_id = str(message["user"])
        if user_id not in user_profiles:
            user_profiles[user_id] = client.user_profile(user_id)
        user_profile = user_profiles[user_id]
        display_name = user_profile.display_name or f"slack:{user_id}"

        if user_id not in seen_users:
            participants.append(
                slack_person_input(
                    slack_user_id=user_id,
                    user_profile=user_profile,
                    role="speaker",
                    person_id_resolver=person_id_resolver,
                )
            )
            seen_users.add(user_id)

        message_time = slack_ts_to_datetime(str(message["ts"])).isoformat()
        text, message_mentions = format_slack_text(
            str(message.get("text") or ""),
            client=client,
            user_profiles=user_profiles,
        )
        for mentioned_user_id in message_mentions:
            if mentioned_user_id not in mentioned_user_ids:
                mentioned_user_ids.append(mentioned_user_id)
        transcript_lines.append(f"[{message_time}] {display_name}: {text}")

    mentioned_people = [
        EpisodeMentionInput(
            person=slack_person_input(
                slack_user_id=user_id,
                user_profile=user_profiles[user_id],
                role="mentioned",
                person_id_resolver=person_id_resolver,
            ),
            source="slack",
        )
        for user_id in mentioned_user_ids
    ]

    return EpisodeInput(
        id=f"slack:{channel}:{thread_timestamp}",
        episode_type="conversation",
        start_time=slack_ts_to_datetime(str(ordered[0]["ts"])).isoformat(),
        end_time=slack_ts_to_datetime(max_ts(ordered)).isoformat(),
        transcript="\n".join(transcript_lines),
        retention_class=retention_class,
        place=PlaceInput(building_code="SLACK", room_id=channel),
        participants=participants,
        mentioned_people=mentioned_people,
    )


def slack_person_input(
    *,
    slack_user_id: str,
    user_profile: SlackProfile,
    role: str,
    person_id_resolver: PersonIdResolver | None,
) -> PersonInput:
    """Return Tailwag person input for one Slack user."""
    display_name = user_profile.display_name or f"slack:{slack_user_id}"
    email = normalize_email(user_profile.email)
    person_id, resolved_to_canonical = resolve_slack_person_id(
        slack_user_id=slack_user_id,
        email=email,
        person_id_resolver=person_id_resolver,
    )
    return PersonInput(
        id=person_id,
        display_name=None if resolved_to_canonical else display_name,
        email=None if resolved_to_canonical else email,
        role=role,
        source="slack",
    )


def resolve_slack_person_id(
    *,
    slack_user_id: str,
    email: str | None,
    person_id_resolver: PersonIdResolver | None,
) -> tuple[str, bool]:
    """Resolve a Slack participant to a caller-owned canonical person id when possible."""
    fallback_person_id = f"slack:{slack_user_id}"
    if email and person_id_resolver is not None:
        resolved = str(person_id_resolver(email) or "").strip()
        if resolved:
            return resolved, resolved != fallback_person_id
    return fallback_person_id, False


def is_memory_message(
    message: dict[str, Any],
) -> bool:
    """Return whether a Slack message should be ingested."""
    subtype = message.get("subtype")
    if subtype in {"message_deleted", "channel_join", "channel_leave", "bot_message"} or message.get("bot_id"):
        return False
    return (
        bool(message.get("user"))
        and bool(clean_text(str(message.get("text") or "")))
        and bool(message.get("ts"))
    )


def thread_ts(message: dict[str, Any]) -> str | None:
    """Return the thread timestamp for a Slack message."""
    timestamp = message.get("thread_ts") or message.get("ts")
    return str(timestamp) if timestamp is not None else None


def clean_text(text: str) -> str:
    """Collapse whitespace in Slack text."""
    return " ".join(text.split())


def format_slack_text(
    text: str,
    *,
    client: SlackProfileClient,
    user_profiles: dict[str, SlackProfile],
) -> tuple[str, list[str]]:
    """Format Slack mrkdwn into transcript text."""
    text = html.unescape(text)
    text, mentioned_user_ids = replace_user_mentions(
        text,
        client=client,
        user_profiles=user_profiles,
    )
    return clean_text(replace_slack_entities(text)), mentioned_user_ids


def replace_user_mentions(
    text: str,
    *,
    client: SlackProfileClient,
    user_profiles: dict[str, SlackProfile],
) -> tuple[str, list[str]]:
    """Replace Slack user mention tokens with display names."""
    mentioned_user_ids: list[str] = []

    def replace(match: re.Match[str]) -> str:
        user_id = match.group("user_id")
        label = match.group("label")
        if user_id not in mentioned_user_ids:
            mentioned_user_ids.append(user_id)
        if user_id not in user_profiles:
            user_profiles[user_id] = client.user_profile(user_id)
        display_name = user_profiles[user_id].display_name or label or f"slack:{user_id}"
        return f"@{display_name}"

    return re.sub(r"<@(?P<user_id>[A-Z0-9]+)(?:\|(?P<label>[^>]+))?>", replace, text), mentioned_user_ids


def replace_slack_entities(text: str) -> str:
    """Replace Slack entity tokens with readable labels."""
    def replace(match: re.Match[str]) -> str:
        body = match.group("body")
        if body.startswith("#"):
            channel_id, _, label = body[1:].partition("|")
            return f"#{label or channel_id}"
        if body.startswith("!"):
            mention, _, label = body[1:].partition("|")
            return f"@{label or mention}"

        target, _, label = body.partition("|")
        if target.startswith("mailto:"):
            return label or target.removeprefix("mailto:")
        if "://" in target or target.startswith("www."):
            return label or target
        return match.group(0)

    return re.sub(r"<(?P<body>[^<>]+)>", replace, text)


def normalize_email(email: Any) -> str | None:
    """Normalize a Slack profile email value."""
    if not isinstance(email, str):
        return None
    normalized = email.strip().lower()
    return normalized or None


def max_ts(messages: list[dict[str, Any]]) -> str:
    """Return the maximum Slack timestamp in a message list."""
    return max((str(message["ts"]) for message in messages if message.get("ts") is not None), key=float)


def slack_ts_to_datetime(ts: str) -> datetime:
    """Convert a Slack timestamp to a UTC datetime."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)
