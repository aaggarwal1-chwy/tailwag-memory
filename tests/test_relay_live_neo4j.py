"""Opt-in relay integration tests against a real Neo4j 5.26 database.

Run these tests only against a disposable or dedicated development database:

    TAILWAG_RUN_LIVE_NEO4J_TESTS=1 \
    NEO4J_URI=bolt://localhost:7687 \
    NEO4J_USER=neo4j \
    NEO4J_PASSWORD=tailwag-memory \
    TAILWAG_LIVE_NEO4J_TEST_DATABASE=I_UNDERSTAND_THIS_MUTATES_SCHEMA \
    PYTHONPATH=src python3 -m unittest tests.test_relay_live_neo4j

Add ``TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS=1`` to include the retained-terminal
PROFILE comparison. ``TAILWAG_LIVE_NEO4J_TERMINAL_VOLUME`` controls its bounded
fixture count (default 250, maximum 5000).

The fixtures use unique IDs and delete only the nodes created by each test.
They never perform database-wide cleanup.
"""

from __future__ import annotations

import unittest

from tests.relay_live_neo4j_concurrency_cases import (
    RelayLiveNeo4jConcurrencyCases,
)
from tests.relay_live_neo4j_lifecycle_cases import RelayLiveNeo4jLifecycleCases
from tests.relay_live_neo4j_plan_cases import RelayLiveNeo4jPlanCases
from tests.relay_live_neo4j_support import (
    LIVE_NEO4J_ENABLED,
    RelayLiveNeo4jHarness,
)


@unittest.skipUnless(
    LIVE_NEO4J_ENABLED,
    "set TAILWAG_RUN_LIVE_NEO4J_TESTS=1 to run real-Neo4j relay tests",
)
class RelayMessagesLiveNeo4jTest(
    RelayLiveNeo4jConcurrencyCases,
    RelayLiveNeo4jLifecycleCases,
    RelayLiveNeo4jPlanCases,
    RelayLiveNeo4jHarness,
    unittest.TestCase,
):
    """Exercise relay locking and lifecycle behavior in Neo4j transactions."""


if __name__ == "__main__":
    unittest.main()
