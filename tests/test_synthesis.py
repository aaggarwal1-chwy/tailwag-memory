from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.models import PersonContextItem
from tailwag_memory.retrieval import PersonContextRetrievalService
from tailwag_memory.synthesis import (
    UNKNOWN_PERSON_MESSAGE,
    OpenAIPersonContextProvider,
    PersonContextSynthesisService,
)
import unittest


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    def synthesize(self, *, person_id, display_name, items):
        self.calls.append(
            {
                "person_id": person_id,
                "display_name": display_name,
                "items": items,
            }
        )
        return "Jamie recently discussed chargers and has a design review coming up."


class PersonContextSynthesisServiceTest(unittest.TestCase):
    def test_unknown_person_returns_exact_message_without_provider_call(self) -> None:
        provider = FakeProvider()
        service = PersonContextSynthesisService(
            PersonContextRetrievalService(RecordingQueryRunner(results=[[]])),
            provider,
        )

        result = service.context_for_person("person_missing")

        self.assertEqual(result, UNKNOWN_PERSON_MESSAGE)
        self.assertEqual(provider.calls, [])

    def test_person_with_no_recent_items_returns_local_paragraph(self) -> None:
        provider = FakeProvider()
        service = PersonContextSynthesisService(
            PersonContextRetrievalService(
                RecordingQueryRunner(
                    results=[
                        [{"person_id": "person_jamie", "display_name": "Jamie"}],
                        [],
                        [],
                    ]
                )
            ),
            provider,
        )

        result = service.context_for_person("person_jamie")

        self.assertIn("Jamie", result)
        self.assertIn("no recent related events or episodes", result)
        self.assertEqual(provider.calls, [])

    def test_person_with_items_uses_provider(self) -> None:
        provider = FakeProvider()
        service = PersonContextSynthesisService(
            PersonContextRetrievalService(
                RecordingQueryRunner(
                    results=[
                        [{"person_id": "person_jamie", "display_name": "Jamie"}],
                        [
                            {
                                "item_id": "episode_1",
                                "item_type": "episode",
                                "text": "Summary: Asha asked about chargers.\nTranscript:\nAsha: Do we have chargers?\nJamie: I found them.",
                                "start_time": "2026-06-16T14:00:00+00:00",
                            }
                        ],
                        [],
                    ]
                )
            ),
            provider,
        )

        result = service.context_for_person("person_jamie")

        self.assertIn("chargers", result)
        self.assertEqual(provider.calls[0]["person_id"], "person_jamie")
        self.assertEqual(provider.calls[0]["items"][0].item_id, "episode_1")
        self.assertIn("Jamie: I found them.", provider.calls[0]["items"][0].text)

    def test_person_with_semantic_scope_no_matches_returns_local_paragraph(self) -> None:
        provider = FakeProvider()
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [],
                [],
            ]
        )
        service = PersonContextSynthesisService(
            PersonContextRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8)),
            provider,
        )

        result = service.context_for_person("person_jamie", semantic_scope="chargers")

        self.assertIn("Jamie", result)
        self.assertIn("no episodes matched the semantic scope: chargers", result)
        self.assertEqual(provider.calls, [])


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {"output_text": "Jamie recently asked about chargers."}


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


class OpenAIPersonContextProviderTest(unittest.TestCase):
    def test_openai_provider_sends_evidence_and_returns_text(self) -> None:
        client = FakeOpenAIClient()
        provider = OpenAIPersonContextProvider(api_key=None, model="gpt-test", client=client)

        result = provider.synthesize(
            person_id="person_jamie",
            display_name="Jamie",
            items=[
                PersonContextItem(
                    item_id="episode_1",
                    item_type="episode",
                    text="Jamie asked about chargers.",
                    start_time="2026-06-16T14:00:00+00:00",
                )
            ],
        )

        self.assertEqual(result, "Jamie recently asked about chargers.")
        self.assertEqual(client.responses.calls[0]["model"], "gpt-test")
        self.assertIn("one concise natural-language paragraph", client.responses.calls[0]["input"][0]["content"])
        self.assertIn("episode_1", client.responses.calls[0]["input"][1]["content"])


if __name__ == "__main__":
    unittest.main()
