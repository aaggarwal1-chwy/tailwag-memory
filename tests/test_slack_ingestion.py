from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from tailwag_memory.slack_ingestion import (
    SlackMemoryPoller,
    SlackWebApiClient,
    SlackUserProfile,
    build_episode_from_slack_thread,
)
from tailwag_memory.models import EpisodeRecordResult, PersonMemoryExtractionResult


def _ts(offset_seconds: float = 0.0) -> str:
    return f"{datetime.now(timezone.utc).timestamp() + offset_seconds:.6f}"


class FakeSlackClient:
    def __init__(
        self,
        *,
        history_messages: list[dict] | None = None,
        replies_by_thread: dict[str, list[dict]] | None = None,
        user_names: dict[str, str] | None = None,
        user_emails: dict[str, str] | None = None,
    ) -> None:
        self.history_messages = history_messages or []
        self.replies_by_thread = replies_by_thread or {}
        self.user_names = user_names or {}
        self.user_emails = user_emails or {}
        self.history_calls: list[dict] = []
        self.reply_calls: list[dict] = []

    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict]:
        self.history_calls.append({"channel": channel, "oldest": oldest, "limit": limit})
        return self.history_messages

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict]:
        self.reply_calls.append({"channel": channel, "thread_ts": thread_ts, "limit": limit})
        return self.replies_by_thread.get(thread_ts, [])

    def user_profile(self, user_id: str) -> SlackUserProfile:
        return SlackUserProfile(
            display_name=self.user_names.get(user_id),
            email=self.user_emails.get(user_id),
        )


class FakeEpisodeRecorder:
    def __init__(self, *, fail: bool = False, memory_errors: list[dict[str, str]] | None = None) -> None:
        self.fail = fail
        self.memory_errors = memory_errors or []
        self.episodes = []
        self.record_calls = []

    def record_episode(self, episode, *, extract_memory: bool = True):
        if self.fail:
            raise RuntimeError("ingest failed")
        self.episodes.append(episode)
        self.record_calls.append({"episode_id": episode.id, "extract_memory": extract_memory})
        return EpisodeRecordResult(
            episode_id=episode.id,
            memory_results=(
                [PersonMemoryExtractionResult(person_id=episode.participants[0].id, created_memory_ids=["mem_1"])]
                if extract_memory and episode.participants
                else []
            ),
            memory_errors=self.memory_errors,
        )


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
        self.assertEqual(episode.summary, "Asha: Can someone review the deck?")
        self.assertEqual(episode.place.building_code, "SLACK")
        self.assertEqual(episode.place.room_id, "C123")
        self.assertEqual([person.id for person in episode.participants], ["slack:U1", "slack:U2"])
        self.assertEqual([person.display_name for person in episode.participants], ["Asha", "Ben"])
        self.assertIsNone(episode.participants[0].email)
        self.assertIsNone(episode.participants[0].face_embedding)
        self.assertIsNone(episode.participants[0].audio_embedding)
        self.assertEqual(episode.participants[0].source, "slack")
        self.assertEqual(
            episode.transcript,
            "\n".join(
                [
                    f"[{datetime.fromtimestamp(float(root_ts), tz=timezone.utc).isoformat()}] Asha: Can someone review the deck?",
                    f"[{datetime.fromtimestamp(float(reply_ts), tz=timezone.utc).isoformat()}] Ben: Yes, I can help.",
                ]
            ),
        )

    def test_thread_keeps_slack_person_id_and_stores_email_metadata(self) -> None:
        root_ts = _ts()
        client = FakeSlackClient(
            user_names={"U1": "Asha"},
            user_emails={"U1": "Asha.Example@Example.COM"},
        )
        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[{"ts": root_ts, "user": "U1", "text": "Can someone review the deck?"}],
            client=client,
        )

        self.assertEqual(episode.participants[0].id, "slack:U1")
        self.assertEqual(episode.participants[0].email, "asha.example@example.com")

    def test_thread_replaces_slack_user_mentions_with_display_names(self) -> None:
        root_ts = _ts()
        reply_ts = _ts(2)
        client = FakeSlackClient(user_names={"U1": "Asha", "U2": "Ben", "U3": "Chandra"})
        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[
                {"ts": root_ts, "user": "U1", "text": "Can <@U2> and <@U3|fallback> review this?"},
                {"ts": reply_ts, "thread_ts": root_ts, "user": "U2", "text": "Looping <@U3> in."},
            ],
            client=client,
        )

        self.assertEqual(episode.summary, "Asha: Can @Ben and @Chandra review this?")
        self.assertIn("Asha: Can @Ben and @Chandra review this?", episode.transcript)
        self.assertIn("Ben: Looping @Chandra in.", episode.transcript)
        self.assertEqual([person.id for person in episode.participants], ["slack:U1", "slack:U2"])


class SlackWebApiClientTest(unittest.TestCase):
    def test_user_profile_reads_and_normalizes_email(self) -> None:
        class FakeWebClient:
            def __init__(self) -> None:
                self.calls = 0

            def users_info(self, user: str) -> dict:
                self.calls += 1
                return {
                    "user": {
                        "profile": {
                            "display_name": "Asha",
                            "email": " Asha.Example@Example.COM ",
                        }
                    }
                }

        fake_web_client = FakeWebClient()
        client = SlackWebApiClient.__new__(SlackWebApiClient)
        client._client = fake_web_client
        client._user_cache = {}

        profile = client.user_profile("U1")
        cached_profile = client.user_profile("U1")

        self.assertEqual(profile, SlackUserProfile(display_name="Asha", email="asha.example@example.com"))
        self.assertEqual(cached_profile, profile)
        self.assertEqual(fake_web_client.calls, 1)


class SlackMemoryPollerTest(unittest.TestCase):
    def test_first_poll_without_backfill_arms_state_without_ingesting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            service = FakeEpisodeRecorder()
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
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread", "reply_count": 1}],
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
            self.assertEqual(result.ingested_episode_ids, [f"slack:C123:{root_ts}"])
            self.assertTrue(result.memory_extraction_enabled)
            self.assertEqual(result.episode_records[0].memory_results[0].created_memory_ids, ["mem_1"])
            self.assertEqual(service.record_calls[0]["extract_memory"], True)
            self.assertEqual(service.episodes[0].id, f"slack:C123:{root_ts}")
            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"]["latest_history_ts"], root_ts)

    def test_backfill_can_skip_memory_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123", backfill_hours=1, extract_memory=False)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(result.ingested_episode_ids, [f"slack:C123:{root_ts}"])
            self.assertFalse(result.memory_extraction_enabled)
            self.assertEqual(result.episode_records[0].memory_results, [])
            self.assertEqual(service.record_calls, [{"episode_id": f"slack:C123:{root_ts}", "extract_memory": False}])

    def test_memory_extraction_errors_are_returned_and_state_advances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            service = FakeEpisodeRecorder(memory_errors=[{"person_id": "slack:U1", "error": "model unavailable"}])
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123", backfill_hours=1)

            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(result.episode_records[0].memory_errors, [{"person_id": "slack:U1", "error": "model unavailable"}])
            self.assertTrue(state_path.exists())

    def test_force_backfill_ignores_saved_cursor_and_reingests_seen_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            state_path.write_text(
                json.dumps(
                    {
                        "channels": {
                            "C123": {
                                "active_threads": {root_ts: {"latest_ts": root_ts}},
                                "latest_history_ts": _ts(300),
                            }
                        }
                    }
                )
            )
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread", "reply_count": 1}],
                replies_by_thread={root_ts: [{"ts": root_ts, "user": "U1", "text": "Start thread"}]},
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123", backfill_hours=1, force_backfill=True)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(service.episodes[0].id, f"slack:C123:{root_ts}")
            self.assertLess(float(client.history_calls[0]["oldest"]), float(root_ts))

    def test_active_thread_is_refreshed_when_new_reply_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            first_reply_ts = _ts(2)
            second_reply_ts = _ts(4)
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread", "reply_count": 1}],
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
            service = FakeEpisodeRecorder(fail=True)
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread", "reply_count": 1}],
                replies_by_thread={root_ts: [{"ts": root_ts, "user": "U1", "text": "Start thread"}]},
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            with self.assertRaises(RuntimeError):
                poller.poll_once("C123", backfill_hours=1)

            self.assertFalse(state_path.exists())

    def test_empty_history_poll_advances_saved_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            prior_ts = _ts(-300)
            state_path.write_text(
                json.dumps(
                    {
                        "channels": {
                            "C123": {
                                "latest_history_ts": prior_ts,
                            }
                        }
                    }
                )
            )
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(history_messages=[])
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123")

            self.assertEqual(result.checked_threads, 0)
            self.assertEqual(result.ingested_threads, 0)
            self.assertEqual(service.episodes, [])
            state = json.loads(state_path.read_text())
            latest_history_ts = state["channels"]["C123"]["latest_history_ts"]
            self.assertEqual(result.latest_history_ts, latest_history_ts)
            self.assertGreater(float(latest_history_ts), float(prior_ts))

    def test_unthreaded_history_message_is_tracked_without_fetching_replies_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Standalone update"}],
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path)

            result = poller.poll_once("C123", backfill_hours=1)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(client.reply_calls, [])
            self.assertEqual(service.episodes[0].id, f"slack:C123:{root_ts}")
            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"]["active_threads"], {root_ts: {"latest_ts": root_ts}})

    def test_late_first_reply_updates_previously_unthreaded_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts(-3600)
            reply_ts = _ts()
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Can someone review this?"}],
                user_names={"U1": "Asha", "U2": "Ben"},
            )
            poller = SlackMemoryPoller(client, service, state_path)
            poller.poll_once("C123", backfill_hours=2)

            client.history_messages = []
            client.replies_by_thread[root_ts] = [
                {"ts": root_ts, "user": "U1", "text": "Can someone review this?"},
                {"ts": reply_ts, "thread_ts": root_ts, "user": "U2", "text": "I can take it."},
            ]
            result = poller.poll_once("C123", backfill_hours=2)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(client.reply_calls[-1]["thread_ts"], root_ts)
            self.assertEqual(len(service.episodes), 2)
            self.assertEqual(service.episodes[-1].id, f"slack:C123:{root_ts}")
            self.assertIn("I can take it.", service.episodes[-1].transcript)
            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"]["active_threads"], {root_ts: {"latest_ts": reply_ts}})

    def test_stale_active_thread_is_removed_after_active_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts(-7200)
            state_path.write_text(
                json.dumps(
                    {
                        "channels": {
                            "C123": {
                                "active_threads": {root_ts: {"latest_ts": root_ts}},
                                "latest_history_ts": root_ts,
                            }
                        }
                    }
                )
            )
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                replies_by_thread={root_ts: [{"ts": root_ts, "user": "U1", "text": "Old standalone"}]},
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, state_path, active_thread_hours=1)

            result = poller.poll_once("C123")

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 0)
            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"].get("active_threads"), {})


if __name__ == "__main__":
    unittest.main()
