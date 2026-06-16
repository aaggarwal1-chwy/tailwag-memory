from __future__ import annotations

from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner


def reset_database() -> None:
    settings = load_settings()
    runner = Neo4jQueryRunner(settings)
    try:
        runner.run("MATCH (n) DETACH DELETE n")
    finally:
        runner.close()


if __name__ == "__main__":
    reset_database()
    print("Neo4j data reset.")
