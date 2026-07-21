from __future__ import annotations

import re
from collections.abc import Mapping

from .models import RobotParticipationResult


_CYPHER_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def episode_place_projection_subquery(episode_variable: str) -> str:
    """Return an isolated single-place projection for an episode row."""
    episode = _validated_identifier(episode_variable)
    return f"""
            CALL ({episode}) {{
                OPTIONAL MATCH ({episode})-[:OCCURRED_AT]->(matched_place:Place)
                RETURN head(collect(DISTINCT matched_place)) AS place
            }}
            """


def robot_participation_projection_subquery(episode_variable: str) -> str:
    """Return an isolated, stable-ID-ordered robot projection for an episode."""
    episode = _validated_identifier(episode_variable)
    return f"""
            CALL ({episode}) {{
                OPTIONAL MATCH (robot:Robot)-[participation:PARTICIPATED_IN]->({episode})
                WITH DISTINCT robot.id AS robot_id,
                     robot.display_name AS display_name,
                     participation.role AS role,
                     participation.source AS source
                ORDER BY robot_id
                RETURN [item IN collect(CASE WHEN robot_id IS NULL THEN null ELSE {{
                    robot_id: robot_id,
                    display_name: display_name,
                    role: role,
                    source: source
                }} END) WHERE item IS NOT NULL] AS robots
            }}
            """


def robot_participations_from_row(row: Mapping[str, object]) -> list[RobotParticipationResult]:
    """Convert a projected Neo4j robot list into deterministic result models."""
    robots: list[RobotParticipationResult] = []
    for robot in row.get("robots") or []:
        if not isinstance(robot, Mapping) or robot.get("robot_id") is None:
            continue
        robots.append(
            RobotParticipationResult(
                robot_id=str(robot["robot_id"]),
                display_name=str(robot.get("display_name") or ""),
                role=str(robot.get("role") or ""),
                source=str(robot.get("source") or ""),
            )
        )
    robots.sort(key=lambda robot: robot.robot_id)
    return robots


def _validated_identifier(value: str) -> str:
    """Reject unsafe identifiers before interpolating internal query variables."""
    if not _CYPHER_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid Cypher identifier: {value!r}")
    return value
