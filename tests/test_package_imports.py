import inspect
import unittest

import tailwag_memory
from tailwag_memory import (
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    EmbeddingProvider,
    EpisodeIngestionService,
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    EpisodeMemoryExtractionService,
    EpisodeMemoryResult,
    EpisodeRecordResult,
    EpisodeRetrievalService,
    EventAttendeeInput,
    EventIngestionService,
    EventInput,
    EventResult,
    EventRetrievalService,
    MemoryConsolidationResult,
    MemoryConsolidationService,
    MemoryItemInput,
    MemoryItemResult,
    MemoryItemService,
    MockOpenAIEmbeddingProvider,
    Neo4jQueryRunner,
    OpenAIMemoryConsolidationProvider,
    OpenAIConfigurationError,
    OpenAIEmbeddingProvider,
    PersonContextItem,
    PersonContextRetrievalService,
    PersonContextSource,
    PersonContextTranscriptLine,
    PersonIngestionService,
    PersonInput,
    PersonMemoryConsolidationResult,
    PersonMemoryContextService,
    PersonMemoryExtractionResult,
    PersonRecognitionResult,
    PersonRecognitionService,
    PlaceInput,
    QueryRunner,
    SearchQuery,
    Settings,
    TailwagMemoryClient,
    initialize_schema,
    load_settings,
)


class PackageImportTest(unittest.TestCase):
    def test_public_facade_exports_consumer_imports(self) -> None:
        expected_exports = {
            "DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES",
            "EmbeddingProvider",
            "EpisodeIngestionService",
            "EpisodeInput",
            "EpisodeMemoryExtractionResult",
            "EpisodeMemoryExtractionService",
            "EpisodeMemoryResult",
            "EpisodeRecordResult",
            "EpisodeRetrievalService",
            "EventAttendeeInput",
            "EventIngestionService",
            "EventInput",
            "EventResult",
            "EventRetrievalService",
            "MemoryConsolidationResult",
            "MemoryConsolidationService",
            "MemoryItemInput",
            "MemoryItemResult",
            "MemoryItemService",
            "MockOpenAIEmbeddingProvider",
            "Neo4jQueryRunner",
            "OpenAIMemoryConsolidationProvider",
            "OpenAIConfigurationError",
            "OpenAIEmbeddingProvider",
            "PersonContextItem",
            "PersonContextRetrievalService",
            "PersonContextSource",
            "PersonContextTranscriptLine",
            "PersonIngestionService",
            "PersonInput",
            "PersonMemoryConsolidationResult",
            "PersonMemoryContextService",
            "PersonMemoryExtractionResult",
            "PersonRecognitionResult",
            "PersonRecognitionService",
            "PlaceInput",
            "QueryRunner",
            "SearchQuery",
            "Settings",
            "TailwagMemoryClient",
            "initialize_schema",
            "load_settings",
        }
        imported = {
            DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
            EmbeddingProvider,
            EpisodeIngestionService,
            EpisodeInput,
            EpisodeMemoryExtractionResult,
            EpisodeMemoryExtractionService,
            EpisodeMemoryResult,
            EpisodeRecordResult,
            EpisodeRetrievalService,
            EventAttendeeInput,
            EventIngestionService,
            EventInput,
            EventResult,
            EventRetrievalService,
            MemoryConsolidationResult,
            MemoryConsolidationService,
            MemoryItemInput,
            MemoryItemResult,
            MemoryItemService,
            MockOpenAIEmbeddingProvider,
            Neo4jQueryRunner,
            OpenAIMemoryConsolidationProvider,
            OpenAIConfigurationError,
            OpenAIEmbeddingProvider,
            PersonContextItem,
            PersonContextRetrievalService,
            PersonContextSource,
            PersonContextTranscriptLine,
            PersonIngestionService,
            PersonInput,
            PersonMemoryConsolidationResult,
            PersonMemoryContextService,
            PersonMemoryExtractionResult,
            PersonRecognitionResult,
            PersonRecognitionService,
            PlaceInput,
            QueryRunner,
            SearchQuery,
            Settings,
            TailwagMemoryClient,
            initialize_schema,
            load_settings,
        }

        self.assertEqual(set(tailwag_memory.__all__), expected_exports)
        self.assertEqual(len(imported), len(expected_exports))
        self.assertIs(tailwag_memory.TailwagMemoryClient, TailwagMemoryClient)
        self.assertIs(tailwag_memory.Settings, Settings)
        self.assertIs(tailwag_memory.EpisodeInput, EpisodeInput)
        self.assertIs(tailwag_memory.EpisodeIngestionService, EpisodeIngestionService)
        self.assertIs(tailwag_memory.EpisodeRetrievalService, EpisodeRetrievalService)

    def test_client_exposes_email_rekey_contract(self) -> None:
        signature = inspect.signature(TailwagMemoryClient.rekey_person_by_email)

        self.assertEqual(list(signature.parameters), ["self", "email", "new_person_id"])
        self.assertEqual(signature.parameters["email"].annotation, "str")
        self.assertEqual(signature.parameters["new_person_id"].annotation, "str")
        self.assertEqual(signature.return_annotation, "bool")


if __name__ == "__main__":
    unittest.main()
