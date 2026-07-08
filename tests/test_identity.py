from tests.helpers import RecordingQueryRunner
from tailwag_memory.identity import DirectoryIdentityService
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
        self.assertEqual(query.parameters["records"][0]["normalized_name"], "jamie example")
        self.assertEqual(query.parameters["records"][0]["site_code"], "BOS3")

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
        self.assertEqual(query.parameters["directory_username"], "jamie")
        self.assertEqual(query.parameters["directory_site_code"], "BOS3")


if __name__ == "__main__":
    unittest.main()
