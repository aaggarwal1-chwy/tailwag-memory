from datetime import datetime, timezone
from pathlib import Path
import unittest

from tests.helpers import RecordingQueryRunner
import tailwag_memory.inspect as inspect_tools
from tailwag_memory.inspect import (
    AffectScore,
    FoldEnsembleAffectProvider,
    FollowupValidityInspectService,
    followup_validity_report,
    followup_validity_report_html,
    InspectRelatedMemoryItem,
    MemoryItemInspectService,
    PersonEpisodeAffectPoint,
    PersonEpisodeTranscriptService,
    PersonEpisodeTranscriptPoint,
    PersonTimelineRetrievalService,
    affect_report,
    affect_report_html,
    memory_items_report,
    memory_items_report_html,
    person_timeline_report,
    person_timeline_report_html,
    recent_person_episode_rows,
)
from tailwag_memory.inspect.html_utils import INSPECT_CSS_FILENAME, INSPECT_JS_FILENAME, inspect_asset_text
from tailwag_memory.inspect.models import InspectReport as ModelInspectReport
from tailwag_memory.inspect.reports import InspectReport as ReportsInspectReport
from tailwag_memory.models import PersonTimelineItem, PersonTimelineTranscriptSnippet


def _assert_canonical_nav(testcase: unittest.TestCase, html: str, current_href: str | None = None) -> None:
    """Assert inspect reports render the canonical nav order."""
    followup_index = html.index('href="tailwag-followup-validity.html"')
    affect_index = html.index('href="tailwag-affect.html"')
    timeline_index = html.index('href="tailwag-person-timeline.html"')
    memory_index = html.index('href="tailwag-memory-items.html"')
    testcase.assertLess(followup_index, affect_index)
    testcase.assertLess(affect_index, timeline_index)
    testcase.assertLess(timeline_index, memory_index)
    if current_href is not None:
        testcase.assertIn(f'href="{current_href}" aria-current="page"', html)


def _assert_css_rule_contains(
    testcase: unittest.TestCase,
    html: str,
    selector: str,
    declarations: list[str],
) -> None:
    """Assert the first rendered CSS rule for a selector includes declarations."""
    rule_start = html.index(f"{selector} {{")
    rule_end = html.index("}", rule_start)
    rule = html[rule_start:rule_end]
    for declaration in declarations:
        testcase.assertIn(declaration, rule)


class InspectPackageImportTest(unittest.TestCase):
    def test_inspect_package_exports_inspection_utilities(self) -> None:
        expected_exports = {
            "AffectScore",
            "AffectScoringConfigurationError",
            "AffectScoringProvider",
            "FoldEnsembleAffectProvider",
            "FollowupValidityInspectService",
            "HuggingFaceXLMRobertaLargeAffectProvider",
            "InspectFollowupValidityItem",
            "InspectMemoryAddressedEpisode",
            "InspectMemoryItem",
            "InspectRelatedMemoryItem",
            "InspectSankeyLink",
            "InspectReport",
            "InspectTranscriptLine",
            "MemoryItemInspectService",
            "PersonEpisodeAffectPoint",
            "PersonEpisodeTranscriptPoint",
            "PersonEpisodeTranscriptService",
            "PersonTimelineRetrievalService",
            "affect_report",
            "affect_report_html",
            "followup_validity_report",
            "followup_validity_report_html",
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
        self.assertIs(inspect_tools.FollowupValidityInspectService, FollowupValidityInspectService)
        self.assertIs(inspect_tools.PersonEpisodeTranscriptService, PersonEpisodeTranscriptService)
        self.assertIs(inspect_tools.MemoryItemInspectService, MemoryItemInspectService)
        self.assertIs(inspect_tools.person_timeline_report, person_timeline_report)

    def test_inspect_report_preserves_legacy_and_model_import_paths(self) -> None:
        self.assertIs(inspect_tools.InspectReport, ModelInspectReport)
        self.assertIs(ReportsInspectReport, ModelInspectReport)


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
        self.assertIn("related_memory_items AS related_memory_items", runner.queries[0].query)
        self.assertIn("person.id AS person_id", runner.queries[0].query)
        self.assertIn("e.id AS episode_id", runner.queries[0].query)
        self.assertIn("LIMIT $limit", runner.queries[0].query)
        upper_query = runner.queries[0].query.upper()
        for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
            self.assertNotIn(write_keyword, upper_query)


class InspectNavigationTest(unittest.TestCase):
    def test_affect_report_uses_canonical_nav_order(self) -> None:
        html = affect_report_html(affect_report([]))

        _assert_canonical_nav(self, html, "tailwag-affect.html")

    def test_affect_report_detail_includes_related_memory_item_summaries(self) -> None:
        report = affect_report(
            [
                PersonEpisodeAffectPoint(
                    transcript=PersonEpisodeTranscriptPoint(
                        person_id="person_jamie",
                        display_name="Jamie",
                        episode_id="episode_1",
                        text="I like concise demos.",
                        line_count=1,
                        has_memory_items=True,
                        memory_item_count=1,
                        related_memory_items=[
                            InspectRelatedMemoryItem(
                                memory_id="mem_demo",
                                kind="preference",
                                status="active",
                                summary="<Jamie likes concise demos>",
                            )
                        ],
                    ),
                    valence=0.75,
                    arousal=0.35,
                )
            ]
        )

        html = affect_report_html(report)

        self.assertIn("Related memory items", html)
        self.assertIn("tailwag-person-timeline.html", html)
        self.assertIn("tailwag-memory-items.html", html)
        self.assertIn("\\u003cJamie likes concise demos>", html)


class FollowupValidityInspectServiceTest(unittest.TestCase):
    def test_items_fetches_followups_and_groups_by_validity_duration(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_expired",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "summary": "Ask Jamie about the launch.",
                        "status": "active",
                        "observed_at": "2026-07-01T10:00:00+00:00",
                        "created_at": "",
                        "updated_at": "",
                        "due_at": "2026-07-01T10:00:00+00:00",
                        "expires_at": "2026-07-02T10:00:00+00:00",
                        "addressed_count": 0,
                        "superseded_count": 0,
                    },
                    {
                        "memory_id": "mem_visible",
                        "person_id": "person_casey",
                        "display_name": "Casey",
                        "summary": "Ask Casey about the demo.",
                        "status": "active",
                        "observed_at": "2026-07-01T10:00:00+00:00",
                        "created_at": "",
                        "updated_at": "",
                        "due_at": "2026-07-08T10:00:00+00:00",
                        "expires_at": "2026-07-15T10:00:00+00:00",
                        "addressed_count": 0,
                        "superseded_count": 0,
                    },
                    {
                        "memory_id": "mem_future",
                        "person_id": "person_lee",
                        "display_name": "Lee",
                        "summary": "Ask Lee next month.",
                        "status": "active",
                        "observed_at": "2026-07-01T10:00:00+00:00",
                        "created_at": "",
                        "updated_at": "",
                        "due_at": "2026-08-01T10:00:00+00:00",
                        "expires_at": "2026-08-20T10:00:00+00:00",
                        "addressed_count": 0,
                        "superseded_count": 0,
                    },
                ]
            ]
        )

        items = FollowupValidityInspectService(runner).items(
            limit=10,
            now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(runner.queries[0].parameters, {"limit": 10})
        self.assertIn("WHERE memory.kind = 'followup'", runner.queries[0].query)
        self.assertIn("ADDRESSED_BY", runner.queries[0].query)
        self.assertIn("SUPERSEDED_BY", runner.queries[0].query)
        upper_query = runner.queries[0].query.upper()
        for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
            self.assertNotIn(write_keyword, upper_query)
        self.assertEqual([item.followup_state for item in items], ["expired_active", "visible_now", "not_yet_due"])
        self.assertEqual([item.validity_bucket for item in items], ["1_to_3_days", "4_to_7_days", "15_to_30_days"])

    def test_followup_validity_report_html_groups_all_followup_states_together(self) -> None:
        items = FollowupValidityInspectService(
            RecordingQueryRunner(results=[
                [
                    {
                        "memory_id": "mem_visible",
                        "person_id": "person_jamie",
                        "display_name": "<Jamie>",
                        "summary": "<script>alert(1)</script>",
                        "status": "active",
                        "observed_at": "2026-07-01T10:00:00+00:00",
                        "due_at": "2026-07-08T10:00:00+00:00",
                        "expires_at": "2026-07-15T10:00:00+00:00",
                        "addressed_count": 0,
                        "superseded_count": 0,
                    }
                ]
            ])
        ).items(now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))

        report = followup_validity_report(items, limit=10, generated_at="2026-07-08T12:00:00+00:00")
        html = followup_validity_report_html(report)

        self.assertEqual(report.title, "Follow-Up Validity")
        self.assertEqual(report.metadata["distributions"]["validity_bucket"], {"4_to_7_days": 1})
        self.assertEqual(report.metadata["distributions"]["followup_state"], {"visible_now": 1})
        _assert_canonical_nav(self, html, "tailwag-followup-validity.html")
        self.assertIn("Follow-Up Validity", html)
        self.assertIn("validity_bucket", html)
        self.assertIn("visible_now", html)
        self.assertIn("tailwag-memory-items.html", html)
        self.assertIn("tailwag-person-timeline.html", html)
        self.assertIn("\\u003cscript>alert(1)\\u003c/script>", html)


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
                        "related_memory_items": [
                            {
                                "memory_id": "mem_demo",
                                "kind": "preference",
                                "status": "active",
                                "summary": "Jamie likes concise demos.",
                            }
                        ],
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
        self.assertEqual(points[0].related_memory_items[0].summary, "Jamie likes concise demos.")
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
        self.assertIn("related_memory_items AS related_memory_items", runner.queries[0].query)
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

    def test_episode_conversion_fetches_read_only_episode_memory_counts(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_count": 8,
                        "memory_episode_count": 3,
                        "memory_count": 5,
                    }
                ]
            ]
        )

        conversion = MemoryItemInspectService(runner).episode_conversion()

        self.assertEqual(conversion, {"episode_count": 8, "memory_episode_count": 3, "memory_count": 5})
        self.assertEqual(runner.queries[0].parameters, {})
        self.assertIn("MATCH (episode:Episode)", runner.queries[0].query)
        self.assertIn("SUPPORTED_BY", runner.queries[0].query)
        upper_query = runner.queries[0].query.upper()
        for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
            self.assertNotIn(write_keyword, upper_query)

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
                    {
                        "memory_id": "mem_superseded",
                        "person_id": "person_jamie",
                        "display_name": "<Jamie>",
                        "kind": "fact",
                        "key": "old_fact",
                        "summary": "Jamie used to prefer the old demo.",
                        "source": "extractor",
                        "status": "active",
                        "metadata_json": "",
                        "supported_episode_ids": ["episode_0"],
                        "addressed_by": [],
                        "superseded_by_memory_ids": ["mem_new"],
                        "supersedes_memory_ids": [],
                    },
                ]
            ]
        )
        items = MemoryItemInspectService(runner).items(
            limit=10,
            now=datetime(2026, 7, 7, tzinfo=timezone.utc),
        )

        report = memory_items_report(
            items,
            person_id=None,
            limit=10,
            episode_conversion={"episode_count": 4, "memory_episode_count": 2, "memory_count": 3},
            generated_at="2026-07-07T12:00:00+00:00",
        )
        html = memory_items_report_html(report)

        self.assertEqual(report.title, "Memory Items")
        self.assertEqual(report.metadata["storage"], "read_only")
        self.assertEqual(report.metadata["distributions"]["kind"], {"preference": 1, "followup": 1, "fact": 1})
        self.assertEqual(report.metadata["distributions"]["person"], {"person_jamie": 3})
        self.assertEqual(report.metadata["distributions"]["status"], {"active": 2, "superseded": 1})
        self.assertEqual(report.metadata["distributions"]["followup_state"]["visible_now"], 1)
        self.assertEqual(report.metadata["episode_counts"]["All Episodes"], 4)
        self.assertEqual(report.metadata["episode_counts"]["Episodes With Memories"], 2)
        self.assertEqual(report.metadata["episode_counts"]["Episodes Without Memories"], 2)
        self.assertEqual(report.metadata["terminal_counts"]["Superseded"], 1)
        _assert_canonical_nav(self, html, "tailwag-memory-items.html")
        self.assertIn("Memory Overview", html)
        self.assertIn("height: 440px", html)
        self.assertIn("margin: -70px 0", html)
        self.assertIn('viewBox="0 0 1120 440"', html)
        self.assertIn('"source": "All Episodes"', html)
        self.assertIn('"source": "Created"', html)
        self.assertIn("Follow-Up State", html)
        self.assertIn("followup_state", html)
        self.assertIn("\\u003cJamie>", html)
        self.assertIn("tailwag-memory-items.html", html)
        self.assertIn("tailwag-person-timeline.html", html)
        self.assertIn("tailwag-affect.html", html)
        self.assertIn("evidenceHtml(record, supported, addressed, supersededBy, supersedes)", html)
        self.assertIn("timelineHref({ person: personId || '', item: itemId || '' })", html)
        self.assertIn('href="#${focusedMemoryHash(record.memory_id || \'\')}"', html)
        self.assertIn("function focusedMemoryHash(memoryId)", html)
        self.assertIn("status: ''", html)
        self.assertIn("followup_state: ''", html)
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
                        "memory_item_count": 2,
                        "memory_item_ids": ["mem_episode"],
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
        self.assertTrue(episode.has_memory_items)
        self.assertEqual(episode.memory_item_count, 2)
        self.assertEqual(episode.memory_item_ids, ["mem_episode"])
        self.assertEqual(
            [(line.timestamp, line.speaker, line.text) for line in episode.transcript_snippets],
            [("", "Jamie", "I shipped the patch.")],
        )
        event = items[0]
        self.assertEqual(event.event_id, "event_1")
        self.assertEqual(event.text, "Design review")
        self.assertFalse(event.has_memory_items)
        self.assertEqual(event.memory_item_count, 0)
        self.assertEqual(runner.queries[0].parameters, {"person_id": None, "limit": 5})
        self.assertEqual(runner.queries[1].parameters, {"person_id": None, "limit": 5})
        self.assertIn("MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)", runner.queries[0].query)
        self.assertIn("WHERE ($person_id IS NULL OR person.id = $person_id)", runner.queries[0].query)
        self.assertIn("count(DISTINCT memory) AS memory_item_count", runner.queries[0].query)
        self.assertIn("memory_item_ids AS memory_item_ids", runner.queries[0].query)
        self.assertIn("type(r) = 'ATTENDED'", runner.queries[1].query)
        self.assertIn("0 AS memory_item_count", runner.queries[1].query)
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
    def test_person_timeline_report_html_embeds_nav_memory_flags_and_escaped_text(self) -> None:
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
                    has_memory_items=True,
                    memory_item_count=2,
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

        self.assertIn("Person Timeline", html)
        _assert_canonical_nav(self, html, "tailwag-person-timeline.html")
        self.assertIn("tailwag-person-timeline.html", html)
        self.assertIn("tailwag-affect.html", html)
        self.assertIn("tailwag-memory-items.html", html)
        self.assertIn("Linked memories", html)
        self.assertIn("min-height: 220px", html)
        self.assertIn("const markerLayout = layoutMarkers(sorted, domain);", html)
        self.assertIn("64 + markerLayout.rowCount * 168", html)
        self.assertIn("top:${top}px", html)
        self.assertIn("is not in this exported timeline", html)
        self.assertIn("recordMatchesItem(record, selectedItem) ? 'active' : ''", html)
        _assert_css_rule_contains(self, html, "body", ["height: 100vh", "overflow: hidden"])
        _assert_css_rule_contains(self, html, "main", ["overflow: hidden"])
        _assert_css_rule_contains(
            self,
            html,
            "aside",
            ["position: sticky", "top: 0", "align-self: start"],
        )
        _assert_css_rule_contains(self, html, ".timeline", ["min-height: 0", "overflow: auto"])
        self.assertIn('"person_id": "person_jamie"', html)
        self.assertIn('"has_memory_items": true', html)
        self.assertIn('"memory_item_count": 2', html)
        self.assertIn("\\u003cscript>alert(1)\\u003c/script>", html)


class InspectPlaceholderFilesTest(unittest.TestCase):
    def test_committed_inspect_placeholders_use_canonical_names(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inspect_dir = root / "inspect"
        expected = [
            "index.html",
            "tailwag-followup-validity.html",
            "tailwag-affect.html",
            "tailwag-person-timeline.html",
            "tailwag-memory-items.html",
        ]
        command_hints = {
            "index.html": [
                "tailwag inspect followup-validity",
                "tailwag inspect affect",
                "tailwag inspect person-timeline",
                "tailwag inspect memory-items",
            ],
            "tailwag-followup-validity.html": ["tailwag inspect followup-validity"],
            "tailwag-affect.html": ["tailwag inspect affect"],
            "tailwag-person-timeline.html": ["tailwag inspect person-timeline"],
            "tailwag-memory-items.html": ["tailwag inspect memory-items"],
        }
        self.assertIn("color-scheme: light", inspect_asset_text(INSPECT_CSS_FILENAME))
        self.assertIn("window.inspectFilters", inspect_asset_text(INSPECT_JS_FILENAME))

        for filename in expected:
            html = (inspect_dir / filename).read_text()
            current = None if filename == "index.html" else filename
            _assert_canonical_nav(self, html, current)
            self.assertIn('href="tailwag-inspect.css"', html)
            for command in command_hints[filename]:
                self.assertIn(command, html)
            if filename != "index.html":
                self.assertIn('src="tailwag-inspect.js"', html)
                self.assertIn('id="report-data"', html)


if __name__ == "__main__":
    unittest.main()
