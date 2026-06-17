from __future__ import annotations

from .config import Settings, load_settings
from .db import Neo4jQueryRunner
from .embeddings import OpenAIEmbeddingProvider
from .retrieval import PersonContextRetrievalService
from .synthesis import OpenAIPersonContextProvider, PersonContextSynthesisService


class TailwagMemoryClient:
    def __init__(
        self,
        runner: Neo4jQueryRunner,
        settings: Settings,
    ) -> None:
        self.runner = runner
        self.settings = settings

    @classmethod
    def from_env(cls) -> "TailwagMemoryClient":
        settings = load_settings()
        return cls(Neo4jQueryRunner(settings), settings)

    def close(self) -> None:
        self.runner.close()

    def __enter__(self) -> "TailwagMemoryClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def person_context(self, person_id: str, limit: int = 10, semantic_scope: str | None = None) -> str:
        embeddings = OpenAIEmbeddingProvider(
            api_key=self.settings.openai_api_key,
            model=self.settings.embedding_model,
            dimension=self.settings.embedding_dimension,
        )
        retrieval = PersonContextRetrievalService(self.runner, embeddings)
        provider = OpenAIPersonContextProvider(
            api_key=self.settings.openai_api_key,
            model=self.settings.synthesis_model,
        )
        return PersonContextSynthesisService(retrieval, provider).context_for_person(
            person_id,
            limit=limit,
            semantic_scope=semantic_scope,
        )
