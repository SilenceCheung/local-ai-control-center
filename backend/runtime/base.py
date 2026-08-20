"""RuntimeProvider abstraction.

A provider owns one inference server process. Implementations must be honest:
status() reflects the real process + HTTP health, never optimistic UI state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RuntimeProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def start(self, mode: str) -> dict[str, Any]:
        """Start the inference server in 'safe' (target only) or 'fast'
        (target + draft) mode. Returns the resulting status dict."""

    @abstractmethod
    async def stop(self) -> dict[str, Any]:
        """Stop the inference server and wait until the process is gone."""

    @abstractmethod
    async def restart(self, mode: str | None = None) -> dict[str, Any]:
        ...

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Real status: process alive + HTTP reachable + which models."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Cheap HTTP-level health probe of the inference server."""

    @abstractmethod
    async def metrics(self) -> dict[str, Any]:
        """Runtime performance metrics (acceptance rate, tok/s, ...)."""

    @abstractmethod
    def logs(self, lines: int = 200) -> list[str]:
        ...
