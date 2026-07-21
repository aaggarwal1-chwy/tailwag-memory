from tests.helpers import RecordingQueryRunner
from tailwag_memory.schema import initialize_schema, schema_statements
import unittest


def _compact(statement: str) -> str:
    return " ".join(statement.split())


class SchemaTest(unittest.TestCase):
    def test_schema_excludes_deferred_fields_and_org_id(self) -> None:
        text = "\n".join(schema_statements(64))

        self.assertNotIn("org_id", text)
        self.assertNotIn("identity_status", text)
        self.assertNotIn("confidence", text)
        self.assertNotIn("ObjectConcept", text)
        self.assertNotIn("Activity", text)
        self.assertNotIn("Utterance", text)
        self.assertNotIn("SemanticFact", text)

    def test_schema_creates_expected_constraints_and_vector_indexes(self) -> None:
        statements = [_compact(statement) for statement in schema_statements(64)]

        self.assertEqual(len(statements), 14)
        self.assertEqual(
            statements[:10],
            [
                "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
                "CREATE CONSTRAINT person_email IF NOT EXISTS FOR (p:Person) REQUIRE p.email IS UNIQUE",
                "CREATE CONSTRAINT episode_id IF NOT EXISTS FOR (e:Episode) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT robot_id IF NOT EXISTS FOR (r:Robot) REQUIRE r.id IS UNIQUE",
                "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT memory_item_id IF NOT EXISTS FOR (m:MemoryItem) REQUIRE m.id IS UNIQUE",
                "CREATE CONSTRAINT employee_directory_record_key IF NOT EXISTS FOR (d:EmployeeDirectoryRecord) REQUIRE (d.site_code, d.username) IS UNIQUE",
                "CREATE CONSTRAINT face_reference_id IF NOT EXISTS FOR (r:FaceReference) REQUIRE r.id IS UNIQUE",
                "CREATE CONSTRAINT voice_reference_id IF NOT EXISTS FOR (r:VoiceReference) REQUIRE r.id IS UNIQUE",
                "CREATE CONSTRAINT place_key IF NOT EXISTS FOR (p:Place) REQUIRE (p.building_code, p.room_id) IS UNIQUE",
            ],
        )
        expected_indexes = [
            ("episode_transcript_embedding", "Episode", "transcript_embedding"),
            ("face_reference_embedding", "FaceReference", "embedding"),
            ("voice_reference_embedding", "VoiceReference", "embedding"),
            ("memory_item_summary_embedding", "MemoryItem", "summary_embedding"),
        ]
        for statement, (name, label, property_name) in zip(statements[10:], expected_indexes):
            self.assertIn(f"CREATE VECTOR INDEX {name} IF NOT EXISTS", statement)
            self.assertIn(f"FOR (", statement)
            self.assertIn(f":{label}) ON", statement)
            self.assertIn(f".{property_name})", statement)
            self.assertIn("`vector.similarity_function`: 'cosine'", statement)
        self.assertIn("`vector.dimensions`: 64", statements[10])
        self.assertIn("`vector.dimensions`: 512", statements[11])
        self.assertIn("`vector.dimensions`: 192", statements[12])
        self.assertIn("`vector.dimensions`: 64", statements[13])

    def test_initialize_schema_runs_all_statements(self) -> None:
        runner = RecordingQueryRunner()

        initialize_schema(runner, embedding_dimension=64)

        self.assertEqual(len(runner.queries), len(schema_statements(64)))
        self.assertEqual(
            [_compact(query.query) for query in runner.queries],
            [_compact(statement) for statement in schema_statements(64)],
        )

    def test_schema_rejects_invalid_embedding_dimension(self) -> None:
        for value in (0, -1, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    schema_statements(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
