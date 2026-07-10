from __future__ import annotations

from collections.abc import Iterator

from tailwag_memory.client import TailwagMemoryClient


def get_client() -> Iterator[TailwagMemoryClient]:
    """Yield a request-scoped Tailwag memory client."""
    with TailwagMemoryClient.from_env() as client:
        yield client
