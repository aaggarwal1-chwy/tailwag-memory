from __future__ import annotations

from tailwag_memory.demo import seed_demo


if __name__ == "__main__":
    from tailwag_memory.config import load_settings
    from tailwag_memory.db import Neo4jQueryRunner
    from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider

    settings = load_settings()
    runner = Neo4jQueryRunner(settings)
    try:
        seed_demo(runner, MockOpenAIEmbeddingProvider(settings.embedding_dimension))
        print("Demo data seeded.")
    finally:
        runner.close()
