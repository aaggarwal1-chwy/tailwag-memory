from dataclasses import dataclass
import os
import unittest

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - optional dependency guard
    TestClient = None

from tailwag_memory.models import (
    EpisodeInput,
    EpisodeRecordResult,
    PersonInput,
    PersonMemoryExtractionResult,
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

    def test_memory_routes_require_bearer_token(self) -> None:
        from tailwag_memory.api.app import create_app

        client = TestClient(create_app())
        response = client.post(f"{API_BASE}/person-context", json={"person_id": "person_jamie"})

        self.assertEqual(response.status_code, 401)

    def test_memory_routes_require_memory_provider_and_resource(self) -> None:
        from tailwag_memory.api.app import create_app

        client = TestClient(create_app())
        wrong_provider = client.post(
            "/argos/providers/search/resources/memory/request/person-context",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        wrong_resource = client.post(
            "/argos/providers/memory/resources/search/request/person-context",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        legacy_root = client.post(
            "/person-context",
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
            f"{API_BASE}/person-context",
            headers=_auth_header(),
            json={
                "person_id": "person_jamie",
                "limit": 3,
                "semantic_scope": "chargers",
                "current_text": "robot demo",
                "memory_limit": 4,
                "recent_episode_limit": 2,
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
                        "limit": 3,
                        "semantic_scope": "chargers",
                        "current_text": "robot demo",
                        "now": None,
                        "memory_limit": 4,
                        "recent_episode_limit": 2,
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
        }

        response = TestClient(app).post(f"{API_BASE}/episodes", headers=_auth_header(), json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "episode_id": "episode_1",
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

    def test_episode_endpoint_rejects_malformed_payload_as_422(self) -> None:
        from tailwag_memory.api.app import create_app

        response = TestClient(create_app()).post(
            f"{API_BASE}/episodes",
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
            f"{API_BASE}/people",
            headers=_auth_header(),
            json={"person": {"id": "person_jamie", "display_name": "Jamie"}},
        )
        archive = client.post(
            f"{API_BASE}/people/archive",
            headers=_auth_header(),
            json={"person_id": "person_jamie"},
        )
        rekey = client.post(
            f"{API_BASE}/people/rekey-by-email",
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
            f"{API_BASE}/semantic-search",
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


def _auth_header() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@dataclass
class _FakeClient:
    calls: list = None

    def __post_init__(self) -> None:
        self.calls = []

    def person_context_structured(self, *args, **kwargs):
        raise AssertionError("API must not call person_context_structured")

    def person_context(self, person_id: str, **kwargs) -> str:
        self.calls.append(("person_context", person_id, kwargs))
        return "[PERSON MEMORY]\n- likes robot demos"

    def record_episode(self, episode: EpisodeInput, *, extract_memory: bool = True) -> EpisodeRecordResult:
        self.calls.append(("record_episode", episode, {"extract_memory": extract_memory}))
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


if __name__ == "__main__":
    unittest.main()
