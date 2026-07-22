import json
import unittest

from tailwag_memory.biometrics import BiometricReferenceService
from tests.helpers import RecordingQueryRunner


class BiometricReferenceServiceTest(unittest.TestCase):
    def test_enrollment_validation_errors_and_consent_rejection_are_stable(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        with self.assertRaisesRegex(ValueError, "^person_id is required$"):
            service.enroll_face_reference(person_id="  ", embedding=[1.0])
        with self.assertRaisesRegex(ValueError, "^embedding is required$"):
            service.enroll_face_reference(person_id="person_jamie", embedding=[])
        rejected = service.enroll_face_reference(
            person_id=" person_jamie ",
            embedding=[1.0],
            consent_status="denied",
        )

        self.assertFalse(rejected.saved)
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason, "consent_required")
        self.assertEqual(rejected.person_id, "person_jamie")
        self.assertEqual(rejected.reference_id, "")
        # Privacy guard: denied consent must stop before any graph write.
        self.assertEqual(runner.queries, [])

    def test_observation_validation_errors_are_stable(self) -> None:
        service = BiometricReferenceService(RecordingQueryRunner())

        with self.assertRaisesRegex(ValueError, "^person_id is required$"):
            service.observe_face_embedding(
                person_id="",
                embedding=[1.0],
                evidence={},
            )
        with self.assertRaisesRegex(ValueError, "^embedding is required$"):
            service.observe_voice_embedding(
                person_id="person_jamie",
                embedding=[0.0, 0.0],
                evidence={},
            )

    def test_search_without_embedding_returns_before_query(self) -> None:
        runner = RecordingQueryRunner()

        result = BiometricReferenceService(runner).search_face(embedding=[])

        self.assertEqual(result.modality, "face")
        self.assertFalse(result.recognized)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "no_embedding")
        self.assertEqual(result.candidates, [])
        self.assertEqual(runner.queries, [])

    def test_has_voice_reference_handles_blank_and_active_reference(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        self.assertFalse(service.has_voice_reference("  "))
        self.assertEqual(runner.queries, [])

        runner = RecordingQueryRunner(results=[[{"reference_id": "voice:1"}]])

        exists = BiometricReferenceService(runner).has_voice_reference(" person_jamie ")

        self.assertTrue(exists)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie"})

    def test_has_face_reference_handles_blank_and_active_reference(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        self.assertFalse(service.has_face_reference("  "))
        self.assertEqual(runner.queries, [])

        runner = RecordingQueryRunner(results=[[{"reference_id": "face:1"}]])

        exists = BiometricReferenceService(runner).has_face_reference(" person_jamie ")

        self.assertTrue(exists)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie"})

        query = runner.queries[0].query
        self.assertIn("HAS_FACE_REFERENCE", query)
        self.assertIn("FaceReference", query)
        self.assertIn("coalesce(r.status, 'active') = 'active'", query)

    def test_observation_missing_reference_result_is_stable(self) -> None:
        runner = RecordingQueryRunner(results=[[]])
        service = BiometricReferenceService(runner)

        result = service.observe_face_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "primary_face_person_id": "person_jamie",
                "audio_speaker_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.3,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "missing_reference")
        self.assertEqual(result.person_id, "person_jamie")
        self.assertEqual(result.modality, "face")

    def test_observation_dimension_mismatch_result_is_stable(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "reference_id": "voice:person_jamie:1",
                        "embedding": [1.0, 0.0, 0.0],
                        "sample_count": "2",
                        "target_sample_count": "5",
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.observe_voice_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "primary_face_person_id": "person_jamie",
                "audio_speaker_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.3,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "dimension_mismatch")
        self.assertEqual(result.reference_id, "voice:person_jamie:1")
        self.assertEqual(result.sample_count, 2)
        self.assertEqual(result.target_sample_count, 5)

    def test_enroll_face_reference_returns_saved_result_and_write_parameters(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner, face_embedding_model="facenet-vggface2")

        result = service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            metadata={"quality": "good"},
        )

        self.assertTrue(result.saved)
        query = runner.queries[-1]
        self.assertEqual(query.parameters["person_id"], "person_jamie")
        self.assertEqual(query.parameters["model"], "facenet-vggface2")
        self.assertEqual(query.parameters["dimension"], 512)
        self.assertEqual(query.parameters["target_sample_count"], 5)
        self.assertEqual(json.loads(query.parameters["metadata_json"]), {"quality": "good"})

    def test_enroll_face_reference_updates_person_profile_from_metadata(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
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

    def test_enroll_voice_reference_without_name_metadata_does_not_use_person_id_as_display_name(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_voice_reference(
            person_id="person_jamie",
            embedding=[0.1] * 192,
            metadata={"attempt_kind": "silent"},
        )

        person_query = next(query for query in runner.queries if "person" in query.parameters)
        self.assertIsNone(person_query.parameters["person"]["display_name"])
        self.assertIsNone(person_query.parameters["person"]["official_name"])

    def test_enroll_face_reference_serializes_nested_metadata_for_neo4j(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
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
        stored = json.loads(query.parameters["metadata_json"])
        self.assertEqual(stored["metadata"]["username"], "jamie")
        self.assertEqual(stored["directory_profile_lines"], ["Title: Engineer"])

    def test_enroll_face_reference_passes_verified_directory_identity(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            metadata={
                "metadata": {
                    "username": "jamie",
                    "site_code": "BOS3",
                }
            },
        )

        query = runner.queries[-1]
        self.assertEqual(query.parameters["directory_username"], "jamie")
        self.assertEqual(query.parameters["directory_site_code"], "BOS3")

    def test_enroll_face_reference_adds_readable_reference_name(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
            metadata={"official_name": "Jamie Example"},
        )

        query = runner.queries[-1]
        self.assertEqual(
            query.parameters["reference_display_name"],
            "Face reference for Jamie Example",
        )

    def test_search_voice_returns_candidate_and_metadata(self) -> None:
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

        result = service.search_voice(embedding=[0.2] * 192)

        self.assertTrue(result.recognized)
        self.assertEqual(result.candidates[0].person_id, "person_jamie")
        self.assertEqual(result.candidates[0].metadata, {"quality": "good"})

    def test_search_voice_rejects_below_updated_threshold(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "reference_id": "voice:1",
                        "model": "ecapa",
                        "metadata_json": "{}",
                        "score": 0.49,
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.search_voice(embedding=[0.2] * 192)

        self.assertFalse(result.recognized)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "below_threshold")
        self.assertEqual(result.threshold, 0.50)

    def test_search_voice_converts_neo4j_score_to_raw_cosine_before_threshold(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "reference_id": "voice:1",
                        "model": "ecapa",
                        "metadata_json": "{}",
                        "neo4j_score": 0.568,
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.search_voice(embedding=[0.2] * 192)

        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "below_threshold")
        self.assertAlmostEqual(result.top_score, 0.136)
        self.assertAlmostEqual(result.candidates[0].score, 0.136)

    def test_search_voice_margin_uses_raw_cosine_scale(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "reference_id": "voice:1",
                        "model": "ecapa",
                        "metadata_json": "{}",
                        "neo4j_score": 0.78,
                    },
                    {
                        "person_id": "person_riley",
                        "display_name": "Riley",
                        "consent_status": "consented",
                        "reference_id": "voice:2",
                        "model": "ecapa",
                        "metadata_json": "{}",
                        "neo4j_score": 0.61,
                    },
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.search_voice(embedding=[0.2] * 192, limit=2)

        self.assertTrue(result.recognized)
        self.assertAlmostEqual(result.top_score, 0.56)
        self.assertAlmostEqual(result.runner_up_score, 0.22)
        self.assertAlmostEqual(result.margin, 0.34)

    def test_search_face_converts_neo4j_score_to_raw_cosine_before_threshold(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "reference_id": "face:1",
                        "model": "facenet",
                        "metadata_json": "{}",
                        "neo4j_score": 0.73,
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.search_face(embedding=[0.1] * 512)

        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "below_threshold")
        self.assertAlmostEqual(result.top_score, 0.46)
        self.assertAlmostEqual(result.threshold, 0.60)

    def test_search_face_passes_site_filter(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        service.search_face(embedding=[0.1] * 512, site_code="BOS3")

        self.assertEqual(runner.queries[0].parameters["site_code"], "BOS3")

    def test_observe_face_embedding_updates_reference_from_agreement(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "reference_id": "face:person_jamie:1",
                        "embedding": [1.0, 0.0, 0.0],
                        "sample_count": 1,
                        "accepted_update_count": 0,
                        "target_sample_count": 5,
                        "metadata_json": '{"quality": "good"}',
                    }
                ],
                [],
            ]
        )
        service = BiometricReferenceService(runner, face_embedding_model="facenet-vggface2")

        result = service.observe_face_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "primary_face_person_id": "person_jamie",
                "audio_speaker_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.25,
                "unknown_count": 0,
            },
            metadata={"scene": "clean"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "updated")
        self.assertEqual(result.sample_count, 2)
        self.assertEqual(result.target_sample_count, 5)
        self.assertAlmostEqual(result.similarity, 1.0)
        update_query = runner.queries[-1]
        self.assertEqual(update_query.parameters["sample_count"], 2)
        self.assertEqual(update_query.parameters["accepted_update_count"], 1)
        stored = json.loads(update_query.parameters["metadata_json"])
        self.assertEqual(stored["quality"], "good")
        self.assertEqual(stored["adaptive_last_update"]["metadata"], {"scene": "clean"})

    def test_observe_reference_rejects_after_sample_target(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "reference_id": "voice:person_jamie:1",
                        "embedding": [1.0, 0.0],
                        "sample_count": 5,
                        "accepted_update_count": 4,
                        "target_sample_count": 5,
                        "metadata_json": "{}",
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.observe_voice_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "audio_speaker_id": "person_jamie",
                "primary_face_person_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.3,
                "recognized_count": 1,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.reason, "sample_target_reached")
        self.assertEqual(result.sample_count, 5)

    def test_observe_reference_rejects_low_similarity(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "reference_id": "face:person_jamie:1",
                        "embedding": [1.0, 0.0],
                        "sample_count": 1,
                        "accepted_update_count": 0,
                        "target_sample_count": 5,
                        "metadata_json": "{}",
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner)

        result = service.observe_face_embedding(
            person_id="person_jamie",
            embedding=[0.0, 1.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "primary_face_person_id": "person_jamie",
                "audio_speaker_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.3,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "below_similarity_threshold")
        self.assertEqual(result.sample_count, 1)
        self.assertAlmostEqual(result.similarity, 0.0)

    def test_observe_reference_rejects_model_mismatch(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "reference_id": "face:person_jamie:1",
                        "embedding": [1.0, 0.0],
                        "model": "facenet-vggface2",
                        "sample_count": 1,
                        "accepted_update_count": 0,
                        "target_sample_count": 5,
                        "metadata_json": "{}",
                    }
                ]
            ]
        )
        service = BiometricReferenceService(runner, face_embedding_model="other-face-model")

        result = service.observe_face_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "primary_face_person_id": "person_jamie",
                "audio_speaker_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.3,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "model_mismatch")

    def test_observe_face_embedding_rejects_face_only_evidence(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        result = service.observe_face_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "face",
                "primary_face_person_id": "person_jamie",
                "face_margin": 0.3,
                "recognized_count": 1,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "weak_evidence")
        # Privacy guard: weak evidence must never adapt a biometric reference.
        self.assertEqual(runner.queries, [])

    def test_observe_voice_embedding_rejects_face_only_evidence(self) -> None:
        runner = RecordingQueryRunner()
        service = BiometricReferenceService(runner)

        result = service.observe_voice_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "face",
                "primary_face_person_id": "person_jamie",
                "face_margin": 0.3,
                "recognized_count": 1,
                "unknown_count": 0,
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "weak_evidence")
        # Privacy guard: weak evidence must never adapt a biometric reference.
        self.assertEqual(runner.queries, [])

    def test_observe_voice_embedding_accepts_audio_face_agreement(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "reference_id": "voice:person_jamie:1",
                        "embedding": [1.0, 0.0],
                        "sample_count": 1,
                        "accepted_update_count": 0,
                        "target_sample_count": 5,
                        "metadata_json": "{}",
                    }
                ],
                [],
            ]
        )
        service = BiometricReferenceService(runner, voice_embedding_model="ecapa")

        result = service.observe_voice_embedding(
            person_id="person_jamie",
            embedding=[1.0, 0.0],
            evidence={
                "owner_id": "person_jamie",
                "owner_source": "audio_face_agree",
                "primary_face_person_id": "person_jamie",
                "audio_speaker_id": "person_jamie",
                "face_margin": 0.3,
                "voice_margin": 0.3,
                "recognized_count": 1,
                "unknown_count": 0,
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.modality, "voice")
        self.assertEqual(result.sample_count, 2)


if __name__ == "__main__":
    unittest.main()
