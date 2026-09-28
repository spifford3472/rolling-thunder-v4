"""Typed transport boundary for semicolon-terminated CAT communication."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CatTransport(Protocol):
    """Small synchronous boundary implemented by serial and fake transports."""

    def open(self) -> None:
        """Open the underlying CAT connection."""
        ...

    def close(self) -> None:
        """Close the underlying CAT connection."""
        ...

    def query(self, command: bytes) -> bytes:
        """Send a read command and return one complete semicolon reply."""
        ...

    def command(self, command: bytes) -> None:
        """Send a set command that does not require a reply."""
        ...
