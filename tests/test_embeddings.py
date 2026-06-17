from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider, OpenAIConfigurationError, OpenAIEmbeddingProvider
import unittest


class MockOpenAIEmbeddingProviderTest(unittest.TestCase):
    def test_mock_embeddings_are_deterministic(self) -> None:
        provider = MockOpenAIEmbeddingProvider(dimension=8)

        first = provider.embed("Jamie asked about chargers")
        second = provider.embed("Jamie asked about chargers")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)

    def test_mock_embeddings_change_with_text(self) -> None:
        provider = MockOpenAIEmbeddingProvider(dimension=8)

        self.assertNotEqual(provider.embed("chargers"), provider.embed("projector"))

    def test_mock_embeddings_reject_invalid_dimension(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimension"):
            MockOpenAIEmbeddingProvider(dimension=0)


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddings()


class OpenAIEmbeddingProviderTest(unittest.TestCase):
    def test_openai_embeddings_use_configured_model_and_dimension(self) -> None:
        client = FakeOpenAIClient()
        provider = OpenAIEmbeddingProvider(
            api_key=None,
            model="text-embedding-3-small",
            dimension=3,
            client=client,
        )

        embedding = provider.embed("Jamie asked about chargers.")

        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.assertEqual(
            client.embeddings.calls,
            [
                {
                    "model": "text-embedding-3-small",
                    "input": "Jamie asked about chargers.",
                    "dimensions": 3,
                }
            ],
        )

    def test_openai_embeddings_require_api_key_without_injected_client(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key=None, dimension=3)

        with self.assertRaisesRegex(OpenAIConfigurationError, "OPENAI_API_KEY"):
            provider.embed("chargers")


if __name__ == "__main__":
    unittest.main()
