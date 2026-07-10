from tests.helpers import RecordingQueryRunner
from tailwag_memory.identity import DirectoryIdentityService, load_directory_records_from_snowflake
from tailwag_memory.models import DirectoryPersonRecord
import unittest


class DirectoryIdentityServiceTest(unittest.TestCase):
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
        self.assertIn("p.name = coalesce(p.name, $person_id)", query.query)
        self.assertEqual(query.parameters["directory_username"], "jamie")
        self.assertEqual(query.parameters["directory_site_code"], "BOS3")

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
