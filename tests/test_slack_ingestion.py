from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import typing
import unittest

from tailwag_memory.slack_ingestion import (
    SlackChannelState,
    SlackFilePollStateStore,
    SlackMemoryPoller,
    SlackPollStateConflict,
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
        history_error: Exception | None = None,
        replies_error: Exception | None = None,
    ) -> None:
        self.history_messages = history_messages or []
        self.replies_by_thread = replies_by_thread or {}
        self.user_names = user_names or {}
        self.user_emails = user_emails or {}
        self.history_error = history_error
        self.replies_error = replies_error
        self.history_calls: list[dict] = []
        self.reply_calls: list[dict] = []

    def history(self, channel: str, oldest: str | None, limit: int) -> list[dict]:
        self.history_calls.append({"channel": channel, "oldest": oldest, "limit": limit})
        if self.history_error is not None:
            raise self.history_error
        return self.history_messages

    def replies(self, channel: str, thread_ts: str, limit: int) -> list[dict]:
        self.reply_calls.append({"channel": channel, "thread_ts": thread_ts, "limit": limit})
        if self.replies_error is not None:
            raise self.replies_error
        return self.replies_by_thread.get(thread_ts, [])

    def user_profile(self, user_id: str) -> SlackUserProfile:
        return SlackUserProfile(
            display_name=self.user_names.get(user_id),
            email=self.user_emails.get(user_id),
        )


class FakeEpisodeRecorder:
    def __init__(
        self,
        *,
        fail: bool = False,
        memory_errors: list[dict[str, str]] | None = None,
        canonical_ids_by_email: dict[str, str] | None = None,
    ) -> None:
        self.fail = fail
        self.memory_errors = memory_errors or []
        self.canonical_ids_by_email = canonical_ids_by_email or {}
        self.episodes = []
        self.record_calls = []
        self.canonical_lookup_calls: list[str] = []

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

    def canonical_person_id_by_email(self, email: str) -> str | None:
        self.canonical_lookup_calls.append(email)
        return self.canonical_ids_by_email.get(email)


class FakeStateStore:
    def __init__(self, states: dict[str, SlackChannelState] | None = None, *, fail_on_save: bool = False) -> None:
        self.states = states or {}
        self.fail_on_save = fail_on_save
        self.load_calls: list[str] = []
        self.save_calls: list[dict] = []

    def load_channel(self, channel: str) -> SlackChannelState:
        self.load_calls.append(channel)
        state = self.states.get(channel, SlackChannelState())
        return SlackChannelState(
            latest_history_ts=state.latest_history_ts,
            active_threads={thread_ts: dict(thread_state) for thread_ts, thread_state in state.active_threads.items()},
            version=state.version,
        )

    def save_channel(self, channel: str, state: SlackChannelState, expected_version: object | None) -> None:
        self.save_calls.append(
            {
                "channel": channel,
                "latest_history_ts": state.latest_history_ts,
                "active_threads": {thread_ts: dict(thread_state) for thread_ts, thread_state in state.active_threads.items()},
                "expected_version": expected_version,
            }
        )
        if self.fail_on_save:
            raise SlackPollStateConflict(f"Slack poll state changed for channel {channel}.")
        self.states[channel] = SlackChannelState(
            latest_history_ts=state.latest_history_ts,
            active_threads={thread_ts: dict(thread_state) for thread_ts, thread_state in state.active_threads.items()},
            version="saved",
        )


class SlackThreadConversionTest(unittest.TestCase):
    def test_thread_becomes_episode_with_slack_people_and_virtual_place(self) -> None:
        type_hints = typing.get_type_hints(build_episode_from_slack_thread)
        self.assertIn("client", type_hints)

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
        self.assertEqual(episode.place.building_code, "SLACK")
        self.assertEqual(episode.place.room_id, "C123")
        self.assertEqual([person.id for person in episode.participants], ["slack:U1", "slack:U2"])
        self.assertEqual([person.display_name for person in episode.participants], ["Asha", "Ben"])
        self.assertIsNone(episode.participants[0].email)
        self.assertFalse(hasattr(episode.participants[0], "face_embedding"))
        self.assertFalse(hasattr(episode.participants[0], "audio_embedding"))
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

    def test_thread_uses_canonical_person_id_when_email_resolves(self) -> None:
        root_ts = _ts()
        client = FakeSlackClient(
            user_names={"U1": "Asha"},
            user_emails={"U1": "Asha.Example@Example.COM"},
        )
        lookup_calls: list[str] = []

        def resolve_person_id(email: str) -> str | None:
            lookup_calls.append(email)
            return {"asha.example@example.com": "person_asha"}.get(email)

        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[{"ts": root_ts, "user": "U1", "text": "Can someone review the deck?"}],
            client=client,
            person_id_resolver=resolve_person_id,
        )

        self.assertEqual(episode.participants[0].id, "person_asha")
        self.assertIsNone(episode.participants[0].display_name)
        self.assertIsNone(episode.participants[0].email)
        self.assertIn("Asha: Can someone review the deck?", episode.transcript)
        self.assertEqual(lookup_calls, ["asha.example@example.com"])

    def test_thread_keeps_slack_person_id_when_email_does_not_resolve(self) -> None:
        root_ts = _ts()
        client = FakeSlackClient(
            user_names={"U1": "Asha"},
            user_emails={"U1": "asha.example@example.com"},
        )

        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[{"ts": root_ts, "user": "U1", "text": "Can someone review the deck?"}],
            client=client,
            person_id_resolver=lambda _email: None,
        )

        self.assertEqual(episode.participants[0].id, "slack:U1")
        self.assertEqual(episode.participants[0].display_name, "Asha")
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

        self.assertIn("Asha: Can @Ben and @Chandra review this?", episode.transcript)
        self.assertIn("Ben: Looping @Chandra in.", episode.transcript)
        self.assertEqual([person.id for person in episode.participants], ["slack:U1", "slack:U2"])
        self.assertEqual([mention.person.id for mention in episode.mentioned_people], ["slack:U2", "slack:U3"])
        self.assertEqual([mention.person.role for mention in episode.mentioned_people], ["mentioned", "mentioned"])
        self.assertEqual([mention.source for mention in episode.mentioned_people], ["slack", "slack"])

    def test_thread_uses_canonical_person_id_for_mentions_when_email_resolves(self) -> None:
        root_ts = _ts()
        client = FakeSlackClient(
            user_names={"U1": "Asha", "U3": "Chandra"},
            user_emails={"U3": "Chandra.Example@Example.COM"},
        )
        lookup_calls: list[str] = []

        def resolve_person_id(email: str) -> str | None:
            lookup_calls.append(email)
            return {"chandra.example@example.com": "person_chandra"}.get(email)

        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[{"ts": root_ts, "user": "U1", "text": "Can <@U3|fallback> review this?"}],
            client=client,
            person_id_resolver=resolve_person_id,
        )

        mention = episode.mentioned_people[0]
        self.assertEqual(mention.person.id, "person_chandra")
        self.assertIsNone(mention.person.display_name)
        self.assertIsNone(mention.person.email)
        self.assertEqual(mention.person.source, "slack")
        self.assertEqual(mention.source, "slack")
        self.assertIn("Asha: Can @Chandra review this?", episode.transcript)
        self.assertEqual(lookup_calls, ["chandra.example@example.com"])

    def test_thread_mention_fallback_label_does_not_define_identity(self) -> None:
        root_ts = _ts()
        client = FakeSlackClient(user_names={"U1": "Asha"})
        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[{"ts": root_ts, "user": "U1", "text": "Can <@U9|fallback-name> review this?"}],
            client=client,
        )

        mention = episode.mentioned_people[0]
        self.assertEqual(mention.person.id, "slack:U9")
        self.assertEqual(mention.person.display_name, "slack:U9")
        self.assertIn("Asha: Can @fallback-name review this?", episode.transcript)

    def test_thread_formats_slack_channel_special_link_and_mail_entities(self) -> None:
        root_ts = _ts()
        client = FakeSlackClient(user_names={"U1": "Asha"})
        episode = build_episode_from_slack_thread(
            channel="C123",
            messages=[
                {
                    "ts": root_ts,
                    "user": "U1",
                    "text": "See <#C999|proj-alpha>, <!here>, <https://example.com/brief?x=1&amp;y=2|the brief>, and <mailto:asha@example.com|Asha>.",
                }
            ],
            client=client,
        )

        self.assertIn("Asha: See #proj-alpha, @here, the brief, and Asha.", episode.transcript)


class SlackWebApiClientTest(unittest.TestCase):
    def test_user_profile_omits_email_by_default(self) -> None:
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
        client.include_email = False

        profile = client.user_profile("U1")
        cached_profile = client.user_profile("U1")

        self.assertEqual(profile, SlackUserProfile(display_name="Asha", email=None))
        self.assertEqual(cached_profile, profile)
        self.assertEqual(fake_web_client.calls, 1)

    def test_user_profile_reads_email_when_enabled(self) -> None:
        class FakeWebClient:
            def users_info(self, user: str) -> dict:
                return {
                    "user": {
                        "profile": {
                            "display_name": "Asha",
                            "email": " Asha.Example@Example.COM ",
                        }
                    }
                }

        client = SlackWebApiClient.__new__(SlackWebApiClient)
        client._client = FakeWebClient()
        client._user_cache = {}
        client.include_email = True

        self.assertEqual(client.user_profile("U1"), SlackUserProfile(display_name="Asha", email="asha.example@example.com"))

    def test_history_fetches_all_pages_using_limit_as_page_size(self) -> None:
        class FakeWebClient:
            def __init__(self) -> None:
                self.calls = []

            def conversations_history(self, **params) -> dict:
                self.calls.append(params)
                if "cursor" not in params:
                    return {"messages": [{"ts": "2.0"}], "has_more": True, "response_metadata": {"next_cursor": "next"}}
                return {"messages": [{"ts": "1.0"}], "has_more": False, "response_metadata": {}}

        fake = FakeWebClient()
        client = SlackWebApiClient.__new__(SlackWebApiClient)
        client._client = fake
        client._user_cache = {}
        client.include_email = False

        messages = client.history("C123", oldest="0.0", limit=1)

        self.assertEqual([message["ts"] for message in messages], ["2.0", "1.0"])
        self.assertEqual([call["limit"] for call in fake.calls], [1, 1])
        self.assertEqual(fake.calls[1]["cursor"], "next")

    def test_replies_fetches_all_pages_using_limit_as_page_size(self) -> None:
        class FakeWebClient:
            def __init__(self) -> None:
                self.calls = []

            def conversations_replies(self, **params) -> dict:
                self.calls.append(params)
                if "cursor" not in params:
                    return {"messages": [{"ts": "1.0"}], "has_more": True, "response_metadata": {"next_cursor": "next"}}
                return {"messages": [{"ts": "2.0"}], "has_more": False, "response_metadata": {}}

        fake = FakeWebClient()
        client = SlackWebApiClient.__new__(SlackWebApiClient)
        client._client = fake
        client._user_cache = {}
        client.include_email = False

        messages = client.replies("C123", thread_ts="1.0", limit=1)

        self.assertEqual([message["ts"] for message in messages], ["1.0", "2.0"])
        self.assertEqual([call["limit"] for call in fake.calls], [1, 1])
        self.assertEqual(fake.calls[1]["cursor"], "next")


class SlackMemoryPollerTest(unittest.TestCase):
    def test_poller_uses_recorder_canonical_resolver_unless_explicitly_overridden(self) -> None:
        recorder = FakeEpisodeRecorder(
            canonical_ids_by_email={"jamie@example.com": "person_jamie"},
        )
        state_store = SlackFilePollStateStore(Path("unused.json"))
        automatic = SlackMemoryPoller(FakeSlackClient(), recorder, state_store)

        self.assertEqual(automatic.person_id_resolver("jamie@example.com"), "person_jamie")
        self.assertEqual(recorder.canonical_lookup_calls, ["jamie@example.com"])

        explicit_calls: list[str] = []

        def explicit_resolver(email: str) -> str:
            explicit_calls.append(email)
            return "person_explicit"

        explicit = SlackMemoryPoller(
            FakeSlackClient(),
            recorder,
            state_store,
            person_id_resolver=explicit_resolver,
        )
        self.assertEqual(explicit.person_id_resolver("other@example.com"), "person_explicit")
        self.assertEqual(explicit_calls, ["other@example.com"])
        self.assertEqual(recorder.canonical_lookup_calls, ["jamie@example.com"])

    def test_enqueue_memory_extraction_true_is_omitted_and_false_is_forwarded(self) -> None:
        class KeywordRecordingEpisodeRecorder:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def record_episode(self, episode, *, extract_memory: bool = True, **kwargs):
                self.calls.append({"extract_memory": extract_memory, **kwargs})
                return EpisodeRecordResult(episode_id=episode.id)

        root_ts = _ts()
        client = FakeSlackClient(
            history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
            user_names={"U1": "Asha"},
        )
        recorder = KeywordRecordingEpisodeRecorder()

        SlackMemoryPoller(client, recorder, FakeStateStore()).poll_once("C123", backfill_hours=1)
        SlackMemoryPoller(client, recorder, FakeStateStore()).poll_once(
            "C456",
            backfill_hours=1,
            enqueue_memory_extraction=False,
        )

        self.assertEqual(
            recorder.calls,
            [
                {"extract_memory": True},
                {"extract_memory": True, "enqueue_memory_extraction": False},
            ],
        )

    def test_corrupt_state_file_fails_before_slack_or_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            state_path.write_text("{not json")
            service = FakeEpisodeRecorder()
            client = FakeSlackClient()
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                poller.poll_once("C123", backfill_hours=1)

            self.assertEqual(client.history_calls, [])
            self.assertEqual(service.episodes, [])

    def test_first_poll_without_backfill_arms_state_without_ingesting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            service = FakeEpisodeRecorder()
            client = FakeSlackClient()
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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

    def test_poll_once_uses_injected_state_store_without_filesystem_state(self) -> None:
        root_ts = _ts()
        store = FakeStateStore()
        service = FakeEpisodeRecorder()
        client = FakeSlackClient(
            history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
            user_names={"U1": "Asha"},
        )
        poller = SlackMemoryPoller(client, service, store)

        result = poller.poll_once("C123", backfill_hours=1)

        self.assertEqual(result.ingested_episode_ids, [f"slack:C123:{root_ts}"])
        self.assertEqual(store.load_calls, ["C123"])
        self.assertEqual(len(store.save_calls), 1)
        self.assertEqual(store.save_calls[0]["channel"], "C123")
        self.assertEqual(store.save_calls[0]["latest_history_ts"], root_ts)
        self.assertEqual(store.save_calls[0]["active_threads"], {root_ts: {"latest_ts": root_ts}})
        self.assertIsNone(store.save_calls[0]["expected_version"])

    def test_state_store_conflict_is_reported_on_save(self) -> None:
        root_ts = _ts()
        store = FakeStateStore(fail_on_save=True)
        service = FakeEpisodeRecorder()
        client = FakeSlackClient(
            history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
            user_names={"U1": "Asha"},
        )
        poller = SlackMemoryPoller(client, service, store)

        with self.assertRaisesRegex(SlackPollStateConflict, "C123"):
            poller.poll_once("C123", backfill_hours=1)

        self.assertEqual(len(store.save_calls), 1)
        self.assertEqual(service.episodes[0].id, f"slack:C123:{root_ts}")

    def test_backfill_can_skip_memory_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[{"ts": root_ts, "user": "U1", "text": "Start thread"}],
                user_names={"U1": "Asha"},
            )
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))
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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))
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
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path), active_thread_hours=1)

            result = poller.poll_once("C123")

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 0)
            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"].get("active_threads"), {})

    def test_slack_history_api_error_does_not_advance_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(history_error=RuntimeError("slack api unavailable"))
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

            with self.assertRaisesRegex(RuntimeError, "slack api unavailable"):
                poller.poll_once("C123", backfill_hours=1)

            self.assertFalse(state_path.exists())
            self.assertEqual(service.episodes, [])

    def test_slack_reply_rate_limit_does_not_advance_state(self) -> None:
        class RateLimitedSlackError(Exception):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            original_state = {
                "channels": {
                    "C123": {
                        "active_threads": {root_ts: {"latest_ts": root_ts}},
                        "latest_history_ts": root_ts,
                    }
                }
            }
            state_path.write_text(json.dumps(original_state))
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(replies_error=RateLimitedSlackError("rate_limited"))
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

            with self.assertRaisesRegex(RateLimitedSlackError, "rate_limited"):
                poller.poll_once("C123")

            self.assertEqual(json.loads(state_path.read_text()), original_state)
            self.assertEqual(service.episodes, [])

    def test_bot_and_file_only_messages_are_skipped_but_edited_user_messages_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            root_ts = _ts()
            bot_ts = _ts(1)
            file_ts = _ts(2)
            service = FakeEpisodeRecorder()
            client = FakeSlackClient(
                history_messages=[
                    {"ts": bot_ts, "user": "Ubot", "bot_id": "B123", "subtype": "bot_message", "text": "system update"},
                    {"ts": file_ts, "user": "U2", "text": "", "files": [{"id": "F1", "name": "brief.pdf"}]},
                    {"ts": root_ts, "user": "U1", "text": "Edited plan is ready.", "edited": {"user": "U1", "ts": _ts(3)}},
                ],
                user_names={"U1": "Asha", "U2": "Ben", "Ubot": "Build Bot"},
            )
            poller = SlackMemoryPoller(client, service, SlackFilePollStateStore(state_path))

            result = poller.poll_once("C123", backfill_hours=1)

            self.assertEqual(result.checked_threads, 1)
            self.assertEqual(result.ingested_threads, 1)
            self.assertEqual(service.episodes[0].id, f"slack:C123:{root_ts}")
            self.assertIn("Asha: Edited plan is ready.", service.episodes[0].transcript)
            self.assertNotIn("system update", service.episodes[0].transcript)
            self.assertNotIn("brief.pdf", service.episodes[0].transcript)

    def test_stale_state_handles_preserve_other_channel_cursor_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            state_path.write_text(json.dumps({"metadata": {"owner": "tailwag"}}))
            store = SlackFilePollStateStore(state_path)
            first = store.load_channel("C123")
            second = store.load_channel("C999")

            first.latest_history_ts = "100.000000"
            store.save_channel("C123", first, first.version)
            second.latest_history_ts = "200.000000"
            store.save_channel("C999", second, second.version)

            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"]["latest_history_ts"], "100.000000")
            self.assertEqual(state["channels"]["C999"]["latest_history_ts"], "200.000000")
            self.assertEqual(state["metadata"], {"owner": "tailwag"})

    def test_stale_same_channel_file_state_raises_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "slack-state.json"
            store = SlackFilePollStateStore(state_path)
            first = store.load_channel("C123")
            second = store.load_channel("C123")

            first.latest_history_ts = "100.000000"
            store.save_channel("C123", first, first.version)
            second.latest_history_ts = "200.000000"

            with self.assertRaisesRegex(SlackPollStateConflict, "C123"):
                store.save_channel("C123", second, second.version)

            state = json.loads(state_path.read_text())
            self.assertEqual(state["channels"]["C123"]["latest_history_ts"], "100.000000")


if __name__ == "__main__":
    unittest.main()
