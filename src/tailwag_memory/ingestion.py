from __future__ import annotations

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .models import EpisodeInput, EventInput, PersonInput, utc_now_iso


def _person_upsert_cypher(
    person_variable: str,
    id_property: str,
    *,
    set_lifecycle_fields: bool = False,
    monotonic_last_seen: bool = True,
    preserve_archived_biometrics: bool = True,
) -> str:
    """Return Cypher for consent-aware person upserts."""
    last_seen_assignment = (
        f"""CASE
                      WHEN p.last_seen IS NULL OR datetime(p.last_seen) < datetime($last_seen) THEN $last_seen
                      ELSE p.last_seen
                    END"""
        if monotonic_last_seen
        else "$last_seen"
    )
    lifecycle_fields = (
        """,
                    p.updated_at = $updated_at,
                    p.status = 'active',
                    p.archived_at = NULL"""
        if set_lifecycle_fields
        else ""
    )
    archived_face_guard = "\n                      WHEN p.status = 'archived' THEN p.face_embedding" if preserve_archived_biometrics else ""
    archived_audio_guard = "\n                      WHEN p.status = 'archived' THEN p.audio_embedding" if preserve_archived_biometrics else ""
    return f"""
                MERGE (p:Person {{id: {person_variable}.{id_property}}})
                SET p.display_name = coalesce({person_variable}.display_name, p.display_name),
                    p.email = coalesce({person_variable}.email, p.email),
                    p.consent_status = coalesce({person_variable}.consent_status, p.consent_status),
                    p.face_embedding = CASE
                      WHEN {person_variable}.consent_status IS NOT NULL AND {person_variable}.consent_status <> 'consented' THEN NULL
                      {archived_face_guard}
                      ELSE coalesce({person_variable}.face_embedding, p.face_embedding)
                    END,
                    p.audio_embedding = CASE
                      WHEN {person_variable}.consent_status IS NOT NULL AND {person_variable}.consent_status <> 'consented' THEN NULL
                      {archived_audio_guard}
                      ELSE coalesce({person_variable}.audio_embedding, p.audio_embedding)
                    END,
                    p.created_at = coalesce(p.created_at, $created_at),
                    p.last_seen = {last_seen_assignment}{lifecycle_fields}
                """


class PersonIngestionService:
    """Persist low-level person records without episode or event context."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store dependencies for person ingestion."""
        self.runner = runner

    def upsert(self, person: PersonInput) -> str:
        """Upsert a person profile and return its id."""
        written_at = utc_now_iso()
        person_data = {
            "id": person.id,
            "display_name": person.display_name,
            "email": person.email,
            "consent_status": person.consent_status,
            "face_embedding": person.face_embedding,
            "audio_embedding": person.audio_embedding,
        }

        self.runner.run(
            """
            WITH $person AS person
            """
            + _person_upsert_cypher(
                "person",
                "id",
                set_lifecycle_fields=True,
                monotonic_last_seen=False,
                preserve_archived_biometrics=False,
            )
            + """
            RETURN p.id AS person_id
            """,
            {
                "person": person_data,
                "created_at": written_at,
                "updated_at": written_at,
                "last_seen": written_at,
            },
        )

        return person.id

    def archive(self, person_id: str) -> bool:
        """Archive a person by id while preserving profile fields and relationships."""
        written_at = utc_now_iso()
        rows = self.runner.run(
            """
            MATCH (p:Person {id: $person_id})
            SET p.status = 'archived',
                p.archived_at = $archived_at,
                p.updated_at = $updated_at,
                p.face_embedding = NULL,
                p.audio_embedding = NULL
            RETURN p.id AS person_id
            """,
            {
                "person_id": person_id,
                "archived_at": written_at,
                "updated_at": written_at,
            },
        )
        return bool(rows)

    def rekey_by_email(self, email: str, new_person_id: str) -> bool:
        """Rename one email-matched Slack person to a caller-owned canonical id."""
        rendered_email = str(email or "").strip()
        rendered_person_id = str(new_person_id or "").strip()
        if not rendered_email:
            raise ValueError("email is required")
        if not rendered_person_id:
            raise ValueError("new_person_id is required")

        written_at = utc_now_iso()
        rows = self.runner.run(
            """
            MATCH (p:Person)
            WHERE p.email IS NOT NULL AND toLower(trim(p.email)) = toLower($email)
            WITH collect(p) AS matches
            WHERE size(matches) = 1
            WITH matches[0] AS p
            WHERE p.id = $new_person_id OR p.id STARTS WITH 'slack:'
            OPTIONAL MATCH (existing:Person {id: $new_person_id})
            WITH p, existing
            WHERE existing IS NULL OR existing = p
            SET p.id = $new_person_id,
                p.updated_at = $updated_at
            RETURN p.id AS person_id
            """,
            {
                "email": rendered_email,
                "new_person_id": rendered_person_id,
                "updated_at": written_at,
            },
        )
        return bool(rows)

    def canonical_id_by_email(self, email: str) -> str | None:
        """Return one canonical Argos person id for an email when unambiguous."""
        rendered_email = str(email or "").strip()
        if not rendered_email:
            return None

        rows = self.runner.run(
            """
            MATCH (p:Person)
            WHERE p.email IS NOT NULL
                AND toLower(trim(p.email)) = toLower($email)
                AND p.id STARTS WITH 'person_'
            WITH collect(DISTINCT p.id) AS person_ids
            WHERE size(person_ids) = 1
            RETURN person_ids[0] AS person_id
            """,
            {"email": rendered_email},
        )
        if not rows:
            return None
        return str(rows[0].get("person_id") or "").strip() or None


class EpisodeIngestionService:
    """Persist episodes, places, participants, and embeddings."""

    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        """Store dependencies for episode ingestion."""
        self.runner = runner
        self.embeddings = embeddings

    def ingest(self, episode: EpisodeInput) -> str:
        """Write an episode graph snapshot and return its id."""
        written_at = utc_now_iso()
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
                e.created_at = coalesce(e.created_at, $created_at),
                e.updated_at = $updated_at
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
            """
            + _person_upsert_cypher("person", "id")
            + """
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
                    "created_at": written_at,
                    "updated_at": written_at,
                    "last_seen": episode.end_time or episode.start_time,
                },
            )

        return episode.id


class EventIngestionService:
    """Persist events, places, and accepted attendee links."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store dependencies for event ingestion."""
        self.runner = runner

    def ingest(self, event: EventInput) -> str:
        """Write an event graph snapshot and return its id."""
        written_at = utc_now_iso()
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
                e.created_at = coalesce(e.created_at, $created_at),
                e.updated_at = $updated_at
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
            """
            + _person_upsert_cypher("attendee", "person_id")
            + """
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
                    "created_at": written_at,
                    "updated_at": written_at,
                    "last_seen": event.end_time or event.start_time,
                },
            )

        return event.id
