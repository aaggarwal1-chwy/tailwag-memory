from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.schema import initialize_schema, schema_statements
import unittest


class SchemaTest(unittest.TestCase):
    def test_schema_excludes_deferred_fields_and_org_id(self) -> None:
        text = "\n".join(schema_statements(64))

        self.assertNotIn("org_id", text)
        self.assertNotIn("identity_status", text)
        self.assertNotIn("confidence", text)
        self.assertNotIn("Robot", text)
        self.assertNotIn("ObjectConcept", text)
        self.assertNotIn("Activity", text)
        self.assertNotIn("Utterance", text)
        self.assertNotIn("SemanticFact", text)

    def test_schema_creates_expected_constraints_and_vector_indexes(self) -> None:
        text = "\n".join(schema_statements(64))

        self.assertIn("CONSTRAINT person_id", text)
        self.assertIn("CONSTRAINT episode_id", text)
        self.assertIn("CONSTRAINT event_id", text)
        self.assertIn("CONSTRAINT place_key", text)
        self.assertIn("episode_summary_embedding", text)
        self.assertIn("episode_transcript_embedding", text)
        self.assertIn("person_face_embedding", text)
        self.assertIn("person_audio_embedding", text)
        self.assertIn("`vector.dimensions`: 64", text)

    def test_initialize_schema_runs_all_statements(self) -> None:
        runner = RecordingQueryRunner()

        initialize_schema(runner, embedding_dimension=64)

        self.assertEqual(len(runner.queries), len(schema_statements(64)))


if __name__ == "__main__":
    unittest.main()
