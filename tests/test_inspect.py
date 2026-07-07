import unittest

from tailwag_memory.db import RecordingQueryRunner
import tailwag_memory.inspect as inspect_tools
from tailwag_memory.inspect import (
    AffectScore,
    FoldEnsembleAffectProvider,
    PersonEpisodeTranscriptService,
    recent_person_episode_rows,
)


class InspectPackageImportTest(unittest.TestCase):
    def test_inspect_package_exports_inspection_utilities(self) -> None:
        expected_exports = {
            "AffectScore",
            "AffectScoringConfigurationError",
            "AffectScoringProvider",
            "FoldEnsembleAffectProvider",
            "HuggingFaceXLMRobertaLargeAffectProvider",
            "InspectReport",
            "InspectTranscriptLine",
            "PersonEpisodeAffectPoint",
            "PersonEpisodeTranscriptPoint",
            "PersonEpisodeTranscriptService",
            "affect_report",
            "affect_report_html",
            "recent_person_episode_rows",
            "report_json",
            "score_transcript_points",
        }

        self.assertEqual(set(inspect_tools.__all__), expected_exports)
        self.assertIs(inspect_tools.AffectScore, AffectScore)
        self.assertIs(inspect_tools.FoldEnsembleAffectProvider, FoldEnsembleAffectProvider)
        self.assertIs(inspect_tools.PersonEpisodeTranscriptService, PersonEpisodeTranscriptService)


class InspectTranscriptRowsTest(unittest.TestCase):
    def test_recent_person_episode_rows_fetches_bounded_participation_pairs(self) -> None:
        runner = RecordingQueryRunner(results=[[]])

        rows = recent_person_episode_rows(runner, 25)

        self.assertEqual(rows, [])
        self.assertEqual(runner.queries[0].parameters, {"limit": 25})
        self.assertIn("MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)", runner.queries[0].query)
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
        self.assertIn("MATCH (person:Person {id: $person_id})", runner.queries[0].query)
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


if __name__ == "__main__":
    unittest.main()
