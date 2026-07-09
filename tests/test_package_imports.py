import inspect
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import tailwag_memory
import tailwag_memory.memory_items as memory_items
from tailwag_memory import (
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    BiometricCandidate,
    BiometricEnrollmentResult,
    BiometricSearchResult,
    BiometricUpdateResult,
    DirectoryPersonRecord,
    DirectorySyncResult,
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
    IdentityCandidate,
    IdentityResolutionResult,
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
    OwnerResolutionResult,
    PersonContextItem,
    PersonContextResult,
    PersonContextRetrievalService,
    PersonContextSource,
    PersonContextTranscriptLine,
    PersonIngestionService,
    PersonInput,
    PersonMemoryConsolidationResult,
    PersonMemoryContextService,
    PersonMemoryExtractionResult,
    PersonProfile,
    PersonRecognitionResult,
    PlaceInput,
    QueryRunner,
    SearchQuery,
    Settings,
    TailwagMemoryClient,
    VerifiedProfile,
    initialize_schema,
    load_settings,
)


class PackageImportTest(unittest.TestCase):
    def test_public_facade_exports_consumer_imports(self) -> None:
        expected_exports = {
            "DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES",
            "BiometricCandidate",
            "BiometricEnrollmentResult",
            "BiometricSearchResult",
            "BiometricUpdateResult",
            "DirectoryPersonRecord",
            "DirectorySyncResult",
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
            "IdentityCandidate",
            "IdentityResolutionResult",
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
            "OwnerResolutionResult",
            "PersonContextItem",
            "PersonContextResult",
            "PersonContextRetrievalService",
            "PersonContextSource",
            "PersonContextTranscriptLine",
            "PersonIngestionService",
            "PersonInput",
            "PersonMemoryConsolidationResult",
            "PersonMemoryContextService",
            "PersonMemoryExtractionResult",
            "PersonProfile",
            "PersonRecognitionResult",
            "PlaceInput",
            "QueryRunner",
            "SearchQuery",
            "Settings",
            "TailwagMemoryClient",
            "VerifiedProfile",
            "initialize_schema",
            "load_settings",
        }
        imported = {
            DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
            BiometricCandidate,
            BiometricEnrollmentResult,
            BiometricSearchResult,
            BiometricUpdateResult,
            DirectoryPersonRecord,
            DirectorySyncResult,
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
            IdentityCandidate,
            IdentityResolutionResult,
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
            OwnerResolutionResult,
            PersonContextItem,
            PersonContextResult,
            PersonContextRetrievalService,
            PersonContextSource,
            PersonContextTranscriptLine,
            PersonIngestionService,
            PersonInput,
            PersonMemoryConsolidationResult,
            PersonMemoryContextService,
            PersonMemoryExtractionResult,
            PersonProfile,
            PersonRecognitionResult,
            PlaceInput,
            QueryRunner,
            SearchQuery,
            Settings,
            TailwagMemoryClient,
            VerifiedProfile,
            initialize_schema,
            load_settings,
        }

        self.assertEqual(set(tailwag_memory.__all__), expected_exports)
        self.assertEqual(len(imported), len(expected_exports))
        for name in expected_exports:
            self.assertIsNotNone(getattr(tailwag_memory, name))
        self.assertIs(tailwag_memory.TailwagMemoryClient, TailwagMemoryClient)
        self.assertIs(tailwag_memory.Settings, Settings)
        self.assertNotIn("address_item", tailwag_memory.__all__)
        self.assertNotIn("address_item", memory_items.__all__)
        self.assertNotIn("stable_memory_id", tailwag_memory.__all__)
        self.assertNotIn("stable_memory_id", memory_items.__all__)
        self.assertNotIn("AffectScore", tailwag_memory.__all__)
        self.assertNotIn("PersonEpisodeTranscriptService", tailwag_memory.__all__)

    def test_client_exposes_email_rekey_contract(self) -> None:
        signature = inspect.signature(TailwagMemoryClient.rekey_person_by_email)

        self.assertEqual(list(signature.parameters), ["self", "email", "new_person_id"])
        self.assertEqual(signature.parameters["email"].annotation, "str")
        self.assertEqual(signature.parameters["new_person_id"].annotation, "str")
        self.assertEqual(signature.return_annotation, "bool")

    def test_neo4j_runner_disables_unrecognized_notification_category(self) -> None:
        graph_database = Mock()
        driver = Mock()
        graph_database.driver.return_value = driver
        neo4j_module = SimpleNamespace(GraphDatabase=graph_database)
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
            embedding_dimension=64,
        )

        with patch.dict(sys.modules, {"neo4j": neo4j_module}):
            runner = Neo4jQueryRunner(settings)

        graph_database.driver.assert_called_once_with(
            "bolt://example.test:7687",
            auth=("neo4j", "secret"),
            notifications_disabled_categories=["UNRECOGNIZED"],
        )
        self.assertIs(runner._driver, driver)


if __name__ == "__main__":
    unittest.main()
