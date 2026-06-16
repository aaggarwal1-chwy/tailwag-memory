from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
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


if __name__ == "__main__":
    unittest.main()
