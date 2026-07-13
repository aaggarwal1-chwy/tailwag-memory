from __future__ import annotations

import unittest

from tests.helpers import RecordingQueryRunner
from tailwag_memory.deletion import NodeDeletionService


class NodeDeletionServiceTest(unittest.TestCase):
    def test_delete_missing_node_returns_not_found_without_delete_query(self) -> None:
        runner = RecordingQueryRunner(results=[[]])

        result = NodeDeletionService(runner).delete_node(label="Person", node_id="person_missing")

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.label, "Person")
        self.assertEqual(result.id, "person_missing")
        self.assertEqual(result.deleted_counts, {})
        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(runner.queries[0].parameters, {"node_id": "person_missing"})

    def test_delete_person_uses_type_specific_cascade(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"node_id": "person_jamie"}],
                [
                    {
                        "persons_deleted": 1,
                        "episodes_deleted": 1,
                        "memory_items_deleted": 2,
                        "face_references_deleted": 1,
                        "voice_references_deleted": 1,
                        "event_links_deleted": 1,
                        "directory_links_deleted": 1,
                    }
                ],
            ]
        )

        result = NodeDeletionService(runner).delete_node(label="Person", node_id="person_jamie")

        self.assertEqual(result.status, "deleted")
        self.assertEqual(result.deleted_counts["persons_deleted"], 1)
        self.assertEqual(result.deleted_counts["episodes_deleted"], 1)
        self.assertEqual(result.deleted_counts["memory_items_deleted"], 2)
        query = runner.queries[1].query
        self.assertIn("HAS_MEMORY", query)
        self.assertIn("HAS_FACE_REFERENCE", query)
        self.assertIn("HAS_VOICE_REFERENCE", query)
        self.assertIn("HAS_DIRECTORY_RECORD", query)
        self.assertIn("EmployeeDirectoryRecord", query)
        self.assertIn("ATTENDED", query)
        self.assertIn("Event", query)
        self.assertIn("WHERE NOT kept_episode IN owned_episodes", query)
        self.assertEqual(runner.queries[1].parameters, {"node_id": "person_jamie"})

    def test_delete_episode_preserves_people_and_removes_memory_evidence(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"node_id": "episode_1"}],
                [
                    {
                        "episodes_deleted": 1,
                        "memory_items_deleted": 1,
                        "support_links_deleted": 2,
                        "addressed_links_deleted": 1,
                        "places_deleted": 0,
                    }
                ],
            ]
        )

        result = NodeDeletionService(runner).delete_node(label="Episode", node_id="episode_1")

        self.assertEqual(result.status, "deleted")
        self.assertEqual(result.deleted_counts["episodes_deleted"], 1)
        query = runner.queries[1].query
        self.assertIn("SUPPORTED_BY", query)
        self.assertIn("ADDRESSED_BY", query)
        self.assertIn("single_support_memories", query)
        self.assertIn("OCCURRED_AT", query)
        self.assertNotIn("MATCH (person:Person", query)
        self.assertEqual(runner.queries[1].parameters, {"node_id": "episode_1"})

    def test_delete_memory_item_deletes_transitive_outgoing_supersession_chain(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"node_id": "mem_1"}],
                [{"memory_items_deleted": 3}],
            ]
        )

        result = NodeDeletionService(runner).delete_node(label="MemoryItem", node_id="mem_1")

        self.assertEqual(result.status, "deleted")
        self.assertEqual(result.deleted_counts, {"memory_items_deleted": 3})
        query = runner.queries[1].query
        self.assertIn("SUPERSEDED_BY*0..", query)
        self.assertIn("DETACH DELETE deleted_memory", query)
        self.assertNotIn("Episode", query)
        self.assertNotIn("Person", query)
        self.assertEqual(runner.queries[1].parameters, {"node_id": "mem_1"})

    def test_rejects_unsupported_label(self) -> None:
        runner = RecordingQueryRunner()

        with self.assertRaises(ValueError):
            NodeDeletionService(runner).delete_node(label="Event", node_id="event_1")

        self.assertEqual(runner.queries, [])


if __name__ == "__main__":
    unittest.main()
