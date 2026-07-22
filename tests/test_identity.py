import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import RecordingQueryRunner
from tailwag_memory.identity import DirectoryIdentityService, load_directory_records_from_snowflake
from tailwag_memory.identity.snowflake import load_env_file as load_snowflake_env_file
from tailwag_memory.models import DirectoryPersonRecord


class DirectoryIdentityServiceTest(unittest.TestCase):
    def test_snowflake_env_loader_preserves_candidate_precedence_and_quote_handling(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cwd_env = root / ".snowflake_env"
            explicit_env = root / "explicit.env"
            fallback_env = root / ".env"
            cwd_env.write_text('SOURCE="cwd snowflake"\n', encoding="utf-8")
            explicit_env.write_text("SOURCE='explicit path'\n", encoding="utf-8")
            fallback_env.write_text("SOURCE=fallback env\n", encoding="utf-8")

            os.chdir(root)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    load_snowflake_env_file(explicit_env)
                    self.assertEqual(os.environ["SOURCE"], "cwd snowflake")

                cwd_env.unlink()
                with patch.dict(os.environ, {}, clear=True):
                    load_snowflake_env_file(explicit_env)
                    self.assertEqual(os.environ["SOURCE"], "explicit path")

                explicit_env.unlink()
                with patch.dict(os.environ, {}, clear=True):
                    load_snowflake_env_file(explicit_env)
                    self.assertEqual(os.environ["SOURCE"], "fallback env")
            finally:
                os.chdir(original_cwd)

    def test_sync_directory_people_writes_normalized_rows(self) -> None:
        runner = RecordingQueryRunner()
        service = DirectoryIdentityService(runner)

        result = service.sync_directory_people(
            "BOS3",
            [
                DirectoryPersonRecord(
                    site_code="BOS3",
                    username="jamie",
                    official_name="Jamie Example",
                    employee_email="jamie@example.com",
                    business_title="Engineer",
                )
            ],
        )

        self.assertEqual(result.records_written, 1)
        query = runner.queries[0]
        self.assertIn("EmployeeDirectoryRecord", query.query)
        self.assertIn("HAS_DIRECTORY_RECORD", query.query)
        self.assertIn("p.official_name", query.query)
        self.assertIn("p.name = p.id", query.query)
        self.assertIn("d.name = record.official_name", query.query)
        self.assertIn("toLower(split(p.email, '@')[0]) = record.username", query.query)
        self.assertNotIn("p.id = 'person_' + record.username", query.query)
        self.assertEqual(query.parameters["records"][0]["normalized_name"], "jamie example")
        self.assertEqual(query.parameters["records"][0]["site_code"], "BOS3")
        self.assertEqual(query.parameters["records"][0]["display_name"], "Jamie Example")
        self.assertEqual(query.parameters["records"][0]["name"], "Jamie Example")
        self.assertEqual(query.parameters["records"][0]["source"], "snowflake")

    def test_sync_directory_people_links_person_by_email_username_without_employee_email(self) -> None:
        runner = RecordingQueryRunner()
        service = DirectoryIdentityService(runner)

        service.sync_directory_people(
            "BOS3",
            [
                DirectoryPersonRecord(
                    site_code="BOS3",
                    username="jamie",
                    official_name="Jamie Example",
                )
            ],
        )

        query = runner.queries[0]
        self.assertEqual(query.parameters["records"][0]["username"], "jamie")
        self.assertEqual(query.parameters["records"][0]["employee_email"], "")
        self.assertIn("p.email CONTAINS '@'", query.query)
        self.assertIn("toLower(split(p.email, '@')[0]) = record.username", query.query)
        self.assertIn("MERGE (p)-[:HAS_DIRECTORY_RECORD]->(d)", query.query)

    def test_resolve_identity_returns_single_match(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "site_code": "BOS3",
                        "official_name": "Jamie Example",
                        "username": "jamie",
                        "employee_email": "jamie@example.com",
                        "business_title": "Engineer",
                    }
                ]
            ]
        )
        service = DirectoryIdentityService(runner)

        result = service.resolve_identity(
            shared_first_name="Jamie",
            shared_last_name="Example",
            site_code="BOS3",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "single_match")
        self.assertEqual(result.candidates[0].username, "jamie")

    def test_resolve_identity_preserves_input_and_directory_error_statuses(self) -> None:
        service = DirectoryIdentityService(RecordingQueryRunner())

        invalid = service.resolve_identity(shared_first_name="Jamie", shared_last_name="")
        unavailable = service.resolve_identity(shared_first_name="Jamie", shared_last_name="Example")

        self.assertEqual(
            (invalid.success, invalid.status, invalid.message),
            (False, "invalid_input", "Please provide the person's official first and last name."),
        )
        self.assertEqual(
            (unavailable.success, unavailable.status, unavailable.message),
            (False, "directory_unavailable", "The employee directory is unavailable or empty."),
        )

    def test_resolve_identity_preserves_ambiguous_and_clarification_statuses(self) -> None:
        service = DirectoryIdentityService(
            RecordingQueryRunner(
                results=[
                    [
                        {"official_name": "Jamie Example", "username": "jamie"},
                        {"official_name": "Jamie Example", "username": "jamie_2"},
                    ],
                    [{"official_name": "J Xample", "username": "jamie"}],
                    [{"official_name": "Morgan Elsewhere", "username": "morgan"}],
                ]
            )
        )

        ambiguous = service.resolve_identity(shared_first_name="Jamie", shared_last_name="Example")
        unclear = service.resolve_identity(shared_first_name="Jamie", shared_last_name="Example")
        missing = service.resolve_identity(shared_first_name="Jamie", shared_last_name="Example")

        self.assertEqual(
            (ambiguous.success, ambiguous.status, ambiguous.message),
            (False, "multiple_matches", "Multiple plausible employees matched that name."),
        )
        self.assertEqual(
            [candidate.username for candidate in ambiguous.candidates],
            ["jamie", "jamie_2"],
        )
        self.assertEqual(
            (unclear.success, unclear.status, unclear.message),
            (
                False,
                "needs_clarification",
                "A possible employee match was found, but confirmation is needed.",
            ),
        )
        self.assertEqual([candidate.username for candidate in unclear.candidates], ["jamie"])
        self.assertEqual(
            (missing.success, missing.status, missing.message, missing.candidates),
            (False, "no_match", "No plausible employee match was found.", []),
        )

    def test_get_verified_profile_returns_directory_projection(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "site_code": "BOS3",
                        "official_name": "Jamie Example",
                        "username": "jamie",
                        "employee_email": "jamie@example.com",
                        "business_title": "Engineer",
                        "tenure": "2 years",
                        "manager_name": "Manager Example",
                    }
                ]
            ]
        )
        service = DirectoryIdentityService(runner)

        profile = service.get_verified_profile(
            username="Jamie",
            official_name="Jamie Example",
            site_code="BOS3",
        )

        self.assertIsNotNone(profile)
        self.assertEqual(profile.person_id, "person_jamie")
        self.assertEqual(
            profile.directory_profile_lines,
            ("Title: Engineer", "Manager: Manager Example", "Tenure: 2 years"),
        )
        self.assertIn("d.senior_leadership_team AS senior_leadership_team", runner.queries[0].query)

    def test_get_verified_profile_rejects_invalid_ambiguous_and_name_mismatch(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {"official_name": "Jamie Example", "username": "jamie"},
                    {"official_name": "Jamie Example", "username": "jamie"},
                ],
                [{"official_name": "James Example", "username": "jamie"}],
            ]
        )
        service = DirectoryIdentityService(runner)

        self.assertIsNone(service.get_verified_profile(username="", official_name="Jamie Example"))
        self.assertIsNone(service.get_verified_profile(username="jamie", official_name="Jamie Example"))
        self.assertIsNone(service.get_verified_profile(username="jamie", official_name="Jamie Example"))
        self.assertEqual(len(runner.queries), 2)

    def test_record_encounter_links_verified_person_to_directory_record(self) -> None:
        runner = RecordingQueryRunner()
        service = DirectoryIdentityService(runner)

        service.record_encounter(
            person_id="person_jamie",
            metadata={
                "display_name": "Jamie Example",
                "username": "jamie",
                "site_code": "BOS3",
            },
        )

        query = runner.queries[0]
        self.assertIn("HAS_DIRECTORY_RECORD", query.query)
        self.assertIn("WHEN $official_name IS NOT NULL THEN $official_name", query.query)
        self.assertIn("$display_name <> $person_id", query.query)
        self.assertIn("p.name = coalesce(p.name, $person_id)", query.query)
        self.assertEqual(query.parameters["directory_username"], "jamie")
        self.assertEqual(query.parameters["directory_site_code"], "BOS3")

    def test_record_encounter_prefers_official_name_over_display_name(self) -> None:
        runner = RecordingQueryRunner()
        service = DirectoryIdentityService(runner)

        service.record_encounter(
            person_id="person_jamie",
            metadata={
                "display_name": "person_jamie",
                "official_name": "Jamie Example",
            },
        )

        query = runner.queries[0]
        self.assertEqual(query.parameters["display_name"], "person_jamie")
        self.assertEqual(query.parameters["official_name"], "Jamie Example")
        self.assertIn("WHEN $official_name IS NOT NULL THEN $official_name", query.query)

    def test_person_profile_returns_official_name_when_display_name_is_person_id(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "person_jamie",
                        "person_official_name": "Jamie Example",
                        "email": "jamie@example.com",
                        "status": "active",
                    }
                ]
            ]
        )
        service = DirectoryIdentityService(runner)

        profile = service.person_profile("person_jamie")

        self.assertIsNotNone(profile)
        self.assertEqual(profile.display_name, "Jamie Example")

    def test_record_encounter_reconciles_directory_record_by_email_username(self) -> None:
        runner = RecordingQueryRunner()
        service = DirectoryIdentityService(runner)

        service.record_encounter(
            person_id="person_external_jamie",
            metadata={"email": "Jamie@Example.com"},
        )

        query = runner.queries[0]
        self.assertIn("EmployeeDirectoryRecord", query.query)
        self.assertIn("HAS_DIRECTORY_RECORD", query.query)
        self.assertIn("toLower(split(p.email, '@')[0])", query.query)
        self.assertEqual(query.parameters["email"], "Jamie@Example.com")

    def test_record_encounter_rejects_empty_id_and_returns_fallback_profile(self) -> None:
        service = DirectoryIdentityService(RecordingQueryRunner())

        with self.assertRaisesRegex(ValueError, "person_id is required"):
            service.record_encounter(person_id="  ")

        profile = service.record_encounter(
            person_id="person_jamie",
            observed_at="2026-01-02T03:04:05+00:00",
        )

        self.assertEqual(profile.person_id, "person_jamie")
        self.assertEqual(profile.display_name, "person_jamie")
        self.assertEqual(profile.last_seen, "2026-01-02T03:04:05+00:00")
        self.assertEqual(profile.interaction_count, 1)

    def test_snowflake_loader_maps_employee_and_manager_by_column_name(self) -> None:
        class Cursor:
            description = [
                ("MANAGER_NAME",),
                ("EMPLOYEE_NAME",),
                ("EMPLOYEE_USERNAME",),
                ("BUSINESS_TITLE",),
            ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, *_args):
                return None

            def fetchall(self):
                return [("Manager Person", "Employee Person", "employee1", "Engineer")]

        class Connection:
            def cursor(self):
                return Cursor()

            def close(self):
                return None

        records = load_directory_records_from_snowflake(
            "BOS3",
            email_domain="example.com",
            env_loader=lambda: None,
            connector_factory=lambda: Connection(),
        )

        self.assertEqual(records[0].official_name, "Employee Person")
        self.assertEqual(records[0].manager_name, "Manager Person")
        self.assertEqual(records[0].username, "employee1")


if __name__ == "__main__":
    unittest.main()
