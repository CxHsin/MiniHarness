from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Session:
    def __init__(self, cwd: str | Path, history_budget_chars: int = 120000):
        self.cwd = Path(cwd).resolve()
        self.history_budget_chars = history_budget_chars
        self._turns: list[list[dict[str, Any]]] = []

    def add_message(self, message: dict[str, Any]) -> None:
        self._turns.append([message])
        self._trim()

    def add_turn(self, messages: list[dict[str, Any]]) -> None:
        self._turns.append(messages)
        self._trim()

    def get_messages(self) -> list[dict[str, Any]]:
        return [message for turn in self._turns for message in turn]

    def _trim(self) -> None:
        while self._message_size() > self.history_budget_chars:
            removable_index = self._oldest_removable_turn_index()
            if removable_index is None:
                break
            del self._turns[removable_index]

    def _oldest_removable_turn_index(self) -> int | None:
        latest_user_index = self._latest_user_turn_index()
        for index, turn in enumerate(self._turns):
            first = turn[0] if turn else {}
            if first.get("role") == "system":
                continue
            if index == latest_user_index:
                continue
            return index
        return None

    def _latest_user_turn_index(self) -> int | None:
        for index in range(len(self._turns) - 1, -1, -1):
            if any(message.get("role") == "user" for message in self._turns[index]):
                return index
        return None

    def _message_size(self) -> int:
        return len(json.dumps(self.get_messages(), ensure_ascii=False, default=str))
