"""Consumer-facing public API for tailwag-memory."""

from .client import TailwagMemoryClient
from .config import Settings, load_settings
from .db import Neo4jQueryRunner, QueryRunner
from .embeddings import EmbeddingProvider, MockOpenAIEmbeddingProvider, OpenAIConfigurationError, OpenAIEmbeddingProvider
from .ingestion import EpisodeIngestionService, EventIngestionService
from .memory_context import PersonMemoryContextService
from .memory_items import EpisodeMemoryExtractionService, MemoryItemService
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
    PersonContextItem,
    PersonContextSource,
    PersonContextTranscriptLine,
    PersonInput,
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
    "MemoryItemInput",
    "MemoryItemResult",
    "MemoryItemService",
    "MockOpenAIEmbeddingProvider",
    "Neo4jQueryRunner",
    "OpenAIConfigurationError",
    "OpenAIEmbeddingProvider",
    "PersonContextItem",
    "PersonContextRetrievalService",
    "PersonContextSource",
    "PersonContextSynthesisService",
    "PersonContextTranscriptLine",
    "PersonInput",
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
