import inspect
import unittest

import tailwag_memory
import tailwag_memory.memory_items as memory_items
from tailwag_memory import (
    AffectScore,
    AffectScoringProvider,
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    EmbeddingProvider,
    EpisodeIngestionService,
    EpisodeInput,
    EpisodeMentionInput,
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
    MemoryItemMergeResult,
    MemoryItemResult,
    MemoryItemService,
    MockOpenAIEmbeddingProvider,
    Neo4jQueryRunner,
    OpenAIMemoryConsolidationProvider,
    OpenAIConfigurationError,
    OpenAIEmbeddingProvider,
    FoldEnsembleAffectProvider,
    PersonContextItem,
    PersonContextRetrievalService,
    PersonContextSource,
    PersonContextTranscriptLine,
    PersonEpisodeAffectPoint,
    PersonEpisodeTranscriptPoint,
    PersonEpisodeTranscriptService,
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
            "AffectScore",
            "AffectScoringProvider",
            "DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES",
            "EmbeddingProvider",
            "EpisodeIngestionService",
            "EpisodeInput",
            "EpisodeMentionInput",
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
            "MemoryItemMergeResult",
            "MemoryItemResult",
            "MemoryItemService",
            "MockOpenAIEmbeddingProvider",
            "Neo4jQueryRunner",
            "OpenAIMemoryConsolidationProvider",
            "OpenAIConfigurationError",
            "OpenAIEmbeddingProvider",
            "FoldEnsembleAffectProvider",
            "PersonContextItem",
            "PersonContextRetrievalService",
            "PersonContextSource",
            "PersonContextTranscriptLine",
            "PersonEpisodeAffectPoint",
            "PersonEpisodeTranscriptPoint",
            "PersonEpisodeTranscriptService",
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
            AffectScore,
            AffectScoringProvider,
            DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
            EmbeddingProvider,
            EpisodeIngestionService,
            EpisodeInput,
            EpisodeMentionInput,
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
            MemoryItemMergeResult,
            MemoryItemResult,
            MemoryItemService,
            MockOpenAIEmbeddingProvider,
            Neo4jQueryRunner,
            OpenAIMemoryConsolidationProvider,
            OpenAIConfigurationError,
            OpenAIEmbeddingProvider,
            FoldEnsembleAffectProvider,
            PersonContextItem,
            PersonContextRetrievalService,
            PersonContextSource,
            PersonContextTranscriptLine,
            PersonEpisodeAffectPoint,
            PersonEpisodeTranscriptPoint,
            PersonEpisodeTranscriptService,
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
        self.assertIs(tailwag_memory.EpisodeMentionInput, EpisodeMentionInput)
        self.assertIs(tailwag_memory.EpisodeIngestionService, EpisodeIngestionService)
        self.assertIs(tailwag_memory.EpisodeRetrievalService, EpisodeRetrievalService)
        self.assertNotIn("address_item", tailwag_memory.__all__)
        self.assertNotIn("address_item", memory_items.__all__)
        self.assertNotIn("stable_memory_id", tailwag_memory.__all__)
        self.assertNotIn("stable_memory_id", memory_items.__all__)

    def test_client_exposes_email_rekey_contract(self) -> None:
        signature = inspect.signature(TailwagMemoryClient.rekey_person_by_email)

        self.assertEqual(list(signature.parameters), ["self", "email", "new_person_id"])
        self.assertEqual(signature.parameters["email"].annotation, "str")
        self.assertEqual(signature.parameters["new_person_id"].annotation, "str")
        self.assertEqual(signature.return_annotation, "bool")


if __name__ == "__main__":
    unittest.main()
