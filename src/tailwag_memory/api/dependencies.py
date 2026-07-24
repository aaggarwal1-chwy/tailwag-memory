from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from fastapi import Request
from tailwag_memory.client import TailwagMemoryClient


class TailwagMemoryClientProvider:
    """Lazily own one process-lifetime client for the API application."""

    def __init__(
        self,
        factory: Callable[[], TailwagMemoryClient] | None = None,
    ) -> None:
        self._factory = factory
        self._client: TailwagMemoryClient | None = None
        self._lock = Lock()

    def get(self) -> TailwagMemoryClient:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    factory = self._factory or TailwagMemoryClient.from_env
                    self._client = factory()
        return self._client

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()


def get_client_provider(request: Request) -> TailwagMemoryClientProvider:
    """Return the non-creating client provider owned by the application."""
    return request.app.state.tailwag_memory_client_provider


def get_client(request: Request) -> TailwagMemoryClient:
    """Return the API application's shared Tailwag client."""
    return get_client_provider(request).get()
