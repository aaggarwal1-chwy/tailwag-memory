from __future__ import annotations


_VECTOR_INDEX_LABELS = {
    "episode_transcript_embedding": "Episode",
    "person_face_embedding": "Person",
    "person_audio_embedding": "Person",
    "memory_item_summary_embedding": "MemoryItem",
}


def vector_search_clause(index_name: str, variable: str, limit_parameter: str) -> str:
    """Return a Neo4j vector search clause for a known index."""
    label = _VECTOR_INDEX_LABELS.get(index_name)
    if label is None:
        raise ValueError(f"unsupported vector index: {index_name}")
    return f"""
            CALL db.index.vector.queryNodes('{index_name}', ${limit_parameter}, $embedding)
            YIELD node AS {variable}, score
            WHERE {variable}:{label}
            """
