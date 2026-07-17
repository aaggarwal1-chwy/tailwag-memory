from dataclasses import dataclass
import os
from types import SimpleNamespace
import unittest

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - optional dependency guard
    TestClient = None

from tailwag_memory.models import (
    BiometricCandidate,
    BiometricEnrollmentResult,
    BiometricSearchResult,
    BiometricUpdateResult,
    EpisodeInput,
    EpisodeRecordResult,
    IdentityResolutionResult,
    OwnerResolutionResult,
    PersonInput,
    PersonMemoryExtractionResult,
    PersonProfile,
    VerifiedProfile,
)

API_BASE = "/argos/providers/memory/resources/memory/request"


@unittest.skipIf(TestClient is None, "Install tailwag-memory[api] to run API tests.")
class TailwagApiAppTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TAILWAG_API_BEARER_TOKEN"] = "test-token"
        os.environ["TAILWAG_API_DOCS_ENABLED"] = "true"

    def tearDown(self) -> None:
        os.environ.pop("TAILWAG_API_BEARER_TOKEN", None)
        os.environ.pop("TAILWAG_API_DOCS_ENABLED", None)

    def test_health_is_open_and_does_not_create_client(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        app = create_app()

        def fail_client():
            raise AssertionError("health should not create a Tailwag client")

        app.dependency_overrides[get_client] = fail_client
        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "tailwag-memory"})

    def test_provider_health_uses_bearer_token_and_does_not_create_client(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        app = create_app()

        def fail_client():
            raise AssertionError("provider health should not create a Tailwag client")

        app.dependency_overrides[get_client] = fail_client
        client = TestClient(app)

        unauthenticated = client.get("/argos/providers/memory/resources/memory/health")
        authenticated = client.get(
            "/argos/providers/memory/resources/memory/health",
            headers=_auth_header(),
        )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(
            authenticated.json(),
            {
                "ok": True,
                "service": "tailwag-memory",
                "provider": "memory",
                "resource": "memory",
            },
        )

    def test_memory_routes_require_bearer_token(self) -> None:
        from tailwag_memory.api.app import create_app

        client = TestClient(create_app())
        response = client.post(f"{API_BASE}/person_context", json={"person_id": "person_jamie"})

        self.assertEqual(response.status_code, 401)

    def test_memory_routes_require_memory_provider_and_resource(self) -> None:
        from tailwag_memory.api.app import create_app

        client = TestClient(create_app())
        wrong_provider = client.post(
            "/argos/providers/search/resources/memory/request/person_context",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        wrong_resource = client.post(
            "/argos/providers/memory/resources/search/request/person_context",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        legacy_root = client.post(
            "/person_context",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )

        self.assertEqual(wrong_provider.status_code, 404)
        self.assertEqual(wrong_resource.status_code, 404)
        self.assertEqual(legacy_root.status_code, 404)

    def test_openapi_exposes_bearer_authorize_button(self) -> None:
        from tailwag_memory.api.app import create_app

        response = TestClient(create_app()).get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        security_schemes = response.json()["components"]["securitySchemes"]
        self.assertEqual(security_schemes["TailwagBearer"]["type"], "http")
        self.assertEqual(security_schemes["TailwagBearer"]["scheme"], "bearer")

    def test_openapi_docs_are_disabled_by_default(self) -> None:
        from tailwag_memory.api.app import create_app

        os.environ.pop("TAILWAG_API_DOCS_ENABLED", None)

        client = TestClient(create_app())

        self.assertEqual(client.get("/docs").status_code, 404)
        self.assertEqual(client.get("/openapi.json").status_code, 404)

    def test_person_context_calls_markdown_context_not_structured_context(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake

        response = TestClient(app).post(
            f"{API_BASE}/person_context",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "semantic_scope": "chargers",
                "current_text": "robot demo",
                "memory_limit": 4,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["person_id"], "person_jamie")
        self.assertEqual(body["context_markdown"], "[PERSON MEMORY]\n- likes robot demos")
        self.assertTrue(body["generated_at"])
        self.assertEqual(
            fake.calls,
            [
                (
                    "person_context",
                    "person_jamie",
                    {
                        "semantic_scope": "chargers",
                        "current_text": "robot demo",
                        "now": None,
                        "memory_limit": 4,
                    },
                )
            ],
        )

    def test_episode_endpoint_uses_existing_episode_input_shape(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        payload = {
            "episode": {
                "id": "episode_1",
                "episode_type": "conversation",
                "start_time": "2026-06-18T10:00:00+00:00",
                "end_time": None,
                "transcript": "Jamie: I like robot demos.",
                "retention_class": "standard",
                "place": {"building_code": "MAIN", "room_id": "101"},
                "participants": [
                    {
                        "id": "person_jamie",
                        "display_name": "Jamie",
                        "official_name": "Jamie Example",
                        "role": "speaker",
                    }
                ],
            },
            "extract_memory": False,
            "enqueue_memory_extraction": False,
        }

        response = TestClient(app).post(f"{API_BASE}/episodes_record", headers=_auth_header(), json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "episode_id": "episode_1",
                "memory_extraction_job_id": None,
                "memory_results": [
                    {
                        "person_id": "person_jamie",
                        "update_requested": True,
                        "created_memory_ids": ["mem_1"],
                        "addressed_memory_ids": [],
                        "supported_memory_ids": [],
                        "skipped_ops": [],
                        "error": None,
                    }
                ],
                "memory_errors": [],
            },
        )
        self.assertIsInstance(fake.calls[0][1], EpisodeInput)
        self.assertEqual(fake.calls[0][1].participants[0].official_name, "Jamie Example")
        self.assertFalse(fake.calls[0][2]["extract_memory"])
        self.assertFalse(fake.calls[0][2]["enqueue_memory_extraction"])

    def test_episode_endpoint_rejects_malformed_payload_as_422(self) -> None:
        from tailwag_memory.api.app import create_app

        response = TestClient(create_app()).post(
            f"{API_BASE}/episodes_record",
            headers=_auth_header(),
            json={"episode": {"id": "episode_1"}, "extract_memory": False},
        )

        self.assertEqual(response.status_code, 422)

    def test_people_endpoints_wrap_primitive_client_returns(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        upsert = client.post(
            f"{API_BASE}/people_upsert",
            headers=_auth_header(),
            json={"person": {"id": "person_jamie", "display_name": "Jamie"}},
        )
        archive = client.post(
            f"{API_BASE}/people_archive",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        rekey = client.post(
            f"{API_BASE}/people_rekey_by_email",
            headers=_auth_header(),
            json={"email": "jamie@example.com", "new_person_id": "person_jamie"},
        )

        self.assertEqual(upsert.json(), {"person_id": "person_jamie"})
        self.assertIsInstance(fake.calls[0][1], PersonInput)
        self.assertEqual(archive.json(), {"archived": True})
        self.assertEqual(rekey.json(), {"rekeyed": True})

    def test_semantic_search_returns_existing_client_shape(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake

        response = TestClient(app).post(
            f"{API_BASE}/semantic_search",
            headers=_auth_header(),
            json={"text": "demos", "person_id": "person_jamie", "building_code": "MAIN", "limit": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "episodes": [
                    {"episode_id": "episode_1", "transcript": "Jamie: I like robot demos."}
                ],
                "memory_items": [],
            },
        )
        self.assertEqual(
            fake.calls,
            [
                (
                    "search_semantic_memory",
                    {
                        "text": "demos",
                        "person_id": "person_jamie",
                        "building_code": "MAIN",
                        "limit": 2,
                        "now": None,
                    },
                )
            ],
        )

    def test_identity_routes_call_matching_client_methods(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        profile = client.post(
            f"{API_BASE}/people_profile",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        resolved = client.post(
            f"{API_BASE}/identity_resolve",
            headers=_auth_header(),
            json={
                "shared_first_name": "Jamie",
                "shared_last_name": "Example",
                "shared_name": "Jamie Example",
                "site_code": "BOS3",
            },
        )
        verified = client.post(
            f"{API_BASE}/identity_verified_profile",
            headers=_auth_header(),
            json={"username": "jexample", "official_name": "Jamie Example", "site_code": "BOS3"},
        )

        self.assertEqual(profile.json()["person_id"], "person_jamie")
        self.assertTrue(resolved.json()["success"])
        self.assertEqual(verified.json()["username"], "jexample")
        self.assertEqual(
            fake.calls,
            [
                ("person_profile", "person_jamie"),
                (
                    "resolve_identity",
                    {
                        "shared_first_name": "Jamie",
                        "shared_last_name": "Example",
                        "shared_name": "Jamie Example",
                        "site_code": "BOS3",
                    },
                ),
                (
                    "get_verified_profile",
                    {
                        "username": "jexample",
                        "official_name": "Jamie Example",
                        "site_code": "BOS3",
                    },
                ),
            ],
        )

    def test_biometric_search_routes_delegate_and_narrow_response(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        face = client.post(
            f"{API_BASE}/biometrics_face_search",
            headers=_auth_header(),
            json={"embedding": [0.1, 0.2], "limit": 2, "site_code": "BOS3"},
        )
        voice = client.post(
            f"{API_BASE}/biometrics_voice_search",
            headers=_auth_header(),
            json={"embedding": [0.3, 0.4], "limit": 2, "site_code": "BOS3"},
        )

        self.assertEqual(face.status_code, 200)
        self.assertTrue(face.json()["recognized"])
        self.assertEqual(face.json()["candidates"][0]["person_id"], "person_jamie")
        self.assertNotIn("embedding", face.json()["candidates"][0])
        self.assertEqual(voice.status_code, 200)
        self.assertEqual(
            fake.calls,
            [
                (
                    "search_face",
                    {"embedding": [0.1, 0.2], "limit": 2, "site_code": "BOS3"},
                ),
                (
                    "search_voice",
                    {"embedding": [0.3, 0.4], "limit": 2, "site_code": "BOS3"},
                ),
            ],
        )

    def test_biometric_write_routes_delegate_to_matching_client_methods(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        face_enroll = client.post(
            f"{API_BASE}/biometrics_face_references",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "embedding": [0.1, 0.2],
                "metadata": {"source": "test"},
                "consent_status": "consented",
            },
        )
        voice_enroll = client.post(
            f"{API_BASE}/biometrics_voice_references",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "embedding": [0.3, 0.4],
                "metadata": {"source": "test"},
                "consent_status": "revoked",
            },
        )
        face_observe = client.post(
            f"{API_BASE}/biometrics_face_observations",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "embedding": [0.5, 0.6],
                "evidence": {"owner_source": "audio_face_agree"},
                "metadata": {"source": "runtime"},
            },
        )
        voice_observe = client.post(
            f"{API_BASE}/biometrics_voice_observations",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "embedding": [0.7, 0.8],
                "evidence": {"owner_source": "audio_face_agree"},
                "metadata": {"source": "runtime"},
            },
        )

        self.assertEqual(face_enroll.json()["status"], "saved")
        self.assertEqual(voice_enroll.json()["status"], "rejected")
        self.assertEqual(voice_enroll.json()["reason"], "consent_required")
        self.assertTrue(face_observe.json()["accepted"])
        self.assertTrue(voice_observe.json()["accepted"])
        self.assertEqual(
            [call[0] for call in fake.calls],
            [
                "enroll_face_reference",
                "enroll_voice_reference",
                "observe_face_embedding",
                "observe_voice_embedding",
            ],
        )

    def test_voice_reference_and_turn_owner_routes_delegate(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        exists = client.post(
            f"{API_BASE}/biometrics_voice_references_exists",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        owner = client.post(
            f"{API_BASE}/turn_owner_resolve",
            headers=_auth_header(),
            json={
                "primary_face_candidate": {
                    "person_id": "person_jamie",
                    "display_name": "Jamie",
                    "score": 0.91,
                },
                "visible_face_candidates": [
                    {"person_id": "person_jamie", "display_name": "Jamie", "score": 0.91}
                ],
                "voice_candidate": {
                    "person_id": "person_jamie",
                    "display_name": "Jamie",
                    "score": 0.87,
                },
                "policy_context": {"source": "test"},
            },
        )

        self.assertEqual(exists.json(), {"has_voice_reference": True})
        self.assertEqual(owner.json()["owner_id"], "person_jamie")
        self.assertEqual(owner.json()["owner_source"], "audio_face_agree")
        self.assertEqual(
            fake.calls,
            [
                ("has_voice_reference", "person_jamie"),
                (
                    "resolve_turn_owner",
                    {
                        "primary_face_candidate": {
                            "person_id": "person_jamie",
                            "display_name": "Jamie",
                            "score": 0.91,
                            "metadata": {},
                        },
                        "visible_face_candidates": [
                            {
                                "person_id": "person_jamie",
                                "display_name": "Jamie",
                                "score": 0.91,
                                "metadata": {},
                            }
                        ],
                        "voice_candidate": {
                            "person_id": "person_jamie",
                            "display_name": "Jamie",
                            "score": 0.87,
                            "metadata": {},
                        },
                        "policy_context": {"source": "test"},
                    },
                ),
            ],
        )

    def test_biometric_routes_reject_raw_media_and_wrong_dimensions(self) -> None:
        from tailwag_memory.api.app import create_app
        from tailwag_memory.api.dependencies import get_client

        fake = _FakeClient()
        app = create_app()
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        raw_media = client.post(
            f"{API_BASE}/biometrics_face_references",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "embedding": [0.1, 0.2],
                "metadata": {"raw_image": "data:image/png;base64,abc"},
            },
        )
        unexpected_field = client.post(
            f"{API_BASE}/biometrics_voice_observations",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "embedding": [0.1, 0.2],
                "evidence": {"owner_source": "audio_face_agree"},
                "confidence": 0.99,
            },
        )
        wrong_dimension = client.post(
            f"{API_BASE}/biometrics_voice_search",
            headers=_auth_header(),
            json={"embedding": [0.1], "limit": 2},
        )

        self.assertEqual(raw_media.status_code, 422)
        self.assertEqual(unexpected_field.status_code, 422)
        self.assertEqual(wrong_dimension.status_code, 422)

    def test_openapi_exposes_argos_parity_routes_without_raw_media_fields(self) -> None:
        from tailwag_memory.api.app import create_app

        response = TestClient(create_app()).get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        document = response.json()
        paths = set(document["paths"])
        self.assertIn(f"{API_BASE}/biometrics_face_search", paths)
        self.assertIn(f"{API_BASE}/person_context", paths)
        self.assertIn(f"{API_BASE}/turn_owner_resolve", paths)
        rendered = str(document)
        self.assertIn("embedding", rendered)
        self.assertNotIn("raw_image", rendered)
        self.assertNotIn("raw_audio", rendered)


def _auth_header() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@dataclass
class _FakeClient:
    calls: list = None
    settings: object = None

    def __post_init__(self) -> None:
        self.calls = []
        self.settings = SimpleNamespace(face_embedding_dimension=2, voice_embedding_dimension=2)

    def person_context(self, person_id: str, **kwargs) -> str:
        self.calls.append(("person_context", person_id, kwargs))
        return "[PERSON MEMORY]\n- likes robot demos"

    def record_episode(
        self,
        episode: EpisodeInput,
        *,
        extract_memory: bool = True,
        enqueue_memory_extraction: bool = True,
    ) -> EpisodeRecordResult:
        self.calls.append(
            (
                "record_episode",
                episode,
                {
                    "extract_memory": extract_memory,
                    "enqueue_memory_extraction": enqueue_memory_extraction,
                },
            )
        )
        return EpisodeRecordResult(
            episode_id=episode.id,
            memory_results=[
                PersonMemoryExtractionResult(
                    person_id="person_jamie",
                    update_requested=True,
                    created_memory_ids=["mem_1"],
                )
            ],
        )

    def search_semantic_memory(self, **kwargs):
        self.calls.append(("search_semantic_memory", kwargs))
        return {
            "episodes": [{"episode_id": "episode_1", "transcript": "Jamie: I like robot demos."}],
            "memory_items": [],
        }

    def upsert_person(self, person: PersonInput) -> str:
        self.calls.append(("upsert_person", person))
        return person.id

    def archive_person(self, person_id: str) -> bool:
        self.calls.append(("archive_person", person_id))
        return True

    def rekey_person_by_email(self, email: str, new_person_id: str) -> bool:
        self.calls.append(("rekey_person_by_email", email, new_person_id))
        return True

    def person_profile(self, person_id: str) -> PersonProfile:
        self.calls.append(("person_profile", person_id))
        return PersonProfile(
            person_id=person_id,
            display_name="Jamie",
            email="jamie@example.com",
            directory_profile_lines=("Jamie Example",),
        )

    def resolve_identity(self, **kwargs) -> IdentityResolutionResult:
        self.calls.append(("resolve_identity", kwargs))
        return IdentityResolutionResult(
            success=True,
            status="matched",
            message="matched",
            data={"person_id": "person_jamie"},
        )

    def get_verified_profile(self, **kwargs) -> VerifiedProfile:
        self.calls.append(("get_verified_profile", kwargs))
        return VerifiedProfile(
            person_id="person_jamie",
            official_name=kwargs["official_name"],
            username=kwargs["username"],
            employee_email="jamie@example.com",
        )

    def search_face(self, **kwargs) -> BiometricSearchResult:
        self.calls.append(("search_face", kwargs))
        return BiometricSearchResult(
            modality="face",
            candidates=[
                BiometricCandidate(
                    person_id="person_jamie",
                    display_name="Jamie",
                    score=0.91,
                    reference_id="face-ref-1",
                    metadata={"source": "test"},
                )
            ],
            recognized=True,
            status="accepted",
            reason="matched",
            threshold=0.6,
            top_score=0.91,
            margin=0.3,
        )

    def search_voice(self, **kwargs) -> BiometricSearchResult:
        self.calls.append(("search_voice", kwargs))
        return BiometricSearchResult(
            modality="voice",
            candidates=[
                BiometricCandidate(person_id="person_jamie", display_name="Jamie", score=0.87)
            ],
            recognized=True,
            status="accepted",
            reason="matched",
            threshold=0.5,
            top_score=0.87,
            margin=0.27,
        )

    def enroll_face_reference(self, **kwargs) -> BiometricEnrollmentResult:
        self.calls.append(("enroll_face_reference", kwargs))
        return BiometricEnrollmentResult(
            saved=True,
            status="saved",
            reason="saved",
            person_id=kwargs["person_id"],
            reference_id="face-ref-1",
        )

    def enroll_voice_reference(self, **kwargs) -> BiometricEnrollmentResult:
        self.calls.append(("enroll_voice_reference", kwargs))
        if kwargs["consent_status"] != "consented":
            return BiometricEnrollmentResult(
                saved=False,
                status="rejected",
                reason="consent_required",
                person_id=kwargs["person_id"],
            )
        return BiometricEnrollmentResult(
            saved=True,
            status="saved",
            reason="saved",
            person_id=kwargs["person_id"],
            reference_id="voice-ref-1",
        )

    def observe_face_embedding(self, **kwargs) -> BiometricUpdateResult:
        self.calls.append(("observe_face_embedding", kwargs))
        return BiometricUpdateResult(
            accepted=True,
            status="updated",
            reason="updated",
            person_id=kwargs["person_id"],
            reference_id="face-ref-1",
            modality="face",
            sample_count=2,
            target_sample_count=5,
            similarity=0.92,
        )

    def observe_voice_embedding(self, **kwargs) -> BiometricUpdateResult:
        self.calls.append(("observe_voice_embedding", kwargs))
        return BiometricUpdateResult(
            accepted=True,
            status="updated",
            reason="updated",
            person_id=kwargs["person_id"],
            reference_id="voice-ref-1",
            modality="voice",
            sample_count=2,
            target_sample_count=5,
            similarity=0.88,
        )

    def has_voice_reference(self, person_id: str) -> bool:
        self.calls.append(("has_voice_reference", person_id))
        return True

    def resolve_turn_owner(self, **kwargs) -> OwnerResolutionResult:
        self.calls.append(("resolve_turn_owner", kwargs))
        return OwnerResolutionResult(
            audio_speaker_id="person_jamie",
            top_score=0.87,
            runner_up_score=0.6,
            margin=0.27,
            speaker_visible=True,
            owner_id="person_jamie",
            owner_source="audio_face_agree",
            owner_confidence=0.87,
        )


if __name__ == "__main__":
    unittest.main()
