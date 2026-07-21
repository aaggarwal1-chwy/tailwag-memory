from __future__ import annotations

from .db import QueryRunner
from .episode_result_projection import (
    episode_place_projection_subquery,
    robot_participation_projection_subquery,
)


def person_episode_rows(
    runner: QueryRunner,
    *,
    person_id: str | None = None,
    limit: int,
    include_memory_count: bool = False,
    include_memory_items: bool = False,
    include_context_fields: bool = False,
    include_event_placeholder: bool = False,
    always_include_person_filter: bool = False,
) -> list[dict[str, object]]:
    """Fetch read-only person/episode participation rows."""
    rendered_person_id = str(person_id or "").strip()
    with_memory = include_memory_count or include_memory_items
    memory_with_parts = []
    memory_return_parts = []
    if with_memory:
        memory_with_parts.append("count(DISTINCT memory) AS memory_item_count")
        memory_with_parts.append("[id IN collect(DISTINCT memory.id) WHERE id IS NOT NULL] AS memory_item_ids")
        memory_return_parts.append("memory_item_count AS memory_item_count")
        memory_return_parts.append("memory_item_ids AS memory_item_ids")
    if include_memory_items:
        memory_with_parts.append(
            """
                 [item IN collect(DISTINCT CASE WHEN memory IS NULL THEN null ELSE {
                     memory_id: memory.id,
                     kind: coalesce(memory.kind, ''),
                     status: coalesce(memory.status, ''),
                     summary: coalesce(memory.summary, '')
                 } END) WHERE item IS NOT NULL] AS related_memory_items""".strip()
        )
        memory_return_parts.append("related_memory_items AS related_memory_items")
    memory_subquery = ""
    if memory_with_parts:
        memory_subquery = f"""
            CALL (person, e) {{
                OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)-[:SUPPORTED_BY]->(e)
                RETURN {", ".join(memory_with_parts)}
            }}
            """
    memory_return = ",\n                   " + ",\n                   ".join(memory_return_parts) if memory_return_parts else ""
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
            CALL (e) {{
                OPTIONAL MATCH (speaker:Person)-[:PARTICIPATED_IN]->(e)
                RETURN collect(DISTINCT speaker.id) + collect(DISTINCT speaker.display_name) AS speaker_labels
            }}
            {robot_participation_projection_subquery("e")}
            {memory_subquery}
            {episode_place_projection_subquery("e")}
            RETURN person.id AS person_id,
                   person.display_name AS display_name,{context_return}{event_return}{text_return}
                   speaker_labels AS speaker_labels,
                   robots AS robots,
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
