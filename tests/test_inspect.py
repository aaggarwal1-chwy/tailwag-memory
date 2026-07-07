from datetime import datetime, timezone
from pathlib import Path
import unittest

from tests.helpers import RecordingQueryRunner
import tailwag_memory.inspect as inspect_tools
from tailwag_memory.inspect import (
    AffectScore,
    FoldEnsembleAffectProvider,
    MemoryItemInspectService,
    PersonEpisodeTranscriptService,
    PersonTimelineRetrievalService,
    memory_items_report,
    memory_items_report_html,
    person_timeline_report,
    person_timeline_report_html,
    recent_person_episode_rows,
)
from tailwag_memory.models import PersonTimelineItem, PersonTimelineTranscriptSnippet


class InspectPackageImportTest(unittest.TestCase):
    def test_inspect_package_exports_inspection_utilities(self) -> None:
        expected_exports = {
            "AffectScore",
            "AffectScoringConfigurationError",
            "AffectScoringProvider",
            "FoldEnsembleAffectProvider",
            "HuggingFaceXLMRobertaLargeAffectProvider",
            "InspectMemoryAddressedEpisode",
            "InspectMemoryItem",
            "InspectReport",
            "InspectTranscriptLine",
            "MemoryItemInspectService",
            "PersonEpisodeAffectPoint",
            "PersonEpisodeTranscriptPoint",
            "PersonEpisodeTranscriptService",
            "PersonTimelineRetrievalService",
            "affect_report",
            "affect_report_html",
            "memory_items_report",
            "memory_items_report_html",
            "person_timeline_report",
            "person_timeline_report_html",
            "recent_person_episode_rows",
            "report_json",
            "score_transcript_points",
        }

        self.assertEqual(set(inspect_tools.__all__), expected_exports)
        self.assertIs(inspect_tools.AffectScore, AffectScore)
        self.assertIs(inspect_tools.FoldEnsembleAffectProvider, FoldEnsembleAffectProvider)
        self.assertIs(inspect_tools.PersonEpisodeTranscriptService, PersonEpisodeTranscriptService)
        self.assertIs(inspect_tools.MemoryItemInspectService, MemoryItemInspectService)
        self.assertIs(inspect_tools.person_timeline_report, person_timeline_report)


class InspectTranscriptRowsTest(unittest.TestCase):
    def test_recent_person_episode_rows_fetches_bounded_participation_pairs(self) -> None:
        runner = RecordingQueryRunner(results=[[]])

        rows = recent_person_episode_rows(runner, 25)

        self.assertEqual(rows, [])
        self.assertEqual(runner.queries[0].parameters, {"limit": 25})
        self.assertIn("MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)", runner.queries[0].query)
        self.assertIn("OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)-[:SUPPORTED_BY]->(e)", runner.queries[0].query)
        self.assertIn("count(DISTINCT memory) AS memory_item_count", runner.queries[0].query)
        self.assertIn("memory_item_count AS memory_item_count", runner.queries[0].query)
        self.assertIn("person.id AS person_id", runner.queries[0].query)
        self.assertIn("e.id AS episode_id", runner.queries[0].query)
        self.assertIn("LIMIT $limit", runner.queries[0].query)
        upper_query = runner.queries[0].query.upper()
        for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
            self.assertNotIn(write_keyword, upper_query)


class PersonEpisodeTranscriptServiceTest(unittest.TestCase):
    def test_points_without_person_filter_uses_recent_participation_pairs(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "speaker_labels": ["person_jamie", "Jamie", "Assistant"],
                        "transcript": "Jamie: I felt good about the demo. Assistant: Great.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": "2026-06-16T14:05:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "speaker",
                        "source": "caller",
                        "memory_item_count": 2,
                    }
                ]
            ]
        )
        service = PersonEpisodeTranscriptService(runner)

        points = service.points(limit=10)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].person_id, "person_jamie")
        self.assertEqual(points[0].display_name, "Jamie")
        self.assertEqual(points[0].episode_id, "episode_1")
        self.assertEqual(points[0].text, "I felt good about the demo.")
        self.assertEqual(points[0].line_count, 1)
        self.assertEqual(points[0].building_code, "MAIN")
        self.assertEqual(points[0].room_id, "101")
        self.assertEqual(points[0].role, "speaker")
        self.assertEqual(points[0].source, "caller")
        self.assertTrue(points[0].has_memory_items)
        self.assertEqual(points[0].memory_item_count, 2)
        self.assertIn("MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)", runner.queries[0].query)

    def test_points_with_person_filter_uses_person_episode_query(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "item_id": "episode_1",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "speaker_labels": ["person_jamie", "Jamie", "Casey"],
                        "transcript": (
                            "[2026-06-16T14:00:00+00:00] Casey: Can someone review this?\n"
                            "[2026-06-16T14:05:00+00:00] Jamie: I already reviewed it."
                        ),
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": None,
                        "building_code": "SLACK",
                        "room_id": "C123",
                        "role": "speaker",
                        "source": "slack",
                    }
                ]
            ]
        )
        service = PersonEpisodeTranscriptService(runner)

        points = service.points(person_id=" person_jamie ", limit=3)

        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 3})
        self.assertIn("WHERE person.id = $person_id", runner.queries[0].query)
        self.assertIn("OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)-[:SUPPORTED_BY]->(e)", runner.queries[0].query)
        self.assertEqual(points[0].text, "I already reviewed it.")
        self.assertEqual(
            [(line.timestamp, line.speaker, line.text) for line in points[0].transcript_lines],
            [("2026-06-16T14:05:00+00:00", "Jamie", "I already reviewed it.")],
        )

    def test_points_skips_episodes_without_target_person_text(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "speaker_labels": ["person_jamie", "Jamie", "Assistant"],
                        "transcript": "Assistant: Jamie was not speaking.",
                    }
                ]
            ]
        )
        service = PersonEpisodeTranscriptService(runner)

        self.assertEqual(service.points(limit=5), [])


class MemoryItemInspectServiceTest(unittest.TestCase):
    def test_items_fetches_read_only_memory_item_rows_with_evidence(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_followup",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "kind": "followup",
                        "key": "demo",
                        "summary": "Ask Jamie about the demo.",
                        "source": "extractor",
                        "source_ref": "episode_1",
                        "status": "active",
                        "observed_at": "2026-07-01T10:00:00+00:00",
                        "due_at": "2026-07-02T10:00:00+00:00",
                        "expires_at": "2026-07-09T10:00:00+00:00",
                        "metadata_json": '{"topic": "demo"}',
                        "supported_episode_ids": ["episode_1", None, "episode_1"],
                        "addressed_by": [
                            {"episode_id": None},
                            {"episode_id": "episode_2", "addressed_at": "2026-07-03T10:00:00+00:00"},
                        ],
                        "superseded_by_memory_ids": [],
                        "supersedes_memory_ids": ["mem_old"],
                    }
                ]
            ]
        )

        items = MemoryItemInspectService(runner).items(
            person_id=" person_jamie ",
            limit=5,
        )

        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 5})
        self.assertIn("MATCH (person:Person)-[:HAS_MEMORY]->(memory:MemoryItem)", runner.queries[0].query)
        self.assertIn("OPTIONAL MATCH (memory)-[:SUPPORTED_BY]->(support:Episode)", runner.queries[0].query)
        self.assertIn("OPTIONAL MATCH (memory)-[addressed:ADDRESSED_BY]->(addressed_episode:Episode)", runner.queries[0].query)
        self.assertIn("OPTIONAL MATCH (memory)-[:SUPERSEDED_BY]->(replacement:MemoryItem)", runner.queries[0].query)
        upper_query = runner.queries[0].query.upper()
        for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
            self.assertNotIn(write_keyword, upper_query)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].memory_id, "mem_followup")
        self.assertEqual(items[0].metadata, {"topic": "demo"})
        self.assertEqual(items[0].supported_episode_ids, ["episode_1"])
        self.assertEqual(items[0].addressed_by[0].episode_id, "episode_2")
        self.assertEqual(items[0].supersedes_memory_ids, ["mem_old"])
        self.assertEqual(items[0].followup_state, "addressed")

    def test_items_marks_active_followups_with_invalid_timing(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_missing_expiry",
                        "person_id": "person_jamie",
                        "kind": "followup",
                        "key": "missing_expiry",
                        "summary": "Ask Jamie about the demo.",
                        "source": "extractor",
                        "status": "active",
                        "due_at": "2026-07-01T10:00:00+00:00",
                        "expires_at": "",
                        "metadata_json": "",
                        "supported_episode_ids": [],
                        "addressed_by": [],
                        "superseded_by_memory_ids": [],
                        "supersedes_memory_ids": [],
                    },
                    {
                        "memory_id": "mem_bad_due",
                        "person_id": "person_jamie",
                        "kind": "followup",
                        "key": "bad_due",
                        "summary": "Ask Jamie about the launch.",
                        "source": "extractor",
                        "status": "active",
                        "due_at": "not-a-date",
                        "expires_at": "2026-07-09T10:00:00+00:00",
                        "metadata_json": "",
                        "supported_episode_ids": [],
                        "addressed_by": [],
                        "superseded_by_memory_ids": [],
                        "supersedes_memory_ids": [],
                    },
                    {
                        "memory_id": "mem_inverted_window",
                        "person_id": "person_jamie",
                        "kind": "followup",
                        "key": "inverted_window",
                        "summary": "Ask Jamie about the patch.",
                        "source": "extractor",
                        "status": "active",
                        "due_at": "2026-07-10T10:00:00+00:00",
                        "expires_at": "2026-07-09T10:00:00+00:00",
                        "metadata_json": "",
                        "supported_episode_ids": [],
                        "addressed_by": [],
                        "superseded_by_memory_ids": [],
                        "supersedes_memory_ids": [],
                    },
                ]
            ]
        )

        items = MemoryItemInspectService(runner).items(now=datetime(2026, 7, 7, tzinfo=timezone.utc))

        self.assertEqual([item.followup_state for item in items], ["invalid", "invalid", "invalid"])

    def test_memory_items_report_includes_distributions_and_html_hash_support(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_preference",
                        "person_id": "person_jamie",
                        "display_name": "<Jamie>",
                        "kind": "preference",
                        "key": "snacks",
                        "summary": "<script>alert(1)</script>",
                        "source": "caller",
                        "status": "active",
                        "metadata_json": "",
                        "supported_episode_ids": [],
                        "addressed_by": [],
                        "superseded_by_memory_ids": [],
                        "supersedes_memory_ids": [],
                    },
                    {
                        "memory_id": "mem_followup",
                        "person_id": "person_jamie",
                        "display_name": "<Jamie>",
                        "kind": "followup",
                        "key": "demo",
                        "summary": "Ask Jamie about the demo.",
                        "source": "extractor",
                        "status": "active",
                        "due_at": "2026-07-01T10:00:00+00:00",
                        "expires_at": "2026-07-09T10:00:00+00:00",
                        "metadata_json": "",
                        "supported_episode_ids": ["episode_1"],
                        "addressed_by": [],
                        "superseded_by_memory_ids": [],
                        "supersedes_memory_ids": [],
                    },
                ]
            ]
        )
        items = MemoryItemInspectService(runner).items(
            limit=10,
            now=datetime(2026, 7, 7, tzinfo=timezone.utc),
        )

        report = memory_items_report(items, person_id=None, limit=10, generated_at="2026-07-07T12:00:00+00:00")
        html = memory_items_report_html(report)

        self.assertEqual(report.title, "Tailwag Memory Items")
        self.assertEqual(report.metadata["storage"], "read_only")
        self.assertEqual(report.metadata["distributions"]["kind"], {"preference": 1, "followup": 1})
        self.assertEqual(report.metadata["distributions"]["person"], {"person_jamie": 2})
        self.assertEqual(report.metadata["distributions"]["followup_state"]["visible_now"], 1)
        self.assertIn("Follow-Up State", html)
        self.assertIn("tailwag-memory-items.html", html)
        self.assertIn("tailwag-person-timeline.html", html)
        self.assertIn("tailwag-affect.html", html)
        self.assertIn("hashPerson()", html)
        self.assertIn("window.addEventListener('hashchange', render)", html)
        self.assertIn("#person=", html)
        self.assertIn("\\u003cscript>alert(1)\\u003c/script>", html)


class PersonTimelineRetrievalServiceTest(unittest.TestCase):
    def test_items_combines_episode_and_event_rows_with_target_person_snippets(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "episode_id": "episode_1",
                        "event_id": None,
                        "text": "Jamie: I shipped the patch. Casey: Thanks.",
                        "transcript": "Jamie: I shipped the patch. Casey: Thanks.",
                        "speaker_labels": ["Jamie", "Casey"],
                        "start_time": "2026-07-07T14:00:00+00:00",
                        "end_time": "2026-07-07T14:05:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "speaker",
                        "source": "caller",
                    }
                ],
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "item_id": "event_1",
                        "item_type": "event",
                        "episode_id": None,
                        "event_id": "event_1",
                        "text": "Design review",
                        "transcript": None,
                        "speaker_labels": [],
                        "start_time": "2026-07-07T15:00:00+00:00",
                        "end_time": "2026-07-07T16:00:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "accepted",
                        "source": "calendar",
                    }
                ],
            ]
        )
        service = PersonTimelineRetrievalService(runner)

        items = service.items(limit=5)

        self.assertEqual([item.item_id for item in items], ["event_1", "episode_1"])
        episode = items[1]
        self.assertEqual(episode.episode_id, "episode_1")
        self.assertIsNone(episode.event_id)
        self.assertEqual(episode.text, "I shipped the patch.")
        self.assertEqual(
            [(line.timestamp, line.speaker, line.text) for line in episode.transcript_snippets],
            [("", "Jamie", "I shipped the patch.")],
        )
        event = items[0]
        self.assertEqual(event.event_id, "event_1")
        self.assertEqual(event.text, "Design review")
        self.assertEqual(runner.queries[0].parameters, {"person_id": None, "limit": 5})
        self.assertEqual(runner.queries[1].parameters, {"person_id": None, "limit": 5})
        self.assertIn("MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)", runner.queries[0].query)
        self.assertIn("WHERE ($person_id IS NULL OR person.id = $person_id)", runner.queries[0].query)
        self.assertIn("type(r) = 'ATTENDED'", runner.queries[1].query)
        for query in runner.queries:
            upper_query = query.query.upper()
            for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
                self.assertNotIn(write_keyword, upper_query)

    def test_items_applies_person_filter_to_both_read_queries(self) -> None:
        runner = RecordingQueryRunner(results=[[], []])
        service = PersonTimelineRetrievalService(runner)

        self.assertEqual(service.items(person_id=" person_jamie ", limit=3), [])

        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 3})
        self.assertEqual(runner.queries[1].parameters, {"person_id": "person_jamie", "limit": 3})
        self.assertIn("person.id = $person_id", runner.queries[0].query)
        self.assertIn("person.id = $person_id", runner.queries[1].query)


class PersonTimelineReportTest(unittest.TestCase):
    def test_person_timeline_report_html_has_nav_and_hash_person_filter(self) -> None:
        report = person_timeline_report(
            [
                PersonTimelineItem(
                    person_id="person_jamie",
                    display_name="<Jamie>",
                    item_id="episode_1",
                    item_type="episode",
                    episode_id="episode_1",
                    start_time="2026-07-07T14:00:00+00:00",
                    text="<script>alert(1)</script>",
                    transcript_snippets=[
                        PersonTimelineTranscriptSnippet(
                            timestamp="2026-07-07T14:00:00+00:00",
                            speaker="<Jamie>",
                            text="I shipped it.",
                        )
                    ],
                )
            ],
            filters={"person_id": None, "limit": 10},
            metadata={"utility": "inspect person-timeline"},
        )

        html = person_timeline_report_html(report)

        self.assertIn("Tailwag Person Timeline", html)
        self.assertIn("tailwag-person-timeline.html", html)
        self.assertIn("tailwag-affect.html", html)
        self.assertIn("tailwag-memory-items.html", html)
        self.assertIn("new URLSearchParams(location.hash.slice(1))", html)
        self.assertIn("params.get('person')", html)
        self.assertIn("location.hash = `person=${encodeURIComponent(personId)}`", html)
        self.assertIn('"person_id": "person_jamie"', html)
        self.assertIn("\\u003cscript>alert(1)\\u003c/script>", html)


class InspectPlaceholderFilesTest(unittest.TestCase):
    def test_committed_inspect_placeholders_use_canonical_names(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inspect_dir = root / "inspect"
        expected = [
            "index.html",
            "tailwag-affect.html",
            "tailwag-person-timeline.html",
            "tailwag-memory-items.html",
        ]

        for filename in expected:
            html = (inspect_dir / filename).read_text()
            self.assertIn("tailwag-affect.html", html)
            self.assertIn("tailwag-person-timeline.html", html)
            self.assertIn("tailwag-memory-items.html", html)
            if filename != "index.html":
                self.assertIn("No Generated Data Yet", html)


if __name__ == "__main__":
    unittest.main()
