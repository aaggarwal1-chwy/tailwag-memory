"""Consumer-facing public API for tailwag-memory."""

from .client import TailwagMemoryClient
from .config import Settings, load_settings
from .db import Neo4jQueryRunner, QueryRunner
from .embeddings import EmbeddingProvider, MockOpenAIEmbeddingProvider, OpenAIConfigurationError, OpenAIEmbeddingProvider
from .ingestion import EpisodeIngestionService, EventIngestionService, PersonIngestionService
from .memory_context import PersonMemoryContextService
from .memory_items import (
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    EpisodeMemoryExtractionService,
    MemoryConsolidationService,
    MemoryItemService,
    OpenAIMemoryConsolidationProvider,
)
from .models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    EpisodeMemoryResult,
    EpisodeRecordResult,
    EventAttendeeInput,
    EventInput,
    EventResult,
    MemoryItemInput,
    MemoryItemResult,
    MemoryConsolidationResult,
    PersonContextItem,
    PersonContextSource,
    PersonContextTranscriptLine,
    PersonInput,
    PersonMemoryConsolidationResult,
    PersonMemoryExtractionResult,
    PersonRecognitionResult,
    PlaceInput,
    SearchQuery,
)
from .retrieval import (
    EpisodeRetrievalService,
    EventRetrievalService,
    PersonContextRetrievalService,
    PersonRecognitionService,
)
from .schema import initialize_schema
from .synthesis import PersonContextSynthesisService

__all__ = [
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
    "DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES",
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
    "PersonContextSynthesisService",
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
]
