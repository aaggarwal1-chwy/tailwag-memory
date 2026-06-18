from __future__ import annotations

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .models import EpisodeInput, EventInput, utc_now_iso


class EpisodeIngestionService:
    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        self.runner = runner
        self.embeddings = embeddings

    def ingest(self, episode: EpisodeInput) -> str:
        created_at = utc_now_iso()
        summary_embedding = self.embeddings.embed(episode.summary)
        transcript_embedding = self.embeddings.embed(episode.transcript)
        participants = [
            {
                "id": person.id,
                "display_name": person.display_name,
                "email": person.email,
                "consent_status": person.consent_status,
                "face_embedding": person.face_embedding,
                "audio_embedding": person.audio_embedding,
                "role": person.role,
                "source": person.source,
            }
            for person in episode.participants
        ]

        self.runner.run(
            """
            MERGE (e:Episode {id: $id})
            SET e.episode_type = $episode_type,
                e.start_time = $start_time,
                e.end_time = $end_time,
                e.summary = $summary,
                e.transcript = $transcript,
                e.retention_class = $retention_class,
                e.summary_embedding = $summary_embedding,
                e.transcript_embedding = $transcript_embedding,
                e.created_at = coalesce(e.created_at, $created_at)
            WITH e
            OPTIONAL MATCH (e)-[old_place:OCCURRED_AT]->(:Place)
            FOREACH (_ IN CASE WHEN old_place IS NULL THEN [] ELSE [1] END | DELETE old_place)
            WITH e
            MERGE (p:Place {building_code: $building_code, room_id: $room_id})
            MERGE (e)-[:OCCURRED_AT]->(p)
            WITH e
            OPTIONAL MATCH (old_person:Person)-[old_rel:PARTICIPATED_IN]->(e)
            WITH e, old_person, old_rel
            FOREACH (_ IN CASE WHEN old_person IS NOT NULL AND NOT old_person.id IN $participant_ids THEN [1] ELSE [] END | DELETE old_rel)
            WITH DISTINCT e
            UNWIND $participants AS person
                MERGE (p:Person {id: person.id})
                SET p.display_name = coalesce(person.display_name, p.display_name),
                    p.email = coalesce(person.email, p.email),
                    p.consent_status = coalesce(person.consent_status, p.consent_status),
                    p.face_embedding = CASE
                      WHEN person.consent_status IS NOT NULL AND person.consent_status <> 'consented' THEN NULL
                      ELSE coalesce(person.face_embedding, p.face_embedding)
                    END,
                    p.audio_embedding = CASE
                      WHEN person.consent_status IS NOT NULL AND person.consent_status <> 'consented' THEN NULL
                      ELSE coalesce(person.audio_embedding, p.audio_embedding)
                    END,
                    p.created_at = coalesce(p.created_at, $created_at),
                    p.last_seen = CASE
                      WHEN p.last_seen IS NULL OR datetime(p.last_seen) < datetime($last_seen) THEN $last_seen
                      ELSE p.last_seen
                    END
                MERGE (p)-[r:PARTICIPATED_IN]->(e)
                SET r.role = person.role,
                    r.source = person.source
                """,
                {
                    "id": episode.id,
                    "episode_type": episode.episode_type,
                    "start_time": episode.start_time,
                    "end_time": episode.end_time,
                    "summary": episode.summary,
                    "transcript": episode.transcript,
                    "retention_class": episode.retention_class,
                    "summary_embedding": summary_embedding,
                    "transcript_embedding": transcript_embedding,
                    "building_code": episode.place.building_code,
                    "room_id": episode.place.room_id,
                    "participants": participants,
                    "participant_ids": [person["id"] for person in participants],
                    "created_at": created_at,
                    "last_seen": episode.end_time or episode.start_time,
                },
            )

        return episode.id


class EventIngestionService:
    def __init__(self, runner: QueryRunner) -> None:
        self.runner = runner

    def ingest(self, event: EventInput) -> str:
        created_at = utc_now_iso()
        attendees = [
            {
                "person_id": attendee.person.id,
                "display_name": attendee.person.display_name,
                "email": attendee.person.email,
                "consent_status": attendee.person.consent_status,
                "face_embedding": attendee.person.face_embedding,
                "audio_embedding": attendee.person.audio_embedding,
                "source": attendee.source,
                "response": attendee.response,
                "response_time": attendee.response_time,
            }
            for attendee in event.accepted_attendees
        ]

        self.runner.run(
            """
            MERGE (e:Event {id: $id})
            SET e.description = $description,
                e.start_time = $start_time,
                e.end_time = $end_time,
                e.created_at = coalesce(e.created_at, $created_at)
            WITH e
            OPTIONAL MATCH (e)-[old_place:OCCURRED_AT]->(:Place)
            FOREACH (_ IN CASE WHEN old_place IS NULL THEN [] ELSE [1] END | DELETE old_place)
            WITH e
            MERGE (p:Place {building_code: $building_code, room_id: $room_id})
            MERGE (e)-[:OCCURRED_AT]->(p)
            WITH e
            OPTIONAL MATCH (old_person:Person)-[old_rel:ATTENDED]->(e)
            WITH e, old_person, old_rel
            FOREACH (_ IN CASE WHEN old_person IS NOT NULL AND NOT old_person.id IN $attendee_ids THEN [1] ELSE [] END | DELETE old_rel)
            WITH DISTINCT e
            UNWIND $attendees AS attendee
                MERGE (p:Person {id: attendee.person_id})
                SET p.display_name = coalesce(attendee.display_name, p.display_name),
                    p.email = coalesce(attendee.email, p.email),
                    p.consent_status = coalesce(attendee.consent_status, p.consent_status),
                    p.face_embedding = CASE
                      WHEN attendee.consent_status IS NOT NULL AND attendee.consent_status <> 'consented' THEN NULL
                      ELSE coalesce(attendee.face_embedding, p.face_embedding)
                    END,
                    p.audio_embedding = CASE
                      WHEN attendee.consent_status IS NOT NULL AND attendee.consent_status <> 'consented' THEN NULL
                      ELSE coalesce(attendee.audio_embedding, p.audio_embedding)
                    END,
                    p.created_at = coalesce(p.created_at, $created_at),
                    p.last_seen = CASE
                      WHEN p.last_seen IS NULL OR datetime(p.last_seen) < datetime($last_seen) THEN $last_seen
                      ELSE p.last_seen
                    END
                MERGE (p)-[r:ATTENDED]->(e)
                SET r.source = attendee.source,
                    r.response = attendee.response,
                    r.response_time = attendee.response_time
                """,
                {
                    "id": event.id,
                    "description": event.description,
                    "start_time": event.start_time,
                    "end_time": event.end_time,
                    "building_code": event.place.building_code,
                    "room_id": event.place.room_id,
                    "attendees": attendees,
                    "attendee_ids": [attendee["person_id"] for attendee in attendees],
                    "created_at": created_at,
                    "last_seen": event.end_time or event.start_time,
                },
            )

        return event.id
