"""Identity resolution for relay senders, recipients, and assigned robots."""

from __future__ import annotations

from .db import QueryRunner
from .relay_message_validation import required


def resolve_identities(
    runner: QueryRunner,
    *,
    sender_email: str,
    recipient_email: str,
    robot_id: str,
) -> dict[str, str] | None:
    """Resolve one active sender and recipient for an existing robot."""
    rows = runner.run(
        """
        MATCH (robot:Robot {id: $robot_id})
        MATCH (sender:Person)
        WHERE toLower(trim(sender.email)) = $sender_email
          AND coalesce(sender.status, 'active') <> 'archived'
        WITH robot, collect(sender) AS senders
        MATCH (recipient:Person)
        WHERE toLower(trim(recipient.email)) = $recipient_email
          AND coalesce(recipient.status, 'active') <> 'archived'
        WITH robot, senders, collect(recipient) AS recipients
        WHERE size(senders) = 1 AND size(recipients) = 1
        WITH robot, senders[0] AS sender, recipients[0] AS recipient
        WHERE sender <> recipient
        RETURN sender.id AS sender_person_id,
               recipient.id AS recipient_person_id,
               toLower(trim(sender.email)) AS sender_email,
               toLower(trim(recipient.email)) AS recipient_email,
               coalesce(sender.display_name, sender.official_name, sender.email) AS sender_display_name,
               coalesce(recipient.display_name, recipient.official_name, recipient.email) AS recipient_display_name
        """,
        {
            "sender_email": sender_email,
            "recipient_email": recipient_email,
            "robot_id": required(robot_id, "robot_id"),
        },
    )
    return dict(rows[0]) if len(rows) == 1 else None
