from __future__ import annotations

import copy
from decimal import Decimal
import unittest
from typing import Any

from tailwag_memory.aws.slack_state import SlackDynamoDBPollStateStore
from tailwag_memory.slack_ingestion import SlackChannelState, SlackPollStateConflict


class ConditionalCheckFailed(Exception):
    def __init__(self) -> None:
        super().__init__("conditional check failed")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeDynamoDBTable:
    def __init__(self, items: dict[str, dict[str, Any]] | None = None) -> None:
        self.items = copy.deepcopy(items or {})
        self.get_calls: list[dict[str, Any]] = []
        self.put_calls: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(copy.deepcopy(kwargs))
        channel = kwargs["Key"]["channel_id"]
        if channel not in self.items:
            return {}
        return {"Item": copy.deepcopy(self.items[channel])}

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(copy.deepcopy(kwargs))
        item = kwargs["Item"]
        channel = item["channel_id"]
        condition = kwargs["ConditionExpression"]

        if condition == "attribute_not_exists(#channel_key)":
            if channel in self.items:
                raise ConditionalCheckFailed()
        elif condition == "#version = :expected_version":
            expected = kwargs["ExpressionAttributeValues"][":expected_version"]
            current = self.items.get(channel)
            if current is None or current.get("version") != expected:
                raise ConditionalCheckFailed()
        else:
            raise AssertionError(f"unexpected condition: {condition}")

        self.items[channel] = copy.deepcopy(item)
        return {}


class SlackDynamoDBPollStateStoreTest(unittest.TestCase):
    def test_missing_channel_loads_empty_state(self) -> None:
        table = FakeDynamoDBTable()
        store = SlackDynamoDBPollStateStore(table)

        state = store.load_channel("C123")

        self.assertEqual(state, SlackChannelState())
        self.assertEqual(table.get_calls, [{"Key": {"channel_id": "C123"}, "ConsistentRead": True}])

    def test_load_channel_reads_cursor_threads_and_version(self) -> None:
        table = FakeDynamoDBTable(
            {
                "C123": {
                    "channel_id": "C123",
                    "latest_history_ts": "100.000000",
                    "active_threads": {"99.000000": {"latest_ts": "101.000000"}},
                    "version": Decimal("7"),
                }
            }
        )
        store = SlackDynamoDBPollStateStore(table)

        state = store.load_channel("C123")

        self.assertEqual(state.latest_history_ts, "100.000000")
        self.assertEqual(state.active_threads, {"99.000000": {"latest_ts": "101.000000"}})
        self.assertEqual(state.version, Decimal("7"))

    def test_save_new_channel_uses_create_condition_and_initial_version(self) -> None:
        table = FakeDynamoDBTable()
        store = SlackDynamoDBPollStateStore(table, lease_owner="worker-1", lease_expires_at=12345)
        state = SlackChannelState(
            latest_history_ts="100.000000",
            active_threads={"99.000000": {"latest_ts": "101.000000"}},
        )

        store.save_channel("C123", state, expected_version=None)

        self.assertEqual(
            table.items["C123"],
            {
                "channel_id": "C123",
                "latest_history_ts": "100.000000",
                "active_threads": {"99.000000": {"latest_ts": "101.000000"}},
                "version": 1,
                "lease_owner": "worker-1",
                "lease_expires_at": 12345,
            },
        )
        self.assertEqual(table.put_calls[0]["ConditionExpression"], "attribute_not_exists(#channel_key)")
        self.assertNotIn("ExpressionAttributeValues", table.put_calls[0])

    def test_save_existing_channel_uses_version_condition_and_increments_version(self) -> None:
        table = FakeDynamoDBTable(
            {
                "C123": {
                    "channel_id": "C123",
                    "latest_history_ts": "100.000000",
                    "active_threads": {},
                    "version": Decimal("3"),
                }
            }
        )
        store = SlackDynamoDBPollStateStore(table)
        state = store.load_channel("C123")
        state.latest_history_ts = "200.000000"

        store.save_channel("C123", state, expected_version=state.version)

        self.assertEqual(table.items["C123"]["latest_history_ts"], "200.000000")
        self.assertEqual(table.items["C123"]["active_threads"], {})
        self.assertEqual(table.items["C123"]["version"], Decimal("4"))
        self.assertEqual(table.put_calls[0]["ConditionExpression"], "#version = :expected_version")
        self.assertEqual(table.put_calls[0]["ExpressionAttributeValues"], {":expected_version": Decimal("3")})

    def test_stale_expected_version_raises_poll_state_conflict(self) -> None:
        table = FakeDynamoDBTable(
            {
                "C123": {
                    "channel_id": "C123",
                    "latest_history_ts": "100.000000",
                    "active_threads": {},
                    "version": 3,
                }
            }
        )
        store = SlackDynamoDBPollStateStore(table)

        with self.assertRaisesRegex(SlackPollStateConflict, "C123"):
            store.save_channel("C123", SlackChannelState(latest_history_ts="200.000000"), expected_version=2)

        self.assertEqual(table.items["C123"]["latest_history_ts"], "100.000000")
        self.assertEqual(table.items["C123"]["version"], 3)

    def test_existing_channel_conflicts_with_new_channel_expected_version(self) -> None:
        table = FakeDynamoDBTable(
            {
                "C123": {
                    "channel_id": "C123",
                    "active_threads": {},
                    "version": 1,
                }
            }
        )
        store = SlackDynamoDBPollStateStore(table)

        with self.assertRaisesRegex(SlackPollStateConflict, "C123"):
            store.save_channel("C123", SlackChannelState(latest_history_ts="200.000000"), expected_version=None)

    def test_invalid_loaded_item_raises_value_error(self) -> None:
        table = FakeDynamoDBTable(
            {
                "C123": {
                    "channel_id": "C123",
                    "active_threads": {"99.0": {"latest_ts": 99}},
                    "version": 1,
                }
            }
        )
        store = SlackDynamoDBPollStateStore(table)

        with self.assertRaisesRegex(ValueError, "latest_ts"):
            store.load_channel("C123")

    def test_non_integer_expected_version_is_rejected(self) -> None:
        table = FakeDynamoDBTable()
        store = SlackDynamoDBPollStateStore(table)

        with self.assertRaisesRegex(ValueError, "expected version"):
            store.save_channel("C123", SlackChannelState(), expected_version="opaque")


if __name__ == "__main__":
    unittest.main()
