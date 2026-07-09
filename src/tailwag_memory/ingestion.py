from __future__ import annotations

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .episode_normalization import normalize_robot_speaker_labels
from .models import EpisodeInput, EventInput, PersonInput, utc_now_iso


def _normalize_email(email: str | None) -> str | None:
    """Return the stable email identity key used by Neo4j uniqueness."""
    if email is None:
        return None
    normalized = str(email).strip().lower()
    return normalized or None


def _resolved_person_id_by_email(
    runner: QueryRunner,
    email: object,
    incoming_id: str,
    *,
    updated_at: str | None = None,
) -> str | None:
    """Return the existing or safely rekeyed person ID for a normalized email value."""
    if not email or not incoming_id:
        return None
    rows = runner.run(
        """
        MATCH (p:Person {email: $email})
        WITH collect(p) AS matches
        WHERE size(matches) = 1
        WITH matches[0] AS p
        OPTIONAL MATCH (target:Person {id: $incoming_id})
        WITH p, target
        WHERE p.id = $incoming_id
            OR NOT (p.id STARTS WITH 'slack:' AND $incoming_id STARTS WITH 'person_')
            OR target IS NULL
            OR target = p
        WITH p, p.id STARTS WITH 'slack:' AND $incoming_id STARTS WITH 'person_' AND (target IS NULL OR target = p) AS should_rekey
        SET p.id = CASE WHEN should_rekey THEN $incoming_id ELSE p.id END,
            p.updated_at = CASE WHEN should_rekey THEN coalesce($updated_at, p.updated_at) ELSE p.updated_at END
        RETURN p.id AS person_id
        """,
        {
            "email": email,
            "incoming_id": incoming_id,
            "updated_at": updated_at,
        },
    )
    if not rows:
        return None

    resolved_id = str(rows[0].get("person_id") or "").strip()
    if not resolved_id:
        return None
    return resolved_id


def _resolve_person_data_by_email(
    runner: QueryRunner,
    person_data: dict[str, object],
    *,
    updated_at: str | None = None,
) -> dict[str, object]:
    """Resolve incoming person data to an existing same-email person when present."""
    incoming_id = str(person_data.get("id") or "").strip()
    resolved_id = _resolved_person_id_by_email(
        runner,
        person_data.get("email"),
        incoming_id,
        updated_at=updated_at,
    )
    if resolved_id is None:
        return person_data
    return {**person_data, "id": resolved_id}


def _person_upsert_cypher(
    person_variable: str,
    id_property: str,
    *,
    set_lifecycle_fields: bool = False,
    monotonic_last_seen: bool = True,
    update_last_seen: bool = True,
) -> str:
    """Return Cypher for consent-aware person upserts."""
    last_seen_assignment = "p.last_seen"
    if update_last_seen:
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
    return f"""
                MERGE (p:Person {{id: {person_variable}.{id_property}}})
                SET p.display_name = coalesce({person_variable}.display_name, p.display_name),
                    p.official_name = coalesce({person_variable}.official_name, p.official_name),
                    p.name = coalesce(p.name, {person_variable}.id),
                    p.email = coalesce({person_variable}.email, p.email),
                    p.consent_status = coalesce({person_variable}.consent_status, p.consent_status),
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
            "official_name": person.official_name,
            "email": _normalize_email(person.email),
            "consent_status": person.consent_status,
        }
        person_data = _resolve_person_data_by_email(self.runner, person_data, updated_at=written_at)

        rows = self.runner.run(
            """
            WITH $person AS person
            """
            + _person_upsert_cypher(
                "person",
                "id",
                set_lifecycle_fields=True,
                monotonic_last_seen=False,
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

        if not rows:
            return str(person_data["id"])
        return str(rows[0].get("person_id") or person_data["id"])

    def archive(self, person_id: str) -> bool:
        """Archive a person by id while preserving profile fields and relationships."""
        written_at = utc_now_iso()
        rows = self.runner.run(
            """
            MATCH (p:Person {id: $person_id})
            SET p.status = 'archived',
                p.archived_at = $archived_at,
                p.updated_at = $updated_at
            WITH p
            OPTIONAL MATCH (p)-[:HAS_FACE_REFERENCE|HAS_VOICE_REFERENCE]->(ref)
            SET ref.status = 'archived',
                ref.archived_at = $archived_at,
                ref.updated_at = $updated_at
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

        resolved_id = _resolved_person_id_by_email(
            self.runner,
            _normalize_email(rendered_email),
            rendered_person_id,
            updated_at=utc_now_iso(),
        )
        return resolved_id == rendered_person_id

    def canonical_id_by_email(self, email: str) -> str | None:
        """Return one canonical Argos person id for an email when unambiguous."""
        rendered_email = str(email or "").strip()
        if not rendered_email:
            return None

        rows = self.runner.run(
            """
            MATCH (p:Person)
            WHERE p.email = $email
                AND p.id STARTS WITH 'person_'
            WITH collect(DISTINCT p.id) AS person_ids
            WHERE size(person_ids) = 1
            RETURN person_ids[0] AS person_id
            """,
            {"email": _normalize_email(rendered_email)},
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
        episode = normalize_robot_speaker_labels(episode)
        written_at = utc_now_iso()
        transcript_embedding = self.embeddings.embed(episode.transcript)
        participants = [
            _resolve_person_data_by_email(
                self.runner,
                {
                    "id": person.id,
                    "display_name": person.display_name,
                    "email": _normalize_email(person.email),
                    "consent_status": person.consent_status,
                    "role": person.role,
                    "source": person.source,
                },
                updated_at=written_at,
            )
            for person in episode.participants
        ]
        mentioned_people = [
            _resolve_person_data_by_email(
                self.runner,
                {
                    "person_id": mention.person.id,
                    "id": mention.person.id,
                    "display_name": mention.person.display_name,
                    "email": _normalize_email(mention.person.email),
                    "consent_status": mention.person.consent_status,
                    "source": mention.source,
                },
                updated_at=written_at,
            )
            for mention in episode.mentioned_people
        ]

        participant_ids = [str(person["id"]) for person in participants]
        for person, participant_id in zip(participants, participant_ids, strict=True):
            person["id"] = participant_id
        mentioned_person_ids = [str(person["id"]) for person in mentioned_people]
        for person, mentioned_person_id in zip(mentioned_people, mentioned_person_ids, strict=True):
            person["person_id"] = mentioned_person_id

        self.runner.run(
            """
            MERGE (e:Episode {id: $id})
            SET e.episode_type = $episode_type,
                e.start_time = $start_time,
                e.end_time = $end_time,
                e.transcript = $transcript,
                e.retention_class = $retention_class,
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
            OPTIONAL MATCH (old_mentioned:Person)-[old_mention:MENTIONED_IN]->(e)
            WITH e, old_mentioned, old_mention
            FOREACH (_ IN CASE WHEN old_mentioned IS NOT NULL AND NOT old_mentioned.id IN $mentioned_person_ids THEN [1] ELSE [] END | DELETE old_mention)
            WITH DISTINCT e
            CALL {
              WITH e
              UNWIND $participants AS person
            """
            + _person_upsert_cypher("person", "id")
            + """
                MERGE (p)-[r:PARTICIPATED_IN]->(e)
                SET r.role = person.role,
                    r.source = person.source
              RETURN count(*) AS participant_write_count
            }
            CALL {
              WITH e
              UNWIND $mentioned_people AS mentioned
            """
            + _person_upsert_cypher("mentioned", "person_id", update_last_seen=False)
            + """
                MERGE (p)-[r:MENTIONED_IN]->(e)
                SET r.source = mentioned.source
              RETURN count(*) AS mention_write_count
            }
            RETURN e.id AS episode_id
                """,
            {
                "id": episode.id,
                "episode_type": episode.episode_type,
                "start_time": episode.start_time,
                "end_time": episode.end_time,
                "transcript": episode.transcript,
                "retention_class": episode.retention_class,
                "transcript_embedding": transcript_embedding,
                "building_code": episode.place.building_code,
                "room_id": episode.place.room_id,
                "participants": participants,
                "participant_ids": participant_ids,
                "mentioned_people": mentioned_people,
                "mentioned_person_ids": mentioned_person_ids,
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
            _resolve_person_data_by_email(
                self.runner,
                {
                    "person_id": attendee.person.id,
                    "id": attendee.person.id,
                    "display_name": attendee.person.display_name,
                    "email": _normalize_email(attendee.person.email),
                    "consent_status": attendee.person.consent_status,
                    "source": attendee.source,
                    "response": attendee.response,
                    "response_time": attendee.response_time,
                },
                updated_at=written_at,
            )
            for attendee in event.accepted_attendees
        ]

        attendee_ids = [str(attendee["id"]) for attendee in attendees]
        for attendee, attendee_id in zip(attendees, attendee_ids, strict=True):
            attendee["person_id"] = attendee_id

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
                "attendee_ids": attendee_ids,
                "created_at": written_at,
                "updated_at": written_at,
                "last_seen": event.end_time or event.start_time,
            },
        )

        return event.id
