from tests.helpers import RecordingQueryRunner
from tailwag_memory.biometrics import BiometricReferenceService
import unittest
import json


class BiometricReferenceServiceTest(unittest.TestCase):
    def test_enroll_face_reference_writes_reference_node(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        result = service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            model="facenet-vggface2",
            metadata={"quality": "good"},
        )

        self.assertTrue(result.saved)
        query = runner.queries[-1]
        self.assertIn("CREATE (r:FaceReference", query.query)
        self.assertIn("HAS_FACE_REFERENCE", query.query)
        self.assertEqual(query.parameters["person_id"], "person_jamie")
        self.assertEqual(query.parameters["model"], "facenet-vggface2")
        self.assertEqual(query.parameters["dimension"], 512)
        self.assertEqual(json.loads(query.parameters["metadata_json"]), {"quality": "good"})

    def test_enroll_face_reference_updates_person_profile_from_metadata(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            model="facenet-vggface2",
            metadata={
                "display_name": "Jamie Example",
                "official_name": "Jamie Official",
                "employee_email": "jamie@example.com",
            },
        )

        person_query = next(query for query in runner.queries if "person" in query.parameters)
        self.assertEqual(person_query.parameters["person"]["display_name"], "Jamie Example")
        self.assertEqual(person_query.parameters["person"]["official_name"], "Jamie Official")
        self.assertEqual(person_query.parameters["person"]["email"], "jamie@example.com")

    def test_enroll_face_reference_serializes_nested_metadata_for_neo4j(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            model="facenet-vggface2",
            metadata={
                "display_name": "Jamie Example",
                "directory_profile_lines": ("Title: Engineer",),
                "metadata": {
                    "username": "jamie",
                    "site_code": "BOS3",
                },
            },
        )

        query = runner.queries[-1]
        self.assertIn("r.metadata_json = $metadata_json", query.query)
        stored = json.loads(query.parameters["metadata_json"])
        self.assertEqual(stored["metadata"]["username"], "jamie")
        self.assertEqual(stored["directory_profile_lines"], ["Title: Engineer"])

    def test_enroll_face_reference_links_directory_record_when_metadata_is_verified(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            model="facenet-vggface2",
            metadata={
                "metadata": {
                    "username": "jamie",
                    "site_code": "BOS3",
                }
            },
        )

        query = runner.queries[-1]
        self.assertIn("HAS_DIRECTORY_RECORD", query.query)
        self.assertIn("p.official_name", query.query)
        self.assertIn("p.name = p.id", query.query)
        self.assertEqual(query.parameters["directory_username"], "jamie")
        self.assertEqual(query.parameters["directory_site_code"], "BOS3")

    def test_enroll_face_reference_adds_readable_reference_name(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            model="facenet-vggface2",
            metadata={"official_name": "Jamie Example"},
        )

        query = runner.queries[-1]
        self.assertIn("r.display_name = $reference_display_name", query.query)
        self.assertEqual(
            query.parameters["reference_display_name"],
            "Face reference for Jamie Example",
        )

    def test_search_voice_uses_reference_index_and_thresholds(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "reference_id": "voice:1",
                        "model": "ecapa",
                        "metadata_json": '{"quality": "good"}',
                        "score": 0.81,
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.search_voice(embedding=[0.2] * 192, model="ecapa")

        self.assertTrue(result.recognized)
        self.assertEqual(result.candidates[0].person_id, "person_jamie")
        self.assertEqual(result.candidates[0].metadata, {"quality": "good"})
        self.assertIn("voice_reference_embedding", runner.queries[0].query)
        self.assertIn("HAS_VOICE_REFERENCE", runner.queries[0].query)

    def test_search_face_site_filter_keeps_directoryless_enrolled_people(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.search_face(embedding=[0.1] * 512, model="facenet-vggface2", site_code="BOS3")

        self.assertIn(
            "directory IS NULL OR directory.site_code = $site_code",
            runner.queries[0].query,
        )
        self.assertEqual(runner.queries[0].parameters["site_code"], "BOS3")


if __name__ == "__main__":
    unittest.main()
