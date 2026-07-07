from __future__ import annotations

from .db import QueryRunner


def person_episode_rows(
    runner: QueryRunner,
    *,
    person_id: str | None = None,
    limit: int,
    include_memory_count: bool = False,
    include_context_fields: bool = False,
    include_event_placeholder: bool = False,
    always_include_person_filter: bool = False,
) -> list[dict[str, object]]:
    """Fetch read-only person/episode participation rows."""
    rendered_person_id = str(person_id or "").strip()
    memory_match = "OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)-[:SUPPORTED_BY]->(e)" if include_memory_count else ""
    memory_with = ",\n                 count(DISTINCT memory) AS memory_item_count" if include_memory_count else ""
    memory_return = ",\n                   memory_item_count AS memory_item_count" if include_memory_count else ""
    context_return = (
        """
                   e.id AS item_id,
                   'episode' AS item_type,
                   e.id AS episode_id,"""
        if include_context_fields
        else """
                   e.id AS episode_id,"""
    )
    event_return = "\n                   null AS event_id," if include_event_placeholder else ""
    text_return = "\n                   coalesce(e.transcript, '') AS text," if include_context_fields else ""
    person_filter = "WHERE ($person_id IS NULL OR person.id = $person_id)" if always_include_person_filter else ""
    if rendered_person_id and not always_include_person_filter:
        person_filter = "WHERE person.id = $person_id"
    order_by = "ORDER BY e.start_time DESC, person.id ASC" if not rendered_person_id else "ORDER BY e.start_time DESC"
    query = f"""
            MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)
            {person_filter}
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            OPTIONAL MATCH (speaker:Person)-[:PARTICIPATED_IN]->(e)
            {memory_match}
            WITH e, r, person, place,
                 collect(DISTINCT speaker.id) + collect(DISTINCT speaker.display_name) AS speaker_labels{memory_with}
            RETURN person.id AS person_id,
                   person.display_name AS display_name,{context_return}{event_return}{text_return}
                   speaker_labels AS speaker_labels,
                   e.transcript AS transcript,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   r.role AS role,
                   r.source AS source{memory_return}
            {order_by}
            LIMIT $limit
            """
    if always_include_person_filter:
        return runner.run(query, {"person_id": rendered_person_id or None, "limit": limit})
    return runner.run(query, {"person_id": rendered_person_id, "limit": limit} if rendered_person_id else {"limit": limit})
