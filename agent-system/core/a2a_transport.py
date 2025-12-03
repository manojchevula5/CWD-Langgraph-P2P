"""
A2A transport adapter interface.
Provide a small adapter interface so `A2AClient` can be wired to different
transports (in-process router, Azure Service Bus, Redis pub/sub, Dapr pub/sub).

Adapters should expose:
- `send(message: A2AMessage)`
- `start()` optional (for receivers/processors)
- `stop()` optional

This file provides the abstract base and a lightweight in-process adapter
wrapper (uses existing `A2ARouter`).
"""
from abc import ABC, abstractmethod
from typing import Any
from .a2a_messaging import A2AMessage, A2ARouter


class TransportAdapter(ABC):
    @abstractmethod
    def send(self, message: A2AMessage) -> Any:
        raise NotImplementedError()

    def start(self):
        return None

    def stop(self):
        return None


class InProcessAdapter(TransportAdapter):
    """Wraps an existing `A2ARouter` as a TransportAdapter."""

    def __init__(self, router: A2ARouter):
        self.router = router

    def send(self, message: A2AMessage) -> Any:
        return self.router.route_message(message)

    def start(self):
        return None

    def stop(self):
        return None
