from __future__ import annotations

from .db import QueryRunner


def schema_statements(embedding_dimension: int) -> list[str]:
    """Return idempotent Neo4j schema statements for the configured dimension."""

    if not isinstance(embedding_dimension, int) or embedding_dimension <= 0:
        raise ValueError("embedding_dimension must be a positive integer")
    return [
        """
        CREATE CONSTRAINT person_id IF NOT EXISTS
        FOR (p:Person) REQUIRE p.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT person_email IF NOT EXISTS
        FOR (p:Person) REQUIRE p.email IS UNIQUE
        """,
        """
        CREATE CONSTRAINT episode_id IF NOT EXISTS
        FOR (e:Episode) REQUIRE e.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT event_id IF NOT EXISTS
        FOR (e:Event) REQUIRE e.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT memory_item_id IF NOT EXISTS
        FOR (m:MemoryItem) REQUIRE m.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT place_key IF NOT EXISTS
        FOR (p:Place) REQUIRE (p.building_code, p.room_id) IS UNIQUE
        """,
        f"""
        CREATE VECTOR INDEX episode_transcript_embedding IF NOT EXISTS
        FOR (e:Episode) ON (e.transcript_embedding)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {embedding_dimension},
            `vector.similarity_function`: 'cosine'
          }}
        }}
        """,
        f"""
        CREATE VECTOR INDEX person_face_embedding IF NOT EXISTS
        FOR (p:Person) ON (p.face_embedding)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {embedding_dimension},
            `vector.similarity_function`: 'cosine'
          }}
        }}
        """,
        f"""
        CREATE VECTOR INDEX person_audio_embedding IF NOT EXISTS
        FOR (p:Person) ON (p.audio_embedding)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {embedding_dimension},
            `vector.similarity_function`: 'cosine'
          }}
        }}
        """,
        f"""
        CREATE VECTOR INDEX memory_item_summary_embedding IF NOT EXISTS
        FOR (m:MemoryItem) ON (m.summary_embedding)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {embedding_dimension},
            `vector.similarity_function`: 'cosine'
          }}
        }}
        """,
    ]


def initialize_schema(runner: QueryRunner, embedding_dimension: int) -> None:
    """Run all schema statements against the supplied query runner."""

    for statement in schema_statements(embedding_dimension):
        runner.run(statement)
