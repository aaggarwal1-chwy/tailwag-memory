from __future__ import annotations

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .models import EpisodeInput, utc_now_iso


class EpisodeIngestionService:
    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        self.runner = runner
        self.embeddings = embeddings

    def ingest(self, episode: EpisodeInput) -> str:
        created_at = utc_now_iso()
        summary_embedding = self.embeddings.embed(episode.summary)
        transcript_embedding = self.embeddings.embed(episode.transcript)

        self.runner.run(
            """
            MERGE (e:Episode {id: $id})
            SET e.episode_type = $episode_type,
                e.start_time = $start_time,
                e.end_time = $end_time,
                e.summary = $summary,
                e.transcript = $transcript,
                e.retention_class = $retention_class,
                e.visibility = $visibility,
                e.summary_embedding = $summary_embedding,
                e.transcript_embedding = $transcript_embedding,
                e.created_at = coalesce(e.created_at, $created_at)
            """,
            {
                "id": episode.id,
                "episode_type": episode.episode_type,
                "start_time": episode.start_time,
                "end_time": episode.end_time,
                "summary": episode.summary,
                "transcript": episode.transcript,
                "retention_class": episode.retention_class,
                "visibility": episode.visibility,
                "summary_embedding": summary_embedding,
                "transcript_embedding": transcript_embedding,
                "created_at": created_at,
            },
        )

        self.runner.run(
            """
            MATCH (e:Episode {id: $episode_id})
            MERGE (p:Place {building_code: $building_code, room_id: $room_id})
            MERGE (e)-[:OCCURRED_AT]->(p)
            """,
            {
                "episode_id": episode.id,
                "building_code": episode.place.building_code,
                "room_id": episode.place.room_id,
            },
        )

        for person in episode.participants:
            self.runner.run(
                """
                MATCH (e:Episode {id: $episode_id})
                MERGE (p:Person {id: $person_id})
                SET p.display_name = $display_name,
                    p.consent_status = $consent_status,
                    p.face_embedding = coalesce($face_embedding, p.face_embedding),
                    p.audio_embedding = coalesce($audio_embedding, p.audio_embedding),
                    p.created_at = coalesce(p.created_at, $created_at),
                    p.last_seen = CASE
                      WHEN p.last_seen IS NULL OR p.last_seen < $last_seen THEN $last_seen
                      ELSE p.last_seen
                    END
                MERGE (p)-[r:PARTICIPATED_IN]->(e)
                SET r.role = $role,
                    r.source = $source
                """,
                {
                    "episode_id": episode.id,
                    "person_id": person.id,
                    "display_name": person.display_name,
                    "consent_status": person.consent_status,
                    "face_embedding": person.face_embedding,
                    "audio_embedding": person.audio_embedding,
                    "created_at": created_at,
                    "last_seen": episode.end_time or episode.start_time,
                    "role": person.role,
                    "source": person.source,
                },
            )

        return episode.id
