from tests.helpers import RecordingQueryRunner
from tailwag_memory.schema import initialize_schema, schema_statements
import re
import unittest
from unittest.mock import patch


def _compact(statement: str) -> str:
    return re.sub(r"\s+", " ", statement).strip()


def _statement_names(statements: list[str], kind: str) -> dict[str, str]:
    pattern = re.compile(rf"^CREATE {kind} (?P<name>\S+)")
    return {
        match.group("name"): statement
        for statement in statements
        if (match := pattern.match(statement)) is not None
    }


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

        constraints = _statement_names(statements, "CONSTRAINT")
        # Schema names are a compatibility contract; statement order and formatting are not.
        expected_constraints = {
            "person_id": ("Person", ("id",)),
            "person_email": ("Person", ("email",)),
            "episode_id": ("Episode", ("id",)),
            "robot_id": ("Robot", ("id",)),
            "event_id": ("Event", ("id",)),
            "memory_item_id": ("MemoryItem", ("id",)),
            "relay_message_id": ("RelayMessage", ("id",)),
            "employee_directory_record_key": (
                "EmployeeDirectoryRecord",
                ("site_code", "username"),
            ),
            "face_reference_id": ("FaceReference", ("id",)),
            "voice_reference_id": ("VoiceReference", ("id",)),
            "place_key": ("Place", ("building_code", "room_id")),
        }
        self.assertEqual(set(constraints), set(expected_constraints))
        for name, (label, properties) in expected_constraints.items():
            property_pattern = r",\s*".join(
                rf"(?P=alias)\.{re.escape(property_name)}"
                for property_name in properties
            )
            if len(properties) > 1:
                property_pattern = rf"\({property_pattern}\)"
            with self.subTest(constraint=name):
                self.assertRegex(
                    constraints[name],
                    rf"FOR\s+\((?P<alias>[A-Za-z_]\w*):{re.escape(label)}\)\s+"
                    rf"REQUIRE\s+{property_pattern}\s+IS\s+UNIQUE\b",
                )

        range_indexes = _statement_names(statements, "RANGE INDEX")
        expected_range_indexes = {
            "relay_message_status": ("RelayMessage", ("status",)),
            "relay_message_delivery": (
                "RelayMessage",
                ("assigned_robot_id", "status", "deliver_after", "created_at"),
            ),
            "relay_message_expires_at": ("RelayMessage", ("expires_at",)),
        }
        self.assertEqual(set(range_indexes), set(expected_range_indexes))
        for name, (label, properties) in expected_range_indexes.items():
            property_pattern = r",\s*".join(
                rf"(?P=alias)\.{re.escape(property_name)}"
                for property_name in properties
            )
            with self.subTest(range_index=name):
                self.assertRegex(
                    range_indexes[name],
                    rf"FOR\s+\((?P<alias>[A-Za-z_]\w*):{re.escape(label)}\)\s+"
                    rf"ON\s+\({property_pattern}\)",
                )

        indexes = _statement_names(statements, "VECTOR INDEX")
        expected_indexes = {
            "episode_transcript_embedding": ("Episode", "transcript_embedding", 64),
            "face_reference_embedding": ("FaceReference", "embedding", 512),
            "voice_reference_embedding": ("VoiceReference", "embedding", 192),
            "memory_item_summary_embedding": ("MemoryItem", "summary_embedding", 64),
        }
        self.assertEqual(set(indexes), set(expected_indexes))
        for name, (label, property_name, dimension) in expected_indexes.items():
            with self.subTest(index=name):
                self.assertRegex(
                    indexes[name],
                    rf"FOR\s+\((?P<alias>[A-Za-z_]\w*):{re.escape(label)}\)\s+"
                    rf"ON\s+\((?P=alias)\.{re.escape(property_name)}\)",
                )
                self.assertRegex(
                    indexes[name],
                    rf"`vector\.dimensions`:\s*{dimension}(?=\s*[,}}])",
                )
                self.assertRegex(
                    indexes[name],
                    r"`vector\.similarity_function`:\s*'cosine'",
                )

    def test_schema_statements_are_idempotent(self) -> None:
        for statement in schema_statements(64):
            with self.subTest(statement=_compact(statement)):
                self.assertRegex(
                    _compact(statement),
                    r"^CREATE (?:CONSTRAINT|RANGE INDEX|VECTOR INDEX) \S+ IF NOT EXISTS\b",
                )

    def test_initialize_schema_runs_all_statements(self) -> None:
        runner = RecordingQueryRunner()

        with patch(
            "tailwag_memory.schema.schema_statements",
            return_value=["statement one", "statement two"],
        ) as statements:
            initialize_schema(
                runner,
                embedding_dimension=64,
                face_embedding_dimension=256,
                voice_embedding_dimension=96,
            )

        statements.assert_called_once_with(
            64,
            face_embedding_dimension=256,
            voice_embedding_dimension=96,
        )
        self.assertEqual([query.query for query in runner.queries], ["statement one", "statement two"])

    def test_schema_rejects_invalid_embedding_dimension(self) -> None:
        for value in (0, -1, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    schema_statements(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
