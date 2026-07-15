from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from tailwag_memory.slack_ingestion import SlackChannelState, SlackPollStateConflict


class DynamoDBTable(Protocol):
    """Describe the DynamoDB table methods used by the Slack state store."""

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        """Return one DynamoDB item response."""
        ...

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        """Write one DynamoDB item response."""
        ...


class SlackDynamoDBPollStateStore:
    """Persist Slack polling cursors in a DynamoDB-style table."""

    def __init__(
        self,
        table: DynamoDBTable,
        *,
        channel_key: str = "channel_id",
        version_attribute: str = "version",
        lease_owner: str | None = None,
        lease_expires_at: int | str | None = None,
    ) -> None:
        """Create a DynamoDB-backed Slack poll state store."""
        self.table = table
        self.channel_key = channel_key
        self.version_attribute = version_attribute
        self.lease_owner = lease_owner
        self.lease_expires_at = lease_expires_at

    def load_channel(self, channel: str) -> SlackChannelState:
        """Load one channel's polling state from DynamoDB."""
        response = self.table.get_item(Key={self.channel_key: channel}, ConsistentRead=True)
        item = response.get("Item")
        return self._channel_state(item, channel=channel)

    def save_channel(self, channel: str, state: SlackChannelState, expected_version: object | None) -> None:
        """Save one channel if its current DynamoDB version still matches."""
        new_version = self._next_version(expected_version, channel=channel)
        item = self._serialize_channel_state(channel=channel, state=state, version=new_version)

        expression_values: dict[str, Any] = {}
        if expected_version is None:
            expression_names = {"#channel_key": self.channel_key}
            condition = "attribute_not_exists(#channel_key)"
        else:
            expression_names = {"#version": self.version_attribute}
            condition = "#version = :expected_version"
            expression_values[":expected_version"] = expected_version

        put_kwargs: dict[str, Any] = {
            "Item": item,
            "ConditionExpression": condition,
            "ExpressionAttributeNames": expression_names,
        }
        if expression_values:
            put_kwargs["ExpressionAttributeValues"] = expression_values

        try:
            self.table.put_item(**put_kwargs)
        except Exception as exc:
            if _is_conditional_check_failed(exc):
                raise SlackPollStateConflict(f"Slack poll state changed for channel {channel}.") from exc
            raise

    def _channel_state(self, raw_item: object, *, channel: str) -> SlackChannelState:
        """Return a validated SlackChannelState for a DynamoDB item."""
        if raw_item is None:
            return SlackChannelState(version=None)
        if not isinstance(raw_item, dict):
            raise ValueError(f"Slack poll state item for {channel} must be an object.")

        latest_history_ts = raw_item.get("latest_history_ts")
        if latest_history_ts is not None and not isinstance(latest_history_ts, str):
            raise ValueError(f"Slack poll state latest_history_ts for {channel} must be a string.")

        active_threads = raw_item.get("active_threads", {})
        if not isinstance(active_threads, dict):
            raise ValueError(f"Slack poll state active_threads for {channel} must be an object.")

        normalized_threads: dict[str, dict[str, str]] = {}
        for thread_ts, thread_state in active_threads.items():
            if not isinstance(thread_ts, str) or not isinstance(thread_state, dict):
                raise ValueError(f"Slack poll state active_threads for {channel} must map strings to objects.")
            latest_ts = thread_state.get("latest_ts")
            if latest_ts is not None and not isinstance(latest_ts, str):
                raise ValueError(f"Slack poll state active thread latest_ts for {channel} must be a string.")
            normalized_threads[thread_ts] = dict(thread_state)

        version = raw_item.get(self.version_attribute)
        if version is not None and not _is_integer_version(version):
            raise ValueError(f"Slack poll state version for {channel} must be an integer.")

        return SlackChannelState(
            latest_history_ts=latest_history_ts,
            active_threads=normalized_threads,
            version=version,
        )

    def _serialize_channel_state(
        self,
        *,
        channel: str,
        state: SlackChannelState,
        version: int | Decimal,
    ) -> dict[str, Any]:
        """Return a DynamoDB resource-compatible item."""
        item: dict[str, Any] = {
            self.channel_key: channel,
            self.version_attribute: version,
            "active_threads": {
                thread_ts: dict(thread_state) for thread_ts, thread_state in state.active_threads.items()
            },
        }
        if state.latest_history_ts is not None:
            item["latest_history_ts"] = state.latest_history_ts
        if self.lease_owner is not None:
            item["lease_owner"] = self.lease_owner
        if self.lease_expires_at is not None:
            item["lease_expires_at"] = self.lease_expires_at
        return item

    def _next_version(self, expected_version: object | None, *, channel: str) -> int | Decimal:
        """Return the next integer version for a conditional state write."""
        if expected_version is None:
            return 1
        if isinstance(expected_version, int) and not isinstance(expected_version, bool):
            return expected_version + 1
        if isinstance(expected_version, Decimal) and _is_integer_version(expected_version):
            return expected_version + Decimal(1)
        raise ValueError(f"Slack poll state expected version for {channel} must be an integer or None.")


def _is_integer_version(value: object) -> bool:
    """Return whether a value is an integer DynamoDB version token."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, Decimal):
        return value == value.to_integral_value()
    return False


def _is_conditional_check_failed(exc: Exception) -> bool:
    """Return whether an exception looks like a DynamoDB conditional failure."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if not isinstance(error, dict):
        return False
    return error.get("Code") == "ConditionalCheckFailedException"
