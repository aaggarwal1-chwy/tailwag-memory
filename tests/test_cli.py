from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from tailwag_memory.cli import main
from tailwag_memory.config import Settings


class FakeRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.closed = False

    def run(self, query: str, parameters: dict[str, object] | None = None) -> list[dict[str, object]]:
        self.queries.append((query, parameters))
        return []

    def close(self) -> None:
        self.closed = True


class CliTest(unittest.TestCase):
    def test_db_wipe_requires_confirmation(self) -> None:
        with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(["db", "wipe"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("db wipe requires --yes", stderr.getvalue())
        runner_class.assert_not_called()

    def test_db_wipe_deletes_all_nodes_and_relationships(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
        )
        runner = FakeRunner(settings)

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(["db", "wipe", "--yes"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(runner.queries, [("MATCH (n) DETACH DELETE n", None)])
        self.assertTrue(runner.closed)
        self.assertIn("Neo4j data wiped.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
