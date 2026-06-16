from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from tailwag_memory.slack_ingestion import (
    SlackMemoryPoller,
    build_episode_from_slack_thread,
)


def _ts(offset_seconds: float = 0.0) -> str:
    return f"{datetime.now(timezone.utc).timestamp() + offset_seconds:.6f}"


class FakeSlackClient:
    def __init__(
        self,
        *,
        history_messages: list[dict] | None = None,
        replies_by_thread: dict[str, list[dict]] | None = None,
        user_names: dict[str, str] | None = None,
    ) -> None:
        self.history_messages = history_messages or []
        self.replies_by_thread = replies_by_thread or {}
        self.user_names = user_names or {}
        self.history_calls: list[dict] = []
        self.reply_calls: list[dict] = []

    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict]:
        self.history_calls.append({"channel": channel, "oldest": oldest, "limit": limit})
        return self.history_messages

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict]:
        self.reply_calls.append({"channel": channel, "thread_ts": thread_ts, "limit": limit})
        return self.replies_by_thread.get(thread_ts, [])

    def user_display_name(self, user_id: str) -> str | None:
        return self.user_names.get(user_id)


class FakeEpisodeService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.episodes = []

    def ingest(self, episode):
        if self.fail:
            raise RuntimeError("ingest failed")
        self.episodes.append(episode)
        return episode.id


class SlackThreadConversionTest(unittest.TestCase):
    def test_thread_becomes_episode_with_slack_people_and_virtual_place(self) -> None:
        root_ts = _ts()
        reply_ts = _ts(3)
        client = FakeSlackClient(user_names={"U1": "Asha", "U2": "Ben"})
        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[
                {"ts": reply_ts, "thread_ts": root_ts, "user": "U2", "text": "Yes, I can help."},
                {"ts": root_ts, "user": "U1", "text": "Can someone review the deck?"},
            ],
            client=client,
        )

        self.assertEqual(episode.id, f"slack:C123:{root_ts}")
        self.assertEqual(episode.episode_type, "conversation")
        self.assertEqual(episode.summary, "Can someone review the deck?")
        self.assertEqual(episode.place.building_code, "SLACK")
        self.assertEqual(episode.place.room_id, "C123")
        self.assertEqual([person.id for person in episode.participants], ["slack:U1", "slack:U2"])
        self.assertEqual([person.display_name for person in episode.participants], ["Asha", "Ben"])
        self.assertIsNone(episode.participants[0].face_embedding)
        self.assertIsNone(episode.participants[0].audio_embedding)
        self.assertEqual(episode.participants[0].source, "slack")
        self.assertEqual(episode.transcript, "Asha: Can someone review the deck?\nBen: Yes, I can help.")


class SlackMemoryPollerTest(unittest.TestCase):
    def test_first_poll_without_backfill_arms_state_without_ingesting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            service = FakeEpisodeService()
            client = FakeSlackClient()
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123")

            self.assertTrue(result.armed_without_backfill)
            self.assertEqual(result.ingested_threads, 0)
            self.assertEqual(service.episodes, [])
            state = json.loads(state_path.read_text())
            self.assertIn("latest_history_ts", state["channels"]["C123"])

    def test_backfill_ingests_thread_and_saves_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            reply_ts = _ts(2)
            service = FakeEpisodeService()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
                replies_by_thread={
                    root_ts: [
                        {"ts": root_ts, "user": "U1", "text": "Start thread"},
                        {"ts": reply_ts, "thread_ts": root_ts, "user": "U2", "text": "Reply"},
                    ]
                },
                user_names={"U1": "Asha", "U2": "Ben"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123", backfill_hours=1)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(service.episodes[0].id, f"slack:C123:{root_ts}")
            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"]["latest_history_ts"], root_ts)

    def test_active_thread_is_refreshed_when_new_reply_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            first_reply_ts = _ts(2)
            second_reply_ts = _ts(4)
            service = FakeEpisodeService()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
                replies_by_thread={
                    root_ts: [
                        {"ts": root_ts, "user": "U1", "text": "Start thread"},
                        {"ts": first_reply_ts, "thread_ts": root_ts, "user": "U2", "text": "First reply"},
                    ]
                },
                user_names={"U1": "Asha", "U2": "Ben"},
            )
            poller = SlackMemoryPoller(client, service, state_path)
            poller.poll_once("C123", backfill_hours=1)

            client.history_messages = []
            client.replies_by_thread[root_ts] = [
                {"ts": root_ts, "user": "U1", "text": "Start thread"},
                {"ts": first_reply_ts, "thread_ts": root_ts, "user": "U2", "text": "First reply"},
                {"ts": second_reply_ts, "thread_ts": root_ts, "user": "U1", "text": "Follow-up"},
            ]
            result = poller.poll_once("C123", backfill_hours=1)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(len(service.episodes), 2)
            self.assertIn("Follow-up", service.episodes[-1].transcript)

    def test_failed_ingest_does_not_advance_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            service = FakeEpisodeService(fail=True)
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
                replies_by_thread={root_ts: [{"ts": root_ts, "user": "U1", "text": "Start thread"}]},
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            with self.assertRaises(RuntimeError):
                poller.poll_once("C123", backfill_hours=1)

            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
