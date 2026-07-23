from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .db import QueryRunner


SUPPORTED_DELETE_LABELS = ("Person", "Episode", "MemoryItem")


@dataclass(frozen=True)
class NodeDeleteResult:
    """Internal CLI result for permanent targeted node deletion."""

    label: str
    id: str
    status: str
    deleted_counts: dict[str, int] = field(default_factory=dict)


class NodeDeletionService:
    """Perform permanent CLI-only graph deletes with type-specific cascades."""

    def __init__(self, runner: QueryRunner) -> None:
        self.runner = runner

    def delete_node(self, *, label: str, node_id: str) -> NodeDeleteResult:
        """Delete one supported node by application-level id."""
        rendered_label = str(label or "").strip()
        rendered_id = str(node_id or "").strip()
        if rendered_label not in SUPPORTED_DELETE_LABELS:
            raise ValueError(f"unsupported delete label: {rendered_label}")
        if not rendered_id:
            raise ValueError("id is required")
        if not self._exists(rendered_label, rendered_id):
            return NodeDeleteResult(label=rendered_label, id=rendered_id, status="not_found")

        if rendered_label == "Person":
            counts = self._delete_person(rendered_id)
        elif rendered_label == "Episode":
            counts = self._delete_episode(rendered_id)
        else:
            counts = self._delete_memory_item(rendered_id)
        return NodeDeleteResult(
            label=rendered_label,
            id=rendered_id,
            status="deleted",
            deleted_counts=counts,
        )

    def _exists(self, label: str, node_id: str) -> bool:
        rows = self.runner.run(
            f"""
            MATCH (node:{label} {{id: $node_id}})
            RETURN node.id AS node_id
            LIMIT 1
            """,
            {"node_id": node_id},
        )
        return bool(rows)

    def _delete_person(self, person_id: str) -> dict[str, int]:
        rows = self.runner.run(
            """
            MATCH (person:Person {id: $node_id})
            CALL (person) {
              OPTIONAL MATCH (person)-[:PARTICIPATED_IN]->(episode:Episode)
              WHERE NOT EXISTS {
                MATCH (other_person:Person)-[:PARTICIPATED_IN]->(episode)
                WHERE other_person <> person
              }
              RETURN collect(DISTINCT episode) AS owned_episodes
            }
            CALL (owned_episodes) {
              UNWIND owned_episodes AS episode
              WITH episode
              WHERE episode IS NOT NULL
              OPTIONAL MATCH (episode)-[:OCCURRED_AT]->(place:Place)
              RETURN collect(DISTINCT place) AS owned_episode_places
            }
            CALL (owned_episodes) {
              UNWIND owned_episodes AS episode
              WITH owned_episodes, episode
              WHERE episode IS NOT NULL
              OPTIONAL MATCH (memory:MemoryItem)-[:SUPPORTED_BY]->(episode)
              WITH owned_episodes, memory
              WHERE memory IS NOT NULL
              MATCH (memory)-[:SUPPORTED_BY]->(support_episode:Episode)
              WITH memory, owned_episodes, collect(DISTINCT support_episode) AS support_episodes
              WHERE all(support_episode IN support_episodes WHERE support_episode IN owned_episodes)
              RETURN collect(DISTINCT memory) AS episode_only_memories
            }
            CALL (owned_episodes, episode_only_memories) {
              UNWIND owned_episodes AS episode
              WITH episode, episode_only_memories
              WHERE episode IS NOT NULL
              OPTIONAL MATCH (memory:MemoryItem)-[support:SUPPORTED_BY]->(episode)
              WHERE NOT memory IN episode_only_memories
              RETURN collect(DISTINCT support) AS support_links
            }
            CALL (owned_episodes) {
              UNWIND owned_episodes AS episode
              WITH episode
              WHERE episode IS NOT NULL
              OPTIONAL MATCH (:MemoryItem)-[addressed:ADDRESSED_BY]->(episode)
              RETURN collect(DISTINCT addressed) AS addressed_links
            }
            CALL (person) {
              OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)
              RETURN collect(DISTINCT memory) AS person_memories
            }
            CALL (person) {
              OPTIONAL MATCH (person)-[:HAS_FACE_REFERENCE]->(face:FaceReference)
              WHERE NOT EXISTS {
                MATCH (other_person:Person)-[:HAS_FACE_REFERENCE]->(face)
                WHERE other_person <> person
              }
              RETURN collect(DISTINCT face) AS face_refs
            }
            CALL (person) {
              OPTIONAL MATCH (person)-[:HAS_VOICE_REFERENCE]->(voice:VoiceReference)
              WHERE NOT EXISTS {
                MATCH (other_person:Person)-[:HAS_VOICE_REFERENCE]->(voice)
                WHERE other_person <> person
              }
              RETURN collect(DISTINCT voice) AS voice_refs
            }
            CALL (person, owned_episodes) {
              OPTIONAL MATCH (person)-[participant:PARTICIPATED_IN]->(kept_episode:Episode)
              WHERE NOT kept_episode IN owned_episodes
              RETURN count(participant) AS participant_links_deleted
            }
            CALL (person) {
              OPTIONAL MATCH (person)-[mention:MENTIONED_IN]->(:Episode)
              RETURN count(mention) AS mention_links_deleted
            }
            CALL (person) {
              OPTIONAL MATCH (person)-[attended:ATTENDED]->(:Event)
              RETURN count(attended) AS event_links_deleted
            }
            CALL (person) {
              OPTIONAL MATCH (person)-[directory:HAS_DIRECTORY_RECORD]->(:EmployeeDirectoryRecord)
              RETURN count(directory) AS directory_links_deleted
            }
            WITH person,
                 owned_episodes,
                 owned_episode_places,
                 support_links,
                 addressed_links,
                 face_refs,
                 voice_refs,
                 participant_links_deleted,
                 mention_links_deleted,
                 event_links_deleted,
                 directory_links_deleted,
                 [memory IN person_memories + episode_only_memories WHERE memory IS NOT NULL] AS memory_candidates
            UNWIND (CASE WHEN memory_candidates = [] THEN [NULL] ELSE memory_candidates END) AS memory_candidate
            WITH person,
                 owned_episodes,
                 owned_episode_places,
                 support_links,
                 addressed_links,
                 face_refs,
                 voice_refs,
                 participant_links_deleted,
                 mention_links_deleted,
                 event_links_deleted,
                 directory_links_deleted,
                 collect(DISTINCT memory_candidate) AS memory_delete_candidates
            WITH person,
                 owned_episodes,
                 owned_episode_places,
                 support_links,
                 addressed_links,
                 face_refs,
                 voice_refs,
                 participant_links_deleted,
                 mention_links_deleted,
                 event_links_deleted,
                 directory_links_deleted,
                 [memory IN memory_delete_candidates WHERE memory IS NOT NULL] AS memories_to_delete
            FOREACH (support IN support_links | DELETE support)
            FOREACH (addressed IN addressed_links | DELETE addressed)
            FOREACH (memory IN memories_to_delete | DETACH DELETE memory)
            FOREACH (face IN face_refs | DETACH DELETE face)
            FOREACH (voice IN voice_refs | DETACH DELETE voice)
            FOREACH (episode IN owned_episodes | DETACH DELETE episode)
            DETACH DELETE person
            WITH owned_episode_places,
                 size(owned_episodes) AS episodes_deleted,
                 size(memories_to_delete) AS memory_items_deleted,
                 size(support_links) AS support_links_deleted,
                 size(addressed_links) AS addressed_links_deleted,
                 size(face_refs) AS face_references_deleted,
                 size(voice_refs) AS voice_references_deleted,
                 participant_links_deleted,
                 mention_links_deleted,
                 event_links_deleted,
                 directory_links_deleted
            CALL (owned_episode_places) {
              UNWIND owned_episode_places AS place
              WITH place
              WHERE place IS NOT NULL
                AND NOT EXISTS { MATCH ()-[:OCCURRED_AT]->(place) }
                AND NOT EXISTS { MATCH ()-[:HOME_BASED_AT]->(place) }
              RETURN collect(DISTINCT place) AS orphan_places
            }
            FOREACH (place IN orphan_places | DETACH DELETE place)
            RETURN 1 AS persons_deleted,
                   episodes_deleted,
                   memory_items_deleted,
                   support_links_deleted,
                   addressed_links_deleted,
                   face_references_deleted,
                   voice_references_deleted,
                   participant_links_deleted,
                   mention_links_deleted,
                   event_links_deleted,
                   directory_links_deleted,
                   size(orphan_places) AS places_deleted
            """,
            {"node_id": person_id},
        )
        return _counts_from_row(rows)

    def _delete_episode(self, episode_id: str) -> dict[str, int]:
        rows = self.runner.run(
            """
            MATCH (episode:Episode {id: $node_id})
            CALL (episode) {
              OPTIONAL MATCH (episode)-[:OCCURRED_AT]->(place:Place)
              RETURN collect(DISTINCT place) AS episode_places
            }
            CALL (episode) {
              OPTIONAL MATCH (memory:MemoryItem)-[:SUPPORTED_BY]->(episode)
              WITH episode, memory
              WHERE memory IS NOT NULL
              MATCH (memory)-[:SUPPORTED_BY]->(support_episode:Episode)
              WITH episode, memory, collect(DISTINCT support_episode) AS support_episodes
              WHERE size(support_episodes) = 1 AND episode IN support_episodes
              RETURN collect(DISTINCT memory) AS single_support_memories
            }
            CALL (episode, single_support_memories) {
              OPTIONAL MATCH (memory:MemoryItem)-[support:SUPPORTED_BY]->(episode)
              WHERE NOT memory IN single_support_memories
              RETURN collect(DISTINCT support) AS support_links
            }
            CALL (episode) {
              OPTIONAL MATCH (:MemoryItem)-[addressed:ADDRESSED_BY]->(episode)
              RETURN collect(DISTINCT addressed) AS addressed_links
            }
            FOREACH (support IN support_links | DELETE support)
            FOREACH (addressed IN addressed_links | DELETE addressed)
            FOREACH (memory IN single_support_memories | DETACH DELETE memory)
            DETACH DELETE episode
            WITH episode_places,
                 size(single_support_memories) AS memory_items_deleted,
                 size(support_links) AS support_links_deleted,
                 size(addressed_links) AS addressed_links_deleted
            CALL (episode_places) {
              UNWIND episode_places AS place
              WITH place
              WHERE place IS NOT NULL
                AND NOT EXISTS { MATCH ()-[:OCCURRED_AT]->(place) }
                AND NOT EXISTS { MATCH ()-[:HOME_BASED_AT]->(place) }
              RETURN collect(DISTINCT place) AS orphan_places
            }
            FOREACH (place IN orphan_places | DETACH DELETE place)
            RETURN 1 AS episodes_deleted,
                   memory_items_deleted,
                   support_links_deleted,
                   addressed_links_deleted,
                   size(orphan_places) AS places_deleted
            """,
            {"node_id": episode_id},
        )
        return _counts_from_row(rows)

    def _delete_memory_item(self, memory_id: str) -> dict[str, int]:
        rows = self.runner.run(
            """
            MATCH (memory:MemoryItem {id: $node_id})
            OPTIONAL MATCH (memory)-[:SUPERSEDED_BY*0..]->(deleted_memory:MemoryItem)
            WITH collect(DISTINCT deleted_memory) AS memories_to_delete
            FOREACH (deleted_memory IN memories_to_delete | DETACH DELETE deleted_memory)
            RETURN size(memories_to_delete) AS memory_items_deleted
            """,
            {"node_id": memory_id},
        )
        return _counts_from_row(rows)


def _counts_from_row(rows: list[dict[str, Any]]) -> dict[str, int]:
    if not rows:
        return {}
    counts: dict[str, int] = {}
    for key, value in rows[0].items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            counts[key] = value
    return counts
