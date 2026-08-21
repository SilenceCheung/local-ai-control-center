"""In-process cache for Responses previous_response_id."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class ResponseMemory:
    def __init__(self, max_items: int = 32) -> None:
        self.max_items = max_items
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def put(self, response_id: str, payload: dict[str, Any]) -> None:
        if not response_id:
            return
        if response_id in self._items:
            self._items.move_to_end(response_id)
        self._items[response_id] = payload
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def get(self, response_id: str | None) -> dict[str, Any] | None:
        if not response_id:
            return None
        row = self._items.get(response_id)
        if row is None:
            return None
        self._items.move_to_end(response_id)
        return row


memory = ResponseMemory()
